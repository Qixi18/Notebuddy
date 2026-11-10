import type { Playback } from '../growth/paint'

export type Motion = {
  animate: (element: Element, frames: Keyframe[], timing: { duration: number; delay?: number; easing?: string }) => void
  cleanup: (undo: () => void) => void
}

/** A finite decoration owns its clock, listeners and every temporary mutation. */
export function decorativePlayback(root: SVGGElement, build: (motion: Motion) => void): Playback {
  const effects: Animation[] = [], undo: (() => void)[] = []
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)')
  let done = false, deadline = 0, timer: ReturnType<typeof setTimeout> | undefined, resolve!: () => void
  const finished = new Promise<void>(r => { resolve = r })
  const finish = () => {
    if (done) return
    done = true
    clearTimeout(timer)
    root.removeEventListener('pointerdown', finish, true)
    root.removeEventListener('focusin', finish, true)
    document.removeEventListener('visibilitychange', visibility)
    reduced?.removeEventListener?.('change', preference)
    for (const effect of effects) { try { effect.cancel() } catch { /* Restore the remaining paint too. */ } }
    for (const restore of undo.reverse()) restore()
    resolve()
  }
  const visibility = () => { if (document.visibilityState === 'hidden') finish() }
  const preference = () => { if (reduced?.matches) finish() }
  const playback = { finished, finish }
  if (!root.animate || reduced?.matches || document.visibilityState === 'hidden' || document.querySelector('[role="dialog"], .modal-backdrop')) {
    finish(); return playback
  }
  try {
    build({
      cleanup: restore => undo.push(restore),
      animate: (element, frames, timing) => {
        effects.push(element.animate(frames, { ...timing, fill: 'both', easing: timing.easing ?? 'cubic-bezier(.45,0,.55,1)' }))
        deadline = Math.max(deadline, (timing.delay ?? 0) + timing.duration)
      },
    })
    if (!effects.length) finish()
    else {
      root.addEventListener('pointerdown', finish, true)
      root.addEventListener('focusin', finish, true)
      document.addEventListener('visibilitychange', visibility)
      reduced?.addEventListener?.('change', preference)
      void Promise.all(effects.map(effect => effect.finished)).then(finish, finish)
      timer = setTimeout(finish, deadline + 100)
    }
  } catch { finish() }
  return playback
}
