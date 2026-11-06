<!-- src/components/format/SegmentEditor.vue -->
<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  NForm, NFormItem, NInput, NSelect, NInputNumber,
  NButton, NSpace, NText, NDivider, NSwitch,
} from 'naive-ui'
import type { SegmentConfig } from '@/types'

const props = defineProps<{
  segment: SegmentConfig
}>()

const emit = defineEmits<{
  update: [segment: SegmentConfig]
  cancel: []
}>()

const localSegment = ref<SegmentConfig>(JSON.parse(JSON.stringify(props.segment)))

const dateFormatOptions = [
  { label: 'YYYY (2024)', value: 'YYYY' },
  { label: 'YY (24)', value: 'YY' },
  { label: 'MM (01)', value: 'MM' },
  { label: 'DD (15)', value: 'DD' },
  { label: 'YYYYMMDD (20240115)', value: 'YYYYMMDD' },
  { label: 'YYYYMM (202401)', value: 'YYYYMM' },
  { label: 'DDMMYYYY (15012024)', value: 'DDMMYYYY' },
  { label: 'Q (Çeyrek: 1,2,3,4)', value: 'Q' },
  { label: 'WW (Hafta numarası)', value: 'WW' },
]

const charTypeOptions = [
  { label: 'Sayısal (0-9)', value: 'numeric' },
  { label: 'Alfabetik (A-Z)', value: 'alpha' },
  { label: 'Alfanümerik (A-Z, 0-9)', value: 'alphanumeric' },
  { label: 'Hex (0-9, A-F)', value: 'hex' },
]

const checksumOptions = [
  { label: 'Luhn Algoritması', value: 'luhn' },
  { label: 'Mod 10', value: 'mod10' },
  { label: 'Mod 11', value: 'mod11' },
  { label: 'Basit Toplam', value: 'simple' },
]

const separatorOptions = [
  { label: '- (Tire)', value: '-' },
  { label: '/ (Eğik çizgi)', value: '/' },
  { label: '. (Nokta)', value: '.' },
  { label: '_ (Alt çizgi)', value: '_' },
  { label: '| (Dikey çizgi)', value: '|' },
  { label: ': (İki nokta)', value: ':' },
]

function handleSave() {
  emit('update', localSegment.value)
}
</script>

<template>
  <div>
    <n-form label-placement="top" size="small">
      <!-- Label -->
      <n-form-item label="Segment Etiketi">
        <n-input
          v-model:value="localSegment.label"
          placeholder="Özel etiket (opsiyonel)"
        />
      </n-form-item>

      <n-divider>Segment Konfigürasyonu</n-divider>

      <!-- Static -->
      <template v-if="localSegment.type === 'static'">
        <n-form-item label="Sabit Değer">
          <n-input
            v-model:value="localSegment.config.value"
            placeholder="DOC"
            :maxlength="50"
            show-count
          />
        </n-form-item>
      </template>

      <!-- Date -->
      <template v-else-if="localSegment.type === 'date'">
        <n-form-item label="Tarih Formatı">
          <n-select
            v-model:value="localSegment.config.format"
            :options="dateFormatOptions"
          />
        </n-form-item>
      </template>

      <!-- Sequence / Yearly Sequence -->
      <template v-else-if="['sequence', 'yearly_sequence'].includes(localSegment.type)">
        <n-form-item label="Basamak Sayısı (Padding)">
          <n-input-number
            v-model:value="localSegment.config.padding"
            :min="1"
            :max="20"
            style="width: 100%"
          />
        </n-form-item>
        <n-text depth="3">
          Başlangıç değeri ve adım, formatın Sıra Numarası Ayarları bölümünden belirlenir.
        </n-text>
      </template>

      <!-- Random -->
      <template v-else-if="localSegment.type === 'random'">
        <n-form-item label="Uzunluk">
          <n-input-number
            v-model:value="localSegment.config.length"
            :min="1"
            :max="20"
            style="width: 100%"
          />
        </n-form-item>
        <n-form-item label="Karakter Tipi">
          <n-select
            v-model:value="localSegment.config.char_type"
            :options="charTypeOptions"
          />
        </n-form-item>
      </template>

      <!-- Checksum -->
      <template v-else-if="localSegment.type === 'checksum'">
        <n-form-item label="Algoritma">
          <n-select
            v-model:value="localSegment.config.algorithm"
            :options="checksumOptions"
          />
        </n-form-item>
      </template>

      <!-- Context -->
      <template v-else-if="localSegment.type === 'context'">
        <n-form-item label="Context Anahtarı">
          <n-input
            v-model:value="localSegment.config.key"
            placeholder="department"
          />
        </n-form-item>
        <n-form-item label="Varsayılan Değer">
          <n-input
            v-model:value="localSegment.config.default"
            placeholder="GEN"
          />
        </n-form-item>
        <n-form-item label="Maksimum Uzunluk">
          <n-input-number
            v-model:value="localSegment.config.max_length"
            :min="1"
            :max="20"
            style="width: 100%"
          />
        </n-form-item>
      </template>

      <!-- Separator -->
      <template v-else-if="localSegment.type === 'separator'">
        <n-form-item label="Ayraç">
          <n-select
            v-model:value="localSegment.config.value"
            :options="separatorOptions"
          />
        </n-form-item>
      </template>
    </n-form>

    <n-space justify="end" style="margin-top: 16px">
      <n-button @click="emit('cancel')">İptal</n-button>
      <n-button type="primary" @click="handleSave">Uygula</n-button>
    </n-space>
  </div>
</template>