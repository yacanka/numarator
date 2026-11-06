import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'
import ts from 'typescript'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive } from 'vue'
import * as pinia from 'pinia'

const require = createRequire(import.meta.url)
const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url))

type HostNode = { type: string; props: Record<string, any>; children: HostNode[]; parent?: HostNode; text?: string }
const node = (type: string): HostNode => ({ type, props: {}, children: [] })

/** Compile real SFC scripts/templates; replace only browser UI and external I/O boundaries. */
export function createVueHarness(mocks: Record<string, any> = {}, globals: Record<string, any> = {}) {
  const cache = new Map<string, any>()
  const messages: Array<[string, string]> = []
  const naive = new Proxy({
    useMessage: () => Object.fromEntries(['success', 'error', 'warning'].map(kind => [kind, (text: string) => messages.push([kind, text])])),
  } as Record<string, any>, {
    get(target, key: string) {
      if (!(key in target)) target[key] = (props: any, { slots }: any) => h(key, props, Object.values(slots).flatMap((slot: any) => slot()))
      return target[key]
    },
  })

  function loadModule(specifier: string, importer = resolve(sourceRoot, 'entry.ts')): any {
    if (specifier in mocks) return mocks[specifier]
    if (specifier === 'naive-ui') return naive
    if (specifier === 'pinia') return pinia
    if (specifier === '@vicons/ionicons5') return new Proxy({}, { get: () => () => h('icon') })
    if (!specifier.startsWith('.') && !specifier.startsWith('@/') && !specifier.startsWith('/')) return require(specifier)
    const path = specifier.startsWith('@/') ? resolve(sourceRoot, specifier.slice(2)) : resolve(dirname(importer), specifier)
    const filename = [path, `${path}.ts`, `${path}.vue`, resolve(path, 'index.ts')].find(existsSync)!
    if (!filename) throw new Error(`Cannot resolve ${specifier} from ${importer}`)
    if (cache.has(filename)) return cache.get(filename)
    let content = readFileSync(filename, 'utf8')
    if (filename.endsWith('.vue')) {
      const { descriptor } = parse(content, { filename })
      const script = compileScript(descriptor, { id: filename, genDefaultAs: '__component' })
      const template = compileTemplate({
        source: descriptor.template!.content, filename, id: filename,
        compilerOptions: { bindingMetadata: script.bindings },
      })
      if (template.errors.length) throw new Error(template.errors.join('\n'))
      content = `${script.content}\n${template.code}\n__component.render = render;\nexport default __component;`
    }
    const compiled = ts.transpileModule(content, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText
    const module = { exports: {} }
    cache.set(filename, module.exports)
    vm.runInNewContext(compiled, {
      module, exports: module.exports, require: (name: string) => loadModule(name, filename),
      console, setTimeout, clearTimeout, Date, Blob, URL, ...globals,
    }, { filename })
    cache.set(filename, module.exports)
    return module.exports
  }

  function mount(file: string, values: Record<string, any> = {}, plugins: any[] = []) {
    const component = loadModule(file).default
    const props = reactive(values)
    const container = node('root')
    const renderer = createRenderer<HostNode, HostNode>({
      createElement: node,
      createText: text => ({ ...node('#text'), text }),
      createComment: text => ({ ...node('#comment'), text }),
      setText: (element, text) => { element.text = text },
      setElementText: (element, text) => { element.children = []; element.text = text },
      parentNode: element => element.parent || null,
      nextSibling: element => element.parent?.children[element.parent.children.indexOf(element) + 1] || null,
      patchProp: (element, key, _previous, value) => { element.props[key] = value },
      insert(element, parent, anchor) {
        if (element.parent) element.parent.children.splice(element.parent.children.indexOf(element), 1)
        element.parent = parent
        const index = anchor ? parent.children.indexOf(anchor) : -1
        if (index < 0) parent.children.push(element)
        else parent.children.splice(index, 0, element)
      },
      remove(element) { element.parent?.children.splice(element.parent.children.indexOf(element), 1) },
    })
    const app = renderer.createApp({ setup: () => () => h(component, props) })
    plugins.forEach(plugin => app.use(plugin))
    app.mount(container)
    const instance = app._instance!.subTree.component!
    function find(type: string, root = container): HostNode | undefined {
      if (root.type === type) return root
      return root.children.map(child => find(type, child)).find(Boolean)
    }
    return { props, state: instance.setupState as any, find, unmount: () => app.unmount() }
  }

  return { loadModule, mount, messages }
}

export async function flushPromises() {
  await new Promise(resolve => setImmediate(resolve))
  await nextTick()
}

export function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => { resolve = resolvePromise; reject = rejectPromise })
  return { promise, resolve, reject }
}
