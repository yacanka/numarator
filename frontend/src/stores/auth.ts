// src/stores/auth.ts
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchCsrfToken, fetchCurrentUser, loginWithPassword, logoutSession, updateCurrentUser } from '@/api/auth'
import type { User, UserProfileUpdate } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const sessionReady = ref(false)

  const isAuthenticated = computed(() => sessionReady.value)
  const isAdmin = computed(() => user.value?.is_staff === true)
  const fullName = computed(() => {
    if (!user.value) return ''
    return `${user.value.first_name} ${user.value.last_name}`.trim() || user.value.username
  })

  async function login(username: string, password: string) {
    await fetchCsrfToken()
    await loginWithPassword(username, password)
    await fetchUser()
  }

  async function fetchUser() {
    const response = await fetchCurrentUser()
    user.value = response.data.data
    sessionReady.value = true
  }

  async function updateProfile(payload: UserProfileUpdate) {
    const response = await updateCurrentUser(payload)
    user.value = response.data.data
  }

  async function logout() {
    try {
      await logoutSession()
    } finally {
      user.value = null
      sessionReady.value = false
    }
  }

  return { user, isAuthenticated, isAdmin, fullName, login, logout, fetchUser, updateProfile }
})
