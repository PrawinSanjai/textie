import { useCallback, useEffect, useRef, useState } from 'react'
import { chatWebSocketUrl, getMessages, leaveConversation } from '../api.js'

const MAX_MESSAGE_LENGTH = 4000

function formatTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch (_) {
    return ''
  }
}

function formatNoticeTime(ts) {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch (_) {
    return ''
  }
}

function mapCloseCode(code) {
  if (code === 4100) return 'This conversation has expired.'
  if (code === 4401) return 'You are no longer allowed to join this conversation.'
  return 'This conversation is no longer available.'
}

function noticeId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

export default function Chat({ session, onLeave }) {
  const [messages, setMessages] = useState([])
  const [notices, setNotices] = useState([])
  const [peers, setPeers] = useState(new Set())
  const [connected, setConnected] = useState(false)
  const [loading, setLoading] = useState(true)
  const [historyError, setHistoryError] = useState('')
  const [fatalError, setFatalError] = useState('')
  const [leaving, setLeaving] = useState(false)
  const [input, setInput] = useState('')

  const wsRef = useRef(null)
  const aliveRef = useRef(true)
  const reconnectTimerRef = useRef(null)
  const expiryTimerRef = useRef(null)
  const listRef = useRef(null)

  const pushNotice = useCallback((text) => {
    setNotices((prev) => [
      ...prev.slice(-49),
      { id: noticeId(), text, at: Date.now() },
    ])
  }, [])

  const syncHistory = useCallback(() => {
    return getMessages(session.conversationId, session.participantId, session.participantToken)
      .then((history) => {
        setMessages((prev) => {
          const seen = new Set(prev.map((m) => m.id))
          const fresh = history.filter((m) => !seen.has(m.id))
          return fresh.length ? [...prev, ...fresh] : prev
        })
      })
      .catch(() => {})
  }, [session.conversationId, session.participantId, session.participantToken])

  useEffect(() => {
    let cancelled = false
    getMessages(session.conversationId, session.participantId, session.participantToken)
      .then((history) => {
        if (!cancelled) setMessages((prev) => {
          const seen = new Set(prev.map((m) => m.id))
          return [...prev, ...history.filter((m) => !seen.has(m.id))]
        })
      })
      .catch((err) => {
        if (!cancelled) setHistoryError(err.message || 'Could not load message history.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [session.conversationId, session.participantId, session.participantToken])

  const connect = useCallback(() => {
    if (!aliveRef.current) return

    if (wsRef.current) {
      wsRef.current.onclose = null
      wsRef.current.close()
    }

    const ws = new WebSocket(
      chatWebSocketUrl(session.conversationId, session.participantId, session.participantToken)
    )

    ws.onopen = () => {
      setConnected(true)
      setFatalError('')
      syncHistory()
    }

    ws.onmessage = (event) => {
      let payload
      try {
        payload = JSON.parse(event.data)
      } catch (_) {
        return
      }

      if (payload.type === 'message') {
        setMessages((prev) => {
          if (prev.some((m) => m.id === payload.message_id)) return prev
          return [
            ...prev,
            {
              id: payload.message_id,
              participant_id: payload.participant_id,
              message: payload.message,
              sent_at: payload.sent_at,
            },
          ]
        })
        return
      }

      if (payload.type === 'participant_joined') {
        if (payload.participant_id === session.participantId) return
        setPeers((prev) => new Set(prev).add(payload.participant_id))
        pushNotice('Someone joined the chat.')
        return
      }

      if (payload.type === 'participant_left') {
        if (payload.participant_id === session.participantId) return
        setPeers((prev) => {
          const next = new Set(prev)
          next.delete(payload.participant_id)
          return next
        })
        pushNotice('Someone left the chat.')
      }
    }

    ws.onclose = (event) => {
      setConnected(false)
      if (!aliveRef.current) return
      if (event.code >= 4000) {
        setFatalError(mapCloseCode(event.code))
        return
      }
      reconnectTimerRef.current = setTimeout(connect, 2000)
    }

    wsRef.current = ws
  }, [session.conversationId, session.participantId, session.participantToken, pushNotice, syncHistory])

  useEffect(() => {
    aliveRef.current = true
    connect()
    return () => {
      aliveRef.current = false
      clearTimeout(reconnectTimerRef.current)
      clearTimeout(expiryTimerRef.current)
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [connect])

  useEffect(() => {
    const expiresAt = new Date(session.expiresAt).getTime()
    if (!Number.isFinite(expiresAt)) return
    const delay = Math.max(0, expiresAt - Date.now())
    expiryTimerRef.current = setTimeout(() => {
      aliveRef.current = false
      clearTimeout(reconnectTimerRef.current)
      try {
        if (wsRef.current) wsRef.current.close()
      } catch (_) {
        /* ignore */
      }
      setFatalError('This conversation has expired.')
      setConnected(false)
    }, delay)
    return () => clearTimeout(expiryTimerRef.current)
  }, [session.expiresAt])

  const feed = [
    ...messages.map((m) => ({
      kind: 'message',
      key: m.id,
      at: new Date(m.sent_at).getTime(),
      m,
    })),
    ...notices.map((n) => ({ kind: 'notice', key: n.id, at: n.at, n })),
  ].sort((a, b) => a.at - b.at)

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight
    }
  }, [feed])

  function handleSend(e) {
    e.preventDefault()
    const text = input.trim().slice(0, MAX_MESSAGE_LENGTH)
    if (!text || !connected || !wsRef.current) return
    wsRef.current.send(text)
    setInput('')
  }

  async function handleLeave() {
    aliveRef.current = false
    clearTimeout(reconnectTimerRef.current)
    clearTimeout(expiryTimerRef.current)
    setLeaving(true)
    try {
      if (wsRef.current) wsRef.current.close()
    } catch (_) {
      /* ignore */
    }
    try {
      await leaveConversation(session.conversationId, session.participantId)
    } catch (_) {
      /* backend already cleaned up */
    }
    onLeave()
  }

  const isOwn = (participantId) => participantId === session.participantId
  const peerCount = peers.size
  const peerLabel = peerCount > 0
    ? `${peerCount} online`
    : (session.isOwner ? 'Waiting for someone to join…' : 'Waiting for the owner…')

  return (
    <div className="chat">
      <header className="chat-header">
        <div className="chat-room">
          <span className="chat-room-label">Room</span>
          <span className="chat-room-code">{session.code}</span>
        </div>
        <div className={`status ${connected ? 'on' : 'off'}`}>
          <span className="dot" />
          {connected ? peerLabel : (fatalError ? 'Disconnected' : 'Reconnecting...')}
        </div>
        <button className="btn btn-danger" onClick={handleLeave} disabled={leaving}>
          {leaving ? 'Leaving...' : 'Leave'}
        </button>
      </header>

      <div className="chat-body">
        {loading && <p className="muted center">Loading messages...</p>}
        {historyError && !fatalError && <p className="error center">{historyError}</p>}
        {fatalError && (
          <p className="error center">
            {fatalError}
          </p>
        )}

        <div className="messages" ref={listRef}>
          {feed.map((entry) =>
            entry.kind === 'notice' ? (
              <div key={entry.key} className="system-row">
                <span className="system-text">{entry.n.text}</span>
                <span className="system-time">{formatNoticeTime(entry.n.at)}</span>
              </div>
            ) : (
              <div
                key={entry.key}
                className={`bubble-row ${isOwn(entry.m.participant_id) ? 'own' : ''}`}
              >
                <div className="bubble">
                  <p className="bubble-text">{entry.m.message}</p>
                  <span className="bubble-time">{formatTime(entry.m.sent_at)}</span>
                </div>
              </div>
            )
          )}
          {!loading && feed.length === 0 && (
            <p className="muted center">No messages yet. Say hi!</p>
          )}
        </div>
      </div>

      <form className="chat-input" onSubmit={handleSend}>
        <input
          type="text"
          placeholder="Type a message..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={!connected || !!fatalError}
          autoComplete="off"
          maxLength={MAX_MESSAGE_LENGTH}
        />
        <button type="submit" className="btn btn-primary" disabled={!connected || !!fatalError || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  )
}