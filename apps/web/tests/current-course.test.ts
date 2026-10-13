import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  courseVisitedAt,
  pickFallbackCourseId,
  resolveConversationCourseId,
} from '../src/features/workspace/currentCourse.ts'

const visited: Record<string, string> = {}
const read = (key: string) => visited[key] ?? null
const course = (id: string) => ({ id, name: id.toUpperCase(), created_at: '2026-01-01T00:00:00Z' })

test('没有 URL 课程时落到最近访问过的那门课', () => {
  visited['notebuddy.course.b.lastVisited'] = '2026-10-12T10:00:00Z'
  visited['notebuddy.course.c.lastVisited'] = '2026-10-13T09:00:00Z'
  assert.equal(pickFallbackCourseId([course('a'), course('b'), course('c')], (id) => courseVisitedAt(id, read)), 'c')
})

test('都没有访问记录时退回课程列表第一门', () => {
  assert.equal(pickFallbackCourseId([course('a'), course('b')], () => 0), 'a')
})

test('一门课都没有时没有落点', () => {
  assert.equal(pickFallbackCourseId([], () => 0), undefined)
})

test('URL 里的课程优先于最近访问', () => {
  const courses = [course('a'), course('b')]
  assert.equal(resolveConversationCourseId('a', courses, read), 'a')
  assert.equal(resolveConversationCourseId(undefined, courses, read), 'b')
})

test('时间戳损坏或缺失一律视为未访问，不抛错', () => {
  visited['notebuddy.course.broken.lastVisited'] = 'not-a-date'
  assert.equal(courseVisitedAt('broken', read), 0)
  assert.equal(courseVisitedAt('never-visited', read), 0)
})
