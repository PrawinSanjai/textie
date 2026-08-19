import { useState } from 'react'
import { createConversation, joinConversation } from '../api.js'

export default function Home({ onSession }) {
  const [mode, setMode] = useState('home')
  const [created, setCreated] = useState(null)
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  function enterChat(data, isOwner) {
    onSession({
      conversationId: data.conversation_id,
      code: data.code,
      participantId: data.participant_id,
      participantToken: data.participant_token,
      expiresAt: data.expires_at,
      isOwner,
      createdAt: new Date().toISOString(),
    })
  }

  async function handleCreate() {
    setBusy(true)
    setError('')
    try {
      const data = await createConversation()
      setCreated(data)
      setMode('create')
    } catch (err) {
      setError(err.message || 'Failed to create a conversation.')
    } finally {
      setBusy(false)
    }
  }

  async function handleJoin() {
    const trimmed = code.trim()
    if (!/^\d{6}$/.test(trimmed)) {
      setError('Enter the 6-digit code.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const data = await joinConversation(trimmed)
      enterChat(data, false)
    } catch (err) {
      setError(err.message || 'Failed to join the conversation.')
    } finally {
      setBusy(false)
    }
  }

  async function copyCode() {
    if (!created) return
    try {
      await navigator.clipboard.writeText(created.code)
      setError('')
    } catch (_) {
      /* clipboard unavailable */
    }
  }

  return (
    <div className="home">
      <div className="brand">
        <h1>Textie</h1>
        <p>Nearby texting. Create a room, share the code, start chatting.</p>
      </div>

      {mode === 'home' && (
        <div className="home-actions">
          <button className="btn btn-primary" onClick={handleCreate} disabled={busy}>
            {busy ? 'Creating...' : 'Create a room'}
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => {
              setMode('join')
              setError('')
            }}
          >
            Join with a code
          </button>
        </div>
      )}

      {mode === 'create' && created && (
        <div className="created">
          <p className="muted">Share this code with someone nearby:</p>
          <div className="code-box">{created.code}</div>
          <div className="row">
            <button className="btn btn-ghost" onClick={copyCode}>
              Copy code
            </button>
            <button
              className="btn btn-primary"
              onClick={() => enterChat(created, true)}
            >
              Enter chat
            </button>
          </div>
        </div>
      )}

      {mode === 'join' && (
        <form
          className="join-form"
          onSubmit={(e) => {
            e.preventDefault()
            handleJoin()
          }}
        >
          <label htmlFor="code">6-digit code</label>
          <input
            id="code"
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            placeholder="000000"
            value={code}
            onChange={(e) => {
              setCode(e.target.value.replace(/\D/g, ''))
              setError('')
            }}
            autoFocus
          />
          {error && <p className="error">{error}</p>}
          <div className="row">
            <button type="button" className="btn btn-ghost" onClick={() => setMode('home')}>
              Back
            </button>
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? 'Joining...' : 'Join'}
            </button>
          </div>
        </form>
      )}

      {mode === 'home' && error && <p className="error">{error}</p>}
    </div>
  )
}
