export interface Thread {
  thread_id: string
  session_key: string | null
  created_at: string
}

export interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  citation_url?: string | null
  footer_date?: string | null
}

export interface ChatState {
  threads: Thread[]
  activeThreadId: string | null
  messages: Message[]
  loading: boolean
  error: string | null
}
