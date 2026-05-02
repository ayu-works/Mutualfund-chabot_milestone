'use client'

import { useState, useCallback } from 'react'
import { Menu } from 'lucide-react'
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
    deleteThread,
  } = useChat()

  const [sidebarOpen, setSidebarOpen] = useState(false)

  const handleLoad = useCallback(async () => {
    await loadThreads()
    await newThread()
  }, [loadThreads, newThread])

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        threads={threads}
        activeThreadId={activeThreadId}
        onNew={newThread}
        onSelect={selectThread}
        onLoad={handleLoad}
        onDelete={deleteThread}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      <div className="flex flex-col flex-1 min-w-0 h-full">
        {/* topbar */}
        <header className="flex items-center justify-between px-6 py-3 border-b border-theme bg-sidebar shrink-0">
          <div>
            <button
              onClick={() => setSidebarOpen(true)}
              className="md:hidden p-1 rounded-lg text-secondary hover:text-primary hover:bg-black/5 dark:hover:bg-white/5 transition-colors"
              aria-label="Open sidebar"
            >
              <Menu size={20} />
            </button>
          </div>
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
