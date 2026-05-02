'use client'

import { useEffect } from 'react'
import { Plus, Settings, HelpCircle, Trash2 } from 'lucide-react'
import { Logo } from './Logo'
import type { Thread } from '@/lib/types'

interface Props {
  threads: Thread[]
  activeThreadId: string | null
  onNew: () => void
  onSelect: (id: string) => void
  onLoad: () => void
  onDelete: (id: string) => void
  isOpen: boolean
  onClose: () => void
}

function threadLabel(t: Thread & { _label?: string }): string {
  if (t._label) return t._label
  const d = new Date(t.created_at)
  return `Chat ${d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}`
}

export function Sidebar({ threads, activeThreadId, onNew, onSelect, onLoad, onDelete, isOpen, onClose }: Props) {
  useEffect(() => {
    onLoad()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <>
      {/* Mobile backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 md:hidden"
          onClick={onClose}
        />
      )}

      <aside className={`
        fixed inset-y-0 left-0 z-50
        md:relative md:inset-auto md:z-auto md:translate-x-0
        flex flex-col w-[200px] min-w-[200px] h-full bg-sidebar border-r border-theme
        transition-transform duration-200
        ${isOpen ? 'translate-x-0' : '-translate-x-full'}
      `}>
        {/* logo */}
        <div className="px-4 pt-5 pb-4">
          <Logo />
        </div>

        {/* new chat */}
        <div className="px-3 mb-4">
          <button
            onClick={onNew}
            className="flex items-center gap-2 w-full px-3 py-2.5 rounded-lg bg-accent hover:bg-accent-hover text-white font-medium text-sm transition-colors"
          >
            <Plus size={16} strokeWidth={2.5} />
            New Chat
          </button>
        </div>

        {/* thread list */}
        <div className="flex-1 overflow-y-auto px-3">
          {threads.length > 0 && (
            <p className="text-xs font-semibold uppercase tracking-wider text-muted mb-2 px-1">
              Recent Chats
            </p>
          )}
          <ul className="space-y-0.5">
            {threads.map((t) => {
              const active = t.thread_id === activeThreadId
              const label = threadLabel(t as Thread & { _label?: string })
              return (
                <li key={t.thread_id} className="group relative">
                  <button
                    onClick={() => { onSelect(t.thread_id); onClose() }}
                    className={`w-full text-left px-2 py-2 pr-7 rounded-lg text-sm truncate transition-colors ${
                      active
                        ? 'bg-accent/10 text-accent font-medium'
                        : 'text-secondary hover:bg-black/5 dark:hover:bg-white/5 hover:text-primary'
                    }`}
                    title={label}
                  >
                    {label}
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); onDelete(t.thread_id) }}
                    className="absolute right-1 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 p-1 rounded text-muted hover:text-red-500 transition-all"
                    title="Delete chat"
                  >
                    <Trash2 size={13} />
                  </button>
                </li>
              )
            })}
          </ul>
        </div>

        {/* bottom nav */}
        <div className="border-t border-theme px-3 py-3 space-y-0.5">
          <button className="flex items-center gap-2 w-full px-2 py-2 rounded-lg text-sm text-secondary hover:text-primary hover:bg-black/5 dark:hover:bg-white/5 transition-colors">
            <Settings size={16} />
            Settings
          </button>
          <button className="flex items-center gap-2 w-full px-2 py-2 rounded-lg text-sm text-secondary hover:text-primary hover:bg-black/5 dark:hover:bg-white/5 transition-colors">
            <HelpCircle size={16} />
            Help Center
          </button>
        </div>
      </aside>
    </>
  )
}
