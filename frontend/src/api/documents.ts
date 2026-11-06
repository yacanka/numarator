// src/api/documents.ts
import { apiClient } from './client'
import type {
  GeneratedDocument,
  ApiResponse,
  PaginatedResponse,
  DocumentStats,
} from '@/types'

export interface DocumentFilters {
  format_id?: string
  category?: number
  status?: string
  search?: string
  date_from?: string
  date_to?: string
  page?: number
  page_size?: number
}

export const documentsApi = {
  getDocuments: (filters?: DocumentFilters) =>
    apiClient.get<PaginatedResponse<GeneratedDocument>>('/documents/', {
      params: filters,
    }),

  getDocument: (id: string) =>
    apiClient.get<ApiResponse<GeneratedDocument>>(`/documents/${id}/`),

  cancelDocument: (id: string, reason?: string) =>
    apiClient.post(`/documents/${id}/cancel/`, { reason }),

  markUsed: (id: string) =>
    apiClient.post(`/documents/${id}/mark-used/`),

  updateStatus: (id: string, status: GeneratedDocument['status'], reason = '') =>
    apiClient.patch<ApiResponse<GeneratedDocument>>(`/documents/${id}/status/`, {
      status,
      reason,
    }),

  validateNumber: (number: string) =>
    apiClient.get<ApiResponse<any>>('/documents/validate/', { params: { number } }),

  getStats: () =>
    apiClient.get<ApiResponse<DocumentStats>>('/documents/stats/'),
}
