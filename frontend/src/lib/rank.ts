// Fractional ranks — mirror of backend/src/mediamaster_api/rank.py.
// Column order = rank ascending; rankBetween(null, top) prepends.

const DIGITS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
const BASE = DIGITS.length

const val = (ch: string) => DIGITS.indexOf(ch)

export function rankBetween(a: string | null | undefined, b: string | null | undefined): string {
  const lo = a ?? ''
  const hi = b ?? ''
  if (lo && hi && lo >= hi) throw new Error(`rankBetween requires a < b: ${lo} >= ${hi}`)

  const result: string[] = []
  let i = 0
  for (;;) {
    const da = i < lo.length ? val(lo[i]) : 0
    const db = i < hi.length ? val(hi[i]) : BASE
    if (db - da > 1) {
      result.push(DIGITS[Math.floor((da + db) / 2)])
      return result.join('')
    }
    if (db - da === 1) {
      result.push(DIGITS[da])
      let j = i + 1
      for (;;) {
        const dj = j < lo.length ? val(lo[j]) : 0
        if (BASE - dj > 1) {
          result.push(DIGITS[Math.floor((dj + BASE) / 2)])
          return result.join('')
        }
        result.push(DIGITS[dj])
        j += 1
      }
    }
    result.push(DIGITS[da])
    i += 1
  }
}

/** Rank for inserting at `index` within a rank-sorted list. */
export function rankAt(ranks: (string | null | undefined)[], index: number): string {
  const lo = index > 0 ? ranks[index - 1] : null
  const hi = index < ranks.length ? ranks[index] : null
  return rankBetween(lo ?? null, hi ?? null)
}
