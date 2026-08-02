import { useState, type FormEvent } from 'react'
import { savedEmail, signInWithPasskey, signInWithPassword } from '../api/client'

export function LoginPage() {
  const [email, setEmail] = useState(savedEmail() ?? '')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const passkey = () => {
    if (!email.trim()) {
      setError('Enter your email first')
      return
    }
    run(() => signInWithPasskey(email.trim()))
  }

  const password_ = (e: FormEvent) => {
    e.preventDefault()
    run(() => signInWithPassword(email.trim(), password))
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <h1 className="login-masthead">
          Media<span>master</span>
        </h1>
        <p className="login-tagline">the watchlist that knows your taste</p>

        <form onSubmit={password_}>
          <label>
            <span>Email</span>
            <input
              type="email"
              value={email}
              autoComplete="username webauthn"
              onChange={(e) => setEmail(e.target.value)}
              autoFocus={!email}
            />
          </label>

          <button type="button" className="button-primary" disabled={busy} onClick={passkey}>
            {busy ? 'Signing in…' : 'Sign in with passkey'}
          </button>

          {!showPassword ? (
            <button
              type="button"
              className="link-button login-alt"
              onClick={() => setShowPassword(true)}
            >
              use password instead
            </button>
          ) : (
            <>
              <label>
                <span>Password</span>
                <input
                  type="password"
                  value={password}
                  autoComplete="current-password"
                  onChange={(e) => setPassword(e.target.value)}
                  autoFocus
                />
              </label>
              <button type="submit" className="button-secondary" disabled={busy || !password}>
                Sign in with password
              </button>
            </>
          )}
        </form>

        {error && <p className="login-error">{error}</p>}
      </div>
    </div>
  )
}
