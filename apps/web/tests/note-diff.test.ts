import assert from 'node:assert/strict'
import { test } from 'node:test'

import { applySelected, diffRows, hunksOf } from '../src/features/assistant/noteDiff.ts'

test('diffRows 标出新增、删除与未变行', () => {
  const rows = diffRows('共用标题\n旧行\n共用结尾', '共用标题\n新行甲\n新行乙\n共用结尾')

  assert.deepEqual(rows.map((row) => row.type), ['same', 'removed', 'added', 'added', 'same'])
  const removed = rows.find((row) => row.type === 'removed')
  const added = rows.filter((row) => row.type === 'added')
  assert.equal(removed?.text, '旧行')
  assert.deepEqual(added.map((row) => row.text), ['新行甲', '新行乙'])
  // 一个修改区域里的删+增属于同一变更块
  assert.ok(removed?.hunk && added.every((row) => row.hunk === removed.hunk))
})

test('hunksOf 按相邻关系分组，same 行打断块', () => {
  const rows = diffRows('A\nB\nC\nD', 'A\nX\nC\nY')
  const hunks = hunksOf(rows)

  assert.equal(hunks.length, 2)
  // "B 改成 X"是一个变更块：删除行 + 新增行
  assert.deepEqual(hunks[0].rows.map((row) => row.type), ['removed', 'added'])
  assert.deepEqual(hunks[0].rows.map((row) => row.text), ['B', 'X'])
  assert.deepEqual(hunks[1].rows.map((row) => row.text), ['D', 'Y'])
})

test('applySelected：跳过的块保持原文，选中的块应用变更', () => {
  const rows = diffRows('第一段\n旧行\n第三段', '第一段\n新行\n第三段\n追加行')
  const hunks = hunksOf(rows)
  assert.equal(hunks.length, 2)

  // 全选：等于建议全文
  assert.equal(applySelected(rows, new Set(hunks.map((h) => h.key))), '第一段\n新行\n第三段\n追加行')
  // 全不选：等于原文
  assert.equal(applySelected(rows, new Set()), '第一段\n旧行\n第三段')
  // 只选追加块：旧行保留 + 追加行生效
  const appendHunk = hunks.find((hunk) => hunk.rows.every((row) => row.type === 'added'))
  assert.ok(appendHunk)
  assert.equal(applySelected(rows, new Set([appendHunk.key])), '第一段\n旧行\n第三段\n追加行')
})

test('纯新增与全删场景', () => {
  const onlyAdded = diffRows('', '新笔记')
  assert.deepEqual(onlyAdded.map((row) => row.type), ['added'])
  assert.equal(applySelected(onlyAdded, new Set()), '')

  const onlyRemoved = diffRows('旧笔记', '')
  assert.deepEqual(onlyRemoved.map((row) => row.type), ['removed'])
  assert.equal(applySelected(onlyRemoved, new Set(['h0'])), '')
})
