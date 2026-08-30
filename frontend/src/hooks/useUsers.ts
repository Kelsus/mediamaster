import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { OtherUser } from '../api/types'

/** Everyone except me — transfer targets for "not mine" triage. */
export function useOtherUsers() {
  return useQuery<OtherUser[]>({
    queryKey: ['users'],
    queryFn: () => api<OtherUser[]>('/api/users'),
    staleTime: Infinity,
  })
}
