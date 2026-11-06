import { apiClient } from './client'
import { fetchAllFormats } from './formats'
import type { ApiResponse, DocumentFormat } from '@/types'

export interface ApiScope {
  code: string
  description: string
}

export interface ApiCredential {
  id: string
  name: string
  key_prefix: string
  scopes: string[]
  allowed_formats: string[]
  allowed_format_codes: string[]
  all_formats: boolean
  active: boolean
  expires_at: string | null
  revoked_at: string | null
  last_used_at: string | null
  created_at: string
}

export interface ApiCredentialInput {
  name: string
  scopes: string[]
  allowed_formats: string[]
  expires_at: string | null
}

const endpoint = '/integrations/api-keys/'

export const integrationsApi = {
  list: () => apiClient.get<ApiResponse<ApiCredential[]>>(endpoint),
  scopes: () => apiClient.get<ApiResponse<ApiScope[]>>(`${endpoint}scopes/`),
  create: (data: ApiCredentialInput) =>
    apiClient.post<ApiResponse<ApiCredential & { api_key: string }>>(endpoint, data),
  revoke: (id: string) =>
    apiClient.post<ApiResponse<ApiCredential>>(`${endpoint}${id}/revoke/`),
}

/** Load every page so format selection is not limited to the first 100 entries. */
export async function fetchActiveFormats(): Promise<DocumentFormat[]> {
  return fetchAllFormats({ status: 'active' })
}
