// Session management + authenticated fetch. Access token lives in memory,
// refresh token in localStorage; refresh happens transparently before expiry.
import { passwordLogin, passkeyLogin, refreshTokens, type Tokens } from './cognito'

const REFRESH_KEY = 'mm.refreshToken'
const EMAIL_KEY = 'mm.email'
const METHOD_KEY = 'mm.lastLoginMethod'

let session: Tokens | null = null
const listeners = new Set<() => void>()

export function onAuthChange(fn: () => void): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

function notify() {
  listeners.forEach((fn) => fn())
}

// Dev-only bypass for the moto mock server (scripts/local_mock.py); stripped
// from production builds (VITE_ALLOW_MOCK lets a local `vite build` keep it,
// for testing production-bundle performance against the mock).
const devBypass = (): boolean =>
  (import.meta.env.DEV || import.meta.env.VITE_ALLOW_MOCK === '1') &&
  !!localStorage.getItem('mm.devBypass')

export const savedEmail = (): string | null => localStorage.getItem(EMAIL_KEY)
export const lastLoginMethod = (): string | null => localStorage.getItem(METHOD_KEY)
export const isSignedIn = (): boolean => session !== null || devBypass()

function setSession(tokens: Tokens, email?: string, method?: 'password' | 'passkey') {
  session = tokens
  if (tokens.refreshToken) localStorage.setItem(REFRESH_KEY, tokens.refreshToken)
  if (email) localStorage.setItem(EMAIL_KEY, email)
  if (method) localStorage.setItem(METHOD_KEY, method)
  notify()
}

export async function signInWithPassword(email: string, password: string) {
  setSession(await passwordLogin(email, password), email, 'password')
}

export async function signInWithPasskey(email: string) {
  setSession(await passkeyLogin(email), email, 'passkey')
}

export function signOut() {
  session = null
  localStorage.removeItem(REFRESH_KEY)
  notify()
}

/** Try to restore a session from a stored refresh token. */
export async function restoreSession(): Promise<boolean> {
  const stored = localStorage.getItem(REFRESH_KEY)
  if (!stored) return false
  try {
    setSession(await refreshTokens(stored))
    return true
  } catch {
    localStorage.removeItem(REFRESH_KEY)
    return false
  }
}

export async function getAccessToken(): Promise<string> {
  if (devBypass()) return 'dev-bypass'
  if (!session) throw new Error('Not signed in')
  if (Date.now() > session.expiresAt - 60_000 && session.refreshToken) {
    try {
      session = await refreshTokens(session.refreshToken)
      if (session.refreshToken) localStorage.setItem(REFRESH_KEY, session.refreshToken)
    } catch {
      signOut()
      throw new Error('Session expired')
    }
  }
  return session.accessToken
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await getAccessToken()
  const resp = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...init?.headers,
    },
  })
  if (resp.status === 401) {
    signOut()
    throw new ApiError(401, 'Session expired')
  }
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      detail = (await resp.json()).detail ?? detail
    } catch {
      /* not json */
    }
    throw new ApiError(resp.status, detail)
  }
  if (resp.status === 204) return undefined as T
  return resp.json()
}
