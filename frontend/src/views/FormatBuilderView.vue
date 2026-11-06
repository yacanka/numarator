<!-- src/views/FormatBuilderView.vue -->
<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  NCard, NSpace, NGrid, NGi, NButton, NInput, NForm,
  NFormItem, NSelect, NTag, NText, NDivider, NModal,
  NIcon, NSpin, NAlert, NInputNumber, useMessage,
} from 'naive-ui'
import { SaveOutline, PlayOutline, ArrowBackOutline, CopyOutline } from '@vicons/ionicons5'
import { useFormatsStore } from '@/stores/formats'
import SegmentPalette from '@/components/format/SegmentPalette.vue'
import SegmentEditor from '@/components/format/SegmentEditor.vue'
import FormatPreview from '@/components/format/FormatPreview.vue'
import type { SegmentConfig, DocumentFormat, ResetPeriod, FormatStatus, SegmentType } from '@/types'

const router = useRouter()
const route = useRoute()
const message = useMessage()
const store = useFormatsStore()

const isEdit = computed(() => Boolean(route.params.id))
const loading = ref(false)
const saving = ref(false)
const savingCategory = ref(false)
const generating = ref(false)
const generatedNumber = ref('')
const formRef = ref()
const form = ref<Partial<DocumentFormat>>(createEmptyFormat())
const segments = ref<SegmentConfig[]>([])
const editingSegmentIndex = ref<number | null>(null)
const showSegmentEditor = ref(false)
const newCategoryName = ref('')
let latestFormatLoad = 0

const statusOptions = [
  { label: 'Taslak', value: 'draft' },
  { label: 'Aktif', value: 'active' },
  { label: 'Kullanım Dışı', value: 'deprecated' },
]

const resetPeriodOptions = [
  { label: 'Hiçbir Zaman', value: 'never' },
  { label: 'Günlük', value: 'daily' },
  { label: 'Haftalık', value: 'weekly' },
  { label: 'Aylık', value: 'monthly' },
  { label: 'Çeyreklik', value: 'quarterly' },
  { label: 'Yıllık', value: 'yearly' },
]

const categoryOptions = computed(() =>
  store.categories.map((category) => ({ label: category.name, value: category.id }))
)

const formRules = {
  code: [
    { required: true, message: 'Kod gereklidir' },
    { pattern: /^[A-Z0-9_]+$/, message: 'Sadece büyük harf, rakam ve alt çizgi' },
    { min: 2, max: 50, message: '2-50 karakter' },
  ],
  name: [{ required: true, message: 'İsim gereklidir' }],
}

onMounted(loadReferenceData)
onBeforeUnmount(() => { latestFormatLoad += 1 })

watch(
  () => route.params.id,
  () => loadFormat(),
  { immediate: true }
)

function createEmptyFormat(): Partial<DocumentFormat> {
  return {
    code: '',
    name: '',
    description: '',
    status: 'draft' as FormatStatus,
    category: null,
    segments_config: [],
    sequence_reset_period: 'never' as ResetPeriod,
    sequence_start: 1,
    sequence_step: 1,
    validation_regex: '',
    tags: [],
  }
}

async function loadReferenceData() {
  await Promise.all([store.fetchCategories(), store.fetchSegmentTypes()])
}

async function loadFormat() {
  const loadId = ++latestFormatLoad
  const formatId = route.params.id as string | undefined
  generatedNumber.value = ''
  closeSegmentEditor()
  resetBuilder()

  if (!formatId) {
    loading.value = false
    return
  }

  loading.value = true
  try {
    const loadedFormat = await store.fetchFormat(formatId)
    if (loadId === latestFormatLoad) applyLoadedFormat(loadedFormat)
  } catch (err: any) {
    if (loadId === latestFormatLoad) {
      message.error(err.response?.data?.error?.message || 'Format detayları alınamadı')
    }
  } finally {
    if (loadId === latestFormatLoad) loading.value = false
  }
}

function applyLoadedFormat(loadedFormat: DocumentFormat) {
  form.value = { ...createEmptyFormat(), ...loadedFormat }
  segments.value = sortSegments(loadedFormat.segments_config || [])
}

function resetBuilder() {
  form.value = createEmptyFormat()
  segments.value = []
}

function sortSegments(items: SegmentConfig[]): SegmentConfig[] {
  return items
    .map((segment) => ({ ...segment, config: { ...(segment.config || {}) } }))
    .sort((left, right) => (left.order ?? 0) - (right.order ?? 0))
    .map((segment, index) => ({ ...segment, order: index }))
}

