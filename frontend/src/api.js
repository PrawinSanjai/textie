const API_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/+$/, '')
const REQUEST_TIMEOUT_MS = 12000

async function request(path, options = {}) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  let res
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers || {}),
      },
      signal: options.signal || controller.signal,
    })
  } catch (_) {
    throw new Error('Could not reach the server. Check your connection.')
  } finally {
    clearTimeout(timeout)
  }

  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      if (body && body.detail) detail = body.detail
    } catch (_) {
      /* keep statusText */
    }
    const error = new Error(detail)
    error.status = res.status
    throw error
  }

  return res.json()
}

export function createConversation() {
  return request('/conversation/create', { method: 'POST' })
}

export function joinConversation(code) {
  return request('/conversation/join', {
    method: 'POST',
    body: JSON.stringify({ code }),
  })
}

export function leaveConversation(conversationId, participantId, participantToken) {
  return request(`/conversation/${conversationId}/leave`, {
    method: 'POST',
    body: JSON.stringify({
      participant_id: participantId,
      participant_token: participantToken,
    }),
  })
}

export function getMessages(conversationId, token, afterSequence = 0) {
  return request(`/conversation/${conversationId}/chat`, {
    method: 'POST',
    body: JSON.stringify({ participant_token: token, after_sequence: afterSequence, limit: 200 }),
  })
}

export function chatWebSocketUrl(conversationId) {
  const base = API_URL.replace(/^http/, 'ws')
  return `${base}/ws/${conversationId}`
}

export { API_URL }
