// frontend/src/api/config.ts
import { api } from './client'
import type { AppConfig } from './types'

export async function getAppConfig(): Promise<AppConfig> {
  const r = await api.get('/api/config')
  return r.data
}