function addSegment(segmentType: string) {
  segments.value.push({
    type: segmentType as SegmentType,
    config: createDefaultSegmentConfig(segmentType),
    order: segments.value.length,
    label: store.segmentTypes.find((segment) => segment.type === segmentType)?.label || segmentType,
  })
}

function createDefaultSegmentConfig(segmentType: string): Record<string, any> {
  const defaultConfigs: Record<string, Record<string, any>> = {
    static: { value: 'DOC' },
    date: { format: 'YYYY' },
    sequence: { padding: 4, start: 1, step: 1 },
    yearly_sequence: { padding: 4 },
    random: { length: 6, char_type: 'alphanumeric' },
    checksum: { algorithm: 'mod10' },
    context: { key: 'department', default: 'GEN' },
    separator: { value: '-' },
  }
  return { ...(defaultConfigs[segmentType] || {}) }
}

function editSegment(index: number) {
  editingSegmentIndex.value = index
  showSegmentEditor.value = true
}

function removeSegment(index: number) {
  segments.value.splice(index, 1)
  syncSegmentOrder()
}

function moveSegment(from: number, to: number) {
  const item = segments.value.splice(from, 1)[0]
  segments.value.splice(to, 0, item)
  syncSegmentOrder()
}

function updateSegment(index: number, updated: SegmentConfig) {
  segments.value[index] = { ...updated, order: index }
  closeSegmentEditor()
}

function closeSegmentEditor() {
  showSegmentEditor.value = false
  editingSegmentIndex.value = null
}

function syncSegmentOrder() {
  segments.value.forEach((segment, index) => (segment.order = index))
}

async function handleCreateCategory() {
  const name = newCategoryName.value.trim()
  if (!name) return

  savingCategory.value = true
  try {
    const category = await store.createCategory({ name, code: buildCategoryCode(name) })
    form.value.category = category.id
    newCategoryName.value = ''
    message.success('Kategori oluşturuldu')
  } catch (err: any) {
    message.error(err.response?.data?.error?.message || 'Kategori oluşturulamadı')
  } finally {
    savingCategory.value = false
  }
}

function buildCategoryCode(name: string) {
  const asciiName = name.replace(/ı/g, 'i').replace(/İ/g, 'I')
  const normalized = asciiName.normalize('NFD').replace(/[\u0300-\u036f]/g, '')
  const code = normalized.toUpperCase().replace(/[^A-Z0-9]+/g, '_').replace(/^_|_$/g, '')
  return code || 'CATEGORY'
}

async function handleSave() {
  if (!(await validateBeforeSave())) return

  saving.value = true
  try {
    const data = { ...form.value, segments_config: segments.value }
    await saveFormat(data)
  } catch (err: any) {
    message.error(err.response?.data?.error?.message || 'Kaydetme hatası')
  } finally {
    saving.value = false
  }
}

async function validateBeforeSave(): Promise<boolean> {
  try {
    await formRef.value?.validate()
  } catch {
    message.error('Formu kontrol edin')
    return false
  }

  if (segments.value.length > 0) return true
  message.error('En az bir segment ekleyin')
  return false
}

async function saveFormat(data: Partial<DocumentFormat>) {
  if (isEdit.value) {
    const updated = await store.updateFormat(route.params.id as string, data)
    applyLoadedFormat(updated)
    message.success('Format güncellendi')
    return
  }

  const created = await store.createFormat(data)
  message.success('Format oluşturuldu')
  router.replace(`/formats/${created.id}/edit`)
}

async function handleGenerate() {
  if (!isEdit.value) {
    message.warning('Önce formatı kaydedin')
    return
  }

  generating.value = true
  try {
    const result = await store.generateNumber(route.params.id as string, { context_data: {} })
    generatedNumber.value = result.document_number
    message.success('Numara oluşturuldu!')
  } catch (err: any) {
    message.error(err.response?.data?.error?.message || 'Oluşturma hatası')
  } finally {
    generating.value = false
  }
}

async function copyToClipboard() {
  if (!generatedNumber.value) return
  await navigator.clipboard.writeText(generatedNumber.value)
  message.success('Kopyalandı!')
}

function handleBack() {
  router.push('/formats')
}
</script>

