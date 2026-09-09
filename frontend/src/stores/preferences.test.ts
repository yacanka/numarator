import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createPinia } from 'pinia'
import { nextTick } from 'vue'
import { usePreferencesStore } from './preferences.ts'

const cases = [
  { name: 'new installations use defaults', saved: {}, theme: 'light', density: 'comfortable' },
  {
    name: 'legacy preferences are copied to the new keys',
    saved: { docnumber_theme: 'dark', docnumber_density: 'compact' },
    theme: 'dark', density: 'compact',
  },
  {
    name: 'new preferences take precedence over legacy values',
    saved: {
      numarator_theme: 'light', numarator_density: 'comfortable',
      docnumber_theme: 'dark', docnumber_density: 'compact',
    },
    theme: 'light', density: 'comfortable',
  },
  {
    name: 'invalid legacy preferences use defaults',
    saved: { docnumber_theme: 'invalid', docnumber_density: 'invalid' },
    theme: 'light', density: 'comfortable',
  },
]

for (const scenario of cases) {
  test(scenario.name, async (context) => {
    const storage = new Map(Object.entries(scenario.saved))
    const dataset: Record<string, string> = {}
    const replacements = {
      localStorage: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => storage.set(key, value),
      },
      document: { documentElement: { dataset } },
    }
    for (const [key, value] of Object.entries(replacements)) {
      const descriptor = Object.getOwnPropertyDescriptor(globalThis, key)
      Object.defineProperty(globalThis, key, { configurable: true, value })
      context.after(() => {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor)
        else Reflect.deleteProperty(globalThis, key)
      })
    }

    const store = usePreferencesStore(createPinia())
    context.after(() => store.$dispose())
    assert.equal(store.theme, scenario.theme)
    assert.equal(store.density, scenario.density)
    assert.equal(storage.get('numarator_theme'), scenario.theme)
    assert.equal(storage.get('numarator_density'), scenario.density)
    assert.equal(dataset.theme, scenario.theme)

    store.setTheme(store.theme === 'light' ? 'dark' : 'light')
    store.setDensity(store.density === 'comfortable' ? 'compact' : 'comfortable')
    await nextTick()
    assert.equal(storage.get('numarator_theme'), store.theme)
    assert.equal(storage.get('numarator_density'), store.density)
    assert.equal(dataset.theme, store.theme)
    assert.equal(storage.get('docnumber_theme'), scenario.saved.docnumber_theme)
    assert.equal(storage.get('docnumber_density'), scenario.saved.docnumber_density)
  })
}
