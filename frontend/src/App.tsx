import { useEffect, useState } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { isSignedIn, onAuthChange, restoreSession } from './api/client'
import { BoardPage } from './pages/BoardPage'
import { LoginPage } from './pages/LoginPage'
import { SettingsPage } from './pages/SettingsPage'

export function App() {
  const [signedIn, setSignedIn] = useState(isSignedIn())
  const [restoring, setRestoring] = useState(true)

  useEffect(() => {
    const off = onAuthChange(() => setSignedIn(isSignedIn()))
    restoreSession().finally(() => setRestoring(false))
    return off
  }, [])

  if (restoring) return <div className="board-status">…</div>
  if (!signedIn) return <LoginPage />

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<BoardPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<BoardPage />} />
      </Routes>
    </BrowserRouter>
  )
}
