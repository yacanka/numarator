// src/api/client.ts
import axios, {
  type AxiosInstance,
  type AxiosRequestConfig,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios'
import { useAuthStore } from '@/stores/auth'
import { isAuthenticationEndpoint, shouldRefreshAccessToken } from '@/api/authRefreshPolicy'

type RetriableRequestConfig = InternalAxiosRequestConfig & { _retry?: boolean }

class ApiClient {
  private instance: AxiosInstance
  private refreshTokenRequest: Promise<void> | null = null

  constructor() {
    this.instance = axios.create({
      baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
      timeout: 30000,
      withCredentials: true,
      xsrfCookieName:
        import.meta.env.VITE_CSRF_COOKIE_NAME ||
        (import.meta.env.DEV ? 'dn_csrftoken' : 'csrftoken'),
      xsrfHeaderName: 'X-CSRFToken',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
    })

    this.setupInterceptors()
  }

  private setupInterceptors() {
    this.instance.interceptors.response.use(
      (response: AxiosResponse) => response,
      async (error) => this.handleUnauthorizedResponse(error)
    )
  }

  private async handleUnauthorizedResponse(error: any) {
    const originalRequest = error.config as RetriableRequestConfig | undefined

    if (!originalRequest || !shouldRefreshAccessToken(error.response?.status, originalRequest)) {
      return Promise.reject(error)
    }

    originalRequest._retry = true

    try {
      await this.refreshAccessToken()
      return this.instance(originalRequest)
    } catch (refreshError) {
      await this.redirectToLogin()
      return Promise.reject(refreshError)
    }
  }

  private refreshAccessToken() {
    this.refreshTokenRequest ??= this.requestNewAccessToken().finally(() => {
      this.refreshTokenRequest = null
    })
    return this.refreshTokenRequest
  }

  private async requestNewAccessToken() {
    await this.instance.post('/auth/token/refresh/')
  }

  private async redirectToLogin() {
    const authStore = useAuthStore()
    await authStore.logout()

    if (window.location.pathname !== '/login') {
      window.location.href = '/login'
    }
  }

  get<T>(url: string, config?: AxiosRequestConfig) {
    return this.instance.get<T>(url, config)
  }

  post<T>(url: string, data?: any, config?: AxiosRequestConfig) {
    return this.instance.post<T>(url, data, config)
  }

  put<T>(url: string, data?: any, config?: AxiosRequestConfig) {
    return this.instance.put<T>(url, data, config)
  }

  patch<T>(url: string, data?: any, config?: AxiosRequestConfig) {
    return this.instance.patch<T>(url, data, config)
  }

  delete<T>(url: string, config?: AxiosRequestConfig) {
    return this.instance.delete<T>(url, config)
  }
}

export const apiClient = new ApiClient()
