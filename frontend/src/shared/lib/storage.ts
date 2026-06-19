// frontend/src/lib/storage.ts
type StorageEventDetail = {
  action: 'get' | 'set' | 'remove' | 'parse'
  key: string
}

const STORAGE_EVENT = 'cs-storage-error'
let warned = false

const dispatchStorageWarning = (detail: StorageEventDetail, error: unknown) => {
  if (warned) return
  warned = true
  // eslint-disable-next-line no-console
  console.warn('localStorage unavailable:', detail, error)
  if (typeof window === 'undefined') return
  try {
    window.dispatchEvent(new CustomEvent<StorageEventDetail>(STORAGE_EVENT, { detail }))
  } catch {}
}

export const addStorageErrorListener = (
  handler: (detail: StorageEventDetail) => void
): (() => void) => {
  if (typeof window === 'undefined') return () => {}
  const wrapped = (event: Event) => {
    const detail = (event as CustomEvent<StorageEventDetail>)?.detail
    if (detail) handler(detail)
  }
  window.addEventListener(STORAGE_EVENT, wrapped)
  return () => window.removeEventListener(STORAGE_EVENT, wrapped)
}

export const safeStorageGet = (key: string, fallback: string | null = null): string | null => {
  try {
    return localStorage.getItem(key)
  } catch (error) {
    dispatchStorageWarning({ action: 'get', key }, error)
    return fallback
  }
}

export const safeStorageSet = (key: string, value: string): boolean => {
  try {
    localStorage.setItem(key, value)
    return true
  } catch (error) {
    dispatchStorageWarning({ action: 'set', key }, error)
    return false
  }
}

export const safeStorageRemove = (key: string): boolean => {
  try {
    localStorage.removeItem(key)
    return true
  } catch (error) {
    dispatchStorageWarning({ action: 'remove', key }, error)
    return false
  }
}

export const safeStorageGetJson = <T>(key: string, fallback: T): T => {
  const raw = safeStorageGet(key)
  if (!raw) return fallback
  try {
    return JSON.parse(raw) as T
  } catch (error) {
    dispatchStorageWarning({ action: 'parse', key }, error)
    return fallback
  }
}
