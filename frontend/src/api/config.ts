// frontend/src/api/config.ts
import { api } from './client'
import type { AppConfig } from './types'

export async function getAppConfig(): Promise<AppConfig> {
  const r = await api.get('/config')
  return r.data
}
