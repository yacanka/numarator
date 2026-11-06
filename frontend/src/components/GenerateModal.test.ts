import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createVueHarness, deferred, flushPromises } from '../../test-support/vue.ts'
import { document, format } from '../../test-support/fixtures.ts'

function setup(context: any, generateNumber = async () => document(), globals = {}) {
  const emitted: any[] = []
  const harness = createVueHarness({
    'vue-router': { useRouter: () => ({ push() {} }) },
    '@/stores/formats': { useFormatsStore: () => ({ generateNumber }) },
  }, globals)
  const view = harness.mount('@/components/document/GenerateModal.vue', {
    format: format(), show: true,
    'onUpdate:show': (show: boolean) => { view.props.show = show },
    onGenerated: (documents: any[]) => emitted.push(documents),
  })
  context.after(view.unmount)
  return { ...view, emitted, messages: harness.messages }
}

test('modal close event clears generated numbers and context before another format opens', async context => {
  const view = setup(context)
  view.state.contextData = { department: 'FIN' }
  view.state.count = 3
  await view.state.generate()
  view.find('NModal')!.props['onUpdate:show'](false)
  await flushPromises()
  view.props.format = format('format-b', 'FORMAT_B')
  view.props.show = true
  await flushPromises()
  assert.equal(view.state.generatedDocs.length, 0)
  assert.deepEqual({ ...view.state.contextData }, {})
  assert.equal(view.state.count, 1)
})

test('closing and reopening while generation runs ignores the stale response and keeps the new request loading', async context => {
  const first = deferred<any>()
  const second = deferred<any>()
  let calls = 0
  const view = setup(context, () => (++calls === 1 ? first.promise : second.promise))
  const previousGeneration = view.state.generate()
  view.find('NModal')!.props['onUpdate:show'](false)
  await flushPromises()
  view.props.format = format('format-b', 'FORMAT_B')
  view.props.show = true
  await flushPromises()
  const currentGeneration = view.state.generate()
  first.resolve(document('old-document'))
  await previousGeneration
  assert.equal(view.state.generatedDocs.length, 0)
  assert.equal(view.state.loading, true)
  assert.equal(view.emitted.length, 0)
  second.resolve(document('new-document'))
  await currentGeneration
  assert.equal(view.state.generatedDocs[0].id, 'new-document')
  assert.equal(view.emitted.length, 1)
})

test('switching format invalidates an in-flight generation without showing its failure', async context => {
  const pending = deferred<any>()
  const view = setup(context, () => pending.promise)
  view.state.contextData = { department: 'FIN' }
  const generation = view.state.generate()
  view.props.format = format('format-b', 'FORMAT_B')
  await flushPromises()
  pending.reject(new Error('Old request failed'))
  await generation
  assert.deepEqual({ ...view.state.contextData }, {})
  assert.equal(view.state.loading, false)
  assert.equal(view.messages.length, 0)
})

test('double submission does not generate an extra batch while a request is pending', async context => {
  const pending = deferred<any>()
  let calls = 0
  const view = setup(context, () => { calls += 1; return pending.promise })
  const first = view.state.generate()
  const second = view.state.generate()
  pending.resolve(document())
  await Promise.all([first, second])
  assert.equal(calls, 1)
  assert.equal(view.emitted.length, 1)
})

test('CSV preserves commas, quotes and line breaks in a single document-number cell', async context => {
  let blob: Blob | undefined
  const view = setup(context, async () => document(), {
    URL: { createObjectURL(value: Blob) { blob = value; return 'blob:test' }, revokeObjectURL() {} },
    document: { createElement: () => ({ click() {} }) },
  })
  view.state.generatedDocs = [document('doc', 'ACME,"001"\nBRANCH')]
  view.state.downloadCSV()
  assert.equal(await blob!.text(), 'Document Number,Status,Generated At\n"ACME,""001""\nBRANCH","active","2026-11-07T12:00:00Z"')
})

test('CSV neutralizes formula-leading numbers while leaving ordinary document numbers unchanged', async context => {
  let blob: Blob | undefined
  const view = setup(context, async () => document(), {
    URL: { createObjectURL(value: Blob) { blob = value; return 'blob:test' }, revokeObjectURL() {} },
    document: { createElement: () => ({ click() {} }) },
  })
  for (const [number, expected] of [
    ['=1+1', "'=1+1"], ['+1+1', "'+1+1"], ['-1+1', "'-1+1"], ['@SUM(1)', "'@SUM(1)"],
    [' \t=1+1', "' \t=1+1"], ['\tDOC', "'\tDOC"], ['DOC-0001', 'DOC-0001'],
  ]) {
    view.state.generatedDocs = [document('doc', number)]
    view.state.downloadCSV()
    assert.equal(await blob!.text(), `Document Number,Status,Generated At\n"${expected}","active","2026-11-07T12:00:00Z"`)
  }
})
