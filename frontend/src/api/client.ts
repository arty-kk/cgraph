// frontend/src/api/client.ts
import axios from 'axios'

const rawBaseURL = import.meta.env.VITE_API_BASE_URL
const baseURL = (() => {
  const v =
    typeof rawBaseURL === 'string' && rawBaseURL.trim()
      ? rawBaseURL.trim()
      : 'http://localhost:8000'
  const noTrailing = v.replace(/\/+$/, '')
  return noTrailing.replace(/\/api$/, '')
})()

export const api = axios.create({
  baseURL,
  timeout: 120_000,
})
