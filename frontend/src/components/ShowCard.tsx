import { memo, useEffect, useState } from 'react'
import { useDraggable } from '@dnd-kit/core'
import type { Show } from '../api/types'
import { useOtherUsers } from '../hooks/useUsers'
import { EditableText } from './EditableText'
import { ScoreChip } from './ScoreChip'
import { StarRating } from './StarRating'

interface Props {
  show: Show
  onPatch: (patch: object) => void
  onDelete: () => void
  onTransfer: (toUid: string) => void
}

export const ShowCard = memo(function ShowCard({ show, onPatch, onDelete, onTransfer }: Props) {
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
        {show.discovered_at && (
          <span className="new-chip" title="Fresh discovery — not yet ranked into the list">
            ✦ new
          </span>
        )}
        {show.status === 'to_watch' && <ScoreChip show={show} />}
      </header>

      <div className="card-meta">
        {show.medium === 'book' ? (
          <>
            <EditableText
              value={show.author ?? ''}
              placeholder="author"
              className="meta-chip"
              allowEmpty
              onCommit={(v) => onPatch({ author: v || null })}
            />
            {show.series && (
              <span
                className="meta-chip series-chip"
                title={`Part of the ${show.series} series`}
              >
                {show.series}
                {show.series_index ? ` #${show.series_index}` : ''}
              </span>
            )}
            {show.unverified && (
              <button
                type="button"
                className="meta-chip unverified-chip"
                title="Imported from the shared Audible account — click to claim as yours (or delete it)"
                onClick={() => onPatch({ unverified: false })}
                onPointerDown={(e) => e.stopPropagation()}
              >
                yours?
              </button>
            )}
          </>
        ) : (
          <button
            type="button"
            className={`type-chip type-${show.show_type}`}
            title="Toggle tv / movie"
            onClick={() => onPatch({ show_type: show.show_type === 'tv' ? 'movie' : 'tv' })}
            onPointerDown={(e) => e.stopPropagation()}
          >
            {show.show_type === 'tv' ? 'TV' : 'Film'}
          </button>
        )}
        {show.medium !== 'book' && (
          <EditableText
            value={show.service ?? ''}
            placeholder="service"
            className="meta-chip"
            allowEmpty
            onCommit={(v) => onPatch({ service: v || null })}
          />
        )}
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

      {show.unverified && <TransferButton onTransfer={onTransfer} />}
      <DeleteButton onDelete={onDelete} />
    </article>
  )
})

/** Two-click "not mine": arms to "→ Name?", second click transfers the card. */
function TransferButton({ onTransfer }: { onTransfer: (toUid: string) => void }) {
  const others = useOtherUsers()
  const [armed, setArmed] = useState(false)

  useEffect(() => {
    if (!armed) return
    const t = setTimeout(() => setArmed(false), 2500)
    return () => clearTimeout(t)
  }, [armed])

  const target = others.data?.[0]
  if (!target) return null
  const firstName = target.display_name.split(' ')[0]

  return (
    <button
      type="button"
      className={`card-transfer ${armed ? 'card-transfer-armed' : ''}`}
      title={
        armed
          ? `Click again to move this to ${target.display_name}'s board`
          : `Not mine — send to ${target.display_name}`
      }
      onClick={() => (armed ? onTransfer(target.uid) : setArmed(true))}
      onPointerDown={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      {armed ? `→ ${firstName}?` : `→ ${firstName}`}
    </button>
  )
}

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
