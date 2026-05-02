export function Logo() {
  return (
    <div className="flex items-center gap-2">
      <div className="w-8 h-8 flex items-center justify-center">
        <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
          <polygon
            points="16,2 30,11 30,21 16,30 2,21 2,11"
            fill="#00c896"
            stroke="none"
          />
          <polygon
            points="16,8 24,13 24,19 16,24 8,19 8,13"
            fill="white"
            fillOpacity="0.25"
          />
        </svg>
      </div>
      <span className="font-semibold text-lg text-primary tracking-tight">
        GrowwMF
      </span>
    </div>
  )
}
