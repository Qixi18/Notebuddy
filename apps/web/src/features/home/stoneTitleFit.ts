export function stoneTitleUnits(text: string) {
  return Array.from(text).reduce((sum, char) => sum + (/\s/.test(char) ? .3 : /^[\x21-\x7e]$/.test(char) ? .6 : 1), 0)
}

/** Choose the largest legible type that fits; shorten only when necessary. */
export function fitStoneTitle(name: string, fits: (text: string, size: number) => boolean, min: number, max: number, estimate: number) {
  const glyphs = Array.from(name.replace(/\s+/g, ' ').trim())
  let end = 0, units = 0
  while (end < glyphs.length && units + stoneTitleUnits(glyphs[end]) <= 32) units += stoneTitleUnits(glyphs[end++])
  const prefix = (count: number) => glyphs.slice(0, count).join('').trimEnd() + (count < glyphs.length ? '…' : '')
  let text = prefix(end)
  if (!fits(text, min)) {
    let low = 0, high = end
    while (low < high) {
      const mid = Math.ceil((low + high) / 2)
      if (fits(prefix(mid), min)) low = mid
      else high = mid - 1
    }
    text = prefix(low)
  }
  let low = min, high = max
  const initial = Math.max(min, Math.min(max, estimate))
  if (fits(text, initial)) low = initial
  else high = initial
  for (let step = 0; step < 8; step++) {
    const mid = (low + high) / 2
    if (fits(text, mid)) low = mid
    else high = mid
  }
  return { text, fontSize: Math.floor(low * 10) / 10 }
}
