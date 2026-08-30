export type ShowType = 'tv' | 'movie' | 'book'
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

export type Medium = 'show' | 'book'

export interface Show {
  show_id: string
  name: string
  show_type: ShowType
  medium: Medium
  author?: string
  series?: string
  series_index?: number
  unverified?: boolean
  rank?: string
  service?: string
  source?: string
  status: Status
  rating?: number
  created_at: string
  updated_at: string
  status_changed_at: string
  rated_at?: string
  discovered_at?: string
  llm_score?: number
  llm_reason?: string
  scored_at?: string
  predicted_score?: number
  score_breakdown?: ScoreBreakdown
}

export interface OtherUser {
  uid: string
  email: string
  display_name: string
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

export interface ScoutState {
  scout_status: 'idle' | 'running'
  discover_status: 'idle' | 'running'
  last_discover: {
    finished_at: string
    created: string[]
    web_searches: number
    est_cost_usd: string
  } | null
  last_discover_error: string | null
  last_run: {
    finished_at: string
    mode: 'full' | 'single'
    checked: number
    web_searches: number
    created: string[]
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
  rank?: string
  author?: string | null
  unverified?: boolean
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
