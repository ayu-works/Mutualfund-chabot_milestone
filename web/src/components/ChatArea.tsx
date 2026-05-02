'use client'

import { useEffect, useRef } from 'react'
import { MessageBubble } from './MessageBubble'
import { MessageInput } from './MessageInput'
import type { Message } from '@/lib/types'

interface Props {
  messages: Message[]
  loading: boolean
  error: string | null
  onSend: (text: string) => void
  hasThread: boolean
}

export function ChatArea({ messages, loading, error, onSend, hasThread }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  return (
    <div className="flex flex-col flex-1 h-full min-w-0">
      {/* messages */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-5">
        {!hasThread && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
            <div className="w-14 h-14 rounded-full bg-accent/10 flex items-center justify-center">
              <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
                <polygon points="16,2 30,11 30,21 16,30 2,21 2,11" fill="#00c896" />
              </svg>
            </div>
            <div>
              <p className="font-semibold text-primary">Mutual Fund FAQ Assistant</p>
              <p className="text-sm text-secondary mt-1">
                Create a new chat to ask questions about HDFC mutual funds.
              </p>
            </div>
          </div>
        )}

        {hasThread && messages.length === 0 && !loading && (
          <div className="flex justify-center">
            <span className="text-xs text-muted bg-card border border-theme rounded-full px-3 py-1">
              Conversation started today
            </span>
          </div>
        )}

        {messages.length > 0 && (
          <div className="flex justify-center mb-2">
            <span className="text-xs text-muted bg-card border border-theme rounded-full px-3 py-1">
              Conversation started today
            </span>
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble key={i} message={msg} />
        ))}

        {loading && (
          <div className="flex gap-3 items-start">
            <div className="flex-shrink-0 w-9 h-9 rounded-full bg-accent/15 border border-accent/30 flex items-center justify-center">
              <svg width="18" height="18" viewBox="0 0 32 32" fill="none">
                <polygon points="16,2 30,11 30,21 16,30 2,21 2,11" fill="#00c896" />
              </svg>
            </div>
            <div className="bg-card border border-theme rounded-2xl px-4 py-3 shadow-sm">
              <div className="flex gap-1.5 items-center h-5">
                <span className="w-2 h-2 rounded-full bg-accent/60 animate-bounce [animation-delay:0ms]" />
                <span className="w-2 h-2 rounded-full bg-accent/60 animate-bounce [animation-delay:150ms]" />
                <span className="w-2 h-2 rounded-full bg-accent/60 animate-bounce [animation-delay:300ms]" />
              </div>
            </div>
          </div>
        )}

        {error && (
          <div className="flex justify-center">
            <span className="text-xs text-red-500 bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-900/40 rounded-lg px-3 py-2">
              {error}
            </span>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* input */}
      <MessageInput onSend={onSend} disabled={loading || !hasThread} />
    </div>
  )
}
