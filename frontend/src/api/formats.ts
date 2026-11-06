// src/api/formats.ts
import { apiClient } from './client'
import type {
  DocumentFormat,
  FormatCategory,
  SegmentTypeInfo,
  ApiResponse,
  PaginatedResponse,
  DashboardStats,
} from '@/types'

export interface FormatFilters {
  status?: string
  category?: string
  search?: string
  page?: number
  page_size?: number
}

export interface GenerateParams {
  context_data?: Record<string, any>
  metadata?: Record<string, any>
  count?: number
}

export const formatsApi = {
  // Categories
  getCategories: () =>
    apiClient.get<ApiResponse<FormatCategory[]>>('/categories/'),

  createCategory: (data: Partial<FormatCategory>) =>
    apiClient.post<ApiResponse<FormatCategory>>('/categories/', data),

  updateCategory: (id: string, data: Partial<FormatCategory>) =>
    apiClient.put<ApiResponse<FormatCategory>>(`/categories/${id}/`, data),

  deleteCategory: (id: string) =>
    apiClient.delete(`/categories/${id}/`),

  // Formats
  getFormats: (filters?: FormatFilters) =>
    apiClient.get<PaginatedResponse<DocumentFormat>>('/formats/', {
      params: filters,
    }),

  getFormat: (id: string) =>
    apiClient.get<ApiResponse<DocumentFormat> | DocumentFormat>(
      `/formats/${id}/`
    ),

  createFormat: (data: Partial<DocumentFormat>) =>
    apiClient.post<ApiResponse<DocumentFormat>>('/formats/', data),

  updateFormat: (id: string, data: Partial<DocumentFormat>) =>
    apiClient.put<ApiResponse<DocumentFormat>>(`/formats/${id}/`, data),

  patchFormat: (id: string, data: Partial<DocumentFormat>) =>
    apiClient.patch<ApiResponse<DocumentFormat>>(`/formats/${id}/`, data),

  deleteFormat: (id: string) =>
    apiClient.delete(`/formats/${id}/`),

  // Actions
  generateNumber: (id: string, params: GenerateParams) =>
    apiClient.post<ApiResponse<any>>(`/formats/${id}/generate/`, params),

  previewFormat: (id: string, contextData?: Record<string, string>) =>
    apiClient.get<ApiResponse<{ preview: string }>>(`/formats/${id}/preview/`, {
      params: contextData,
    }),

  activateFormat: (id: string) =>
    apiClient.post(`/formats/${id}/activate/`),

  deactivateFormat: (id: string) =>
    apiClient.post(`/formats/${id}/deactivate/`),

  duplicateFormat: (id: string) =>
    apiClient.post<ApiResponse<DocumentFormat>>(`/formats/${id}/duplicate/`),

  getVersions: (id: string) =>
    apiClient.get<ApiResponse<any[]>>(`/formats/${id}/versions/`),

  getSegmentTypes: () =>
    apiClient.get<ApiResponse<SegmentTypeInfo[]>>('/formats/segment-types/'),

  getStats: () =>
    apiClient.get<ApiResponse<DashboardStats>>('/formats/stats/'),
}

/** Load every page for views and selectors that filter the full format collection locally. */
export async function fetchAllFormats(
  filters: Omit<FormatFilters, 'page' | 'page_size'> = {}
): Promise<DocumentFormat[]> {
  const formats: DocumentFormat[] = []
  let page = 1
  let totalPages = 1
  do {
    const response = await formatsApi.getFormats({ ...filters, page, page_size: 100 })
    formats.push(...response.data.data)
    totalPages = response.data.pagination.total_pages
    page += 1
  } while (page <= totalPages)
  return formats
}
