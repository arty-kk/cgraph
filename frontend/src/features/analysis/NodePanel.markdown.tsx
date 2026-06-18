import React from 'react'
import type { Components } from 'react-markdown'

const inlineTokenRegex =
  /([A-Za-z0-9._-]*\/[A-Za-z0-9._/-]*\.[A-Za-z0-9]+|\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+\b|\b[A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]*\b)/

export const renderInlineHighlights = (children: React.ReactNode) =>
  React.Children.map(children, (child, index) => {
    if (typeof child !== 'string') return child
    const parts = child.split(inlineTokenRegex)
    return parts.map((part, partIndex) => {
      if (!part) return null
      if (!inlineTokenRegex.test(part)) {
        return <React.Fragment key={`${index}-${partIndex}`}>{part}</React.Fragment>
      }
      return (
        <span
          key={`${index}-${partIndex}`}
          className="font-mono text-[11px] rounded border border-neutral-700 bg-neutral-950 px-1 py-0.5 text-indigo-100 shadow-inner shadow-black/40"
        >
          {part}
        </span>
      )
    })
  })

export const resultMarkdownComponents: Components = {
  h1: ({ node, className, ...props }) => (
    <h1
      {...props}
      className={['text-sm font-semibold text-neutral-100 mt-1 mb-2', className].filter(Boolean).join(' ')}
    />
  ),
  h2: ({ node, className, ...props }) => (
    <h2
      {...props}
      className={['text-xs font-semibold text-neutral-100 mt-4 mb-2', className].filter(Boolean).join(' ')}
    />
  ),
  h3: ({ node, className, ...props }) => (
    <h3
      {...props}
      className={['text-[11px] font-semibold text-neutral-100 mt-3 mb-2', className].filter(Boolean).join(' ')}
    />
  ),
  p: ({ node, className, children, ...props }) => (
    <p
      {...props}
      className={['text-xs text-neutral-200 leading-relaxed my-2', className].filter(Boolean).join(' ')}
    >
      {renderInlineHighlights(children)}
    </p>
  ),
  ul: ({ node, className, ...props }) => (
    <ul {...props} className={['list-disc pl-5 my-2 space-y-1', className].filter(Boolean).join(' ')} />
  ),
  ol: ({ node, className, ...props }) => (
    <ol {...props} className={['list-decimal pl-5 my-2 space-y-1', className].filter(Boolean).join(' ')} />
  ),
  li: ({ node, className, children, ...props }) => (
    <li {...props} className={['text-xs text-neutral-200', className].filter(Boolean).join(' ')}>
      {renderInlineHighlights(children)}
    </li>
  ),
  pre: ({ node, className, ...props }) => (
    <pre
      {...props}
      className={['text-xs bg-neutral-950 border border-neutral-800 rounded-md p-2 overflow-auto my-2', className]
        .filter(Boolean)
        .join(' ')}
    />
  ),
  table: ({ node, className, ...props }) => (
    <div className="my-3 overflow-auto">
      <table {...props} className={['w-full text-xs border-collapse', className].filter(Boolean).join(' ')} />
    </div>
  ),
  thead: ({ node, className, ...props }) => (
    <thead {...props} className={['bg-neutral-900/40', className].filter(Boolean).join(' ')} />
  ),
  th: ({ node, className, children, ...props }) => (
    <th
      {...props}
      className={['border border-neutral-800 px-2 py-1 text-left text-neutral-200 font-semibold align-top', className]
        .filter(Boolean)
        .join(' ')}
    >
      {renderInlineHighlights(children)}
    </th>
  ),
  td: ({ node, className, children, ...props }) => (
    <td
      {...props}
      className={['border border-neutral-800 px-2 py-1 text-neutral-200 align-top', className]
        .filter(Boolean)
        .join(' ')}
    >
      {renderInlineHighlights(children)}
    </td>
  ),
  code: ({ node, className, children, ...props }) => {
    const isInline = !(className && /\blanguage-/.test(className))

    if (isInline) {
      return (
        <code
          {...props}
          className={[
            'font-mono text-[11px] rounded border border-neutral-700 bg-neutral-950 px-1 py-0.5 text-indigo-100 shadow-inner shadow-black/40',
            className || '',
          ].join(' ')}
        >
          {children}
        </code>
      )
    }

    return (
      <code {...props} className={['font-mono text-[11px]', className || ''].join(' ')}>
        {children}
      </code>
    )
  },
  a: ({ node, className, ...props }) => (
    <a
      {...props}
      className={['text-indigo-300 font-semibold underline decoration-indigo-500/60 hover:text-indigo-200', className]
        .filter(Boolean)
        .join(' ')}
      target={props.target ?? '_blank'}
      rel={props.rel ?? 'noreferrer'}
    />
  ),
}
