<!-- src/views/DocumentsView.vue -->
<script setup lang="ts">
import { computed, h, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  NButton, NCard, NDataTable, NInput, NSelect, NSpace,
  NStatistic, NText, useMessage, type DataTableColumns,
} from 'naive-ui'
import { documentsApi, type DocumentFilters } from '@/api/documents'
import { useFormatsStore } from '@/stores/formats'
import type { GeneratedDocument } from '@/types'

const route = useRoute()
const message = useMessage()
const formatsStore = useFormatsStore()
const SEARCH_DEBOUNCE_MS = 300

const documents = ref<GeneratedDocument[]>([])
const loading = ref(false)
const searchQuery = ref('')
const statusFilter = ref('all')
const formatFilter = ref<string | null>(normalizeFormatId(route.query.format_id))
const categoryFilter = ref<number | null>(null)
const updatingStatusIds = ref<string[]>([])
const pagination = ref({ page: 1, pageSize: 20, itemCount: 0 })
let searchDebounceTimer: ReturnType<typeof setTimeout> | undefined
let latestFetchId = 0

const documentStatusOptions = [
  { label: 'Aktif', value: 'active' },
  { label: 'Kullanıldı', value: 'used' },
  { label: 'İptal', value: 'cancelled' },
  { label: 'Süresi Doldu', value: 'expired' },
]

const statusOptions = [
  { label: 'Tümü', value: 'all' },
  ...documentStatusOptions,
]

const formatOptions = computed(() =>
  formatsStore.formats.map((format) => ({ label: `${format.code} - ${format.name}`, value: format.id }))
)

const categoryOptions = computed(() =>
  formatsStore.categories.map((category) => ({ label: category.name, value: category.id }))
)

const columns: DataTableColumns<GeneratedDocument> = [
  { title: 'Numara', key: 'document_number', render: renderDocumentNumber },
  { title: 'Format', key: 'format_name', render: renderFormat },
  { title: 'Durum', key: 'status', render: renderStatus },
  { title: 'Sıra', key: 'sequence_value', width: 90 },
  { title: 'Oluşturan', key: 'generated_by_username' },
  { title: 'Oluşturulma', key: 'generated_at', render: renderDate },
]

onMounted(async () => {
  formatsStore.fetchCategories().catch(() => message.error('Format kategorileri alınamadı'))
  await formatsStore.fetchFormats()
  await fetchDocuments()
})

watch(searchQuery, () => {
  pagination.value.page = 1
  clearSearchDebounce()
  searchDebounceTimer = setTimeout(fetchDocuments, SEARCH_DEBOUNCE_MS)
})

watch([statusFilter, formatFilter, categoryFilter], () => {
  pagination.value.page = 1
  fetchDocuments()
})

watch(() => route.query.format_id, (formatId) => {
  formatFilter.value = normalizeFormatId(formatId)
})

onBeforeUnmount(() => {
  clearSearchDebounce()
  latestFetchId += 1
})

function normalizeFormatId(formatId: unknown) {
  return typeof formatId === 'string' ? formatId : null
}

function clearSearchDebounce() {
  if (searchDebounceTimer === undefined) return
  clearTimeout(searchDebounceTimer)
  searchDebounceTimer = undefined
}

function buildFilters(): DocumentFilters {
  return {
    page: pagination.value.page,
    page_size: pagination.value.pageSize,
    search: searchQuery.value || undefined,
    format_id: formatFilter.value || undefined,
    category: categoryFilter.value ?? undefined,
    status: statusFilter.value === 'all' ? undefined : statusFilter.value,
  }
}

async function fetchDocuments() {
  clearSearchDebounce()
  const fetchId = ++latestFetchId
  loading.value = true
  try {
    const response = await documentsApi.getDocuments(buildFilters())
    if (fetchId !== latestFetchId) return
    documents.value = response.data.data
    pagination.value.itemCount = response.data.pagination.count
  } catch (err: any) {
    if (fetchId !== latestFetchId) return
    message.error(err.response?.data?.error?.message || 'Belge numaraları alınamadı')
  } finally {
    if (fetchId === latestFetchId) loading.value = false
  }
}

