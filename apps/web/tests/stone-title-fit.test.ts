import assert from 'node:assert/strict'
import test from 'node:test'
import { fitStoneTitle } from '../src/features/home/stoneTitleFit.ts'

// Independent deterministic measurement for the layout search; browser QA uses
// the real inherited font, wrapping and available stone-face dimensions.
const measure = (width: number, height: number) => (text: string, size: number) => {
  const units = Array.from(text).reduce((sum, char) => sum + (/^[\x20-\x7e]$/.test(char) ? .6 : 1), 0)
  const lines = Math.ceil(units * size / width)
  return lines <= 3 && lines * size * 1.25 <= height && size <= width
}

test('ordinary longer course names get smaller letters and retain their complete text', () => {
  const fits = measure(160, 60)
  const short = fitStoneTitle('离散数学', fits, 10, 27, 20)
  const name = '计算机组成原理与硬件描述语言综合实践'
  const long = fitStoneTitle(name, fits, 10, 27, 20)
  assert.equal(long.text, name)
  assert.ok(long.fontSize < short.fontSize)
  assert.ok(fits(long.text, long.fontSize))
})

test('unreasonably long titles use an ellipsis instead of tiny or overflowing letters', () => {
  const fits = measure(70, 55)
  const fitted = fitStoneTitle('非常长的课程名称'.repeat(15), fits, 10, 27, 18)
  assert.ok(fitted.text.endsWith('…'))
  assert.ok(fitted.fontSize >= 10)
  assert.ok(fits(fitted.text, fitted.fontSize))
})

test('unbroken Latin titles fit narrow stones and retain whole Unicode characters', () => {
  const fits = measure(70, 50)
  for (const text of ['AdvancedComputerArchitectureAndHardwareDescriptionLanguage', '数学🌱'.repeat(24)]) {
    const fitted = fitStoneTitle(text, fits, 10, 27, 16)
    assert.ok(fits(fitted.text, fitted.fontSize))
    assert.equal(/\p{Surrogate}/u.test(fitted.text), false)
  }
})
