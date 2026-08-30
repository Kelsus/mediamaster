import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Medium, ScoutState, TasteProfile } from '../api/types'

/** Fire when a boolean transitions true -> false (a background run finished). */
function useRunFinished(running: boolean, onFinish: () => void) {
  const prev = useRef(running)
  useEffect(() => {
    if (prev.current && !running) onFinish()
    prev.current = running
  }, [running, onFinish])
}

/** Discovery + re-rank plumbing for the board header and fresh-finds banner. */
export function useDiscovery(medium: Medium) {
  const qc = useQueryClient()

  const scout = useQuery<ScoutState>({
    queryKey: ['scout', medium],
    queryFn: () => api<ScoutState>(`/api/scout?medium=${medium}`),
    refetchInterval: (q) =>
      q.state.data?.discover_status === 'running' || q.state.data?.scout_status === 'running'
        ? 5000
        : false,
  })

  const taste = useQuery<TasteProfile>({
    queryKey: ['taste', medium],
    queryFn: () => api<TasteProfile>(`/api/taste?medium=${medium}`),
    refetchInterval: (q) => (q.state.data?.scoring_status === 'running' ? 5000 : false),
  })

  const startDiscover = useMutation({
    mutationFn: () => api(`/api/discover?medium=${medium}`, { method: 'POST' }),
    onSettled: () => qc.invalidateQueries({ queryKey: ['scout', medium] }),
  })

  const rescore = useMutation({
    mutationFn: () => api(`/api/rescore?medium=${medium}`, { method: 'POST' }),
    onSettled: () => qc.invalidateQueries({ queryKey: ['taste', medium] }),
  })

  const discoverRunning =
    startDiscover.isPending || scout.data?.discover_status === 'running'
  const rescoreRunning = rescore.isPending || taste.data?.scoring_status === 'running'

  useRunFinished(discoverRunning, () => {
    qc.invalidateQueries({ queryKey: ['board', medium] })
  })
  useRunFinished(rescoreRunning, () => {
    qc.invalidateQueries({ queryKey: ['board', medium] })
  })

  return {
    scout,
    startDiscover: () => startDiscover.mutate(),
    discoverRunning,
    rescore: () => rescore.mutate(),
    rescoreRunning,
  }
}
