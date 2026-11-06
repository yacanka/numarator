<!-- src/components/document/GenerateModal.vue -->
<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import {
  NModal, NButton, NSpace, NText, NInput,
  NForm, NFormItem, NInputNumber, NTag, NDivider,
  NIcon,
} from 'naive-ui'
import { CopyOutline, DownloadOutline, ListOutline } from '@vicons/ionicons5'
import { useRouter } from 'vue-router'
import { useFormatsStore } from '@/stores/formats'
import type { DocumentFormat, GeneratedDocument } from '@/types'
import { useMessage } from 'naive-ui'

const props = defineProps<{
  format: DocumentFormat
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  generated: [documents: GeneratedDocument[]]
}>()

const router = useRouter()
const message = useMessage()
const store = useFormatsStore()
const loading = ref(false)
const count = ref(1)
const contextData = ref<Record<string, string>>({})
const generatedDocs = ref<GeneratedDocument[]>([])
let generationVersion = 0

watch(() => [props.show, props.format.id], resetGeneration, { flush: 'sync' })
onBeforeUnmount(resetGeneration)

function resetGeneration() {
  generationVersion += 1
  generatedDocs.value = []
  contextData.value = {}
  count.value = 1
  loading.value = false
}

// Extract context keys from format segments. List payloads may omit segments_config,
// so the modal must stay render-safe until the detail payload is available.
const contextKeys = computed(() => {
  const segments = props.format.segments_config ?? []

  return segments
    .filter((segment) => segment.type === 'context')
    .map((segment) => ({
      key: String(segment.config?.key ?? ''),
      default: String(segment.config?.default ?? ''),
    }))
    .filter((contextKey) => contextKey.key.length > 0)
})

async function generate() {
  if (loading.value || !props.show) return
  const requestVersion = ++generationVersion
  loading.value = true
  try {
    const result = await store.generateNumber(props.format.id, {
      count: count.value,
      context_data: { ...contextData.value },
    })

    // Closing or switching the modal must not restore another generation session's results.
    if (requestVersion !== generationVersion) return
    generatedDocs.value = Array.isArray(result) ? result : [result]
    emit('generated', generatedDocs.value)

    message.success(`${generatedDocs.value.length} numara oluşturuldu!`)
  } catch (err: any) {
    if (requestVersion === generationVersion) {
      message.error(err.response?.data?.error?.message || 'Oluşturma hatası')
    }
  } finally {
    if (requestVersion === generationVersion) loading.value = false
  }
}

async function copyAll() {
  const numbers = generatedDocs.value.map((d) => d.document_number).join('\n')
  await navigator.clipboard.writeText(numbers)
  message.success('Tümü kopyalandı!')
}

async function copyOne(number: string) {
  await navigator.clipboard.writeText(number)
  message.success('Kopyalandı!')
}

function csvCell(value: string) {
  // Quoting preserves CSV structure; a text prefix also prevents spreadsheet formulas.
  const text = /^[\s]*[=+\-@]|^[\t\r\n]/.test(value) ? `'${value}` : value
  return `"${text.replace(/"/g, '""')}"`
}

function downloadCSV() {
  const csv = 'Document Number,Status,Generated At\n' +
    generatedDocs.value.map((d) =>
      [d.document_number, d.status, d.generated_at].map(csvCell).join(',')
    ).join('\n')

  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${props.format.code}_${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

function openDocumentsPage() {
  handleClose()
  router.push({ path: '/documents', query: { format_id: props.format.id } })
}

function handleClose() {
  resetGeneration()
  emit('update:show', false)
}

function handleVisibilityChange(show: boolean) {
  if (!show) handleClose()
  else emit('update:show', true)
}
</script>

<template>
  <n-modal
    :show="show"
    @update:show="handleVisibilityChange"
    preset="card"
    style="width: 640px"
    :mask-closable="false"
  >
    <template #header>
      <n-space align="center">
        <n-text strong>Belge Numarası Oluştur</n-text>
        <n-tag type="info" style="font-family: monospace">{{ format.code }}</n-tag>
      </n-space>
    </template>

    <n-form label-placement="top" size="small">
      <!-- Context Fields -->
      <template v-if="contextKeys.length > 0">
        <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
          Bu format dinamik değer gerektiriyor:
        </n-text>
        <n-form-item
          v-for="ctx in contextKeys"
          :key="ctx.key"
          :label="ctx.key"
        >
          <n-input
            v-model:value="contextData[ctx.key]"
            :placeholder="ctx.default || ctx.key"
          />
        </n-form-item>
        <n-divider />
      </template>

      <!-- Count -->
      <n-form-item label="Kaç Adet Oluşturulsun?">
        <n-input-number
          v-model:value="count"
          :min="1"
          :max="100"
          style="width: 200px"
        />
        <n-text depth="3" style="margin-left: 12px; font-size: 12px">
          Maksimum 100 adet
        </n-text>
      </n-form-item>
    </n-form>

    <!-- Generate Button -->
    <n-button
      type="primary"
      block
      :loading="loading"
      @click="generate"
      style="margin-bottom: 16px"
    >
      {{ loading ? 'Oluşturuluyor...' : `${count} Numara Oluştur` }}
    </n-button>

    <!-- Results -->
    <template v-if="generatedDocs.length > 0">
      <n-divider>Oluşturulan Numaralar</n-divider>

      <n-space style="margin-bottom: 12px">
        <n-button size="small" @click="copyAll">
          <template #icon><n-icon :component="CopyOutline" /></template>
          Tümünü Kopyala
        </n-button>
        <n-button size="small" @click="downloadCSV">
          <template #icon><n-icon :component="DownloadOutline" /></template>
          CSV İndir
        </n-button>
        <n-button size="small" @click="openDocumentsPage">
          <template #icon><n-icon :component="ListOutline" /></template>
          Belgelerde Göster
        </n-button>
      </n-space>

      <div class="generated-list">
        <div
          v-for="doc in generatedDocs"
          :key="doc.id"
          class="generated-item"
        >
          <n-text strong style="font-family: monospace; font-size: 16px; letter-spacing: 2px">
            {{ doc.document_number }}
          </n-text>
          <n-button text size="small" @click="copyOne(doc.document_number)">
            <template #icon><n-icon :component="CopyOutline" /></template>
          </n-button>
        </div>
      </div>
    </template>

    <template #footer>
      <n-space justify="end">
        <n-button @click="handleClose">Kapat</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<style scoped>
.generated-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 300px;
  overflow-y: auto;
}

.generated-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: var(--n-border-color);
  border-radius: 6px;
  color: var(--n-text-color);
}
</style>
