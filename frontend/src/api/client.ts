// frontend/src/api/client.ts
import axios from 'axios'

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
