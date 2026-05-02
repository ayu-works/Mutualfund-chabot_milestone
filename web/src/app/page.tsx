'use client'

import { useChat } from '@/hooks/useChat'
import { useTheme } from '@/hooks/useTheme'
import { Sidebar } from '@/components/Sidebar'
import { ChatArea } from '@/components/ChatArea'
import { ThemeToggle } from '@/components/ThemeToggle'

export default function HomePage() {
  const { dark, toggle } = useTheme()
  const {
    threads,
    activeThreadId,
    messages,
    loading,
    error,
    loadThreads,
    newThread,
    selectThread,
    sendMessage,
  } = useChat()

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        threads={threads}
        activeThreadId={activeThreadId}
        onNew={newThread}
        onSelect={selectThread}
        onLoad={loadThreads}
      />

      <div className="flex flex-col flex-1 min-w-0 h-full">
        {/* topbar */}
        <header className="flex items-center justify-between px-6 py-3 border-b border-theme bg-sidebar shrink-0">
          <div />
          <div className="flex items-center gap-3">
            <span className="text-xs font-medium text-secondary border border-theme rounded-full px-3 py-1.5">
              Facts-only Assistant: No investment advice
            </span>
            <ThemeToggle dark={dark} toggle={toggle} />
          </div>
        </header>

        <main className="flex-1 min-h-0 bg-main">
          <ChatArea
            messages={messages}
            loading={loading}
            error={error}
            onSend={sendMessage}
            hasThread={activeThreadId !== null}
          />
        </main>
      </div>
    </div>
  )
}
