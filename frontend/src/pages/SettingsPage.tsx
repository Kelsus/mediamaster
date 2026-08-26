import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, getAccessToken } from '../api/client'
import { enrollPasskey, listPasskeys } from '../api/cognito'
import type { ApiToken, Medium, ScoutState, TasteProfile } from '../api/types'

const SCOUT_COPY: Record<Medium, { title: string; blurb: string; cta: string; ctaBusy: string }> = {
  show: {
    title: 'Season Scout',
    blurb:
      'Checks which shows you finished (and liked) have a new season out — using web search for anything recent — and drops the missing "Season N" cards into To Watch. Runs automatically on the 1st of each month, when you rate a season 2★ or better, or on demand here.',
    cta: 'Scout for new seasons',
    ctaBusy: 'Scouting… (takes a few minutes)',
  },
  book: {
    title: 'Series Scout',
    blurb:
      'Checks which book series you\u2019re current on have a next entry published — using web search for recent releases — and queues the real next book in To Read. Runs monthly, when you rate a series book 2★ or better, or on demand here.',
    cta: 'Scout for next books',
    ctaBusy: 'Scouting… (takes a few minutes)',
  },
}

function ScoutSection({ medium }: { medium: Medium }) {
  const qc = useQueryClient()

  const scout = useQuery<ScoutState>({
    queryKey: ['scout', medium],
    queryFn: () => api<ScoutState>(`/api/scout?medium=${medium}`),
    refetchInterval: (query) => (query.state.data?.scout_status === 'running' ? 5000 : false),
  })

  const running = scout.data?.scout_status === 'running'

  const start = useMutation({
    mutationFn: () => api(`/api/scout?medium=${medium}`, { method: 'POST' }),
    onSettled: () => qc.invalidateQueries({ queryKey: ['scout', medium] }),
  })

  const status = scout.data?.scout_status
  useEffect(() => {
    if (status === 'idle') qc.invalidateQueries({ queryKey: ['board'] })
  }, [status, qc])

  const s = scout.data
  const created = s?.last_run?.created ?? []

  const copy = SCOUT_COPY[medium]
  return (
    <section>
      <h2>{copy.title}</h2>
      <p>{copy.blurb}</p>
      <div className="taste-actions">
        <button
          type="button"
          className="button-primary"
          disabled={running || start.isPending}
          onClick={() => start.mutate()}
        >
          {running ? copy.ctaBusy : copy.cta}
        </button>
        {s?.last_run && (
          <span className="settings-msg">
            Last run {new Date(s.last_run.finished_at).toLocaleString()}: checked{' '}
            {s.last_run.checked}, added {created.length} (~${s.last_run.est_cost_usd})
          </span>
        )}
      </div>
      {s?.last_error && <p className="taste-error">Last run failed: {s.last_error}</p>}
      {created.length > 0 && (
        <p className="settings-msg">
          Added to your queue: {created.join(' · ')}
        </p>
      )}
    </section>
  )
}

function TasteSection({ medium }: { medium: Medium }) {
  const qc = useQueryClient()
  const [notes, setNotes] = useState<string | null>(null) // null = not yet edited
  const [showProfile, setShowProfile] = useState(false)

  const taste = useQuery<TasteProfile>({
    queryKey: ['taste', medium],
    queryFn: () => api<TasteProfile>(`/api/taste?medium=${medium}`),
    refetchInterval: (query) => (query.state.data?.scoring_status === 'running' ? 5000 : false),
  })

  const running = taste.data?.scoring_status === 'running'

  const rescore = useMutation({
    mutationFn: () => api(`/api/rescore?medium=${medium}`, { method: 'POST' }),
    onSettled: () => qc.invalidateQueries({ queryKey: ['taste', medium] }),
  })

  const saveNotes = useMutation({
    mutationFn: (n: string) =>
      api<TasteProfile>(`/api/taste/notes?medium=${medium}`, {
        method: 'PUT',
        body: JSON.stringify({ notes: n }),
      }),
    onSuccess: (data) => {
      qc.setQueryData(['taste', medium], data)
      setNotes(null)
    },
  })

  // once a run finishes, pull the freshly scored board
  const wasRunning = taste.data?.scoring_status
  useEffect(() => {
    if (wasRunning === 'idle') qc.invalidateQueries({ queryKey: ['board'] })
  }, [wasRunning, qc])

  const t = taste.data

  return (
    <section>
      <h2>{medium === 'book' ? 'Reading-taste profile' : 'Taste profile'}</h2>
      <p>
        {medium === 'book'
          ? 'Claude Opus 5 reads your rating history, writes a reading-taste profile, and scores every book in To Read (0–100). Re-scoring is manual.'
          : 'Claude Opus 5 reads your entire rating history, writes a taste profile, and scores every show in To Watch (0–100). Re-scoring is manual and costs roughly $1–2 per run.'}
      </p>

      <div className="taste-actions">
        <button
          type="button"
          className="button-primary"
          disabled={running || rescore.isPending}
          onClick={() => rescore.mutate()}
        >
          {running ? 'Scoring… (takes a couple of minutes)' : 'Re-score now'}
        </button>
        {t?.last_run && (
          <span className="settings-msg">
            Last run {new Date(t.last_run.finished_at).toLocaleString()}: scored{' '}
            {t.last_run.scored}/{t.last_run.queue_size} (~${t.last_run.est_cost_usd})
          </span>
        )}
      </div>
      {t?.last_error && <p className="taste-error">Last run failed: {t.last_error}</p>}

      <label className="taste-notes-label">
        <span>Your taste notes (fed to the profiler on the next run)</span>
        <textarea
          rows={4}
          placeholder="e.g. Lately I want slow-burn crime and nothing about tech billionaires…"
          value={notes ?? t?.notes ?? ''}
          onChange={(e) => setNotes(e.target.value)}
        />
      </label>
      {notes !== null && notes !== (t?.notes ?? '') && (
        <button
          type="button"
          className="button-secondary"
          disabled={saveNotes.isPending}
          onClick={() => saveNotes.mutate(notes)}
        >
          Save notes
        </button>
      )}

      {t?.profile_text && (
        <details className="taste-profile" open={showProfile} onToggle={(e) => setShowProfile(e.currentTarget.open)}>
          <summary>
            Claude's profile of your taste
            {t.generated_at && ` (generated ${new Date(t.generated_at).toLocaleDateString()})`}
          </summary>
          <pre>{t.profile_text}</pre>
        </details>
      )}
    </section>
  )
}

