import { useCallback, useEffect, useRef, useState } from 'react'
import { chatWebSocketUrl, getMessages, leaveConversation } from '../api.js'

function formatTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch (_) {
    return ''
  }
}

export default function Chat({ session, onLeave }) {
  const [messages, setMessages] = useState([])
  const [connected, setConnected] = useState(false)
  const [loading, setLoading] = useState(true)
  const [historyError, setHistoryError] = useState('')
  const [leaving, setLeaving] = useState(false)
  const [input, setInput] = useState('')

  const wsRef = useRef(null)
  const aliveRef = useRef(true)
  const reconnectTimerRef = useRef(null)
  const listRef = useRef(null)

  useEffect(() => {
    let cancelled = false
    getMessages(session.conversationId, session.participantId, session.participantToken)
      .then((history) => {
        if (!cancelled) setMessages(history)
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

    ws.onopen = () => setConnected(true)
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data)
        if (payload.type !== 'message') return
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
      } catch (_) {
        /* ignore malformed frames */
      }
    }
    ws.onclose = () => {
      setConnected(false)
      if (aliveRef.current) {
        reconnectTimerRef.current = setTimeout(connect, 2000)
      }
    }
    wsRef.current = ws
  }, [session.conversationId, session.participantId, session.participantToken])

  useEffect(() => {
    aliveRef.current = true
    connect()
    return () => {
      aliveRef.current = false
      clearTimeout(reconnectTimerRef.current)
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [connect])

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight
    }
  }, [messages])

  function handleSend(e) {
    e.preventDefault()
    const text = input.trim()
    if (!text || !connected || !wsRef.current) return
    wsRef.current.send(text)
    setInput('')
  }

  async function handleLeave() {
    aliveRef.current = false
    clearTimeout(reconnectTimerRef.current)
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

  return (
    <div className="chat">
      <header className="chat-header">
        <div className="chat-room">
          <span className="chat-room-label">Room</span>
          <span className="chat-room-code">{session.code}</span>
        </div>
        <div className={`status ${connected ? 'on' : 'off'}`}>
          <span className="dot" />
          {connected ? 'Connected' : 'Reconnecting...'}
        </div>
        <button className="btn btn-danger" onClick={handleLeave} disabled={leaving}>
          {leaving ? 'Leaving...' : 'Leave'}
        </button>
      </header>

      <div className="chat-body">
        {loading && <p className="muted center">Loading messages...</p>}
        {historyError && <p className="error center">{historyError}</p>}

        <div className="messages" ref={listRef}>
          {messages.map((m) => (
            <div key={m.id} className={`bubble-row ${isOwn(m.participant_id) ? 'own' : ''}`}>
              <div className="bubble">
                <p className="bubble-text">{m.message}</p>
                <span className="bubble-time">{formatTime(m.sent_at)}</span>
              </div>
            </div>
          ))}
          {!loading && messages.length === 0 && (
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
          disabled={!connected}
          autoComplete="off"
        />
        <button type="submit" className="btn btn-primary" disabled={!connected || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  )
}
