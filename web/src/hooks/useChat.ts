'use client'

import { useState, useCallback } from 'react'
import type { Thread, Message } from '@/lib/types'
import * as api from '@/lib/api'

export function useChat() {
  const [threads, setThreads] = useState<Thread[]>([])
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadThreads = useCallback(async () => {
    try {
      const data = await api.listThreads()
      setThreads(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load threads')
    }
  }, [])

  const newThread = useCallback(async () => {
    setLoading(true)
    try {
      const t = await api.createThread()
      setThreads((prev) => [t, ...prev])
      setActiveThreadId(t.thread_id)
      setMessages([])
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create thread')
    } finally {
      setLoading(false)
    }
  }, [])

  const selectThread = useCallback(async (threadId: string) => {
    setActiveThreadId(threadId)
    setLoading(true)
    try {
      const msgs = await api.getMessages(threadId)
      setMessages(msgs)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load messages')
    } finally {
      setLoading(false)
    }
  }, [])

  const sendMessage = useCallback(
    async (content: string) => {
      if (!activeThreadId || !content.trim()) return

      const userMsg: Message = {
        role: 'user',
        content,
        timestamp: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, userMsg])
      setLoading(true)
      setError(null)

      try {
        const resp = await api.sendMessage(activeThreadId, content)
        const assistantMsg: Message = {
          role: 'assistant',
          content: resp.assistant_message,
          timestamp: new Date().toISOString(),
          citation_url: resp.citation_url,
          footer_date: resp.footer_date,
        }
        setMessages((prev) => [...prev, assistantMsg])

        // update thread label shown in sidebar
        setThreads((prev) =>
          prev.map((t) =>
            t.thread_id === activeThreadId
              ? { ...t, _label: content.slice(0, 40) } as Thread & { _label: string }
              : t
          )
        )
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to send message')
      } finally {
        setLoading(false)
      }
    },
    [activeThreadId]
  )

  return {
    threads,
    activeThreadId,
    messages,
    loading,
    error,
    loadThreads,
    newThread,
    selectThread,
    sendMessage,
  }
}
