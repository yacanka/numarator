<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import {
  NAlert, NButton, NCard, NCheckbox, NCheckboxGroup, NDatePicker, NEmpty,
  NForm, NFormItem, NInput, NModal, NSelect, NSpace, NSpin, NTag, NText,
  useDialog, useMessage,
} from 'naive-ui'
import type { FormInst, FormRules } from 'naive-ui'
import { isAxiosError } from 'axios'
import {
  fetchActiveFormats, integrationsApi,
  type ApiCredential, type ApiScope,
} from '@/api/integrations'
import type { DocumentFormat } from '@/types'

const message = useMessage()
const dialog = useDialog()
const credentials = ref<ApiCredential[]>([])
const scopes = ref<ApiScope[]>([])
const formats = ref<DocumentFormat[]>([])
const loading = ref(true)
const loadError = ref('')
const createError = ref('')
const creating = ref(false)
const revokingId = ref<string | null>(null)
const showCreate = ref(false)
const newKey = ref('')
const savedKey = ref(false)
const formRef = ref<FormInst | null>(null)
const form = reactive({
  name: '', scopes: [] as string[], allowed_formats: [] as string[],
  allFormats: false, expiresAt: null as number | null,
})

const formatOptions = computed(() => formats.value.map(format => ({
  label: `${format.name} (${format.code})`, value: format.id,
})))
const rules: FormRules = {
  name: { required: true, validator: () => form.name.trim().length > 0 || new Error('Anahtar adı girin.'), trigger: ['input', 'blur'] },
  scopes: { type: 'array', required: true, min: 1, message: 'En az bir yetki seçin.', trigger: 'change' },
  allowed_formats: {
    validator: () => form.allFormats || form.allowed_formats.length > 0 || new Error('En az bir format seçin.'),
    trigger: 'change',
  },
  expiresAt: {
    validator: () => form.expiresAt === null || form.expiresAt > Date.now() || new Error('Gelecekte bir tarih ve saat seçin.'),
    trigger: 'change',
  },
}

function errorText(error: unknown, fallback: string) {
  if (!isAxiosError(error)) return fallback
  if (error.response?.status === 403) return 'Bu işlem için admin yetkisi gerekiyor.'
  if (error.response?.status === 400) return error.response.data?.error?.message || fallback
  return fallback
}

async function loadData() {
  loading.value = true
  loadError.value = ''
  try {
    const [keyResponse, scopeResponse, activeFormats] = await Promise.all([
      integrationsApi.list(), integrationsApi.scopes(), fetchActiveFormats(),
    ])
    credentials.value = keyResponse.data.data
    scopes.value = scopeResponse.data.data
    formats.value = activeFormats
  } catch (error) {
    loadError.value = errorText(error, 'API anahtarları yüklenemedi. Tekrar deneyin.')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, { name: '', scopes: [], allowed_formats: [], allFormats: false, expiresAt: null })
  createError.value = ''
  showCreate.value = true
}

async function createKey() {
  if (creating.value) return
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  creating.value = true
  createError.value = ''
  try {
    const response = await integrationsApi.create({
      name: form.name.trim(), scopes: [...form.scopes],
      allowed_formats: form.allFormats ? [] : [...form.allowed_formats],
      expires_at: form.expiresAt === null ? null : new Date(form.expiresAt).toISOString(),
    })
    // Keep the plaintext secret out of the list and all persistent storage.
    const { api_key, ...credential } = response.data.data
    credentials.value.unshift(credential)
    newKey.value = api_key
    savedKey.value = false
    showCreate.value = false
  } catch (error) {
    createError.value = errorText(error, 'Anahtar oluşturulamadı. Bağlantı kesildiyse yeniden oluşturmadan önce listeyi yenileyin.')
  } finally {
    creating.value = false
  }
}

async function copyKey() {
  try {
    await navigator.clipboard.writeText(newKey.value)
    message.success('API anahtarı kopyalandı.')
  } catch {
    message.error('Panoya kopyalanamadı. Anahtarı metin alanından seçip kopyalayın.')
  }
}

function closeKey() {
  if (!savedKey.value) return
  newKey.value = ''
  savedKey.value = false
}

