const API_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/+$/, '')
const REQUEST_TIMEOUT_MS = 12000

async function request(path, options = {}) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  let res
  try {
    res = await fetch(`${API_URL}${path}`, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      signal: controller.signal,
      ...options,
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

export function leaveConversation(conversationId, participantId) {
  return request(`/conversation/${conversationId}/leave`, {
    method: 'POST',
    body: JSON.stringify({ participant_id: participantId }),
  })
}

export function getMessages(conversationId, participantId, token) {
  const params = new URLSearchParams({ participant_id: participantId, token })
  return request(`/message/${conversationId}/messages?${params}`)
}

export function chatWebSocketUrl(conversationId, participantId, token) {
  const base = API_URL.replace(/^http/, 'ws')
  const params = new URLSearchParams({ participant_id: participantId, token })
  return `${base}/ws/${conversationId}?${params}`
}

export { API_URL }