<template>
  <div>
    <n-spin :show="loading">
      <n-space align="center" justify="space-between" style="margin-bottom: 24px">
        <n-space align="center">
          <n-button text @click="handleBack">
            <template #icon><n-icon :component="ArrowBackOutline" /></template>
          </n-button>
          <n-text tag="h1" style="margin: 0; font-size: 20px; font-weight: 600">
            {{ isEdit ? 'Format Düzenle' : 'Yeni Format Oluştur' }}
          </n-text>
          <n-tag v-if="form.status" :type="form.status === 'active' ? 'success' : 'default'">
            {{ statusOptions.find((status) => status.value === form.status)?.label }}
          </n-tag>
        </n-space>

        <n-space>
          <n-button :loading="generating" :disabled="!isEdit" secondary @click="handleGenerate">
            <template #icon><n-icon :component="PlayOutline" /></template>
            Test Et
          </n-button>
          <n-button type="primary" :loading="saving" @click="handleSave">
            <template #icon><n-icon :component="SaveOutline" /></template>
            Kaydet
          </n-button>
        </n-space>
      </n-space>

      <n-alert
        v-if="generatedNumber"
        type="success"
        style="margin-bottom: 20px"
        closable
        @close="generatedNumber = ''"
      >
        <template #header>
          <n-space align="center">
            <n-text>Oluşturulan Numara:</n-text>
            <n-text strong style="font-family: monospace; font-size: 18px; letter-spacing: 2px">
              {{ generatedNumber }}
            </n-text>
            <n-button text size="small" @click="copyToClipboard">
              <template #icon><n-icon :component="CopyOutline" /></template>
              Kopyala
            </n-button>
          </n-space>
        </template>
      </n-alert>

      <n-grid :cols="3" :x-gap="20" :y-gap="20" responsive="screen" :item-responsive="true">
        <n-gi span="3 l:1">
          <n-card title="Format Bilgileri" size="small">
            <n-form ref="formRef" :model="form" :rules="formRules" label-placement="top" size="small">
              <n-form-item label="Format Kodu" path="code">
                <n-input
                  v-model:value="form.code"
                  placeholder="INVOICE_2024"
                  :input-props="{ style: 'font-family: monospace; text-transform: uppercase' }"
                  @input="(value: string) => form.code = value.toUpperCase()"
                />
              </n-form-item>

              <n-form-item label="Format Adı" path="name">
                <n-input v-model:value="form.name" placeholder="Fatura Numarası" />
              </n-form-item>

              <n-form-item label="Açıklama">
                <n-input v-model:value="form.description" type="textarea" :rows="2" placeholder="Format hakkında açıklama" />
              </n-form-item>

              <n-form-item label="Kategori">
                <n-space vertical style="width: 100%">
                  <n-select
                    v-model:value="form.category"
                    :options="categoryOptions"
                    clearable
                    placeholder="Kategori seçin"
                  />
                  <n-space :wrap="false">
                    <n-input
                      v-model:value="newCategoryName"
                      placeholder="Yeni kategori adı"
                      @keyup.enter="handleCreateCategory"
                    />
                    <n-button
                      :loading="savingCategory"
                      :disabled="!newCategoryName.trim()"
                      @click="handleCreateCategory"
                    >
                      Ekle
                    </n-button>
                  </n-space>
                </n-space>
              </n-form-item>

              <n-form-item label="Durum">
                <n-select v-model:value="form.status" :options="statusOptions" />
              </n-form-item>

              <n-divider>Sıra Numarası Ayarları</n-divider>

              <n-form-item label="Sıfırlama Periyodu">
                <n-select v-model:value="form.sequence_reset_period" :options="resetPeriodOptions" />
              </n-form-item>

              <n-grid :cols="2" :x-gap="12">
                <n-gi>
                  <n-form-item label="Başlangıç Değeri">
                    <n-input-number v-model:value="form.sequence_start" :min="1" style="width: 100%" />
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="Adım">
                    <n-input-number v-model:value="form.sequence_step" :min="1" style="width: 100%" />
                  </n-form-item>
                </n-gi>
              </n-grid>

              <n-form-item label="Doğrulama (Regex)">
                <n-input
                  v-model:value="form.validation_regex"
                  placeholder="^[A-Z]{3}-\d{4}$"
                  :input-props="{ style: 'font-family: monospace' }"
                />
              </n-form-item>
            </n-form>
          </n-card>

          <n-card title="Segment Türleri" size="small" style="margin-top: 16px">
            <segment-palette :segment-types="store.segmentTypes" @add="addSegment" />
          </n-card>
        </n-gi>

        <n-gi span="3 l:2">
          <format-preview :segments="segments" :draft="true" :sequence-start="form.sequence_start" :format-id="isEdit ? (route.params.id as string) : undefined" />

          <n-card title="Segment Yapısı" size="small" style="margin-top: 16px">
            <template #header-extra>
              <n-text depth="3" style="font-size: 12px">Segmentleri oklarla sırala</n-text>
            </template>

            <div v-if="segments.length === 0" class="empty-segments">
              <n-text depth="3">← Sol panelden segment ekleyin</n-text>
            </div>

            <div v-else class="segment-list">
              <TransitionGroup name="segment">
                <div v-for="(segment, index) in segments" :key="`${segment.type}-${index}`" class="segment-item">
                  <div class="segment-handle">{{ index + 1 }}</div>

                  <div class="segment-info">
                    <n-tag size="small" :type="getSegmentTagType(segment.type)" style="font-family: monospace">
                      {{ segment.type }}
                    </n-tag>
                    <n-text style="margin-left: 8px">{{ segment.label || segment.type }}</n-text>
                    <n-text depth="3" style="margin-left: 8px; font-size: 12px">
                      {{ getSegmentDescription(segment) }}
                    </n-text>
                  </div>

                  <n-space size="small">
                    <n-button text size="small" :disabled="index === 0" @click="moveSegment(index, index - 1)">↑</n-button>
                    <n-button text size="small" :disabled="index === segments.length - 1" @click="moveSegment(index, index + 1)">↓</n-button>
                    <n-button text size="small" type="info" @click="editSegment(index)">Düzenle</n-button>
                    <n-button text size="small" type="error" @click="removeSegment(index)">Kaldır</n-button>
                  </n-space>
                </div>
              </TransitionGroup>
            </div>
          </n-card>
        </n-gi>
      </n-grid>
    </n-spin>

    <n-modal
      v-model:show="showSegmentEditor"
      preset="card"
      :title="`Segment Düzenle: ${editingSegmentIndex !== null ? segments[editingSegmentIndex]?.type : ''}`"
      style="width: 600px"
      @after-leave="editingSegmentIndex = null"
    >
      <segment-editor
        v-if="editingSegmentIndex !== null"
        :segment="segments[editingSegmentIndex]"
        @update="(segment) => updateSegment(editingSegmentIndex!, segment)"
        @cancel="closeSegmentEditor"
      />
    </n-modal>
  </div>
