import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createPinia } from 'pinia'
import { createVueHarness, flushPromises } from '../../test-support/vue.ts'
import { format } from '../../test-support/fixtures.ts'

function setup(context: any, file: string) {
  const formats = Array.from({ length: 101 }, (_, index) => format(`format-${index + 1}`, `FORMAT_${index + 1}`))
  const apiClient = {
    async get(url: string, config: any = {}) {
      if (url === '/categories/') return { data: { success: true, data: [] } }
      const source = url === '/formats/' ? formats : []
      const page = config.params?.page || 1
      const pageSize = Math.min(config.params?.page_size || 20, 100)
      return { data: {
        success: true, data: source.slice((page - 1) * pageSize, page * pageSize),
        pagination: { count: source.length, current_page: page, page_size: pageSize,
          total_pages: Math.max(1, Math.ceil(source.length / pageSize)), next: null, previous: null },
      } }
    },
  }
  const harness = createVueHarness({
    '@/api/client': { apiClient }, './client': { apiClient },
    'vue-router': { useRouter: () => ({ push() {} }), useRoute: () => ({ query: {} }) },
  })
  const view = harness.mount(file, {}, [createPinia()])
  context.after(view.unmount)
  return { ...view, formats }
}

test('format management searches formats beyond the API first page and refreshes the full collection', async context => {
  const view = setup(context, '@/views/FormatsView.vue')
  await flushPromises()
  assert.equal(view.state.filteredFormats.length, 101)
  view.state.searchQuery = 'FORMAT_101'
  assert.equal(view.state.filteredFormats.length, 1)
  assert.equal(view.state.filteredFormats[0].id, 'format-101')
  view.formats.push(format('format-102', 'FORMAT_102'))
  await view.state.handleGenerated()
  view.state.searchQuery = 'FORMAT_102'
  assert.equal(view.state.filteredFormats[0].id, 'format-102')
})

test('document filter contains formats beyond the API first page', async context => {
  const view = setup(context, '@/views/DocumentsView.vue')
  await flushPromises()
  assert.equal(view.state.formatOptions.length, 101)
  assert.ok(view.state.formatOptions.some((option: any) => option.value === 'format-101'))
})
