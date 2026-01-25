// frontend/src/ui/components/FileEditorModal.tsx
import { Modal } from './Modal'
import { FileEditorPane, type FileEditorPaneProps } from './FileEditorPane'

type Props = FileEditorPaneProps

export function FileEditorModal({
  open,
  path,
  original,
  content,
  busy,
  saving,
  dirty,
  truncated,
  error,
  onChange,
  onReload,
  onSave,
  onClose,
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
        original={original}
        content={content}
        busy={busy}
        saving={saving}
        dirty={dirty}
        truncated={truncated}
        error={error}
        onChange={onChange}
        onReload={onReload}
        onSave={onSave}
        onClose={onClose}
      />
    </Modal>
  )
}
