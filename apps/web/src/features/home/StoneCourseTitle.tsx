import { useLayoutEffect, useRef, useState } from 'react'
import { fitStoneTitle, stoneTitleUnits } from './stoneTitleFit'

export function StoneCourseTitle({ name }: { name: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  const [layout, setLayout] = useState(() => fitStoneTitle(name, () => true, 10, 27, 27))
  useLayoutEffect(() => {
    const text = ref.current, button = text?.parentElement
    if (!text || !button) return
    let active = true
    const fit = () => {
      if (!active) return
      const box = getComputedStyle(button), font = getComputedStyle(text)
      const width = button.clientWidth - parseFloat(box.paddingLeft) - parseFloat(box.paddingRight) - 1
      const height = button.clientHeight - parseFloat(box.paddingTop) - parseFloat(box.paddingBottom) - 1
      if (!(width > 0 && height > 0)) return
      const probe = document.createElement('span')
      probe.setAttribute('aria-hidden', 'true')
      Object.assign(probe.style, {
        position: 'absolute', visibility: 'hidden', pointerEvents: 'none',
        display: 'block', width: `${width}px`, height: 'auto',
        padding: '0', margin: '0', border: '0',
        whiteSpace: 'normal', overflowWrap: 'anywhere', textWrap: 'balance',
        fontFamily: font.fontFamily, fontWeight: font.fontWeight, fontStyle: font.fontStyle,
        lineHeight: '1.25', letterSpacing: '0',
      })
      button.append(probe)
      try {
        const fits = (value: string, size: number) => {
          probe.textContent = value
          probe.style.fontSize = `${size}px`
          return probe.scrollWidth <= width + 1
            && probe.getBoundingClientRect().height <= Math.min(height, size * 1.25 * 3) + .25
        }
        const estimate = Math.sqrt(width * height / Math.max(1, stoneTitleUnits(name)) / 1.25)
        const next = fitStoneTitle(name, fits, 10, 27, estimate)
        setLayout(previous => previous.text === next.text && previous.fontSize === next.fontSize ? previous : next)
      } finally { probe.remove() }
    }
    fit()
    const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(fit)
    observer?.observe(button)
    window.addEventListener('resize', fit)
    void document.fonts?.ready.then(fit)
    return () => { active = false; observer?.disconnect(); window.removeEventListener('resize', fit) }
  }, [name])
  return <span ref={ref} className="home-course-stone-name" style={{ fontSize: layout.fontSize }}>{layout.text}</span>
}
