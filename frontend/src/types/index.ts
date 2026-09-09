export interface User {
  id: number
  username: string
  email: string
  first_name: string
  last_name: string
  is_staff: boolean
}

export interface UserProfileUpdate {
  email: string
  first_name: string
  last_name: string
}

export type ThemePreference = 'light' | 'dark'
export type InterfaceDensity = 'comfortable' | 'compact'

// src/types/index.ts
export interface SegmentConfig {
  type: SegmentType
  config: Record<string, any>
  order: number
  label?: string
}

export type SegmentType =
  | 'static'
  | 'date'
  | 'sequence'
  | 'yearly_sequence'
  | 'random'
  | 'checksum'
  | 'context'
  | 'separator'

export interface SegmentTypeInfo {
  type: SegmentType
  label: string
  description: string
  icon: string
}

export type FormatStatus = 'draft' | 'active' | 'deprecated' | 'archived'
export type ResetPeriod = 'never' | 'daily' | 'weekly' | 'monthly' | 'quarterly' | 'yearly'

export interface FormatCategory {
  id: string
  name: string
  code: string
  color: string
  icon: string
  order: number
}

export interface DocumentFormat {
  id: string
  code: string
  name: string
  description: string
  status: FormatStatus
  category: string | null
  category_name?: string
  category_color?: string
  segments_config: SegmentConfig[]
  sequence_reset_period: ResetPeriod
  sequence_start: number
  sequence_step: number
  validation_regex: string
  example_output: string
  total_generated: number
  preview: string
  current_sequence?: number
  tags: string[]
  created_at: string
  updated_at: string
}

export interface GeneratedDocument {
  id: string
  document_number: string
  format: string
  format_code: string
  format_name: string
  status: 'active' | 'cancelled' | 'used' | 'expired'
  sequence_value: number
  context_data: Record<string, any>
  metadata: Record<string, any>
  external_reference: string
  generated_by: number
  generated_by_username: string
  generated_at: string
  used_at: string | null
  cancelled_at: string | null
  cancellation_reason: string
}

export interface PaginatedResponse<T> {
  success: boolean
  data: T[]
  pagination: {
    count: number
    total_pages: number
    current_page: number
    next: string | null
    previous: string | null
    page_size: number
  }
}

export interface ApiResponse<T> {
  success: boolean
  data: T
  message?: string
}

export interface DashboardStats {
  total_formats: number
  active_formats: number
  total_documents: number
  today_documents: number
  month_documents: number
}

export interface DocumentStats {
  total_generated: number
  active_count: number
  cancelled_count: number
  used_count: number
  today_count: number
  this_week_count: number
  this_month_count: number
  by_format: Array<{ format__code: string; format__name: string; count: number }>
  daily_trend: Array<{ date: string; count: number }>
}