function handlePageChange(page: number) {
  pagination.value.page = page
  fetchDocuments()
}

function handlePageSizeChange(pageSize: number) {
  pagination.value.page = 1
  pagination.value.pageSize = pageSize
  fetchDocuments()
}

function renderDocumentNumber(row: GeneratedDocument) {
  return h(NText, { strong: true, style: 'font-family: monospace; letter-spacing: 1px' }, {
    default: () => row.document_number,
  })
}

function renderFormat(row: GeneratedDocument) {
  return h('div', [
    h(NText, { strong: true }, { default: () => row.format_code }),
    h('br'),
    h(NText, { depth: 3, style: 'font-size: 12px' }, { default: () => row.format_name }),
  ])
}

function renderStatus(row: GeneratedDocument) {
  return h(NSelect, {
    value: row.status,
    options: documentStatusOptions,
    size: 'small',
    disabled: isStatusUpdating(row.id),
    loading: isStatusUpdating(row.id),
    style: 'width: 140px',
    onUpdateValue: (value) => handleStatusChange(row, value),
  })
}

function renderDate(row: GeneratedDocument) {
  return new Date(row.generated_at).toLocaleString('tr-TR')
}

function isStatusUpdating(id: string) {
  return updatingStatusIds.value.includes(id)
}

async function handleStatusChange(row: GeneratedDocument, nextStatus: GeneratedDocument['status']) {
  if (row.status === nextStatus) return
  updatingStatusIds.value = [...updatingStatusIds.value, row.id]
  try {
    const response = await documentsApi.updateStatus(row.id, nextStatus)
    replaceDocument(response.data.data)
    message.success('Durum güncellendi')
  } catch (err: any) {
    message.error(err.response?.data?.error?.message || 'Durum güncellenemedi')
  } finally {
    updatingStatusIds.value = updatingStatusIds.value.filter((id) => id !== row.id)
  }
}

function replaceDocument(updatedDocument: GeneratedDocument) {
  const index = documents.value.findIndex((item) => item.id === updatedDocument.id)
  if (index !== -1) documents.value[index] = updatedDocument
}

</script>

<template>
  <div>
    <n-space align="center" justify="space-between" style="margin-bottom: 24px">
      <div>
        <n-text tag="h1" style="margin: 0; font-size: 24px; font-weight: 600">
          Belgeler
        </n-text>
        <n-text depth="3">Oluşturulan belge numaralarını buradan takip edebilirsiniz.</n-text>
      </div>
      <n-statistic label="Toplam" :value="pagination.itemCount" />
    </n-space>

    <n-card size="small" style="margin-bottom: 16px">
      <n-space>
        <n-input v-model:value="searchQuery" clearable placeholder="Numara ara..." style="width: 240px" />
        <n-select v-model:value="statusFilter" :options="statusOptions" style="width: 160px" />
        <n-select
          v-model:value="categoryFilter"
          :options="categoryOptions"
          clearable
          filterable
          placeholder="Format kategorisi seçin"
          style="width: 240px"
        />
        <n-select
          v-model:value="formatFilter"
          :options="formatOptions"
          clearable
          filterable
          placeholder="Format seçin"
          style="width: 280px"
        />
        <n-button :loading="loading" @click="fetchDocuments">Yenile</n-button>
      </n-space>
    </n-card>

    <n-card>
      <n-data-table
        remote
        :columns="columns"
        :data="documents"
        :loading="loading"
        :pagination="{
          page: pagination.page,
          pageSize: pagination.pageSize,
          itemCount: pagination.itemCount,
          showSizePicker: true,
          pageSizes: [10, 20, 50, 100],
          onChange: handlePageChange,
          onUpdatePageSize: handlePageSizeChange,
        }"
      />
    </n-card>
  </div>
</template>
