// frontend/src/lib/formatResult.ts
export function formatResult(res: Record<string, any> | null | undefined): string {
  if (!res) return ''

  const normalizeText = (value: unknown): string | undefined => {
    if (typeof value !== 'string') return undefined
    return value.replace(/\\n/g, '\n')
  }

  if (res.impacted) {
    const impacted: string[] = Array.isArray(res.impacted) ? res.impacted : []
    const count = Number.isFinite(res.count) ? res.count : impacted.length
    return `### Impact\n\nЗатронутые файлы (**${count}**):\n\n` + impacted.map((p) => `- \`${p}\``).join('\n')
  }

  const lines: string[] = []
  if (res.summary) lines.push(`### Summary\n\n${normalizeText(res.summary) ?? res.summary}`)
  if (res.diagnosis) lines.push(`### Diagnosis\n\n${normalizeText(res.diagnosis) ?? res.diagnosis}`)
  if (Array.isArray(res.risks) && res.risks.length) {
    lines.push('### Risks\n\n' + res.risks.map((x: string) => `- ${x}`).join('\n'))
  }
  if (Array.isArray(res.evolution_points) && res.evolution_points.length) {
    lines.push('### Evolution points\n\n' + res.evolution_points.map((x: string) => `- ${x}`).join('\n'))
  }
  if (Array.isArray(res.notable_symbols) && res.notable_symbols.length) {
    lines.push('### Notable symbols\n\n' + res.notable_symbols.map((x: string) => `- \`${x}\``).join('\n'))
  }
  if (Array.isArray(res.suggestions) && res.suggestions.length) {
    lines.push('### Suggestions\n\n' + res.suggestions.map((x: string) => `- ${x}`).join('\n'))
  }
  if (Array.isArray(res.plan) && res.plan.length) {
    lines.push('### Plan\n\n' + res.plan.map((x: string) => `- ${x}`).join('\n'))
  }
  if (Array.isArray(res.tests) && res.tests.length) {
    lines.push('### Tests\n\n' + res.tests.map((x: string) => `- ${x}`).join('\n'))
  }
  if (res.notes) lines.push(`### Notes\n\n${normalizeText(res.notes) ?? res.notes}`)
  if (!lines.length) return '```json\n' + JSON.stringify(res, null, 2) + '\n```'
  return lines.join('\n\n')
}
  
