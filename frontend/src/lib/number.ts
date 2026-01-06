// frontend/src/lib/number.ts
export function clampInt(v: number, min: number, max: number) {
    if (!Number.isFinite(v)) return min
    return Math.max(min, Math.min(max, Math.trunc(v)))
  }
  