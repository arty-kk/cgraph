export const clamp = (v: number, lo: number, hi: number) => {
  return Math.max(lo, Math.min(hi, v))
}

export const baseName = (p: string) => {
  const s = String(p || '')
  const parts = s.split('/')
  return parts[parts.length - 1] || s
}
