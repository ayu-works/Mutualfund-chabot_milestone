import { SourceCard } from './SourceCard'
import type { Message } from '@/lib/types'

interface Props {
  message: Message
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('en-IN', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    })
  } catch {
    return ''
  }
}

export function MessageBubble({ message }: Props) {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="flex flex-col items-end gap-1">
        <div className="max-w-[60%] px-4 py-3 rounded-2xl bg-accent text-white text-sm leading-relaxed">
          {message.content}
        </div>
        <span className="text-xs text-muted pr-1">{formatTime(message.timestamp)}</span>
      </div>
    )
  }

  return (
    <div className="flex gap-3 items-start">
      {/* assistant avatar */}
      <div className="flex-shrink-0 w-9 h-9 rounded-full bg-accent/15 border border-accent/30 flex items-center justify-center mt-0.5">
        <svg width="18" height="18" viewBox="0 0 32 32" fill="none">
          <polygon points="16,2 30,11 30,21 16,30 2,21 2,11" fill="#00c896" />
        </svg>
      </div>

      <div className="flex-1 max-w-[80%]">
        <div className="bg-card border border-theme rounded-2xl px-4 py-3 text-sm text-primary leading-relaxed shadow-sm">
          {/* render bold via simple markdown-ish pass */}
          <p
            className="whitespace-pre-wrap"
            dangerouslySetInnerHTML={{
              __html: message.content
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>'),
            }}
          />
          {message.citation_url && (
            <SourceCard
              citationUrl={message.citation_url}
              footerDate={message.footer_date ?? null}
            />
          )}
        </div>
        <span className="text-xs text-muted pl-1 mt-1 block">{formatTime(message.timestamp)}</span>
      </div>
    </div>
  )
}
