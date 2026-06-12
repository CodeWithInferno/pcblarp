const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
}

export interface ChatRequest {
  messages: ChatMessage[]
  context?: Record<string, unknown>
}

export async function sendChat(req: ChatRequest) {
  const res = await fetch(`${API_URL}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function generateDesign(context: Record<string, unknown>, spec: Record<string, unknown>) {
  const res = await fetch(`${API_URL}/design/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ context, spec }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function fetchDesignSpec(context: Record<string, unknown>) {
  const res = await fetch(`${API_URL}/design/spec`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(context),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