export function SettingsPage() {
  const qc = useQueryClient()
  const [medium, setMedium] = useState<Medium>('show')
  const [passkeyMsg, setPasskeyMsg] = useState<string | null>(null)
  const [label, setLabel] = useState('')
  const [freshToken, setFreshToken] = useState<string | null>(null)

  const tokens = useQuery<ApiToken[]>({
    queryKey: ['tokens'],
    queryFn: () => api<ApiToken[]>('/api/tokens'),
  })

  const passkeys = useQuery({
    queryKey: ['passkeys'],
    queryFn: async () => listPasskeys(await getAccessToken()),
    retry: false,
  })

  const createToken = useMutation({
    mutationFn: (label: string) =>
      api<{ token: string }>('/api/tokens', { method: 'POST', body: JSON.stringify({ label }) }),
    onSuccess: (data) => {
      setFreshToken(data.token)
      setLabel('')
      qc.invalidateQueries({ queryKey: ['tokens'] })
    },
  })

  const revokeToken = useMutation({
    mutationFn: (prefix: string) => api(`/api/tokens/${prefix}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tokens'] }),
  })

  const enroll = async () => {
    setPasskeyMsg(null)
    try {
      await enrollPasskey(await getAccessToken())
      localStorage.setItem('mm.enrollNudgeDismissed', '1')
      setPasskeyMsg('Passkey enrolled — next sign-in is one tap.')
      qc.invalidateQueries({ queryKey: ['passkeys'] })
    } catch (e) {
      setPasskeyMsg(`Enrollment failed: ${e instanceof Error ? e.message : e}`)
    }
  }

  return (
    <div className="settings-page">
      <header className="masthead">
        <h1>
          Media<span>master</span>
        </h1>
        <nav>
          <Link to="/">Board</Link>
        </nav>
      </header>

      <main className="settings">
        <div className="medium-tabs" role="tablist" aria-label="Shows or Books">
          <button
            type="button"
            role="tab"
            aria-selected={medium === 'show'}
            className={medium === 'show' ? 'active' : ''}
            onClick={() => setMedium('show')}
          >
            Shows
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={medium === 'book'}
            className={medium === 'book' ? 'active' : ''}
            onClick={() => setMedium('book')}
          >
            Books
          </button>
        </div>
        <TasteSection key={`taste-${medium}`} medium={medium} />
        <ScoutSection key={`scout-${medium}`} medium={medium} />

        <section>
          <h2>Passkeys</h2>
          <p>Enroll a passkey on this device to sign in with Touch ID instead of a password.</p>
          {passkeys.isSuccess && (
            <p className="settings-msg">
              {passkeys.data.length === 0
                ? 'No passkeys enrolled yet.'
                : `${passkeys.data.length} enrolled: ` +
                  passkeys.data
                    .map(
                      (c: any) =>
                        c.FriendlyCredentialName ||
                        `${c.AuthenticatorAttachment ?? 'passkey'} (${new Date(c.CreatedAt * 1000).toLocaleDateString()})`,
                    )
                    .join(', ')}
            </p>
          )}
          <button type="button" className="button-primary" onClick={enroll}>
            Enroll this device
          </button>
          {passkeyMsg && <p className="settings-msg">{passkeyMsg}</p>}
        </section>

        <section>
          <h2>API tokens</h2>
          <p>
            Long-lived tokens for the MCP server and the import script. The full token is shown
            once, at creation.
          </p>

          <form
            className="token-form"
            onSubmit={(e) => {
              e.preventDefault()
              if (label.trim()) createToken.mutate(label.trim())
            }}
          >
            <input
              value={label}
              placeholder="label (e.g. claude-mcp)"
              onChange={(e) => setLabel(e.target.value)}
            />
            <button type="submit" className="button-secondary" disabled={!label.trim()}>
              Mint token
            </button>
          </form>

          {freshToken && (
            <div className="fresh-token">
              <p>Copy this now — it will not be shown again:</p>
              <code>{freshToken}</code>
              <button
                type="button"
                className="link-button"
                onClick={() => navigator.clipboard.writeText(freshToken)}
              >
                copy
              </button>
            </div>
          )}

          <table className="token-table">
            <tbody>
              {(tokens.data ?? []).map((t) => (
                <tr key={t.prefix}>
                  <td>
                    <code>{t.prefix}…</code>
                  </td>
                  <td>{t.label}</td>
                  <td>{new Date(t.created_at).toLocaleDateString()}</td>
                  <td>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => revokeToken.mutate(t.prefix)}
                    >
                      revoke
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </main>
    </div>
  )
}
