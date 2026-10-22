import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  conversationTime,
  conversationTimeLabel,
  groupConversations,
} from '../src/features/conversation/conversationGroups.ts'

/** 全部用本地时间构造，避免测试依赖运行环境时区 */
const now = new Date(2026, 9, 20, 15, 0) // 2026-10-20 15:00

function conversation(id: string, updatedAt: string) {
  return { id, title: `会话 ${id}`, updated_at: updatedAt, created_at: updatedAt }
}

test('会话按 今天 / 昨天 / 更早 分组，只返回非空组', () => {
  const groups = groupConversations([
    conversation('a', new Date(2026, 9, 20, 9, 0).toISOString()),
    conversation('b', new Date(2026, 9, 19, 22, 30).toISOString()),
    conversation('c', new Date(2026, 9, 15, 8, 0).toISOString()),
    conversation('d', new Date(2026, 9, 20, 8, 0).toISOString()),
  ], now)

  assert.deepEqual(groups.map((group) => group.key), ['today', 'yesterday', 'earlier'])
  assert.deepEqual(groups.map((group) => group.label), ['今天', '昨天', '更早'])
  assert.deepEqual(groups[0].items.map((item) => item.id), ['a', 'd']) // 组内按时间倒序
  assert.deepEqual(groups[2].items.map((item) => item.id), ['c'])
})

test('空会话列表不给任何分组', () => {
  assert.deepEqual(groupConversations([], now), [])
})

test('时间标签：今天给时钟、昨天给「昨天」、更早给 MM-DD、跨年带年份', () => {
  assert.equal(conversationTimeLabel(
    { updated_at: new Date(2026, 9, 20, 9, 5).toISOString(), created_at: '' }, now), '09:05')
  assert.equal(conversationTimeLabel(
    { updated_at: new Date(2026, 9, 19, 23, 40).toISOString(), created_at: '' }, now), '昨天')
  assert.equal(conversationTimeLabel(
    { updated_at: new Date(2026, 9, 17, 12, 0).toISOString(), created_at: '' }, now), '10-17')
  assert.equal(conversationTimeLabel(
    { updated_at: new Date(2025, 11, 1, 12, 0).toISOString(), created_at: '' }, now), '2025-12-01')
})

test('updated_at 缺失时退回 created_at；都无效时时间为 0、标签为空', () => {
  const item = { updated_at: '', created_at: new Date(2026, 9, 20, 10, 0).toISOString() }
  assert.equal(conversationTime(item), Date.parse('2026-10-20T10:00:00+08:00'))
  assert.equal(conversationTimeLabel({ updated_at: '', created_at: 'not-a-date' }, now), '')
  assert.equal(conversationTime({ updated_at: '', created_at: '' }), 0)
})

test('无效时间戳的会话沉到「更早」，不影响其他分组', () => {
  const groups = groupConversations([
    conversation('x', 'garbage'),
    conversation('y', new Date(2026, 9, 20, 10, 0).toISOString()),
  ], now)
  assert.deepEqual(groups.map((group) => group.key), ['today', 'earlier'])
  assert.deepEqual(groups[1].items.map((item) => item.id), ['x'])
})
