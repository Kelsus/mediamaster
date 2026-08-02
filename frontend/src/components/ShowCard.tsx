import { memo, useEffect, useState } from 'react'
import { useDraggable } from '@dnd-kit/core'
import type { Show } from '../api/types'
import { EditableText } from './EditableText'
import { ScoreChip } from './ScoreChip'
import { StarRating } from './StarRating'

interface Props {
  show: Show
  onPatch: (patch: object) => void
  onDelete: () => void
}

export const ShowCard = memo(function ShowCard({ show, onPatch, onDelete }: Props) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: show.show_id,
    data: { show },
  })

  return (
    <article
      ref={setNodeRef}
      className={`card ${isDragging ? 'card-dragging' : ''}`}
      {...attributes}
      {...listeners}
    >
      <header className="card-head">
        <EditableText
          value={show.name}
          className="card-title"
          onCommit={(name) => onPatch({ name })}
        />
        {show.status === 'to_watch' && <ScoreChip show={show} />}
      </header>

      <div className="card-meta">
        <button
          type="button"
          className={`type-chip type-${show.show_type}`}
          title="Toggle tv / movie"
          onClick={() => onPatch({ show_type: show.show_type === 'tv' ? 'movie' : 'tv' })}
          onPointerDown={(e) => e.stopPropagation()}
        >
          {show.show_type === 'tv' ? 'TV' : 'Film'}
        </button>
        <EditableText
          value={show.service ?? ''}
          placeholder="service"
          className="meta-chip"
          allowEmpty
          onCommit={(v) => onPatch({ service: v || null })}
        />
        <EditableText
          value={show.source ? `via ${show.source}` : ''}
          placeholder="via …"
          className="meta-chip"
          allowEmpty
          onCommit={(v) => onPatch({ source: v.replace(/^via\s+/i, '') || null })}
        />
      </div>

      {show.status === 'done' && (
        <StarRating rating={show.rating} onRate={(rating) => onPatch({ rating })} />
      )}

      <DeleteButton onDelete={onDelete} />
    </article>
  )
})

/** Two-click delete: first click arms it, second deletes; disarms after 2.5s. */
function DeleteButton({ onDelete }: { onDelete: () => void }) {
  const [armed, setArmed] = useState(false)

  useEffect(() => {
    if (!armed) return
    const t = setTimeout(() => setArmed(false), 2500)
    return () => clearTimeout(t)
  }, [armed])

  return (
    <button
      type="button"
      className={`card-delete ${armed ? 'card-delete-armed' : ''}`}
      title={armed ? 'Click again to delete forever' : 'Delete'}
      aria-label={armed ? 'Confirm permanent delete' : 'Delete show'}
      onClick={() => (armed ? onDelete() : setArmed(true))}
      onPointerDown={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      {armed ? 'delete?' : '×'}
    </button>
  )
}
