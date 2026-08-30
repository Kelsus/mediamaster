import { useCallback, useState } from 'react'
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  MeasuringStrategy,
  MouseSensor,
  TouchSensor,
  closestCorners,
  pointerWithin,
  useDndContext,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
} from '@dnd-kit/core'
import { rankAt, rankBetween } from '../lib/rank'
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

// Only the 4 columns are droppable, so "which column is the finger in" is the
// whole question — answer it literally, falling back to nearest-corner for
// keyboard drags and pointer positions in the gutters.
const columnCollision: CollisionDetection = (args) => {
  const within = pointerWithin(args)
  return within.length > 0 ? within : closestCorners(args)
}

// The overlay is the only part of the page that follows the drag, so it is the
// only component that subscribes to dnd state — BoardPage itself must never
// re-render on drag start/end (that re-render cascaded into all 500 cards).
function BoardOverlay() {
  const { active } = useDndContext()
  const show = (active?.data.current as { show: Show } | undefined)?.show
  return (
    <DragOverlay>
      {show && (
        <article className="card card-overlay">
          <header className="card-head">
            <span className="card-title">{show.name}</span>
          </header>
        </article>
      )}
    </DragOverlay>
  )
}

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

  const onPatchCard = useCallback(
    (showId: string, patch: object) => patchShow.mutate({ showId, patch }),
    [patchShow.mutate],
  )
  const onDeleteCard = useCallback(
    (showId: string) => deleteShow.mutate({ showId }),
    [deleteShow.mutate],
  )
  const onTransferCard = useCallback(
    (showId: string, toUid: string) => transferShow.mutate({ showId, toUid }),
    [transferShow.mutate],
  )

  const onDragEnd = (e: DragEndEvent) => {
    const show = (e.active.data.current as { show: Show })?.show
    const overId = e.over?.id as string | undefined
    if (!show || !overId || !data) return
    if (!(STATUSES as string[]).includes(overId)) return
    const target = overId as Status

    // Layout is static during drags, so the target column's rendered cards ARE
    // the drop geometry — even under the unverified filter, where the DOM is a
    // subset of the column. The slot is wherever the dragged card's center Y
    // sits, and the new rank goes between the displayed neighbors' ranks.
    const rect = e.active.rect.current.translated
    const dropY = rect ? rect.top + rect.height / 2 : Number.NEGATIVE_INFINITY
    let prevId: string | undefined
    let nextId: string | undefined
    for (const el of document.querySelectorAll<HTMLElement>(
      `.column-${target} .column-cards > .card`,
    )) {
      if (el.classList.contains('card-dragging')) continue // the lifted card itself
      const r = el.getBoundingClientRect()
      if (dropY < r.top + r.height / 2) {
        nextId = el.dataset.showId
        break
      }
      prevId = el.dataset.showId
    }
    const byId = new Map(data.columns[target].map((c) => [c.show_id, c]))
    const prevRank = prevId ? byId.get(prevId)?.rank : undefined
    const nextRank = nextId ? byId.get(nextId)?.rank : undefined
    if (
      target === show.status &&
      show.rank &&
      (!prevRank || prevRank < show.rank) &&
      (!nextRank || show.rank < nextRank)
    ) {
      return // dropped back onto its own slot
    }
    let rank: string
    try {
      rank = rankBetween(prevRank, nextRank)
    } catch {
      rank = rankBetween(prevRank, undefined) // neighbor ranks out of order — land after prev
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
        collisionDetection={columnCollision}
        // The 4 columns are the only droppables; one measure pass at drag
        // start covers them (layout is static during drags).
        measuring={{ droppable: { strategy: MeasuringStrategy.BeforeDragging } }}
        autoScroll={{ threshold: { x: 0.15, y: 0.15 }, acceleration: 8 }}
        onDragEnd={onDragEnd}
      >
        <main className="board">
          {STATUSES.map((status) => (
            <Column
              key={status}
              status={status}
              medium={medium}
              shows={columns[status]}
              onPatch={onPatchCard}
              onDelete={onDeleteCard}
              onTransfer={onTransferCard}
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
        <BoardOverlay />
      </DndContext>
    </div>
  )
}
