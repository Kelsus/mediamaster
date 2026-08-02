import { useEffect, useRef, useState } from 'react'

interface Props {
  value: string
  placeholder?: string
  className?: string
  onCommit: (value: string) => void
  /** allow committing an empty value (clears the field) */
  allowEmpty?: boolean
}

export function EditableText({ value, placeholder, className, onCommit, allowEmpty }: Props) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus()
      inputRef.current?.select()
    }
  }, [editing])

  const commit = () => {
    setEditing(false)
    const trimmed = draft.trim()
    if (trimmed === value) return
    if (!trimmed && !allowEmpty) {
      setDraft(value)
      return
    }
    onCommit(trimmed)
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        className={`editable-input ${className ?? ''}`}
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          e.stopPropagation() // keep keystrokes out of the card's drag sensors
          if (e.key === 'Enter') commit()
          if (e.key === 'Escape') {
            setDraft(value)
            setEditing(false)
          }
        }}
        onPointerDown={(e) => e.stopPropagation()}
      />
    )
  }

  return (
    <button
      type="button"
      className={`editable ${className ?? ''} ${value ? '' : 'editable-empty'}`}
      onClick={() => {
        setDraft(value)
        setEditing(true)
      }}
      onPointerDown={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
      aria-label={value ? `${value} — click to edit` : `add ${placeholder ?? 'value'}`}
    >
      {value || placeholder}
    </button>
  )
}
