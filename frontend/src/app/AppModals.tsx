import React from 'react'
import { Modal } from '@/shared/ui/Modal'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { useStubGraphApp } from './useStubGraphApp'

type Params = {
  app: ReturnType<typeof useStubGraphApp>
  docsOpen: boolean
  setDocsOpen: React.Dispatch<React.SetStateAction<boolean>>
  onboardOpen: boolean
  closeOnboarding: (skip: boolean) => void
  onboardStep: number
  setOnboardStep: React.Dispatch<React.SetStateAction<number>>
  onboardSteps: any[]
  totalOnboardSteps: number
  confirmTitle: string
  confirmBody: React.ReactNode
  filePathSet: Set<string>
}

export function AppModals({
  app, docsOpen, setDocsOpen, onboardOpen, closeOnboarding, onboardStep, setOnboardStep,
  onboardSteps, totalOnboardSteps, confirmTitle, confirmBody, filePathSet,
}: Params) {
  return (
    <>
      <Modal
        open={app.confirmOpen}
        title={confirmTitle}
        onClose={app.confirmCancel}
      >
        <div className="space-y-4">
          <div className="text-sm text-neutral-200">{confirmBody}</div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 px-3 py-2 text-sm font-semibold disabled:opacity-50"
              onClick={() => void app.confirmCancel()}
              disabled={app.fileEditorSaving || app.fileEditorBusy}
            >
              Cancel
            </button>
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 px-3 py-2 text-sm font-semibold disabled:opacity-50"
              onClick={() => void app.confirmDiscard()}
              disabled={app.fileEditorSaving || app.fileEditorBusy}
            >
              Continue without saving
            </button>
            <button
              type="button"
              className="rounded-md bg-indigo-600 hover:bg-indigo-500 px-3 py-2 text-sm font-semibold disabled:opacity-50"
              onClick={() => void app.confirmSave()}
              disabled={app.fileEditorSaving || app.fileEditorBusy}
            >
              Save
            </button>
          </div>
        </div>
      </Modal>

      <Modal
        open={Boolean(app.draftRestore)}
        title="Restore draft?"
        onClose={app.discardDraft}
      >
        <div className="space-y-4">
          <div className="text-sm text-neutral-200">
            A local draft was found for <span className="font-semibold">{app.draftRestore?.path}</span>. Restore it?
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 px-3 py-2 text-sm font-semibold"
              onClick={() => app.discardDraft()}
            >
              Discard
            </button>
            <button
              type="button"
              className="rounded-md bg-indigo-600 hover:bg-indigo-500 px-3 py-2 text-sm font-semibold"
              onClick={() => app.restoreDraft()}
            >
              Restore draft
            </button>
          </div>
        </div>
      </Modal>

      <Modal open={docsOpen && !!app.activeProject} title="Project docs" onClose={() => setDocsOpen(false)}>
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="rounded-md bg-neutral-800 hover:bg-neutral-700 px-3 py-2 text-sm font-semibold disabled:opacity-50"
              onClick={() => void app.buildDocs()}
              disabled={!app.activeProject || app.busy || app.docsBuildBusy}
            >
              {app.docsBuildBusy ? 'Building…' : 'Build docs'}
            </button>
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 px-3 py-2 text-sm font-semibold disabled:opacity-50"
              onClick={() => void app.loadDocs()}
              disabled={!app.activeProject || app.busy || app.docsBusy}
            >
              {app.docsBusy ? 'Loading…' : 'Reload'}
            </button>
          </div>

          <div className="text-xs text-neutral-500">
            {app.docs?.created_at ? `Updated: ${app.docs.created_at}` : 'No docs yet'}
          </div>

          <div className="text-xs bg-neutral-950 border border-neutral-800 rounded-md p-3 overflow-auto max-h-[70vh]">
            {app.docsBuildError && app.docs?.markdown && (
              <div className="text-amber-200 bg-amber-500/10 border border-amber-500/30 rounded-md p-2 mb-3">
                Docs failed to update due to an error — showing the previous version.
              </div>
            )}
            {!app.docs?.markdown ? (
              <div className="text-neutral-500">—</div>
            ) : (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  h1: ({ children }) => (
                    <h1 className="text-base font-semibold text-neutral-100 mt-1 mb-2">{children}</h1>
                  ),
                  h2: ({ children }) => (
                    <h2 className="text-sm font-semibold text-neutral-100 mt-4 mb-2">{children}</h2>
                  ),
                  h3: ({ children }) => (
                    <h3 className="text-xs font-semibold text-neutral-100 mt-3 mb-2">{children}</h3>
                  ),
                  p: ({ children }) => <p className="text-xs text-neutral-200 leading-relaxed my-2">{children}</p>,
                  ul: ({ children }) => <ul className="list-disc pl-5 my-2 space-y-1">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal pl-5 my-2 space-y-1">{children}</ol>,
                  li: ({ children }) => <li className="text-xs text-neutral-200">{children}</li>,
                  pre: ({ children }) => (
                    <pre className="text-xs bg-neutral-950 border border-neutral-800 rounded-md p-2 overflow-auto my-2">
                      {children}
                    </pre>
                  ),
                  table: ({ children }) => (
                    <div className="my-3 overflow-auto">
                      <table className="w-full text-xs border-collapse">{children}</table>
                    </div>
                  ),
                  thead: ({ children }) => <thead className="bg-neutral-900/40">{children}</thead>,
                  th: ({ children }) => (
                    <th className="border border-neutral-800 px-2 py-1 text-left text-neutral-200 font-semibold align-top">
                      {children}
                    </th>
                  ),
                  td: ({ children }) => (
                    <td className="border border-neutral-800 px-2 py-1 text-neutral-200 align-top">{children}</td>
                  ),
                  code: ({ children, className }) => {
                    const isInline = !(className && /\blanguage-/.test(className))

                    const text =
                      typeof children === 'string'
                        ? children.trim()
                        : Array.isArray(children)
                          ? String(children[0] ?? '').trim()
                          : String(children ?? '').trim()

                    if (isInline && text && filePathSet.has(text)) {
                      return (
                        <button
                          type="button"
                          className="font-mono text-[11px] rounded border border-neutral-800 bg-neutral-900 px-1 py-0.5 text-indigo-300 hover:underline"
                          title="Open file"
                          onClick={() => {
                            setDocsOpen(false)
                            void Promise.resolve(app.onSelectNodePath(text))
                          }}
                        >
                          {text}
                        </button>
                      )
                    }

                    if (isInline) {
                      return (
                        <code
                          className={[
                            'font-mono text-[11px] rounded border border-neutral-800 bg-neutral-900 px-1 py-0.5',
                            className || '',
                          ].join(' ')}
                        >
                          {children}
                        </code>
                      )
                    }

                    return (
                      <code className={['font-mono text-[11px]', className || ''].join(' ')}>
                        {children}
                      </code>
                    )
                  },
                  a: ({ href, children }) => {
                    const h = String(href || '').trim()
                    if (h.startsWith('file:')) {
                      const p = h.slice('file:'.length).replace(/^\/+/, '').trim()
                      if (p && filePathSet.has(p)) {
                        return (
                          <button
                            type="button"
                            className="text-indigo-300 hover:underline"
                            onClick={() => {
                              setDocsOpen(false)
                              void Promise.resolve(app.onSelectNodePath(p))
                            }}
                          >
                            {children}
                          </button>
                        )
                      }
                    }
                    return (
                      <a
                        href={h || '#'}
                        className="text-indigo-300 hover:underline"
                        target="_blank"
                        rel="noreferrer"
                      >
                        {children}
                      </a>
                    )
                  },
                }}
              >
                {app.docs.markdown}
              </ReactMarkdown>
            )}
          </div>
        </div>
      </Modal>

      <Modal open={onboardOpen && !!app.activeProject} title="Getting started" onClose={() => closeOnboarding(false)}>
        <div className="space-y-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex-1 space-y-2">
              <div className="flex items-center gap-2 text-neutral-200">
                <span>Step {onboardStep + 1}/{totalOnboardSteps}</span>
                <div className="flex items-center gap-1">
                  {onboardSteps.map((_, index) => {
                    const isActive = index === onboardStep
                    return (
                      <span
                        key={`step-dot-${index}`}
                        className={`h-2 w-2 rounded-full ${isActive ? 'bg-indigo-400' : 'bg-neutral-700'}`}
                      />
                    )
                  })}
                </div>
              </div>
              <div className="h-1 w-full rounded-full bg-neutral-800">
                <div
                  className="h-1 rounded-full bg-indigo-500 transition-all"
                  style={{ width: `${((onboardStep + 1) / totalOnboardSteps) * 100}%` }}
                />
              </div>
            </div>
            <button
              className="rounded-md border border-neutral-700 px-3 py-1 text-xs font-semibold text-neutral-200 hover:bg-neutral-900"
              onClick={() => closeOnboarding(true)}
            >
              Don’t show again
            </button>
          </div>

          <div className="space-y-2">
            {onboardSteps.map((step, index) => {
              const isActive = index === onboardStep
              const action = step.action
              return (
                <div
                  key={step.title}
                  className={`rounded-lg border px-3 py-2 ${
                    isActive
                      ? 'border-indigo-500/70 bg-indigo-500/10'
                      : 'border-neutral-800 bg-neutral-900/40'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <span
                      className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold ${
                        isActive ? 'bg-indigo-500 text-white' : 'bg-neutral-800 text-neutral-200'
                      }`}
                    >
                      {index + 1}
                    </span>
                    <div className="space-y-1">
                      <div className="font-semibold text-neutral-100">{step.title}</div>
                      <div className="text-neutral-300">{step.description}</div>
                      <div className="text-xs text-neutral-400">{step.tip}</div>
                      {action && (
                        <button
                          className={`mt-1 rounded-md px-3 py-1.5 text-xs font-semibold ${
                            action.variant === 'primary'
                              ? 'bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-50'
                              : 'bg-neutral-800 text-neutral-100 hover:bg-neutral-700'
                          }`}
                          onClick={action.onClick}
                          disabled={action.disabled}
                        >
                          {action.label}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>

          <div className="flex items-center justify-between gap-2 pt-2">
            <button
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 px-3 py-2 text-sm font-semibold disabled:opacity-50"
              onClick={() => setOnboardStep((s) => Math.max(0, s - 1))}
              disabled={onboardStep === 0}
            >
              Back
            </button>
            <div className="flex gap-2">
              <button
                className="rounded-md bg-indigo-600 hover:bg-indigo-500 px-3 py-2 text-sm font-semibold"
                onClick={() => {
                  if (onboardStep >= totalOnboardSteps - 1) return closeOnboarding(true)
                  setOnboardStep((s) => Math.min(totalOnboardSteps - 1, s + 1))
                }}
              >
                {onboardStep >= totalOnboardSteps - 1 ? 'Finish' : 'Next'}
              </button>
            </div>
          </div>
        </div>
      </Modal>
    </>
  )
}
