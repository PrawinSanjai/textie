const KEY = 'textie.session.v1'

export function getSession() {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? JSON.parse(raw) : null
  } catch (_) {
    return null
  }
}

export function isSessionExpired(session) {
  if (!session) return true
  if (!session.expiresAt) return false
  return new Date(session.expiresAt).getTime() <= Date.now()
}

export function saveSession(session) {
  localStorage.setItem(KEY, JSON.stringify(session))
}

export function clearSession() {
  localStorage.removeItem(KEY)
}