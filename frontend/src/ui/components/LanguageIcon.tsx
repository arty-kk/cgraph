// frontend/src/ui/components/LanguageIcon.tsx
import React from 'react'

type Props = {
  language?: string | null
  className?: string
  title?: string
}

type IconDef = {
  label: string
  className?: string
  svg: React.ReactElement
}

const LANGUAGE_ALIASES: Record<string, string> = {
  ts: 'typescript',
  tsx: 'typescript',
  js: 'javascript',
  jsx: 'javascript',
  py: 'python',
  pyi: 'python',
  csharp: 'csharp',
  'c#': 'csharp',
  cs: 'csharp',
  'c++': 'cpp',
  cpp: 'cpp',
  hpp: 'cpp',
  cc: 'cpp',
  'objective-c': 'objective-c',
  'obj-c': 'objective-c',
  objc: 'objective-c',
}

const makeLangIcon = (text: string) => (
  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <rect x="3.25" y="3.25" width="17.5" height="17.5" rx="4" ry="4" fill="none" stroke="currentColor" strokeWidth="1.5" />
    <text
      x="12"
      y="15"
      textAnchor="middle"
      fontSize="9"
      fontFamily='ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
      fill="currentColor"
      fontWeight="600"
    >
      {text}
    </text>
  </svg>
)

const LANGUAGE_ICONS: Record<string, IconDef> = {
  typescript: { label: 'TypeScript', className: 'text-sky-400', svg: makeLangIcon('TS') },
  javascript: { label: 'JavaScript', className: 'text-yellow-300', svg: makeLangIcon('JS') },
  python: { label: 'Python', className: 'text-blue-400', svg: makeLangIcon('PY') },
  go: { label: 'Go', className: 'text-cyan-300', svg: makeLangIcon('GO') },
  rust: { label: 'Rust', className: 'text-amber-400', svg: makeLangIcon('RS') },
  java: { label: 'Java', className: 'text-orange-400', svg: makeLangIcon('JV') },
  kotlin: { label: 'Kotlin', className: 'text-purple-300', svg: makeLangIcon('KT') },
  swift: { label: 'Swift', className: 'text-orange-300', svg: makeLangIcon('SW') },
  csharp: { label: 'C#', className: 'text-purple-400', svg: makeLangIcon('C#') },
  cpp: { label: 'C++', className: 'text-teal-300', svg: makeLangIcon('C++') },
  c: { label: 'C', className: 'text-teal-200', svg: makeLangIcon('C') },
  'objective-c': { label: 'Objective-C', className: 'text-rose-300', svg: makeLangIcon('OC') },
  ruby: { label: 'Ruby', className: 'text-red-400', svg: makeLangIcon('RB') },
  php: { label: 'PHP', className: 'text-indigo-300', svg: makeLangIcon('PHP') },
}

const normalizeLanguage = (language?: string | null) => {
  const raw = (language || '').trim().toLowerCase()
  if (!raw) return ''
  return LANGUAGE_ALIASES[raw] || raw
}

export function LanguageIcon({ language, className, title }: Props) {
  const rawLabel = (language || '').trim()
  const normalized = normalizeLanguage(language)
  const iconDef = normalized ? LANGUAGE_ICONS[normalized] : undefined
  const ariaLabel = title || rawLabel || iconDef?.label || '—'

  if (!iconDef) {
    return (
      <span
        className={['inline-flex items-center justify-center text-[11px] text-neutral-500', className || ''].join(' ')}
        title={ariaLabel}
        aria-label={ariaLabel}
      >
        —
      </span>
    )
  }

  return (
    <span
      className={['inline-flex items-center justify-center', iconDef.className || '', className || ''].join(' ')}
      role="img"
      aria-label={ariaLabel}
      title={ariaLabel}
    >
      {React.cloneElement(iconDef.svg, {
        className: ['h-3.5 w-3.5', iconDef.svg.props.className || ''].join(' '),
      })}
    </span>
  )
}
