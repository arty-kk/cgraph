// frontend/src/lib/formatResult.ts
export function formatResult(res: Record<string, any> | null | undefined): string {
  if (!res) return ''

  const normalizeText = (value: unknown): string | undefined => {
    if (typeof value !== 'string') return undefined
    return value.replace(/\\n/g, '\n')
  }

  const lines: string[] = []

  const pushList = (title: string, items: unknown) => {
    if (!Array.isArray(items) || !items.length) return
    lines.push(`### ${title}\n\n` + items.map((x: string) => `- ${x}`).join('\n'))
  }

  if (res.impacted) {
    const impacted: string[] = Array.isArray(res.impacted) ? res.impacted : []
    const count = Number.isFinite(res.count) ? res.count : impacted.length
    return `### Impact\n\nImpacted files (**${count}**):\n\n` + impacted.map((p) => `- \`${p}\``).join('\n')
  }

  if (res.summary) lines.push(`### Summary\n\n${normalizeText(res.summary) ?? res.summary}`)
  if (res.diagnosis) lines.push(`### Diagnosis\n\n${normalizeText(res.diagnosis) ?? res.diagnosis}`)
  pushList('Risks', res.risks)
  pushList('Evolution points', res.evolution_points)
  if (Array.isArray(res.notable_symbols) && res.notable_symbols.length) {
    lines.push('### Notable symbols\n\n' + res.notable_symbols.map((x: string) => `- \`${x}\``).join('\n'))
  }
  pushList('Suggestions', res.suggestions)
  pushList('Plan', res.plan)
  pushList('Tests', res.tests)
  const planTz = res.plan_tz
  if (planTz && typeof planTz === 'object') {
    if (typeof res.plan_source === 'string' && res.plan_source.trim()) {
      lines.push(`### Plan source\n\n${res.plan_source}`)
    }
    if ('summary' in planTz && planTz.summary) {
      lines.push(`### Plan summary\n\n${normalizeText(planTz.summary) ?? planTz.summary}`)
    }
    pushList('Plan requirements', planTz.requirements)
    pushList('Plan constraints', planTz.constraints)
    pushList('Plan SDLC', planTz.sdlc_plan)
    pushList('Plan acceptance criteria', planTz.acceptance_criteria)
    pushList('Plan risks', planTz.risks)
    pushList('Plan open questions', planTz.open_questions)
    pushList('Plan deliverables', planTz.deliverables)
  }
  if (res.notes) lines.push(`### Notes\n\n${normalizeText(res.notes) ?? res.notes}`)
  if (!lines.length) return '```json\n' + JSON.stringify(res, null, 2) + '\n```'
  return lines.join('\n\n')
}
  
