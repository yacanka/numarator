import assert from 'node:assert/strict'
import { test } from 'node:test'
import { reactive } from 'vue'
import { createVueHarness, deferred, flushPromises } from '../../test-support/vue.ts'
import { format } from '../../test-support/fixtures.ts'

function setup(context: any) {
  const route = reactive({ params: { id: 'format-a' as string | undefined } })
  const first = deferred<any>()
  const second = deferred<any>()
  const harness = createVueHarness({
    'vue-router': { useRoute: () => route, useRouter: () => ({ push() {} }) },
    '@/stores/formats': { useFormatsStore: () => ({
      categories: [], segmentTypes: [], fetchCategories: async () => {}, fetchSegmentTypes: async () => {},
      fetchFormat: (id: string) => id === 'format-a' ? first.promise : second.promise,
    }) },
    '@/api/formats': { formatsApi: { previewFormat: async () => ({ data: { data: { preview: '' } } }) } },
  })
  const view = harness.mount('@/views/FormatBuilderView.vue')
  context.after(view.unmount)
  return { ...view, route, first, second, messages: harness.messages }
}

const loadedFormat = (id: string, code: string) => ({ ...format(id, code), segments_config: [] })

test('a late format response cannot overwrite the newly selected format', async context => {
  const view = setup(context)
  view.route.params.id = 'format-b'
  await flushPromises()
  view.second.resolve(loadedFormat('format-b', 'B'))
  await flushPromises()
  view.first.resolve(loadedFormat('format-a', 'A'))
  await flushPromises()
  assert.equal(view.state.form.id, 'format-b')
  assert.equal(view.state.form.code, 'B')
  assert.equal(view.state.loading, false)
})

test('opening the new-format route invalidates pending loads and clears loading immediately', async context => {
  const view = setup(context)
  view.route.params.id = undefined
  await flushPromises()
  assert.equal(view.state.loading, false)
  view.first.resolve(loadedFormat('format-a', 'A'))
  await flushPromises()
  assert.equal(view.state.form.code, '')
  assert.equal(view.state.form.id, undefined)
})

test('a late error from the previous format does not show an error for the current format', async context => {
  const view = setup(context)
  view.route.params.id = 'format-b'
  await flushPromises()
  view.second.resolve(loadedFormat('format-b', 'B'))
  await flushPromises()
  view.first.reject(new Error('The previous format is unavailable'))
  await flushPromises()
  assert.equal(view.messages.length, 0)
  assert.equal(view.state.form.id, 'format-b')
})

test('a failed navigation does not leave the previous format available to save under the new URL', async context => {
  const view = setup(context)
  view.first.resolve(loadedFormat('format-a', 'A'))
  await flushPromises()
  view.route.params.id = 'format-b'
  await flushPromises()
  view.second.reject(new Error('Format B cannot be loaded'))
  await flushPromises()
  assert.equal(view.state.form.code, '')
  assert.equal(view.state.form.id, undefined)
  assert.equal(view.state.loading, false)
})
