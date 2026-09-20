import { useState } from 'react'
import Home from './pages/Home.jsx'
import Chat from './pages/Chat.jsx'
import { getSession, saveSession, clearSession, isSessionExpired } from './session.js'

export default function App() {
  const [session, setSession] = useState(() => {
    const stored = getSession()
    if (stored && !isSessionExpired(stored)) return stored
    if (stored) clearSession()
    return null
  })

  function setActiveSession(next) {
    if (next) saveSession(next)
    else clearSession()
    setSession(next)
  }

  if (!session) {
    return <Home onSession={setActiveSession} />
  }

  return <Chat session={session} onLeave={() => setActiveSession(null)} />
}