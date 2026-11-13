import { useCallback, useEffect, useRef, useState } from 'react'
import { chatWebSocketUrl, getMessages, leaveConversation } from '../api.js'

const MAX_MESSAGE_LENGTH = 4000
const PAGE_SIZE = 200

function formatTime(iso) {
  try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) } catch (_) { return '' }
}

function mapCloseCode(code) {
  if (code === 4100) return 'This conversation has expired.'
  if (code === 4401) return 'You are no longer allowed to join this conversation.'
  return 'This conversation is no longer available.'
}

function pendingStorageKey(conversationId) { return `textie:pending:${conversationId}` }

export default function Chat({ session, onLeave }) {
  const [messages, setMessages] = useState([])
  const [pending, setPending] = useState(() => {
    try { return JSON.parse(localStorage.getItem(pendingStorageKey(session.conversationId)) || '[]') } catch (_) { return [] }
  })
  const [peers, setPeers] = useState(new Set())
  const [connected, setConnected] = useState(false)
  const [loading, setLoading] = useState(true)
  const [historyError, setHistoryError] = useState('')
  const [fatalError, setFatalError] = useState('')
  const [sendError, setSendError] = useState('')
  const [leaving, setLeaving] = useState(false)
  const [input, setInput] = useState('')
  const [notices, setNotices] = useState([])
  const wsRef = useRef(null)
  const aliveRef = useRef(true)
  const reconnectTimerRef = useRef(null)
  const expiryTimerRef = useRef(null)
  const heartbeatRef = useRef(null)
  const listRef = useRef(null)
  const cursorRef = useRef(0)
  const pendingRef = useRef(pending)

  const savePending = useCallback((next) => {
    pendingRef.current = next
    setPending(next)
    localStorage.setItem(pendingStorageKey(session.conversationId), JSON.stringify(next.slice(-100)))
  }, [session.conversationId])

  const mergeMessages = useCallback((incoming) => {
    if (!incoming.length) return
    setMessages((old) => {
      const byId = new Map(old.map((message) => [message.id, message]))
      incoming.forEach((message) => byId.set(message.id, message))
      const merged = [...byId.values()].sort((a, b) => a.sequence - b.sequence)
      cursorRef.current = Math.max(cursorRef.current, ...merged.map((message) => message.sequence || 0))
      return merged
    })
  }, [])

  const syncHistory = useCallback(async () => {
    let cursor = cursorRef.current
    try {
      while (aliveRef.current) {
        const page = await getMessages(session.conversationId, session.participantToken, cursor)
        mergeMessages(page.messages)
        const next = page.next_after_sequence
        if (next <= cursor || page.messages.length < PAGE_SIZE) break
        cursor = next
      }
      setHistoryError('')
    } catch (err) {
      setHistoryError(err.message || 'Could not recover message history.')
    } finally { setLoading(false) }
  }, [session.conversationId, session.participantToken, mergeMessages])

  const connect = useCallback(() => {
    if (!aliveRef.current) return
    if (wsRef.current) { wsRef.current.onclose = null; wsRef.current.close() }
    const ws = new WebSocket(chatWebSocketUrl(session.conversationId))
    ws.onopen = () => ws.send(JSON.stringify({
      type: 'authenticate', participant_id: session.participantId,
      participant_token: session.participantToken,
    }))
    ws.onmessage = (event) => {
      let payload
      try { payload = JSON.parse(event.data) } catch (_) { return }
      if (payload.type === 'authenticated') {
        setConnected(true)
        setFatalError('')
        syncHistory()
        pendingRef.current.forEach((item) => ws.send(JSON.stringify({ type: 'message', ...item })))
      } else if (payload.type === 'presence_snapshot') {
        setPeers(new Set((payload.participants || []).filter((id) => id !== session.participantId)))
      } else if (payload.type === 'pong') {
        return
      } else if (payload.type === 'message') {
        mergeMessages([{
          id: payload.message_id, participant_id: payload.participant_id,
          sequence: payload.sequence, message: payload.message, sent_at: payload.sent_at,
        }])
        if (payload.participant_id === session.participantId && payload.client_message_id) {
          savePending(pendingRef.current.filter((item) => item.client_message_id !== payload.client_message_id))
        }
      } else if (payload.type === 'message_ack') {
        savePending(pendingRef.current.filter((item) => item.client_message_id !== payload.client_message_id))
      } else if (payload.type === 'message_error') {
        setSendError(payload.detail || 'Message was not sent.')
        savePending(pendingRef.current.filter((item) => item.client_message_id !== payload.client_message_id))
      } else if (payload.type === 'participant_joined' && payload.participant_id !== session.participantId) {
        setPeers((old) => new Set(old).add(payload.participant_id))
        setNotices((old) => [...old.slice(-49), { id: crypto.randomUUID(), text: 'Someone joined the chat.', at: Date.now() }])
      } else if (payload.type === 'participant_left' && payload.participant_id !== session.participantId) {
        setPeers((old) => { const next = new Set(old); next.delete(payload.participant_id); return next })
        setNotices((old) => [...old.slice(-49), { id: crypto.randomUUID(), text: 'Someone left the chat.', at: Date.now() }])
      }
    }
    ws.onclose = (event) => {
      clearInterval(heartbeatRef.current)
      setConnected(false)
      if (!aliveRef.current) return
      if (event.code >= 4000 && event.code !== 1013) { setFatalError(mapCloseCode(event.code)); return }
      reconnectTimerRef.current = setTimeout(connect, 2000)
    }
    wsRef.current = ws
  }, [session.conversationId, session.participantId, session.participantToken, syncHistory, mergeMessages, savePending])

  useEffect(() => {
    aliveRef.current = true
    connect()
    return () => {
      aliveRef.current = false
      clearTimeout(reconnectTimerRef.current)
      clearTimeout(expiryTimerRef.current)
      clearInterval(heartbeatRef.current)
      if (wsRef.current) { wsRef.current.onclose = null; wsRef.current.close(); wsRef.current = null }
    }
  }, [connect])

  useEffect(() => {
    if (!connected) { clearInterval(heartbeatRef.current); return }
    heartbeatRef.current = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify({ type: 'ping' }))
    }, 15000)
    return () => clearInterval(heartbeatRef.current)
  }, [connected])

  useEffect(() => {
    const expiresAt = new Date(session.expiresAt).getTime()
    if (!Number.isFinite(expiresAt)) return
    expiryTimerRef.current = setTimeout(() => {
      aliveRef.current = false
      clearTimeout(reconnectTimerRef.current)
      wsRef.current?.close()
      setFatalError('This conversation has expired.')
      setConnected(false)
      savePending([])
    }, Math.max(0, expiresAt - Date.now()))
    return () => clearTimeout(expiryTimerRef.current)
  }, [session.expiresAt, savePending])

  const feed = [
    ...messages.map((m) => ({ kind: 'message', key: m.id, at: new Date(m.sent_at).getTime(), m })),
    ...pending.map((m) => ({ kind: 'pending', key: m.client_message_id, at: m.created_at, m })),
    ...notices.map((n) => ({ kind: 'notice', key: n.id, at: n.at, n })),
  ].sort((a, b) => a.at - b.at)

  useEffect(() => { if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight }, [messages, pending, notices])

  function handleSend(event) {
    event.preventDefault()
    const text = input.trim().slice(0, MAX_MESSAGE_LENGTH)
    if (!text || !connected || !wsRef.current) return
    const item = { client_message_id: crypto.randomUUID(), message: text, created_at: Date.now() }
    savePending([...pendingRef.current, item].slice(-100))
    wsRef.current.send(JSON.stringify({ type: 'message', client_message_id: item.client_message_id, message: text }))
    setInput('')
    setSendError('')
  }

  async function handleLeave() {
    aliveRef.current = false
    clearTimeout(reconnectTimerRef.current)
    clearInterval(heartbeatRef.current)
    setLeaving(true)
    savePending([])
    wsRef.current?.close()
    try { await leaveConversation(session.conversationId, session.participantId, session.participantToken) } catch (_) { /* already cleaned up */ }
    onLeave()
  }

  const peerLabel = peers.size ? `${peers.size} online` : (session.isOwner ? 'Waiting for someone to join…' : 'Waiting for the owner…')
  return (
    <div className="chat">
      <header className="chat-header">
        <div className="chat-room"><span className="chat-room-label">Room</span><span className="chat-room-code">{session.code}</span></div>
        <div className={`status ${connected ? 'on' : 'off'}`}><span className="dot" />{connected ? peerLabel : (fatalError ? 'Disconnected' : 'Reconnecting...')}</div>
        <button className="btn btn-danger" onClick={handleLeave} disabled={leaving}>{leaving ? 'Leaving...' : 'Leave'}</button>
      </header>
      <div className="chat-body">
        {loading && <p className="muted center">Loading messages...</p>}
        {(historyError || fatalError || sendError) && <p className="error center">{fatalError || sendError || historyError}</p>}
        <div className="messages" ref={listRef}>
          {feed.map((entry) => entry.kind === 'notice' ? (
            <div key={entry.key} className="system-row"><span className="system-text">{entry.n.text}</span><span className="system-time">{formatTime(entry.n.at)}</span></div>
          ) : (
            <div key={entry.key} className={`bubble-row ${entry.kind === 'pending' || entry.m.participant_id === session.participantId ? 'own' : ''}`}>
              <div className="bubble"><p className="bubble-text">{entry.m.message}</p><span className="bubble-time">{entry.kind === 'pending' ? 'Sending…' : formatTime(entry.m.sent_at)}</span></div>
            </div>
          ))}
          {!loading && feed.length === 0 && <p className="muted center">No messages yet. Say hi!</p>}
        </div>
      </div>
      <form className="chat-input" onSubmit={handleSend}>
        <input type="text" placeholder="Type a message..." value={input} onChange={(e) => setInput(e.target.value)} disabled={!connected || !!fatalError} autoComplete="off" maxLength={MAX_MESSAGE_LENGTH} />
        <button type="submit" className="btn btn-primary" disabled={!connected || !!fatalError || !input.trim()}>Send</button>
      </form>
    </div>
  )
}
