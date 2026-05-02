import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'GrowwMF — Mutual Fund FAQ Assistant',
  description: 'Facts-only assistant for HDFC mutual fund queries',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="bg-main text-primary antialiased">{children}</body>
    </html>
  )
}
