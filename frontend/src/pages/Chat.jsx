import { useCallback, useEffect, useRef, useState } from 'react'
import { chatWebSocketUrl, getMessages, leaveConversation } from '../api.js'

const MAX_MESSAGE_LENGTH = 4000
const HISTORY_PAGE_SIZE = 200
const HEARTBEAT_INTERVAL_MS = 15000
const RECONNECT_DELAY_MS = 2000

function formatTime(value) {
  try {
    return new Date(value).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch (_) {
    return ''
  }
}

function messageFromEvent(event) {
  return {
    id: event.message_id,
    participant_id: event.participant_id,
    sequence: event.sequence,
    message: event.message,
    sent_at: event.sent_at,
  }
}

function getCloseMessage(code) {
  if (code === 4100) return 'This conversation has expired.'
  if (code === 4401) return 'You are no longer allowed to join this conversation.'
  return 'This conversation is no longer available.'
}

function addNotice(notices, text) {
  return [
    ...notices.slice(-49),
    { id: crypto.randomUUID(), text, at: Date.now() },
  ]
}

function getPendingMessages(conversationId) {
  try {
    const stored = localStorage.getItem(`textie:pending:${conversationId}`)
    const messages = stored ? JSON.parse(stored) : []
    return Array.isArray(messages) ? messages : []
  } catch (_) {
    return []
  }
}

export default function Chat({ session, onLeave }) {
  const [messages, setMessages] = useState([])
  const [pending, setPending] = useState(() =>
    getPendingMessages(session.conversationId),
  )
  const [peers, setPeers] = useState(new Set())
  const [notices, setNotices] = useState([])
  const [input, setInput] = useState('')
  const [connected, setConnected] = useState(false)
  const [loading, setLoading] = useState(true)
  const [historyError, setHistoryError] = useState('')
  const [sendError, setSendError] = useState('')
  const [fatalError, setFatalError] = useState('')
  const [leaving, setLeaving] = useState(false)

  const socketRef = useRef(null)
  const aliveRef = useRef(true)
  const messageListRef = useRef(null)
  const historyCursorRef = useRef(0)
  const pendingRef = useRef(pending)
  const reconnectTimerRef = useRef(null)
  const expiryTimerRef = useRef(null)
  const heartbeatTimerRef = useRef(null)

  const savePending = useCallback((nextMessages) => {
    const limitedMessages = nextMessages.slice(-100)
    pendingRef.current = limitedMessages
    setPending(limitedMessages)
    localStorage.setItem(
      `textie:pending:${session.conversationId}`,
      JSON.stringify(limitedMessages),
    )
  }, [session.conversationId])

  const mergeMessages = useCallback((incomingMessages) => {
    if (incomingMessages.length === 0) return

    setMessages((currentMessages) => {
      const messagesById = new Map(
        currentMessages.map((message) => [message.id, message]),
      )

      for (const message of incomingMessages) {
        messagesById.set(message.id, message)
      }

      const mergedMessages = [...messagesById.values()].sort(
        (left, right) => left.sequence - right.sequence,
      )
      const latestSequence = Math.max(
        ...mergedMessages.map((message) => message.sequence || 0),
      )
      historyCursorRef.current = Math.max(
        historyCursorRef.current,
        latestSequence,
      )
      return mergedMessages
    })
  }, [])

  const syncHistory = useCallback(async () => {
    // The sequence cursor fills gaps when the socket was disconnected.
    let cursor = historyCursorRef.current

    try {
      while (aliveRef.current) {
        const page = await getMessages(
          session.conversationId,
          session.participantToken,
          cursor,
        )
        mergeMessages(page.messages)

        const nextCursor = page.next_after_sequence
        const pageIsFull = page.messages.length === HISTORY_PAGE_SIZE
        if (nextCursor <= cursor || !pageIsFull) break
        cursor = nextCursor
      }

      setHistoryError('')
    } catch (error) {
      setHistoryError(error.message || 'Could not recover message history.')
    } finally {
      setLoading(false)
    }
  }, [session.conversationId, session.participantToken, mergeMessages])

  const sendAuthentication = useCallback((socket) => {
    socket.send(JSON.stringify({
      type: 'authenticate',
      participant_id: session.participantId,
      participant_token: session.participantToken,
    }))
  }, [session.participantId, session.participantToken])

  const handleSocketMessage = useCallback((event, socket) => {
    let payload
    try {
      payload = JSON.parse(event.data)
    } catch (_) {
      return
    }

    if (payload.type === 'authenticated') {
      setConnected(true)
      setFatalError('')
      syncHistory()
      // Reusing each message ID makes retries safe after a lost acknowledgement.
      pendingRef.current.forEach((message) => {
        socket.send(JSON.stringify({ type: 'message', ...message }))
      })
      return
    }

    if (payload.type === 'presence_snapshot') {
      const otherParticipants = (payload.participants || []).filter(
        (participantId) => participantId !== session.participantId,
      )
      setPeers(new Set(otherParticipants))
      return
    }

    if (payload.type === 'message') {
      mergeMessages([messageFromEvent(payload)])
      if (payload.participant_id === session.participantId && payload.client_message_id) {
        savePending(pendingRef.current.filter(
          (message) => message.client_message_id !== payload.client_message_id,
        ))
      }
      return
    }

    if (payload.type === 'message_ack') {
      savePending(pendingRef.current.filter(
        (message) => message.client_message_id !== payload.client_message_id,
      ))
      return
    }

    if (payload.type === 'message_error') {
      setSendError(payload.detail || 'Message was not sent.')
      savePending(pendingRef.current.filter(
        (message) => message.client_message_id !== payload.client_message_id,
      ))
      return
    }

    if (payload.type === 'participant_joined' && payload.participant_id !== session.participantId) {
      setPeers((currentPeers) => new Set(currentPeers).add(payload.participant_id))
      setNotices((currentNotices) => addNotice(currentNotices, 'Someone joined the chat.'))
      return
    }

    if (payload.type === 'participant_left' && payload.participant_id !== session.participantId) {
      setPeers((currentPeers) => {
        const nextPeers = new Set(currentPeers)
        nextPeers.delete(payload.participant_id)
        return nextPeers
      })
      setNotices((currentNotices) => addNotice(currentNotices, 'Someone left the chat.'))
    }
  }, [
    mergeMessages,
    savePending,
    session.participantId,
    syncHistory,
  ])

  const connect = useCallback(() => {
    if (!aliveRef.current) return

    if (socketRef.current) {
      socketRef.current.onclose = null
      socketRef.current.close()
    }

    const socket = new WebSocket(chatWebSocketUrl(session.conversationId))
    socket.onopen = () => sendAuthentication(socket)
    socket.onmessage = (event) => handleSocketMessage(event, socket)
    socket.onclose = (event) => {
      clearInterval(heartbeatTimerRef.current)
      setConnected(false)
      if (!aliveRef.current) return

      if (event.code >= 4000 && event.code !== 1013) {
        setFatalError(getCloseMessage(event.code))
        return
      }

      reconnectTimerRef.current = setTimeout(connect, RECONNECT_DELAY_MS)
    }
    socketRef.current = socket
  }, [
    handleSocketMessage,
    sendAuthentication,
    session.conversationId,
  ])

  useEffect(() => {
    aliveRef.current = true
    connect()

    return () => {
      aliveRef.current = false
      clearTimeout(reconnectTimerRef.current)
      clearTimeout(expiryTimerRef.current)
      clearInterval(heartbeatTimerRef.current)

      if (socketRef.current) {
        socketRef.current.onclose = null
        socketRef.current.close()
        socketRef.current = null
      }
    }
  }, [connect])

  useEffect(() => {
    if (!connected) {
      clearInterval(heartbeatTimerRef.current)
      return undefined
    }

    heartbeatTimerRef.current = setInterval(() => {
      if (socketRef.current?.readyState === WebSocket.OPEN) {
        socketRef.current.send(JSON.stringify({ type: 'ping' }))
      }
    }, HEARTBEAT_INTERVAL_MS)

    return () => clearInterval(heartbeatTimerRef.current)
  }, [connected])

  useEffect(() => {
    const expiresAt = new Date(session.expiresAt).getTime()
    if (!Number.isFinite(expiresAt)) return undefined

    expiryTimerRef.current = setTimeout(() => {
      aliveRef.current = false
      clearTimeout(reconnectTimerRef.current)
      socketRef.current?.close()
      setFatalError('This conversation has expired.')
      setConnected(false)
      savePending([])
    }, Math.max(0, expiresAt - Date.now()))

    return () => clearTimeout(expiryTimerRef.current)
  }, [session.expiresAt, savePending])

  const feed = [
    ...messages.map((message) => ({
      kind: 'message',
      key: message.id,
      at: new Date(message.sent_at).getTime(),
      message,
    })),
    ...pending.map((message) => ({
      kind: 'pending',
      key: message.client_message_id,
      at: message.created_at,
      message,
    })),
    ...notices.map((notice) => ({
      kind: 'notice',
      key: notice.id,
      at: notice.at,
      notice,
    })),
  ].sort((left, right) => left.at - right.at)

  useEffect(() => {
    if (messageListRef.current) {
      messageListRef.current.scrollTop = messageListRef.current.scrollHeight
    }
  }, [messages, pending, notices])

  function handleSend(event) {
    event.preventDefault()
    const text = input.trim().slice(0, MAX_MESSAGE_LENGTH)
    if (!text || !connected || !socketRef.current) return

    const message = {
      client_message_id: crypto.randomUUID(),
      message: text,
      created_at: Date.now(),
    }
    savePending([...pendingRef.current, message])
    socketRef.current.send(JSON.stringify({
      type: 'message',
      client_message_id: message.client_message_id,
      message: text,
    }))
    setInput('')
    setSendError('')
  }

  async function handleLeave() {
    aliveRef.current = false
    clearTimeout(reconnectTimerRef.current)
    clearInterval(heartbeatTimerRef.current)
    setLeaving(true)
    savePending([])
    socketRef.current?.close()

    try {
      await leaveConversation(
        session.conversationId,
        session.participantId,
        session.participantToken,
      )
    } catch (_) {
      // The server may already have cleaned up the conversation.
    }

    onLeave()
  }

  const peerLabel = peers.size > 0
    ? `${peers.size} online`
    : session.isOwner
      ? 'Waiting for someone to join…'
      : 'Waiting for the owner…'

  const connectionLabel = connected
    ? peerLabel
    : fatalError
      ? 'Disconnected'
      : 'Reconnecting...'

  return (
    <div className="chat">
      <header className="chat-header">
        <div className="chat-room">
          <span className="chat-room-label">Room</span>
          <span className="chat-room-code">{session.code}</span>
        </div>
        <div className={`status ${connected ? 'on' : 'off'}`}>
          <span className="dot" />
          {connectionLabel}
        </div>
        <button className="btn btn-danger" onClick={handleLeave} disabled={leaving}>
          {leaving ? 'Leaving...' : 'Leave'}
        </button>
      </header>

      <div className="chat-body">
        {loading && <p className="muted center">Loading messages...</p>}
        {(fatalError || sendError || historyError) && (
          <p className="error center">{fatalError || sendError || historyError}</p>
        )}

        <div className="messages" ref={messageListRef}>
          {feed.map((entry) => (
            entry.kind === 'notice'
              ? <Notice key={entry.key} notice={entry.notice} />
              : (
                <MessageBubble
                  key={entry.key}
                  message={entry.message}
                  pending={entry.kind === 'pending'}
                  own={entry.kind === 'pending' || entry.message.participant_id === session.participantId}
                />
              )
          ))}
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
          onChange={(event) => setInput(event.target.value)}
          disabled={!connected || Boolean(fatalError)}
          autoComplete="off"
          maxLength={MAX_MESSAGE_LENGTH}
        />
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!connected || Boolean(fatalError) || !input.trim()}
        >
          Send
        </button>
      </form>
    </div>
  )
}

function Notice({ notice }) {
  return (
    <div className="system-row">
      <span className="system-text">{notice.text}</span>
      <span className="system-time">{formatTime(notice.at)}</span>
    </div>
  )
}

function MessageBubble({ message, pending, own }) {
  return (
    <div className={`bubble-row ${own ? 'own' : ''}`}>
      <div className="bubble">
        <p className="bubble-text">{message.message}</p>
        <span className="bubble-time">
          {pending ? 'Sending…' : formatTime(message.sent_at)}
        </span>
      </div>
    </div>
  )
}
