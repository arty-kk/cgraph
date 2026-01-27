// frontend/src/ui/components/FileEditorModal.tsx
import { Modal } from './Modal'
import { FileEditorPane, type FileEditorPaneProps } from './FileEditorPane'

type Props = FileEditorPaneProps

export function FileEditorModal({
  open,
  path,
  tabs,
  activePath,
  original,
  content,
  busy,
  saving,
  dirty,
  truncated,
  error,
  wrap,
  showDiff,
  fontSize,
  pendingJump,
  onApplyPendingJump,
  onSelectTab,
  onCloseTab,
  onChange,
  onReload,
  onSave,
  onClose,
  onToggleWrap,
  onToggleDiff,
  onSetFontSize,
}: Props) {
  const title = path ? `File: ${path}` : 'File viewer'

  return (
    <Modal
      open={open}
      title={title}
      onClose={onClose}
      panelClassName="w-[min(1400px,calc(100vw-32px))]"
    >
      <FileEditorPane
        open={open}
        path={path}
        tabs={tabs}
        activePath={activePath}
        original={original}
        content={content}
        busy={busy}
        saving={saving}
        dirty={dirty}
        truncated={truncated}
        error={error}
        wrap={wrap}
        showDiff={showDiff}
        fontSize={fontSize}
        pendingJump={pendingJump}
        onApplyPendingJump={onApplyPendingJump}
        onSelectTab={onSelectTab}
        onCloseTab={onCloseTab}
        onChange={onChange}
        onReload={onReload}
        onSave={onSave}
        onClose={onClose}
        onToggleWrap={onToggleWrap}
        onToggleDiff={onToggleDiff}
        onSetFontSize={onSetFontSize}
      />
    </Modal>
  )
}
