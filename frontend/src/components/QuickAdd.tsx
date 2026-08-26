import { useState } from 'react'
import type { Medium, ShowType } from '../api/types'

interface Props {
  medium: Medium
  onAdd: (name: string, showType: ShowType, author?: string) => void
}

export function QuickAdd({ medium, onAdd }: Props) {
  const [name, setName] = useState('')
  const [author, setAuthor] = useState('')
  const [type, setType] = useState<ShowType>(
    () => (localStorage.getItem('mm.lastType') as ShowType) || 'tv',
  )

  const submit = () => {
    const trimmed = name.trim()
    if (!trimmed) return
    if (medium === 'book') {
      onAdd(trimmed, 'book', author.trim() || undefined)
      setAuthor('')
    } else {
      onAdd(trimmed, type)
    }
    setName('')
  }

  const pick = (t: ShowType) => {
    setType(t)
    localStorage.setItem('mm.lastType', t)
  }

  if (medium === 'book') {
    return (
      <div className="quick-add quick-add-book">
        <input
          value={name}
          placeholder="Add something to read…"
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
        />
        <input
          className="quick-add-author"
          value={author}
          placeholder="author (optional)"
          onChange={(e) => setAuthor(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
        />
      </div>
    )
  }

  return (
    <div className="quick-add">
      <input
        value={name}
        placeholder="Add something to watch…"
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && submit()}
      />
      <div className="type-toggle" role="radiogroup" aria-label="tv or movie">
        <button
          type="button"
          className={type === 'tv' ? 'active' : ''}
          onClick={() => pick('tv')}
        >
          TV
        </button>
        <button
          type="button"
          className={type === 'movie' ? 'active' : ''}
          onClick={() => pick('movie')}
        >
          Film
        </button>
      </div>
    </div>
  )
}
