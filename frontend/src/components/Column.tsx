import type { ReactNode } from 'react'
import { useDroppable } from '@dnd-kit/core'
import type { Show, Status } from '../api/types'
import { ShowCard } from './ShowCard'

const TITLES: Record<Status, string> = {
  to_watch: 'To Watch',
  watching: 'Watching',
  done: 'Done',
  poubelle: 'La Poubelle',
}

const EMPTY: Record<Status, string> = {
  to_watch: 'nothing queued — quelle horreur',
  watching: 'nothing playing',
  done: 'nothing finished yet',
  poubelle: 'vide.',
}

interface Props {
  status: Status
  shows: Show[]
  onPatch: (showId: string, patch: object) => void
  onDelete: (showId: string) => void
  children?: ReactNode // quick-add row for to_watch
}

export function Column({ status, shows, onPatch, onDelete, children }: Props) {
  const { setNodeRef, isOver } = useDroppable({ id: status })

  return (
    <section className={`column column-${status} ${isOver ? 'column-over' : ''}`} ref={setNodeRef}>
      <header className="column-head">
        <h2>{TITLES[status]}</h2>
        <span className="column-count">{shows.length}</span>
      </header>
      {children}
      <div className="column-cards">
        {shows.length === 0 && <p className="column-empty">{EMPTY[status]}</p>}
        {shows.map((show) => (
          <ShowCard
            key={show.show_id}
            show={show}
            onPatch={(patch) => onPatch(show.show_id, patch)}
            onDelete={() => onDelete(show.show_id)}
          />
        ))}
      </div>
    </section>
  )
}
