// src/stores/formats.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { formatsApi, fetchAllFormats as fetchAllFormatPages } from '@/api/formats'
import type { ApiResponse, DocumentFormat, FormatCategory, SegmentTypeInfo } from '@/types'

export const useFormatsStore = defineStore('formats', () => {
  const formats = ref<DocumentFormat[]>([])
  const categories = ref<FormatCategory[]>([])
  const segmentTypes = ref<SegmentTypeInfo[]>([])
  const currentFormat = ref<DocumentFormat | null>(null)
  const loading = ref(false)
  const pagination = ref({
    count: 0,
    total_pages: 0,
    current_page: 1,
    page_size: 20,
  })

  const activeFormats = computed(() =>
    formats.value.filter((f) => f.status === 'active')
  )

  async function fetchFormats(filters = {}) {
    loading.value = true
    try {
      const response = await formatsApi.getFormats(filters)
      formats.value = response.data.data
      pagination.value = response.data.pagination
    } finally {
      loading.value = false
    }
  }

  async function fetchAllFormats() {
    loading.value = true
    try {
      formats.value = await fetchAllFormatPages()
    } finally {
      loading.value = false
    }
  }

  /** Fetch a single format and normalize raw or wrapped API payloads. */
  async function fetchFormat(id: string): Promise<DocumentFormat> {
    const response = await formatsApi.getFormat(id)
    currentFormat.value = unwrapApiData(response.data)
    return currentFormat.value
  }

  function unwrapApiData<T>(payload: ApiResponse<T> | T): T {
    if (isApiResponse(payload)) return payload.data
    return payload
  }

  function isApiResponse<T>(payload: ApiResponse<T> | T): payload is ApiResponse<T> {
    return Boolean(payload && typeof payload === 'object' && 'success' in payload && 'data' in payload)
  }

  async function fetchCategories() {
    const response = await formatsApi.getCategories()
    categories.value = response.data.data
  }

  async function fetchSegmentTypes() {
    const response = await formatsApi.getSegmentTypes()
    segmentTypes.value = response.data.data
  }

  async function createCategory(data: Partial<FormatCategory>) {
    const response = await formatsApi.createCategory(data)
    categories.value.push(response.data.data)
    categories.value.sort((left, right) => left.name.localeCompare(right.name))
    return response.data.data
  }

  async function createFormat(data: Partial<DocumentFormat>) {
    const response = await formatsApi.createFormat(data)
    formats.value.unshift(response.data.data)
    return response.data.data
  }

  async function updateFormat(id: string, data: Partial<DocumentFormat>) {
    const response = await formatsApi.updateFormat(id, data)
    const index = formats.value.findIndex((f) => f.id === id)
    if (index !== -1) formats.value[index] = response.data.data
    currentFormat.value = response.data.data
    return response.data.data
  }

  async function deleteFormat(id: string) {
    await formatsApi.deleteFormat(id)
    formats.value = formats.value.filter((f) => f.id !== id)
  }

  async function generateNumber(id: string, params = {}) {
    const response = await formatsApi.generateNumber(id, params)
    return response.data.data
  }

  async function activateFormat(id: string) {
    await formatsApi.activateFormat(id)
    const format = formats.value.find((f) => f.id === id)
    if (format) format.status = 'active'
  }

  async function deactivateFormat(id: string) {
    await formatsApi.deactivateFormat(id)
    const format = formats.value.find((f) => f.id === id)
    if (format) format.status = 'deprecated'
  }

  async function duplicateFormat(id: string) {
    const response = await formatsApi.duplicateFormat(id)
    formats.value.unshift(response.data.data)
    return response.data.data
  }

  return {
    formats, categories, segmentTypes, currentFormat,
    loading, pagination, activeFormats,
    fetchFormats, fetchAllFormats, fetchFormat, fetchCategories, fetchSegmentTypes,
    createCategory, createFormat, updateFormat, deleteFormat,
    generateNumber, activateFormat, deactivateFormat, duplicateFormat,
  }
})
