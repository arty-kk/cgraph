// frontend/src/lib/riskColor.ts
export function riskColor(r: number): string {
  const v = Number.isFinite(r) ? Math.max(0, r) : 0
  const t = 1 - Math.exp(-v / 18)
  const hue = 120 * (1 - t)
  return hslToHex(hue, 85, 55)
}

function hslToHex(h: number, s: number, l: number): string {
  const hh = ((h % 360) + 360) % 360
  const ss = Math.max(0, Math.min(100, s)) / 100
  const ll = Math.max(0, Math.min(100, l)) / 100

  const c = (1 - Math.abs(2 * ll - 1)) * ss
  const x = c * (1 - Math.abs(((hh / 60) % 2) - 1))
  const m = ll - c / 2

  let rr = 0
  let gg = 0
  let bb = 0
  if (hh < 60) [rr, gg, bb] = [c, x, 0]
  else if (hh < 120) [rr, gg, bb] = [x, c, 0]
  else if (hh < 180) [rr, gg, bb] = [0, c, x]
  else if (hh < 240) [rr, gg, bb] = [0, x, c]
  else if (hh < 300) [rr, gg, bb] = [x, 0, c]
  else [rr, gg, bb] = [c, 0, x]

  const toHex = (n: number) => {
    const v = Math.round((n + m) * 255)
    const clamped = Math.max(0, Math.min(255, v))
    return clamped.toString(16).padStart(2, '0')
  }

  return `#${toHex(rr)}${toHex(gg)}${toHex(bb)}`
}
  
