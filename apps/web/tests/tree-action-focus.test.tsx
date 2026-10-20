import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { TreeAction } from '../src/features/tree/TreeAction'

afterEach(cleanup)
test('pressing a visible leaf does not move the camera before its click opens the note', () => {
  const reveal = vi.fn(), open = vi.fn()
  render(<svg><TreeAction label="打开示例知识点" onActivate={open} onFocus={reveal}><ellipse cx="0" cy="-30" rx="19" ry="31" /></TreeAction></svg>)
  const leaf = screen.getByRole('button', { name: '打开示例知识点' })
  fireEvent.pointerDown(leaf)
  fireEvent.focus(leaf)
  expect(reveal).not.toHaveBeenCalled()
  fireEvent.click(leaf)
  expect(open).toHaveBeenCalledOnce()
})

test('keyboard focus still reveals the leaf and Enter opens it', () => {
  const reveal = vi.fn(), open = vi.fn()
  render(<svg><TreeAction label="打开示例知识点" onActivate={open} onFocus={reveal}><ellipse cx="0" cy="-30" rx="19" ry="31" /></TreeAction></svg>)
  const leaf = screen.getByRole('button', { name: '打开示例知识点' })
  fireEvent.focus(leaf)
  expect(reveal).toHaveBeenCalledOnce()
  fireEvent.keyDown(leaf, { key: 'Enter' })
  expect(open).toHaveBeenCalledOnce()
})
