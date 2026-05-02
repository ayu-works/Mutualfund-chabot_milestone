import type { Thread, Message } from './types'

const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export async function createThread(): Promise<Thread> {
  const res = await fetch(`${BASE}/threads`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  if (!res.ok) throw new Error(`Failed to create thread: ${res.status}`)
  return res.json()
}

export async function listThreads(): Promise<Thread[]> {
  const res = await fetch(`${BASE}/threads`)
  if (!res.ok) throw new Error(`Failed to list threads: ${res.status}`)
  return res.json()
}

export async function getMessages(threadId: string): Promise<Message[]> {
  const res = await fetch(`${BASE}/threads/${threadId}/messages`)
  if (!res.ok) throw new Error(`Failed to get messages: ${res.status}`)
  const raw: Array<{ role: string; content: string; timestamp: string }> = await res.json()
  return raw.map((m) => ({ ...m, role: m.role as 'user' | 'assistant' }))
}

export async function deleteThread(threadId: string): Promise<void> {
  const res = await fetch(`${BASE}/threads/${threadId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Failed to delete thread: ${res.status}`)
}

export async function sendMessage(
  threadId: string,
  content: string
): Promise<{ assistant_message: string; citation_url: string | null; footer_date: string | null }> {
  const res = await fetch(`${BASE}/threads/${threadId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, use_query_expansion: true }),
  })
  if (!res.ok) throw new Error(`Failed to send message: ${res.status}`)
  return res.json()
}