function confirmRevoke(credential: ApiCredential) {
  dialog.warning({
    title: 'API anahtarını iptal et',
    content: `“${credential.name}” anahtarı kalıcı olarak iptal edilecek. Bu anahtarı kullanan uygulamalar artık erişemeyecek.`,
    positiveText: 'Anahtarı iptal et', negativeText: 'Vazgeç',
    onPositiveClick: async () => {
      revokingId.value = credential.id
      try {
        const response = await integrationsApi.revoke(credential.id)
        credentials.value = credentials.value.map(item => item.id === credential.id ? response.data.data : item)
        message.success('API anahtarı iptal edildi.')
      } catch (error) {
        message.error(errorText(error, 'Anahtar iptal edilemedi. Tekrar deneyin.'))
        return false
      } finally {
        revokingId.value = null
      }
    },
  })
}

function keyStatus(credential: ApiCredential) {
  if (credential.revoked_at) return { label: 'İptal edildi', type: 'error' as const }
  if (credential.expires_at && new Date(credential.expires_at).getTime() <= Date.now()) {
    return { label: 'Süresi doldu', type: 'warning' as const }
  }
  return credential.active
    ? { label: 'Aktif', type: 'success' as const }
    : { label: 'Devre dışı', type: 'default' as const }
}

function formatDate(value: string | null, empty = '—') {
  return value ? new Date(value).toLocaleString('tr-TR') : empty
}

// Prevent navigation from silently discarding a freshly issued key or its response.
onBeforeRouteLeave(() => !newKey.value && !creating.value)
function warnBeforeUnload(event: BeforeUnloadEvent) {
  if (!newKey.value && !creating.value) return
  event.preventDefault()
  event.returnValue = ''
}
onBeforeUnmount(() => {
  newKey.value = ''
  window.removeEventListener('beforeunload', warnBeforeUnload)
})
onMounted(() => {
  window.addEventListener('beforeunload', warnBeforeUnload)
  loadData()
})
</script>

