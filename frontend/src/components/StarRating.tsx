interface Props {
  rating?: number
  onRate: (rating: number) => void
}

const LABELS = ['it was fine', 'pretty good', 'an absolute favorite']

export function StarRating({ rating, onRate }: Props) {
  return (
    <div className={`stars ${rating ? '' : 'stars-unrated'}`} title={rating ? LABELS[rating - 1] : 'Rate it'}>
      {[1, 2, 3].map((n) => (
        <button
          key={n}
          type="button"
          className={`star ${rating && n <= rating ? 'star-filled' : ''}`}
          aria-label={`${n} star${n > 1 ? 's' : ''} — ${LABELS[n - 1]}`}
          onClick={() => onRate(n)}
          onPointerDown={(e) => e.stopPropagation()}
        >
          {rating && n <= rating ? '★' : '☆'}
        </button>
      ))}
    </div>
  )
}
