import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createVueHarness } from '../../test-support/vue.ts'

test('number validation uses a query value so slash, backslash and URL delimiters remain part of the number', () => {
  const apiClient = { get(path: string, config: any) {
    const url = new URL(path, 'https://example.invalid')
    for (const [key, value] of Object.entries(config?.params || {})) url.searchParams.set(key, String(value))
    return url
  } }
  const { loadModule } = createVueHarness({ './client': { apiClient } })
  const { documentsApi } = loadModule('@/api/documents.ts')
  const number = 'DEPT/2026\\007?#'
  const request = documentsApi.validateNumber(number)
  assert.equal(request.pathname, '/documents/validate/')
  assert.equal(request.searchParams.get('number'), number)
})