</template>

<script lang="ts">
type TagType = 'info' | 'success' | 'warning' | 'error' | 'default' | 'primary'

function getSegmentTagType(type: SegmentType): TagType {
  const types: Record<SegmentType, TagType> = {
    static: 'default',
    date: 'info',
    sequence: 'success',
    yearly_sequence: 'success',
    random: 'warning',
    checksum: 'error',
    context: 'primary',
    separator: 'default',
  }
  return types[type] || 'default'
}

function getSegmentDescription(segment: SegmentConfig) {
  const config = segment.config || {}
  switch (segment.type) {
    case 'static': return `"${config.value || ''}"`
    case 'date': return config.format || 'YYYY'
    case 'sequence': return `${config.padding || 4} basamak`
    case 'yearly_sequence': return `${config.padding || 4} basamak / yıllık`
    case 'random': return `${config.length || 6} ${config.char_type || 'alphanumeric'}`
    case 'checksum': return config.algorithm || 'mod10'
    case 'context': return `key: ${config.key || ''}`
    case 'separator': return `"${config.value || '-'}"`
    default: return ''
  }
}
</script>

<style scoped>
.empty-segments {
  text-align: center;
  padding: 40px;
  border: 2px dashed #d9d9d9;
  border-radius: 8px;
}

.segment-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.segment-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: var(--app-content-bg);
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  transition: all 0.2s;
}

.segment-item:hover {
  border-color: #1890ff;
  background: var(--app-surface-bg);
}

.segment-handle {
  width: 28px;
  color: #8c8c8c;
  font-size: 13px;
  font-weight: 700;
  text-align: center;
  user-select: none;
}

.segment-info {
  flex: 1;
  display: flex;
  align-items: center;
}

.segment-enter-active,
.segment-leave-active {
  transition: all 0.3s ease;
}

.segment-enter-from,
.segment-leave-to {
  opacity: 0;
  transform: translateX(-20px);
}
</style>
