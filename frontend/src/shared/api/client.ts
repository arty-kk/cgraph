// frontend/src/api/client.ts
import axios, { AxiosHeaders } from 'axios'
import { safeStorageGet } from '@/shared/lib/storage'

const rawBaseURL = import.meta.env.VITE_API_BASE_URL
const baseURL = (() => {
  const v =
    typeof rawBaseURL === 'string' && rawBaseURL.trim()
      ? rawBaseURL.trim()
      : 'http://localhost:8000'
  // Нормализуем только пробелы/хвостовые слеши; API-префикс не вырезаем.
  // Endpoint-пути в API-модулях должны быть относительными к baseURL (без встроенного /api).
  return v.replace(/\/+$/, '')
})()

function baseUrlHasApiPrefix(url: string | undefined): boolean {
  if (typeof url !== 'string' || !url) return false
  return /\/api(?:\/v1)?$/.test(url)
}

function shouldPrefixApiPath(url: string | undefined): boolean {
  if (typeof url !== 'string' || !url) return false
  if (/^https?:\/\//.test(url)) return false
  if (!url.startsWith('/')) return false
  if (url === '/api' || url.startsWith('/api/')) return false
  return true
}

export const api = axios.create({
  baseURL,
  timeout: 120_000,
})

const ORG_STORAGE_KEY = 'cs.org.id'
const ORG_HEADER = 'X-Org-ID'

function parsePositiveInteger(value: unknown): number | null {
  const n = Number(value)
  if (!Number.isInteger(n) || n <= 0) return null
  return n
}

api.interceptors.request.use((config) => {
  if (!baseUrlHasApiPrefix(config.baseURL ?? api.defaults.baseURL) && shouldPrefixApiPath(config.url)) {
    config.url = `/api${config.url}`
  }

  const inMemoryOrgId = parsePositiveInteger(selectedOrgId)
  const shouldUseStorageFallback = selectedOrgId !== null && inMemoryOrgId == null
  const fallbackOrgId = shouldUseStorageFallback ? parsePositiveInteger(safeStorageGet(ORG_STORAGE_KEY)) : null
  const resolvedOrgId = inMemoryOrgId ?? fallbackOrgId

  if (resolvedOrgId != null) {
    const value = String(resolvedOrgId)
    if (!config.headers) {
      config.headers = new AxiosHeaders()
    }
    if (typeof (config.headers as AxiosHeaders).set === 'function') {
      ;(config.headers as AxiosHeaders).set(ORG_HEADER, value)
    } else {
      ;(config.headers as Record<string, string>)[ORG_HEADER] = value
    }
  } else if (config.headers) {
    if (typeof (config.headers as AxiosHeaders).delete === 'function') {
      ;(config.headers as AxiosHeaders).delete(ORG_HEADER)
    } else if (ORG_HEADER in (config.headers as Record<string, unknown>)) {
      delete (config.headers as Record<string, unknown>)[ORG_HEADER]
    }
  }
  return config
})

let selectedOrgId: number | null | undefined = undefined

export function setSelectedOrgId(orgId: number | null): void {
  selectedOrgId = orgId
  if (orgId == null) {
    delete api.defaults.headers.common[ORG_HEADER]
    return
  }
  api.defaults.headers.common[ORG_HEADER] = String(orgId)
}

export function getSelectedOrgId(): number | null {
  return selectedOrgId ?? null
}
