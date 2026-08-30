import { useState } from 'react'
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  closestCorners,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { rankAt } from '../lib/rank'
import { Link, NavLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import type { Medium, Show, Status } from '../api/types'
import { getAccessToken, lastLoginMethod, signOut } from '../api/client'
import { enrollPasskey, listPasskeys } from '../api/cognito'
import { useBoard, useShowMutations } from '../hooks/useBoard'
import { useDiscovery } from '../hooks/useDiscovery'
import { Column } from '../components/Column'
import { QuickAdd } from '../components/QuickAdd'

const STATUSES: Status[] = ['to_watch', 'watching', 'done', 'poubelle']

// Only start keyboard drags when the card itself is focused — otherwise
// spaces typed in child edit-in-place inputs would pick the card up.
class CardKeyboardSensor extends KeyboardSensor {
  static activators = [
    {
      eventName: 'onKeyDown' as const,
      handler: (event: any, args: any, context: any) => {
        if (event.target !== event.currentTarget) return false
        return KeyboardSensor.activators[0].handler(event, args, context)
      },
    },
  ]
}

const ADD_PLACEHOLDERS: Record<Medium, Record<Status, string>> = {
  show: {
    to_watch: 'Add something to watch…',
    watching: 'Add something you’re watching…',
    done: 'Add something you’ve watched…',
    poubelle: 'Add something you hated…',
  },
  book: {
    to_watch: 'Add something to read…',
    watching: 'Add something you’re reading…',
    done: 'Add something you’ve read…',
    poubelle: 'Add something you abandoned…',
  },
}

export function BoardPage({ medium }: { medium: Medium }) {
  const { data, isLoading, error } = useBoard(medium)
  const { addShow, patchShow, deleteShow, transferShow } = useShowMutations(medium)
  const { startDiscover, discoverRunning, sortByScore, sortPending } = useDiscovery(medium)
  const [active, setActive] = useState<Show | null>(null)
  const [unverifiedOnly, setUnverifiedOnly] = useState(false)
  const [nudgeState, setNudgeState] = useState<'idle' | 'busy' | 'done' | 'dismissed' | 'error'>(
    () => (localStorage.getItem('mm.enrollNudgeDismissed') ? 'dismissed' : 'idle'),
  )
  const [nudgeError, setNudgeError] = useState('')

  // Offer passkey enrollment after a password login if the account has none.
  const passkeys = useQuery({
    queryKey: ['passkeys'],
    queryFn: async () => listPasskeys(await getAccessToken()),
    enabled: lastLoginMethod() === 'password' && nudgeState !== 'dismissed',
    staleTime: Infinity,
    retry: false,
  })
  const showNudge =
    (passkeys.isSuccess && passkeys.data.length === 0 && nudgeState !== 'dismissed') ||
    nudgeState === 'done'

  const enrollHere = async () => {
    setNudgeState('busy')
    setNudgeError('')
    try {
      await enrollPasskey(await getAccessToken())
      localStorage.setItem('mm.enrollNudgeDismissed', '1')
      setNudgeState('done')
    } catch (e) {
      setNudgeState('error')
      setNudgeError(e instanceof Error ? e.message : String(e))
    }
  }

  // Mouse and touch get separate activation rules: a mouse drag starts after
  // 5px of intent; a finger must DWELL 250ms (scroll flicks never grab cards).
  // PointerSensor is deliberately absent — it would race TouchSensor and lift
  // cards on flicks.
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 8 } }),
    useSensor(CardKeyboardSensor),
  )

  const onDragStart = (e: DragStartEvent) => {
    setActive((e.active.data.current as { show: Show })?.show ?? null)
  }

  const onDragEnd = (e: DragEndEvent) => {
    setActive(null)
    const show = (e.active.data.current as { show: Show })?.show
    const overId = e.over?.id as string | undefined
    if (!show || !overId || !data) return

    const cols = data.columns
    const findContainer = (id: string): Status | undefined => {
      if ((STATUSES as string[]).includes(id)) return id as Status
      return STATUSES.find((st) => cols[st].some((c) => c.show_id === id))
    }
    const target = findContainer(overId)
    if (!target) return

    // Layout never mutates mid-drag, so the cache arrays ARE the geometry:
    // dropping on a card takes its slot; dropping on column chrome goes on top.
    const targetCards = cols[target].filter((c) => c.show_id !== show.show_id)
    let insertAt = 0
    if (overId !== target) {
      const overIndex = targetCards.findIndex((c) => c.show_id === overId)
      if (overIndex < 0) return
      const sameColumn = target === show.status
      const fromIndex = cols[target].findIndex((c) => c.show_id === show.show_id)
      const overOriginal = cols[target].findIndex((c) => c.show_id === overId)
      // Moving down within a column lands AFTER the over card (arrayMove
      // semantics); everything else lands at the over card's slot.
      insertAt = sameColumn && fromIndex >= 0 && fromIndex < overOriginal
        ? overIndex + 1
        : overIndex
    }
    if (target === show.status && cols[target][insertAt]?.show_id === show.show_id) {
      return // dropped back onto its own slot
    }
    let rank: string
    try {
      rank = rankAt(targetCards.map((c) => c.rank), insertAt)
    } catch {
      rank = rankAt([targetCards[insertAt - 1]?.rank].filter(Boolean) as string[], 1)
    }
    const patch: { rank: string; status?: Status } = { rank }
    if (target !== show.status) patch.status = target
    patchShow.mutate({ showId: show.show_id, patch })
  }

  if (isLoading) return <div className="board-status">loading the archive…</div>
  if (error) return <div className="board-status board-error">could not load the board: {String(error)}</div>

  const board = data!
  const columns = unverifiedOnly
    ? (Object.fromEntries(
        Object.entries(board.columns).map(([k, v]) => [k, v.filter((s) => s.unverified)]),
      ) as typeof board.columns)
    : board.columns
  const unverifiedCount = Object.values(board.columns)
    .flat()
    .filter((s) => s.unverified).length
  const freshCount = board.columns.to_watch.filter((s) => s.discovered_at).length

  return (
    <div className="board-page">
      <header className="masthead">
        <h1>
          Media<span>master</span>
        </h1>
        <nav>
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'nav-active' : '')}>
            Shows
          </NavLink>
          <NavLink to="/books" className={({ isActive }) => (isActive ? 'nav-active' : '')}>
            Books
          </NavLink>
          {unverifiedCount > 0 && (
            <button
              type="button"
              className={`link-button ${unverifiedOnly ? 'nav-active' : ''}`}
              title="Imported from the shared Audible account — confirm or delete"
              onClick={() => setUnverifiedOnly((v) => !v)}
            >
              {unverifiedCount} unverified
            </button>
          )}
          <button
            type="button"
            className="link-button discover-button"
            disabled={discoverRunning}
            title={
              medium === 'book'
                ? 'Have Claude find 5 new books your taste profile predicts you will love'
                : 'Have Claude find 5 new movies and 5 new TV shows for your queue'
            }
            onClick={() => startDiscover()}
          >
            {discoverRunning ? 'discovering…' : '✦ Discover'}
          </button>
          <button
            type="button"
            className="link-button"
            disabled={sortPending}
            title={`One-time reorder of ${medium === 'book' ? 'To Read' : 'To Watch'} by taste score — the order stays yours afterwards`}
            onClick={() => sortByScore()}
          >
            {sortPending ? 'sorting…' : 'Sort by score'}
          </button>
          <Link to="/settings">Settings</Link>
          <button type="button" className="link-button" onClick={signOut}>
            Sign out
          </button>
        </nav>
      </header>

      {showNudge && (
        <div className="nudge">
          {nudgeState === 'done' ? (
            <span>Passkey enrolled — next time, sign in with one tap. ✓</span>
          ) : (
            <>
              <span>
                No passkey on this account yet — enroll this device for one-tap logins.
                {nudgeState === 'error' && (
                  <span className="nudge-error"> Failed: {nudgeError}</span>
                )}
              </span>
              <button
                type="button"
                className="nudge-cta"
                disabled={nudgeState === 'busy'}
                onClick={enrollHere}
              >
                {nudgeState === 'busy' ? 'Waiting for Touch ID…' : nudgeState === 'error' ? 'Try again' : 'Enroll passkey'}
              </button>
              <button
                type="button"
                className="link-button"
                onClick={() => {
                  localStorage.setItem('mm.enrollNudgeDismissed', '1')
                  setNudgeState('dismissed')
                }}
              >
                dismiss
              </button>
            </>
          )}
        </div>
      )}

      {freshCount > 0 && (
        <div className="nudge fresh-banner">
          <span>
            ✦ {freshCount} fresh {medium === 'book' ? 'reads' : 'finds'} pinned on top of the
            queue — rank them into the list when you're done looking.
          </span>
          <button
            type="button"
            className="nudge-cta"
            disabled={sortPending}
            onClick={() => sortByScore()}
          >
            {sortPending ? 'Ranking…' : 'Rank into the list'}
          </button>
        </div>
      )}

      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        autoScroll={{ threshold: { x: 0.15, y: 0.15 }, acceleration: 8 }}
        onDragStart={onDragStart}
        onDragMove={(e) => (window as any).__dbg?.push({ over: String(e.over?.id), x: Math.round(e.delta.x), y: Math.round(e.delta.y) })}
        onDragEnd={onDragEnd}
        onDragCancel={() => setActive(null)}
      >
        <main className="board">
          {STATUSES.map((status) => (
            <Column
              key={status}
              status={status}
              medium={medium}
              shows={columns[status]}
              onPatch={(showId, patch) => patchShow.mutate({ showId, patch })}
              onDelete={(showId) => deleteShow.mutate({ showId })}
              onTransfer={(showId, toUid) => transferShow.mutate({ showId, toUid })}
            >
              <QuickAdd
                medium={medium}
                placeholder={ADD_PLACEHOLDERS[medium][status]}
                onAdd={(name, show_type, author) =>
                  addShow.mutate({
                    name,
                    show_type,
                    author,
                    status,
                    rank: rankAt(board.columns[status].map((s) => s.rank), 0),
                  })
                }
              />
            </Column>
          ))}
        </main>
        <DragOverlay>
          {active && (
            <article className="card card-overlay">
              <header className="card-head">
                <span className="card-title">{active.name}</span>
              </header>
            </article>
          )}
        </DragOverlay>
      </DndContext>
    </div>
  )
}
