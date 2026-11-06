import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createVueHarness, flushPromises } from '../../test-support/vue.ts'
import { document } from '../../test-support/fixtures.ts'

function setup(context: any, count = 1) {
  const records = Array.from({ length: count }, (_, index) => document(`document-${index + 1}`, `DOC-${index + 1}`))
  const documentsApi = {
    async getDocuments(filters: any) {
      const filtered = records.filter(item => !filters.status || item.status === filters.status)
      const offset = (filters.page - 1) * filters.page_size
      return { data: { success: true, data: filtered.slice(offset, offset + filters.page_size).map(item => ({ ...item })),
        pagination: { count: filtered.length, total_pages: Math.max(1, Math.ceil(filtered.length / filters.page_size)),
          current_page: filters.page, page_size: filters.page_size, next: null, previous: null } } }
    },
    async updateStatus(id: string, status: string) {
      const record = records.find(item => item.id === id)!
      record.status = status
      return { data: { success: true, data: { ...record } } }
    },
  }
  const harness = createVueHarness({
    'vue-router': { useRoute: () => ({ query: {} }) },
    '@/api/documents': { documentsApi },
    '@/stores/formats': { useFormatsStore: () => ({
      formats: [], categories: [], fetchCategories: async () => {}, fetchAllFormats: async () => {},
    }) },
  })
  const view = harness.mount('@/views/DocumentsView.vue')
  context.after(view.unmount)
  return view
}

test('changing status removes a document from the active filter and refreshes its total', async context => {
  const view = setup(context)
  await flushPromises()
  view.state.statusFilter = 'active'
  await flushPromises()
  await view.state.handleStatusChange(view.state.documents[0], 'used')
  assert.equal(view.state.documents.length, 0)
  assert.equal(view.state.pagination.itemCount, 0)
})

test('changing the final matching document on the last page moves to the preceding page', async context => {
  const view = setup(context, 21)
  await flushPromises()
  view.state.statusFilter = 'active'
  await flushPromises()
  view.state.handlePageChange(2)
  await flushPromises()
  assert.equal(view.state.documents[0].id, 'document-21')
  await view.state.handleStatusChange(view.state.documents[0], 'used')
  assert.equal(view.state.pagination.page, 1)
  assert.equal(view.state.pagination.itemCount, 20)
  assert.equal(view.state.documents.length, 20)
  assert.ok(view.state.documents.every((item: any) => item.status === 'active'))
})

test('changing status with the all filter keeps the document and total visible', async context => {
  const view = setup(context)
  await flushPromises()
  await view.state.handleStatusChange(view.state.documents[0], 'used')
  assert.equal(view.state.documents.length, 1)
  assert.equal(view.state.documents[0].status, 'used')
  assert.equal(view.state.pagination.itemCount, 1)
})
