import { Link } from 'lucide-react'

interface Props {
  citationUrl: string
  footerDate: string | null
}

const FUND_LABELS: Record<string, string> = {
  'hdfc-mid-cap': 'HDFC Mid-Cap Opps',
  'hdfc-equity': 'HDFC Equity Fund',
  'hdfc-focused': 'HDFC Focused Fund',
  'hdfc-elss': 'HDFC ELSS Tax Saver',
  'hdfc-large-cap': 'HDFC Large Cap Fund',
}

function labelFromUrl(url: string): string {
  for (const [key, label] of Object.entries(FUND_LABELS)) {
    if (url.includes(key)) return label
  }
  try {
    return new URL(url).pathname.split('/').filter(Boolean).pop() ?? url
  } catch {
    return url
  }
}

export function SourceCard({ citationUrl, footerDate }: Props) {
  const label = labelFromUrl(citationUrl)

  return (
    <div className="mt-4 pt-3 border-t border-theme">
      <p className="text-xs font-semibold uppercase tracking-wider text-muted mb-2">
        HDFC Mutual Fund Data References:
      </p>
      <div className="flex flex-wrap gap-2 mb-2">
        <a
          href={citationUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-theme text-sm text-secondary hover:text-accent hover:border-accent/40 transition-colors"
        >
          <Link size={13} />
          {label}
        </a>
      </div>
      {footerDate && (
        <div className="flex justify-between items-center text-xs text-muted">
          <span>Source: Groww Factsheet</span>
          <span>Last updated: {footerDate}</span>
        </div>
      )}
    </div>
  )
}
