import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { useForestCamera } from '../src/features/forest/useForestCamera'
beforeEach(() => {
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) =>
    window.setTimeout(() => callback(0), 0),
  )
  vi.stubGlobal('cancelAnimationFrame', (id: number) => window.clearTimeout(id))
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
function Probe({ width, height }: { width: number; height: number }) {
  const camera = useForestCamera({ x: -850, y: -125, k: 1 }, width, height)
  return (
    <>
      <svg ref={camera.svgRef}>
        <g ref={camera.sceneRef} />
      </svg>
      <output aria-label="相机世界中心">{`${(width / 2 - camera.camera.x) / camera.camera.k},${(height / 2 - camera.camera.y) / camera.camera.k}`}</output>
    </>
  )
}
test('resizing from desktop to a narrow viewport preserves the visible world center', async () => {
  const { rerender } = render(<Probe width={1200} height={850} />)
  await waitFor(() => expect(screen.getByLabelText('相机世界中心').textContent).toBe('1450,550'))
  rerender(<Probe width={390} height={700} />)
  await waitFor(() => expect(screen.getByLabelText('相机世界中心').textContent).toBe('1450,550'))
})
