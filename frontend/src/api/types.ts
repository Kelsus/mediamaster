export type ShowType = 'tv' | 'movie'
export type Status = 'to_watch' | 'watching' | 'done' | 'poubelle'

export interface ScoreFeature {
  value: string
  affinity: number
  adjustment: number
  rated_count: number
}

export interface ScoreBreakdown {
  base: number
  source?: ScoreFeature
  service?: ScoreFeature
  show_type?: ScoreFeature
}

export interface Show {
  show_id: string
  name: string
  show_type: ShowType
  service?: string
  source?: string
  status: Status
  rating?: number
  created_at: string
  updated_at: string
  status_changed_at: string
  rated_at?: string
  llm_score?: number
  llm_reason?: string
  scored_at?: string
  predicted_score?: number
  score_breakdown?: ScoreBreakdown
}

export interface TasteProfile {
  profile_text: string | null
  notes: string
  generated_at: string | null
  scoring_status: 'idle' | 'running'
  last_run: {
    finished_at: string
    scored: number
    queue_size: number
    est_cost_usd: string
  } | null
  last_error: string | null
}

export interface Board {
  columns: Record<Status, Show[]>
}

export interface ShowPatch {
  name?: string
  show_type?: ShowType
  service?: string | null
  source?: string | null
  status?: Status
  rating?: number | null
}

export interface AppConfig {
  region: string
  user_pool_id: string
  client_id: string
}

export interface ApiToken {
  prefix: string
  label: string
  created_at: string
}
