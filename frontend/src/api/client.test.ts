import type { AxiosInstance, InternalAxiosRequestConfig } from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'

const { safeStorageGetMock } = vi.hoisted(() => ({
  safeStorageGetMock: vi.fn<(key: string) => string | null>(),
}))

vi.mock('../lib/storage', () => ({
  safeStorageGet: safeStorageGetMock,
}))

type ClientModule = typeof import('./client')

async function loadClient(): Promise<ClientModule> {
  return import('./client')
}

async function runRequestInterceptor(api: AxiosInstance, config: Partial<InternalAxiosRequestConfig>) {
  const interceptor = (api.interceptors.request as any).handlers[0]?.fulfilled
  if (typeof interceptor !== 'function') throw new Error('Request interceptor not found')
  return interceptor(config)
}

function getOrgHeader(headers: unknown): string | undefined {
  if (!headers) return undefined
  if (typeof (headers as { get?: (name: string) => string | undefined }).get === 'function') {
    return (headers as { get: (name: string) => string | undefined }).get('X-Org-ID')
      ?? (headers as { get: (name: string) => string | undefined }).get('x-org-id')
  }
  const record = headers as Record<string, unknown>
  const value = record['X-Org-ID'] ?? record['x-org-id']
  return typeof value === 'string' ? value : undefined
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllEnvs()
  vi.resetModules()
  safeStorageGetMock.mockReset()
})

describe('api client baseURL normalization', () => {
  it.each([
    ['https://host', 'https://host/api/tasks/status/task-1'],
    ['https://host/api', 'https://host/api/tasks/status/task-1'],
    ['https://host/api/v1', 'https://host/api/v1/tasks/status/task-1'],
  ])('builds task status URL correctly for VITE_API_BASE_URL=%s', async (apiBaseURL, expectedUrl) => {
    vi.stubEnv('VITE_API_BASE_URL', apiBaseURL)
    const client = await loadClient()

    const nextConfig = await runRequestInterceptor(client.api, { url: '/tasks/status/task-1', headers: {} as any })
    const uri = client.api.getUri({
      baseURL: nextConfig.baseURL ?? client.api.defaults.baseURL,
      url: nextConfig.url,
    })

    expect(uri).toBe(expectedUrl)
    expect(uri).not.toContain('/api/api/')
  })
})

describe('api client org header interceptor', () => {
  it('uses in-memory selectedOrgId even when storage is empty', async () => {
    safeStorageGetMock.mockReturnValue(null)
    const client = await loadClient()

    client.setSelectedOrgId(17)
    const nextConfig = await runRequestInterceptor(client.api, { headers: {} as any })

    expect(getOrgHeader(nextConfig.headers)).toBe('17')
    expect(safeStorageGetMock).not.toHaveBeenCalled()
  })

  it('removes X-Org-ID after setSelectedOrgId(null) even if storage has old value', async () => {
    safeStorageGetMock.mockReturnValue('55')
    const client = await loadClient()

    client.setSelectedOrgId(21)
    client.setSelectedOrgId(null)
    const nextConfig = await runRequestInterceptor(client.api, { headers: { 'X-Org-ID': '21' } as any })

    expect(getOrgHeader(nextConfig.headers)).toBeUndefined()
  })


  it('falls back to storage when in-memory org is invalid but not explicitly cleared', async () => {
    safeStorageGetMock.mockReturnValue('44')
    const client = await loadClient()

    client.setSelectedOrgId(Number.NaN)
    const nextConfig = await runRequestInterceptor(client.api, { headers: {} as any })

    expect(getOrgHeader(nextConfig.headers)).toBe('44')
    expect(safeStorageGetMock).toHaveBeenCalledTimes(1)
  })

  it('falls back to storage only when in-memory org is not set', async () => {
    safeStorageGetMock.mockReturnValue('33')
    const client = await loadClient()

    const fromStorage = await runRequestInterceptor(client.api, { headers: {} as any })
    expect(getOrgHeader(fromStorage.headers)).toBe('33')
    expect(safeStorageGetMock).toHaveBeenCalledTimes(1)

    safeStorageGetMock.mockClear()
    client.setSelectedOrgId(9)
    const fromMemory = await runRequestInterceptor(client.api, { headers: {} as any })

    expect(getOrgHeader(fromMemory.headers)).toBe('9')
    expect(safeStorageGetMock).not.toHaveBeenCalled()
  })
})
