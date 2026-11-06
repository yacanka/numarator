<!-- src/components/format/FormatPreview.vue -->
<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import { NCard, NText, NSpin, NTag, NSpace, NButton, NIcon } from 'naive-ui'
import { RefreshOutline } from '@vicons/ionicons5'
import { formatsApi } from '@/api/formats'
import type { SegmentConfig } from '@/types'

const props = defineProps<{
  segments: SegmentConfig[]
  formatId?: string
  draft?: boolean
  sequenceStart?: number
}>()

const preview = ref('')
const loading = ref(false)
let latestPreviewRequest = 0

const segmentColors: Record<string, string> = {
  static: '#595959',
  date: '#096dd9',
  sequence: '#389e0d',
  yearly_sequence: '#389e0d',
  random: '#d46b08',
  checksum: '#cf1322',
  context: '#531dab',
  separator: '#8c8c8c',
}

async function fetchPreview() {
  const requestId = ++latestPreviewRequest
  if (props.draft || !props.formatId) {
    loading.value = false
    preview.value = props.segments.map(buildLocalPreview).join('')
    return
  }

  loading.value = true
  try {
    const res = await formatsApi.previewFormat(props.formatId)
    if (requestId === latestPreviewRequest) preview.value = res.data.data.preview
  } catch {
    if (requestId === latestPreviewRequest) preview.value = props.segments.map(buildLocalPreview).join('')
  } finally {
    if (requestId === latestPreviewRequest) loading.value = false
  }
}

function buildLocalPreview(seg: SegmentConfig): string {
  const config = seg.config || {}
  switch (seg.type) {
    case 'static': return config.value || 'TEXT'
    case 'date': return getDatePreview(config.format || 'YYYY')
    case 'sequence':
    case 'yearly_sequence': return String(props.sequenceStart ?? 1).padStart(config.padding ?? 4, '0')
    case 'random': return 'X'.repeat(config.length || 6)
    case 'checksum': return 'C'
    case 'context': return `[${(config.key || 'CTX').toUpperCase()}]`
    case 'separator': return config.value || '-'
    default: return '?'
  }
}

function getDatePreview(format: string): string {
  const now = new Date()
  const map: Record<string, string> = {
    'YYYY': now.getFullYear().toString(),
    'YY': now.getFullYear().toString().slice(2),
    'MM': String(now.getMonth() + 1).padStart(2, '0'),
    'DD': String(now.getDate()).padStart(2, '0'),
    'YYYYMMDD': `${now.getFullYear()}${String(now.getMonth()+1).padStart(2,'0')}${String(now.getDate()).padStart(2,'0')}`,
    'YYYYMM': `${now.getFullYear()}${String(now.getMonth()+1).padStart(2,'0')}`,
    'DDMMYYYY': `${String(now.getDate()).padStart(2,'0')}${String(now.getMonth()+1).padStart(2,'0')}${now.getFullYear()}`,
    'Q': String(Math.ceil((now.getMonth() + 1) / 3)),
    'WW': String(getWeekNumber(now)).padStart(2, '0'),
  }
  return map[format] || format
}

function getWeekNumber(date: Date): number {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()))
  const dayNum = d.getUTCDay() || 7
  d.setUTCDate(d.getUTCDate() + 4 - dayNum)
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1))
  return Math.ceil((((d.valueOf() - yearStart.valueOf()) / 86400000) + 1) / 7)
}

// Debounced watch
let timer: ReturnType<typeof setTimeout>
watch(
  () => [props.segments, props.formatId, props.draft, props.sequenceStart],
  () => {
    clearTimeout(timer)
    latestPreviewRequest += 1
    if (props.draft || !props.formatId) {
      fetchPreview()
      return
    }
    timer = setTimeout(fetchPreview, 500)
  },
  { deep: true, immediate: true }
)

onBeforeUnmount(() => {
  clearTimeout(timer)
  latestPreviewRequest += 1
})
</script>

<template>
  <n-card size="small">
    <template #header>
      <n-space align="center" justify="space-between">
        <n-text strong>Önizleme</n-text>
        <n-button text size="small" @click="fetchPreview" :loading="loading">
          <template #icon><n-icon :component="RefreshOutline" /></template>
        </n-button>
      </n-space>
    </template>

    <n-spin :show="loading">
      <!-- Segment Map -->
      <div class="preview-segments">
        <template v-for="(seg, i) in segments" :key="i">
          <div
            class="preview-segment"
            :style="{ borderColor: segmentColors[seg.type] }"
          >
            <div
              class="preview-segment-label"
              :style="{ background: segmentColors[seg.type] }"
            >
              {{ seg.label || seg.type }}
            </div>
            <div class="preview-segment-value">
              {{ buildLocalPreview(seg) }}
            </div>
          </div>
        </template>
      </div>

      <!-- Full Preview -->
      <div class="preview-full" v-if="preview">
        {{ preview }}
      </div>
      <div class="preview-full preview-empty" v-else-if="segments.length === 0">
        Segment ekleyerek önizleme oluşturun
      </div>
    </n-spin>
  </n-card>
</template>

<style scoped>
.preview-segments {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 16px;
  min-height: 60px;
  align-items: flex-start;
}

.preview-segment {
  border: 2px solid #d9d9d9;
  border-radius: 6px;
  overflow: hidden;
  min-width: 40px;
}

.preview-segment-label {
  font-size: 9px;
  color: white;
  padding: 2px 6px;
  text-transform: uppercase;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.preview-segment-value {
  padding: 4px 8px;
  font-family: monospace;
  font-size: 14px;
  font-weight: 600;
  color: var(--app-text-color);
  white-space: nowrap;
}

.preview-full {
  background: var(--n-border-color);
  color: var(--app-text-color);
  font-family: 'Courier New', monospace;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 3px;
  text-align: center;
  padding: 20px;
  border-radius: 8px;
  word-break: break-all;
}

.preview-empty {
  color: #555;
  font-family: inherit;
  font-size: 14px;
  font-weight: normal;
  letter-spacing: normal;
}
</style>