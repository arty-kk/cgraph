// frontend/src/api/client.ts
import axios, { AxiosHeaders } from 'axios'

const rawBaseURL = import.meta.env.VITE_API_BASE_URL
const baseURL = (() => {
  const v =
    typeof rawBaseURL === 'string' && rawBaseURL.trim()
      ? rawBaseURL.trim()
      : 'http://localhost:8000'
  // Допустимые форматы: https://host, https://host/api, https://host/api/v1 (с хвостовым слешем или без).
  const noTrailing = v.replace(/\/+$/, '')
  return noTrailing.replace(/\/api(?:\/v1)?$/, '')
})()

export const api = axios.create({
  baseURL,
  timeout: 120_000,
})

const ORG_STORAGE_KEY = 'cs.org.id'
const ORG_HEADER = 'X-Org-ID'

api.interceptors.request.use((config) => {
  let raw: string | null = null
  try {
    raw = localStorage.getItem(ORG_STORAGE_KEY)
  } catch {}
  const n = Number(raw)
  const valid = Number.isFinite(n) && n > 0
  if (valid) {
    const value = String(Math.trunc(n))
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

let selectedOrgId: number | null = null

export function setSelectedOrgId(orgId: number | null): void {
  selectedOrgId = orgId
  if (orgId == null) {
    delete api.defaults.headers.common[ORG_HEADER]
    return
  }
  api.defaults.headers.common[ORG_HEADER] = String(orgId)
}

export function getSelectedOrgId(): number | null {
  return selectedOrgId
}