<template>
  <n-space vertical size="large">
    <div class="page-heading">
      <div>
        <n-text tag="h1" class="page-title">API Anahtarları</n-text>
        <n-text depth="3">Dış uygulamalar için oluşturduğunuz anahtarları ve erişim izinlerini yönetin.</n-text>
      </div>
      <n-space>
        <n-button :loading="loading" @click="loadData">Yenile</n-button>
        <n-button type="primary" :disabled="loading || !!loadError" @click="openCreate">Yeni API Anahtarı</n-button>
      </n-space>
    </div>

    <n-alert v-if="loadError" type="error" title="Yükleme hatası">{{ loadError }}</n-alert>
    <n-spin :show="loading">
      <n-card v-if="!credentials.length && !loading && !loadError">
        <n-empty description="Henüz API anahtarınız yok.">
          <template #extra><n-button @click="openCreate">İlk anahtarı oluştur</n-button></template>
        </n-empty>
      </n-card>
      <n-space vertical size="large">
        <n-card v-for="credential in credentials" :key="credential.id" :title="credential.name" size="small">
          <template #header-extra>
            <n-tag :type="keyStatus(credential).type" size="small">{{ keyStatus(credential).label }}</n-tag>
          </template>
          <n-space vertical>
            <n-text depth="3">Anahtar öneki: <code>{{ credential.key_prefix }}…</code></n-text>
            <div><n-text strong>Yetkiler</n-text><n-space class="detail-values" size="small">
              <n-tag v-for="scope in credential.scopes" :key="scope" size="small">{{ scope }}</n-tag>
            </n-space></div>
            <div><n-text strong>Format erişimi</n-text><n-space class="detail-values" size="small">
              <n-tag v-if="credential.all_formats" type="warning" size="small">Tüm aktif formatlar</n-tag>
              <n-tag v-for="code in credential.allowed_format_codes" v-else :key="code" size="small">{{ code }}</n-tag>
            </n-space></div>
            <dl class="key-dates">
              <div><dt>Oluşturulma</dt><dd>{{ formatDate(credential.created_at) }}</dd></div>
              <div><dt>Son kullanım</dt><dd>{{ formatDate(credential.last_used_at, 'Henüz kullanılmadı') }}</dd></div>
              <div><dt>Son geçerlilik</dt><dd>{{ formatDate(credential.expires_at, 'Süresiz') }}</dd></div>
              <div v-if="credential.revoked_at"><dt>İptal tarihi</dt><dd>{{ formatDate(credential.revoked_at) }}</dd></div>
            </dl>
            <n-space justify="end">
              <n-button type="error" secondary size="small" :disabled="!!credential.revoked_at || !!revokingId"
                :loading="revokingId === credential.id" @click="confirmRevoke(credential)">İptal et</n-button>
            </n-space>
          </n-space>
        </n-card>
      </n-space>
    </n-spin>

    <n-modal v-model:show="showCreate" preset="card" title="Yeni API Anahtarı" class="key-modal"
      :closable="!creating" :mask-closable="false" :close-on-esc="!creating">
      <n-form ref="formRef" :model="form" :rules="rules" :disabled="creating" @submit.prevent="createKey">
        <n-form-item label="Anahtar adı" path="name">
          <n-input v-model:value="form.name" placeholder="Örn. AW Center Local" :maxlength="100" />
        </n-form-item>
        <n-form-item label="Yetkiler" path="scopes">
          <n-checkbox-group v-model:value="form.scopes">
            <n-space vertical>
              <n-checkbox v-for="scope in scopes" :key="scope.code" :value="scope.code">
                <strong>{{ scope.code }}</strong> — {{ scope.description }}
              </n-checkbox>
            </n-space>
          </n-checkbox-group>
        </n-form-item>
        <n-form-item label="Format erişimi" path="allowed_formats">
          <n-space vertical style="width: 100%">
            <n-checkbox v-model:checked="form.allFormats">Tüm aktif formatlara erişim ver</n-checkbox>
            <n-alert v-if="form.allFormats" type="warning">
              Bu anahtar, daha sonra aktif edilecek formatlar dahil tüm aktif formatlara erişebilir.
            </n-alert>
            <n-select v-else v-model:value="form.allowed_formats" :options="formatOptions" multiple filterable
              placeholder="İzin verilecek formatları seçin" />
            <n-text depth="3">Yalnızca aktif formatlar listelenir. Formatı önce Format Yönetimi ekranından aktif edin.</n-text>
            <n-text v-if="!formats.length" type="warning">Aktif format bulunamadı.</n-text>
          </n-space>
        </n-form-item>
        <n-form-item label="Son geçerlilik tarihi (isteğe bağlı)" path="expiresAt">
          <n-date-picker v-model:value="form.expiresAt" type="datetime" clearable style="width: 100%"
            placeholder="Boş bırakırsanız süresiz" />
        </n-form-item>
        <n-text depth="3">Tarih ve saat, tarayıcınızın yerel saat dilimine göre kaydedilir.</n-text>
        <n-alert v-if="createError" type="error" class="form-alert">{{ createError }}</n-alert>
        <n-space justify="end" class="modal-actions">
          <n-button :disabled="creating" @click="showCreate = false">Vazgeç</n-button>
          <n-button type="primary" attr-type="submit" :loading="creating">Anahtar oluştur</n-button>
        </n-space>
      </n-form>
    </n-modal>

    <n-modal :show="!!newKey" preset="card" title="API anahtarı oluşturuldu" class="key-modal"
      :closable="false" :mask-closable="false" :close-on-esc="false">
      <n-space vertical size="large">
        <n-alert type="warning" title="Bu anahtar yalnızca bir kez gösterilir">
          Şimdi kopyalayıp uygulamanızın güvenli yapılandırmasına kaydedin. Kaybederseniz yeni bir anahtar
          oluşturmanız ve eskisini iptal etmeniz gerekir.
        </n-alert>
        <n-input :value="newKey" type="textarea" readonly :autosize="{ minRows: 3 }"
          :input-props="{ 'aria-label': 'Oluşturulan API anahtarı', spellcheck: false }" />
        <n-button @click="copyKey">Anahtarı kopyala</n-button>
        <n-text depth="3">
          AW Center’da NUMARATOR_API_KEY alanına bu anahtarı kaydedin. NUMARATOR_PROJECT_FORMATS
          içinde seçtiğiniz formatın kodunu kullanın. Yapılandırmayı kaydettikten sonra AW Center’ı yeniden başlatın.
        </n-text>
        <n-checkbox v-model:checked="savedKey">Anahtarı güvenli bir yere kaydettim.</n-checkbox>
        <n-space justify="end"><n-button type="primary" :disabled="!savedKey" @click="closeKey">Tamam</n-button></n-space>
      </n-space>
    </n-modal>
  </n-space>
</template>

<style scoped>
.page-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px; }
.page-title { margin: 0 0 8px; font-size: 24px; }
.detail-values { margin-top: 6px; }
.key-dates { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 12px 0 0; }
.key-dates dt { opacity: 0.65; font-size: 12px; }
.key-dates dd { margin: 4px 0 0; }
.key-modal { width: min(640px, calc(100vw - 32px)); }
.modal-actions { margin-top: 24px; }
.form-alert { margin-top: 16px; }
</style>
