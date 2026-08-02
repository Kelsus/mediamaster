import { useState } from 'react'
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import type { Show, Status } from '../api/types'
import { getAccessToken, lastLoginMethod, signOut } from '../api/client'
import { enrollPasskey, listPasskeys } from '../api/cognito'
import { useBoard, useShowMutations } from '../hooks/useBoard'
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

export function BoardPage() {
  const { data, isLoading, error } = useBoard()
  const { addShow, patchShow, deleteShow } = useShowMutations()
  const [active, setActive] = useState<Show | null>(null)
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

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(CardKeyboardSensor),
  )

  const onDragStart = (e: DragStartEvent) => {
    setActive((e.active.data.current as { show: Show })?.show ?? null)
  }

  const onDragEnd = (e: DragEndEvent) => {
    setActive(null)
    const show = (e.active.data.current as { show: Show })?.show
    const target = e.over?.id as Status | undefined
    if (!show || !target || target === show.status) return
    patchShow.mutate({ showId: show.show_id, patch: { status: target } })
  }

  if (isLoading) return <div className="board-status">loading the archive…</div>
  if (error) return <div className="board-status board-error">could not load the board: {String(error)}</div>

  const columns = data!.columns

  return (
    <div className="board-page">
      <header className="masthead">
        <h1>
          Media<span>master</span>
        </h1>
        <nav>
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

      <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd}>
        <main className="board">
          {STATUSES.map((status) => (
            <Column
              key={status}
              status={status}
              shows={columns[status]}
              onPatch={(showId, patch) => patchShow.mutate({ showId, patch })}
              onDelete={(showId) => deleteShow.mutate({ showId })}
            >
              {status === 'to_watch' && (
                <QuickAdd onAdd={(name, show_type) => addShow.mutate({ name, show_type })} />
              )}
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
