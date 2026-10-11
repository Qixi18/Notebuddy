import { useCallback, useEffect, useRef, useState } from 'react'
import { select } from 'd3-selection'
import { zoom, zoomIdentity, type ZoomBehavior } from 'd3-zoom'
import type { Camera } from './types'

export function useForestCamera(
  initial: Camera,
  width: number,
  height: number,
  viewportReady = true,
) {
  const svgRef = useRef<SVGSVGElement>(null)
  const sceneRef = useRef<SVGGElement>(null)
  const behavior = useRef<ZoomBehavior<SVGSVGElement, unknown>>(undefined)
  const cameraRef = useRef(initial)
  const viewport = useRef(viewportReady ? { width, height } : undefined)
  const [camera, setCamera] = useState(initial)
  useEffect(() => {
    if (!svgRef.current) return
    // Only measured viewports can establish a resize; the initial fallback is not one.
    if (viewportReady && viewport.current) {
      cameraRef.current = {
        ...cameraRef.current,
        x: cameraRef.current.x + (width - viewport.current.width) / 2,
        y: cameraRef.current.y + (height - viewport.current.height) / 2,
      }
    }
    if (viewportReady) viewport.current = { width, height }
    let frame = 0
    const svg = select(svgRef.current)
    const controller = zoom<SVGSVGElement, unknown>()
      .extent([
        [0, 0],
        [width, height],
      ])
      .scaleExtent([0.35, 2.5])
      .filter(
        (event: MouseEvent | WheelEvent) =>
          !(event.target as Element)?.closest?.('[data-forest-interactive]') &&
          (!event.ctrlKey || event.type === 'wheel') &&
          !event.button,
      )
      .on('zoom', (event: { transform: Camera; sourceEvent?: Event }) => {
        const next = { x: event.transform.x, y: event.transform.y, k: event.transform.k }
        cameraRef.current = next
        if (sceneRef.current)
          select(sceneRef.current).attr(
            'transform',
            `translate(${next.x},${next.y}) scale(${next.k})`,
          )
        cancelAnimationFrame(frame)
        frame = requestAnimationFrame(() => setCamera(next))
      })
    behavior.current = controller
    svg
      .call(controller)
      .call(
        controller.transform,
        zoomIdentity.translate(cameraRef.current.x, cameraRef.current.y).scale(cameraRef.current.k),
      )
    svg.on('dblclick.zoom', null)
    return () => {
      cancelAnimationFrame(frame)
      svg.on('.zoom', null)
    }
  }, [width, height, viewportReady])
  const move = useCallback((next: Camera) => {
    if (svgRef.current && behavior.current)
      select(svgRef.current).call(
        behavior.current.transform,
        zoomIdentity.translate(next.x, next.y).scale(next.k),
      )
    else {
      cameraRef.current = next
      setCamera(next)
    }
  }, [])
  const pan = useCallback(
    (dx: number, dy = 0) =>
      move({ ...cameraRef.current, x: cameraRef.current.x + dx, y: cameraRef.current.y + dy }),
    [move],
  )
  const scale = useCallback(
    (factor: number) => {
      const current = cameraRef.current
      const k = Math.min(2.5, Math.max(0.35, current.k * factor))
      move({
        x: width / 2 - ((width / 2 - current.x) * k) / current.k,
        y: height / 2 - ((height / 2 - current.y) * k) / current.k,
        k,
      })
    },
    [move, width, height],
  )
  const focus = useCallback(
    (x: number, y: number) =>
      move({ x: width / 2 - x * 1.05, y: height * 0.82 - y * 1.05, k: 1.05 }),
    [move, width, height],
  )
  return { svgRef, sceneRef, camera, cameraRef, move, pan, scale, focus }
}
