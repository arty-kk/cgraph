// frontend/src/api/config.ts
import { api } from '@/shared/api/client'
import type { AppConfig } from '@/shared/types'

export async function getAppConfig(): Promise<AppConfig> {
  const r = await api.get('/config')
  return r.data
}
