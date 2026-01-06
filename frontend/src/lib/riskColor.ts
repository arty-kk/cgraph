// frontend/src/lib/riskColor.ts
export function riskColor(r: number) {
    const v = Number.isFinite(r) ? r : 0
    if (v > 25) return '#ef4444'
    if (v > 12) return '#f59e0b'
    return '#22c55e'
  }
  