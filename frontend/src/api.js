const API_PREFIX = import.meta.env.VITE_API_PREFIX || '/api'

async function request(path, options = {}) {
  const response = await fetch(`${API_PREFIX}${path}`, options)
  const text = await response.text()
  let data = null

  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }

  if (!response.ok) {
    const detail = typeof data === 'string' ? data : JSON.stringify(data)
    throw new Error(`${response.status} ${response.statusText}: ${detail}`)
  }

  return data
}

export function getHealth() {
  return request('/health')
}

export function getKnowledgeStats() {
  return request('/knowledge/stats')
}

export function getMonitor() {
  return request('/monitor')
}

export function getSkills() {
  return request('/skills')
}

export function reloadSkills() {
  return request('/skills/reload', { method: 'POST' })
}

export function addKnowledge({ title, content }) {
  return request('/knowledge/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      documents: [{ title, content }]
    })
  })
}

export function uploadKnowledge(file) {
  const form = new FormData()
  form.append('file', file)
  return request('/knowledge/upload', {
    method: 'POST',
    body: form
  })
}

export function runEvaluation() {
  return request('/eval/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({})
  })
}

export function sendChat({ message, userId, conversationId }) {
  return request('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      user_id: userId || 'anonymous',
      conversation_id: conversationId || undefined
    })
  })
}

export function searchKnowledge(query, topK = 5) {
  const params = new URLSearchParams({ query, top_k: String(topK) })
  return request(`/knowledge/search?${params}`)
}
