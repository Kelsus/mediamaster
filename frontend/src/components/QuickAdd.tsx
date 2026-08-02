import { useState } from 'react'
import type { ShowType } from '../api/types'

interface Props {
  onAdd: (name: string, showType: ShowType) => void
}

export function QuickAdd({ onAdd }: Props) {
  const [name, setName] = useState('')
  const [type, setType] = useState<ShowType>(
    () => (localStorage.getItem('mm.lastType') as ShowType) || 'tv',
  )

  const submit = () => {
    const trimmed = name.trim()
    if (!trimmed) return
    onAdd(trimmed, type)
    setName('')
  }

  const pick = (t: ShowType) => {
    setType(t)
    localStorage.setItem('mm.lastType', t)
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
