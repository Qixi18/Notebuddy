import { useEffect, useState } from 'react'

const WIDE_PET_QUERY = '(min-width: 900px)'

/** Parent identity and pet rendering must agree on the narrow-screen fallback. */
export function usePetWideViewport(): boolean {
  const [wide, setWide] = useState(() => typeof matchMedia === 'undefined' || matchMedia(WIDE_PET_QUERY).matches)
  useEffect(() => {
    if (typeof matchMedia === 'undefined') return
    const query = matchMedia(WIDE_PET_QUERY)
    const onChange = (event: MediaQueryListEvent) => setWide(event.matches)
    query.addEventListener('change', onChange)
    setWide(query.matches)
    return () => query.removeEventListener('change', onChange)
  }, [])
  return wide
}
