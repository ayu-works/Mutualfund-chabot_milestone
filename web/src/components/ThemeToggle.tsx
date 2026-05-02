'use client'

import { Sun, Moon } from 'lucide-react'

interface Props {
  dark: boolean
  toggle: () => void
}

export function ThemeToggle({ dark, toggle }: Props) {
  return (
    <button
      onClick={toggle}
      className="p-2 rounded-lg text-secondary hover:text-primary hover:bg-black/5 dark:hover:bg-white/5 transition-colors"
      aria-label="Toggle theme"
    >
      {dark ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  )
}
