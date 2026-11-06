import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createPinia } from 'pinia'
import { createVueHarness } from '../../test-support/vue.ts'
import { format } from '../../test-support/fixtures.ts'

test('API key format options keep the active filter across every page', async () => {
  const items = Array.from({ length: 102 }, (_, index) => format(`format-${index}`, `FORMAT_${index}`))
  items.push({ ...format('draft-format'), status: 'draft' })
  const apiClient = { async get(_path: string, { params }: any) {
    const filtered = items.filter(item => !params.status || item.status === params.status)
    const offset = (params.page - 1) * params.page_size
    return { data: { success: true, data: filtered.slice(offset, offset + params.page_size), pagination: {
      count: filtered.length, total_pages: Math.ceil(filtered.length / params.page_size),
      current_page: params.page, page_size: params.page_size, next: null, previous: null,
    } } }
  } }
  const harness = createVueHarness({ './client': { apiClient } })
  const { fetchActiveFormats } = harness.loadModule('@/api/integrations.ts')
  const loaded = await fetchActiveFormats()
  assert.equal(loaded.length, 102)
  assert.equal(loaded.at(-1).id, 'format-101')
  assert.ok(loaded.every((item: any) => item.status === 'active'))
})

test('a later page failure leaves the previous format collection intact and clears loading', async () => {
  const expectedError = new Error('Connection lost on page two')
  const apiClient = { async get(_path: string, { params }: any) {
    if (params.page === 2) throw expectedError
    return { data: { success: true, data: [format('partial-format')], pagination: {
      count: 101, total_pages: 2, current_page: 1, page_size: 100, next: '?page=2', previous: null,
    } } }
  } }
  const harness = createVueHarness({ './client': { apiClient } })
  const { useFormatsStore } = harness.loadModule('@/stores/formats.ts')
  const store = useFormatsStore(createPinia())
  store.formats = [format('previous-format')]
  await assert.rejects(store.fetchAllFormats(), expectedError)
  assert.equal(store.formats.length, 1)
  assert.equal(store.formats[0].id, 'previous-format')
  assert.equal(store.loading, false)
  store.$dispose()
})
