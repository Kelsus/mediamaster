import type { Show } from '../api/types'

export function ScoreChip({ show }: { show: Show }) {
  // LLM taste score takes over once the show has been profiled
  if (show.llm_score !== undefined && show.llm_score !== null) {
    const s = show.llm_score
    return (
      <span className={`score-chip llm-chip ${s >= 70 ? 'score-hot' : s <= 40 ? 'score-cold' : ''}`}>
        {s}
        <span className="score-tip">
          <strong>Claude's read</strong>
          <span>{show.llm_reason ?? 'no reason recorded'}</span>
          {statsLines(show).map((l) => (
            <span key={l} className="score-tip-secondary">
              {l}
            </span>
          ))}
        </span>
      </span>
    )
  }

  const score = show.predicted_score
  if (score === undefined || !Number.isFinite(score)) return null
  const lines = statsLines(show)
  // A bare 0 with no contributing features says nothing — show nothing.
  if (lines.length === 0 && Math.abs(score) < 0.005) return null

  return (
    <span className={`score-chip ${score > 0.15 ? 'score-hot' : score < -0.15 ? 'score-cold' : ''}`}>
      {score > 0 ? '+' : ''}
      {score.toFixed(1)}
      {lines.length > 0 && (
        <span className="score-tip">
          <strong>predicted taste</strong>
          {lines.map((l) => (
            <span key={l}>{l}</span>
          ))}
        </span>
      )}
    </span>
  )
}

function statsLines(show: Show): string[] {
  const bd = show.score_breakdown
  if (!bd) return []
  const lines: string[] = []
  for (const key of ['source', 'service', 'show_type'] as const) {
    const f = bd[key]
    if (!f) continue
    const label = key === 'show_type' ? (f.value === 'tv' ? 'tv shows' : 'movies') : f.value
    const sign = f.adjustment >= 0 ? '+' : ''
    lines.push(`${label}: ${sign}${f.adjustment.toFixed(2)} (${f.rated_count} rated)`)
  }
  return lines
}
