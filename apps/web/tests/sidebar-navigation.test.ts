import assert from 'node:assert/strict'
import { test } from 'node:test'
import { footerNavItems, primaryNavItems, resolveActiveNav } from '../src/features/navigation/sidebarNav.ts'

test('primary navigation keeps the agreed order', () => {
  assert.deepEqual(primaryNavItems.map((item) => item.label), ['首页', '课程', '知识森林', '答疑桌宠', '回收站'])
})

test('settings is pinned to the footer instead of the primary list', () => {
  assert.deepEqual(footerNavItems.map((item) => item.label), ['设置'])
  assert.equal(primaryNavItems.some((item) => item.id === 'settings'), false)
})

test('every browsing route highlights exactly one navigation item', () => {
  assert.equal(resolveActiveNav('/'), 'home')
  assert.equal(resolveActiveNav('/courses'), 'courses')
  assert.equal(resolveActiveNav('/courses/c1'), 'courses')
  assert.equal(resolveActiveNav('/courses/c1/notebook'), 'courses')
  assert.equal(resolveActiveNav('/forest'), 'forest')
  assert.equal(resolveActiveNav('/recycle'), 'recycle')
})

test('the assistant page wins over the course area that hosts it', () => {
  assert.equal(resolveActiveNav('/courses/c1/assistant'), 'assistant')
})

test('command entries never become the current item', () => {
  const samples = ['/', '/courses', '/courses/c1', '/courses/c1/materials', '/courses/c1/assistant', '/forest', '/recycle']
  for (const pathname of samples) {
    const active = resolveActiveNav(pathname)
    assert.notEqual(active, 'create', `${pathname} must not activate 新建`)
    assert.notEqual(active, 'settings', `${pathname} must not activate 设置`)
  }
})

test('routes without a navigation entry highlight nothing', () => {
  assert.equal(resolveActiveNav('/courses/c1/notes/n1'), 'courses')
  assert.equal(resolveActiveNav('/unknown'), undefined)
})
