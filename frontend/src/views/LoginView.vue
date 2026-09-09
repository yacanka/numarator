<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAlert, NButton, NCard, NForm, NFormItem, NInput, NSpace, useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const authStore = useAuthStore()
const username = ref('')
const password = ref('')
const loading = ref(false)
const errorMessage = ref('')

async function submitLogin() {
  loading.value = true
  errorMessage.value = ''
  try {
    await authStore.login(username.value, password.value)
    await router.push((route.query.redirect as string) || '/')
  } catch {
    errorMessage.value = 'Invalid username or password.'
    message.error(errorMessage.value)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <n-card class="login-card" title="Numarator Login">
      <n-space vertical size="large">
        <n-alert v-if="errorMessage" type="error">{{ errorMessage }}</n-alert>
        <n-form @submit.prevent="submitLogin">
          <n-form-item label="Username">
            <n-input v-model:value="username" autocomplete="username" />
          </n-form-item>
          <n-form-item label="Password">
            <n-input v-model:value="password" type="password" autocomplete="current-password" />
          </n-form-item>
          <n-button type="primary" block attr-type="submit" :loading="loading">Login</n-button>
        </n-form>
      </n-space>
    </n-card>
  </main>
</template>

<style scoped>
.login-page {
  display: grid;
  min-height: 100vh;
  place-items: center;
}
.login-card {
  width: min(420px, calc(100vw - 32px));
}
</style>
