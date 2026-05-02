'use client'

import { useState, useRef, KeyboardEvent } from 'react'
import { Send } from 'lucide-react'

interface Props {
  onSend: (text: string) => void
  disabled: boolean
}

export function MessageInput({ onSend, disabled }: Props) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  function submit() {
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  function onInput() {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`
  }

  return (
    <div className="px-4 pb-4 pt-2">
      <div className="flex items-end gap-2 bg-input-area border border-theme rounded-2xl px-4 py-2 shadow-sm focus-within:border-accent/50 transition-colors">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          onInput={onInput}
          rows={1}
          placeholder="Ask follow-up questions…"
          disabled={disabled}
          className="flex-1 resize-none bg-transparent text-sm text-primary placeholder:text-muted outline-none py-1.5 leading-relaxed max-h-[120px]"
        />
        <button
          onClick={submit}
          disabled={disabled || !value.trim()}
          className="flex-shrink-0 p-1.5 rounded-lg text-accent hover:text-accent-hover disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          aria-label="Send"
        >
          <Send size={18} strokeWidth={2} />
        </button>
      </div>
      <p className="text-center text-xs text-muted mt-2">
        AI can make mistakes. Verify important information.
      </p>
    </div>
  )
}
