// src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      component: () => import('@/components/layout/AppLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        {
          path: '',
          name: 'Dashboard',
          component: () => import('@/views/DashboardView.vue'),
          meta: { title: 'Dashboard' },
        },
        {
          path: 'formats',
          name: 'Formats',
          component: () => import('@/views/FormatsView.vue'),
          meta: { title: 'Format Yönetimi' },
        },
        {
          path: 'formats/new',
          name: 'FormatNew',
          component: () => import('@/views/FormatBuilderView.vue'),
          meta: { title: 'Yeni Format' },
        },
        {
          path: 'formats/:id/edit',
          name: 'FormatEdit',
          component: () => import('@/views/FormatBuilderView.vue'),
          meta: { title: 'Format Düzenle' },
        },
        {
          path: 'documents',
          name: 'Documents',
          component: () => import('@/views/DocumentsView.vue'),
          meta: { title: 'Belgeler' },
        },
        {
          path: 'settings/api-keys',
          name: 'ApiKeys',
          component: () => import('@/views/ApiKeysView.vue'),
          meta: { title: 'API Anahtarları', requiresAdmin: true },
        },
        {
          path: 'settings',
          name: 'Settings',
          component: () => import('@/views/SettingsView.vue'),
          meta: { title: 'Ayarlar' },
        },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const authStore = useAuthStore()

  if (!authStore.user) {
    try {
      await authStore.fetchUser()
    } catch {
      if (!to.meta.public) return { name: 'Login', query: { redirect: to.fullPath } }
    }
  }

  if (!to.meta.public && !authStore.isAuthenticated) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }

  if (to.meta.requiresAdmin && !authStore.isAdmin) {
    return { name: 'Dashboard' }
  }
})

export default router
