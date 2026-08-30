import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Board, Medium, Show, ShowPatch, ShowType, Status } from '../api/types'

const emptyBoard = (): Board => ({
  columns: { to_watch: [], watching: [], done: [], poubelle: [] },
})

export function useBoard(medium: Medium) {
  return useQuery<Board>({
    queryKey: ['board', medium],
    queryFn: () => api<Board>(`/api/board?medium=${medium}`),
    staleTime: 30_000,
  })
}

/** Insert into a column keeping to_watch ordered by known scores, others by recency. */
function insertInto(column: Show[], show: Show, status: Status): Show[] {
  if (status === 'to_watch') {
    const score = show.predicted_score ?? 0
    const idx = column.findIndex((s) => (s.predicted_score ?? 0) < score)
    const at = idx === -1 ? column.length : idx
    return [...column.slice(0, at), show, ...column.slice(at)]
  }
  return [show, ...column]
}

function moveShow(board: Board, showId: string, patch: ShowPatch): Board {
  const columns = { ...board.columns }
  let moved: Show | undefined
  for (const status of Object.keys(columns) as Status[]) {
    const found = columns[status].find((s) => s.show_id === showId)
    if (found) {
      moved = { ...found, ...sanitize(patch) }
      columns[status] = columns[status].filter((s) => s.show_id !== showId)
      break
    }
  }
  if (!moved) return board
  const target = (patch.status ?? moved.status) as Status
  if (patch.status && patch.status !== 'done') {
    moved.rating = undefined
  }
  moved.status = target
  columns[target] = insertInto(columns[target], moved, target)
  return { columns }
}

function sanitize(patch: ShowPatch): Partial<Show> {
  const out: any = {}
  for (const [k, v] of Object.entries(patch)) {
    out[k] = v === null ? undefined : v
  }
  return out
}

export function useShowMutations(medium: Medium) {
  const qc = useQueryClient()
  const KEY = ['board', medium]

  const withOptimistic = <TArgs,>(
    mutationFn: (args: TArgs) => Promise<unknown>,
    apply: (board: Board, args: TArgs) => Board,
  ) =>
    useMutation({
      mutationFn,
      onMutate: async (args: TArgs) => {
        await qc.cancelQueries({ queryKey: KEY })
        const previous = qc.getQueryData<Board>(KEY)
        qc.setQueryData<Board>(KEY, (old) => apply(old ?? emptyBoard(), args))
        return { previous }
      },
      onError: (_err, _args, ctx) => {
        if (ctx?.previous) qc.setQueryData(KEY, ctx.previous)
      },
      onSettled: () => qc.invalidateQueries({ queryKey: KEY }),
    })

  const addShow = withOptimistic(
    (args: {
      name: string
      show_type: ShowType
      status?: Status
      author?: string
      service?: string
      source?: string
    }) => api('/api/shows', { method: 'POST', body: JSON.stringify({ ...args, medium }) }),
    (board, args) => {
      const status: Status = args.status ?? 'to_watch'
      const temp: Show = {
        show_id: `temp-${Date.now()}`,
        name: args.name,
        show_type: args.show_type,
        medium,
        author: args.author,
        service: args.service,
        source: args.source,
        status,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        status_changed_at: new Date().toISOString(),
        predicted_score: Number.POSITIVE_INFINITY, // pin to top until the server scores it
      }
      return { columns: { ...board.columns, [status]: [temp, ...board.columns[status]] } }
    },
  )

  const patchShow = withOptimistic(
    (args: { showId: string; patch: ShowPatch }) =>
      api(`/api/shows/${args.showId}`, { method: 'PATCH', body: JSON.stringify(args.patch) }),
    (board, args) => moveShow(board, args.showId, args.patch),
  )

  const deleteShow = withOptimistic(
    (args: { showId: string }) => api(`/api/shows/${args.showId}`, { method: 'DELETE' }),
    (board, args) => ({
      columns: Object.fromEntries(
        Object.entries(board.columns).map(([k, v]) => [
          k,
          v.filter((s) => s.show_id !== args.showId),
        ]),
      ) as Board['columns'],
    }),
  )

  // Transfer looks like a delete locally: the card leaves this board.
  const transferShow = withOptimistic(
    (args: { showId: string; toUid: string }) =>
      api(`/api/shows/${args.showId}/transfer`, {
        method: 'POST',
        body: JSON.stringify({ to_uid: args.toUid }),
      }),
    (board, args) => ({
      columns: Object.fromEntries(
        Object.entries(board.columns).map(([k, v]) => [
          k,
          v.filter((s) => s.show_id !== args.showId),
        ]),
      ) as Board['columns'],
    }),
  )

  return { addShow, patchShow, deleteShow, transferShow }
}
