import { memo, useEffect, useState, type ReactNode } from 'react'
import { useDraggable } from '@dnd-kit/core'
import type { Show } from '../api/types'
import { useOtherUsers } from '../hooks/useUsers'
import { EditableText } from './EditableText'
import { ScoreChip } from './ScoreChip'
import { StarRating } from './StarRating'

// Handlers take the showId so the same function identities serve every card —
// that's what lets memo() actually bail: per-card closures would re-render all
// 500 cards whenever any parent renders (including at drag activation).
interface Props {
  show: Show
  onPatch: (showId: string, patch: object) => void
  onDelete: (showId: string) => void
  onTransfer: (showId: string, toUid: string) => void
}

// The card's ONLY dnd-context consumer. dnd-kit re-renders every consumer on
// each drag-state change; keeping the hook in this thin wrapper means those
// re-renders rebuild one <article> and bail out of the (identity-stable)
// children — the card body never re-renders during a drag. With 500-card
// columns, hooks inside the body itself melted phone main threads.
function DragShell({ show, children }: { show: Show; children: ReactNode }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: show.show_id,
    data: { show },
  })
  return (
    <article
      ref={setNodeRef}
      className={`card ${isDragging ? 'card-dragging' : ''}`}
      data-show-id={show.show_id}
      {...attributes}
      {...listeners}
    >
      {children}
    </article>
  )
}

export const ShowCard = memo(function ShowCard({ show, onPatch, onDelete, onTransfer }: Props) {
  return (
    <DragShell show={show}>
      <header className="card-head">
        <EditableText
          value={show.name}
          className="card-title"
          onCommit={(name) => onPatch(show.show_id, { name })}
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
              onCommit={(v) => onPatch(show.show_id, { author: v || null })}
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
                onClick={() => onPatch(show.show_id, { unverified: false })}
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
            onClick={() => onPatch(show.show_id, { show_type: show.show_type === 'tv' ? 'movie' : 'tv' })}
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
            onCommit={(v) => onPatch(show.show_id, { service: v || null })}
          />
        )}
        <EditableText
          value={show.source ? `via ${show.source}` : ''}
          placeholder="via …"
          className="meta-chip"
          allowEmpty
          onCommit={(v) => onPatch(show.show_id, { source: v.replace(/^via\s+/i, '') || null })}
        />
      </div>

      {show.status === 'done' && (
        <StarRating rating={show.rating} onRate={(rating) => onPatch(show.show_id, { rating })} />
      )}

      {show.unverified && <TransferButton showId={show.show_id} onTransfer={onTransfer} />}
      <DeleteButton showId={show.show_id} onDelete={onDelete} />
    </DragShell>
  )
})

/** Two-click "not mine": arming reveals one confirm button per household member. */
function TransferButton({ showId, onTransfer }: { showId: string; onTransfer: (showId: string, toUid: string) => void }) {
  const others = useOtherUsers()
  const [armed, setArmed] = useState(false)

  useEffect(() => {
    if (!armed) return
    const t = setTimeout(() => setArmed(false), 4000)
    return () => clearTimeout(t)
  }, [armed])

  const targets = others.data ?? []
  if (targets.length === 0) return null
  const first = (u: { display_name: string }) => u.display_name.split(' ')[0]

  if (!armed) {
    return (
      <button
        type="button"
        className="card-transfer"
        title="Not mine — send to someone else's board"
        onClick={() => setArmed(true)}
        onPointerDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        {targets.length === 1 ? `→ ${first(targets[0])}` : '→ …'}
      </button>
    )
  }

  return (
    <span className="card-transfer-targets" onPointerDown={(e) => e.stopPropagation()}>
      {targets.map((t) => (
        <button
          key={t.uid}
          type="button"
          className="card-transfer card-transfer-armed"
          title={`Move this to ${t.display_name}'s board`}
          onClick={() => onTransfer(showId, t.uid)}
          onKeyDown={(e) => e.stopPropagation()}
        >
          → {first(t)}?
        </button>
      ))}
    </span>
  )
}

/** Two-click delete: first click arms it, second deletes; disarms after 2.5s. */
function DeleteButton({ showId, onDelete }: { showId: string; onDelete: (showId: string) => void }) {
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
      onClick={() => (armed ? onDelete(showId) : setArmed(true))}
      onPointerDown={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      {armed ? 'delete?' : '×'}
    </button>
  )
}
