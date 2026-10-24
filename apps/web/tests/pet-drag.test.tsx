import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

vi.mock('../src/api', () => ({
  ApiError: class ApiError extends Error { status = 0 },
  api: {
    getWebSearchStatus: vi.fn(async () => ({ configured: false, provider: 'none', status: 'ok' })),
    saveFeedback: vi.fn(async () => ({ id: 'fb1' })),
    /* 答疑页挂载即按课程拉待确认建议（P4） */
    listCourseSuggestions: vi.fn(async () => []),
    getNote: vi.fn(),
  },
}))

import type { ConversationMessage } from '../src/types'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
import { AssistantPage } from '../src/pages/AssistantPage'
import { PET_STORAGE_KEY } from '../src/features/pet/petStorage'

afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals() })

/** jsdom 的 matchMedia 不做布局计算，宽度查询恒为 false；桌面拖拽测试需要 ≥900px 的假象 */
beforeEach(() => {
  vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('min-width'),
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })))
})

const course = { id: 'c1', name: '数据结构与算法', description: null, created_at: '2026-01-01T00:00:00Z' }
const greeting: ConversationMessage = {
  id: 'local-greeting', conversation_id: 'conv-1', role: 'assistant',
  content: '你好，我是莉艾尔。', learning_goal: null, status: 'completed', model_version: null,
  failure_type: null, created_at: '', evidence: [], mode: null, sources: [],
}

function renderPage() {
  const conversation = {
    conversations: [{ id: 'conv-1', course_id: 'c1', title: '会话', default_scope: 'course', created_at: new Date().toISOString(), updated_at: new Date().toISOString() }],
    conversationId: 'conv-1' as string | undefined,
    messages: [greeting],
    busy: false,
    ready: true,
    error: undefined as string | undefined,
    agentRun: null,
    selectConversation: vi.fn(async () => {}),
    startNewConversation: vi.fn(async () => {}),
    ask: vi.fn(async () => true),
    askAgent: vi.fn(async () => true),
  }
  const workspace = {
    courses: [course], courseId: 'c1', conversationCourseId: 'c1', course,
    coursesLoading: false, courseContentLoading: false,
    materials: [], selectedMaterialId: undefined, setSelectedMaterialId: vi.fn(),
    pages: [], selectedPageNumber: undefined, setSelectedPageNumber: vi.fn(),
    openMaterialSource: vi.fn(), notes: [], upsertNotes: vi.fn(),
    noteDraft: '', setNoteDraft: vi.fn(), editingNote: false, setEditingNote: vi.fn(),
    graph: { nodes: [], edges: [] }, teacherPersona: 'elf', setTeacherPersona: vi.fn(),
    conversation, busy: false, noteSaving: false, noteDirty: false,
    reloadNote: vi.fn(async () => {}), error: undefined, setError: vi.fn(),
    createCourse: vi.fn(), uploadMaterial: vi.fn(), retryMaterial: vi.fn(), reparseMaterial: vi.fn(),
    requestOCR: vi.fn(), saveNote: vi.fn(async () => {}),
    refreshCourses: vi.fn(async () => {}), refreshCurrentMaterials: vi.fn(async () => {}), refreshCurrentNotes: vi.fn(async () => {}),
  } as never as WorkspaceContextValue

  return render(
    <MemoryRouter initialEntries={['/courses/c1/assistant']}>
      <WorkspaceProvider value={workspace}>
        <AssistantPage />
      </WorkspaceProvider>
    </MemoryRouter>,
  )
}

function pointer(type: string, x: number, y: number, pointerId = 1) {
  return new PointerEvent(type, { pointerId, clientX: x, clientY: y, button: 0, bubbles: true })
}

/** 原生 window 事件驱动的 state 更新需要 act 才会在 jsdom 里刷新 */
function move(x: number, y: number) {
  act(() => { window.dispatchEvent(pointer('pointermove', x, y)) })
}

function up(x: number, y: number) {
  act(() => { window.dispatchEvent(pointer('pointerup', x, y)) })
}

test('从左栏舞台拖出：浮层出现并跟随指针，松手位置写入 localStorage', () => {
  const { container } = renderPage()
  const stage = container.querySelector('.workspace-petstage-drag') as HTMLElement
  expect(stage).toBeTruthy()
  stage.getBoundingClientRect = () => ({ left: 260, top: 120, right: 460, bottom: 332, x: 260, y: 120, width: 200, height: 212, toJSON: () => ({}) }) as DOMRect
  const rail = container.querySelector('.workspace-rail') as HTMLElement
  rail.getBoundingClientRect = () => ({ left: 244, top: 0, right: 500, bottom: 800, x: 244, y: 0, width: 256, height: 800, toJSON: () => ({}) }) as DOMRect

  fireEvent.pointerDown(stage, { button: 0, pointerId: 1, clientX: 300, clientY: 200 })
  move(360, 180) // 位移 > 6px，触发 detach

  expect(container.querySelector('.workspace-petstage-drag')).toBeNull()
  expect(container.querySelector('.workspace-pet-anchor')).toBeTruthy() // 左栏出现锚点行
  const float = document.body.querySelector('.workspace-petfloat') as HTMLElement
  expect(float).toBeTruthy() // 浮层仍挂在 body 顶层，不随形态切换消失

  move(700, 300)
  expect(float.style.transform).toContain('translate3d')

  up(700, 300)
  const placement = JSON.parse(localStorage.getItem(PET_STORAGE_KEY) ?? '{}')
  expect(placement.mode).toBe('float')
  expect(typeof placement.xRatio).toBe('number')
})

test('浮层可继续拖动，双击回到左栏', () => {
  const { container } = renderPage()
  const stage = container.querySelector('.workspace-petstage-drag') as HTMLElement
  stage.getBoundingClientRect = () => ({ left: 260, top: 120, right: 460, bottom: 332, x: 260, y: 120, width: 200, height: 212, toJSON: () => ({}) }) as DOMRect
  const rail = container.querySelector('.workspace-rail') as HTMLElement
  rail.getBoundingClientRect = () => ({ left: 244, top: 0, right: 500, bottom: 800, x: 244, y: 0, width: 256, height: 800, toJSON: () => ({}) }) as DOMRect

  fireEvent.pointerDown(stage, { button: 0, pointerId: 1, clientX: 300, clientY: 200 })
  move(420, 150)
  const float = document.body.querySelector('.workspace-petfloat') as HTMLElement
  expect(float).toBeTruthy()

  // 继续拖动浮层本体（拖到远处，避开左栏回收区）
  fireEvent.pointerDown(float, { button: 0, pointerId: 1, clientX: 420, clientY: 150 })
  move(900, 300)
  up(900, 300)
  expect(localStorage.getItem(PET_STORAGE_KEY)).toContain('"mode":"float"')

  // 双击召回
  fireEvent.doubleClick(float)
  expect(container.querySelector('.workspace-petstage-drag')).toBeTruthy()
  expect(document.body.querySelector('.workspace-petfloat')).toBeNull()
  expect(localStorage.getItem(PET_STORAGE_KEY)).toContain('"mode":"rail"')
})

test('点击（位移 < 6px）不触发 detach，只出气泡', () => {
  const { container } = renderPage()
  const stage = container.querySelector('.workspace-petstage-drag') as HTMLElement
  stage.getBoundingClientRect = () => ({ left: 260, top: 120, right: 460, bottom: 332, x: 260, y: 120, width: 200, height: 212, toJSON: () => ({}) }) as DOMRect

  fireEvent.pointerDown(stage, { button: 0, pointerId: 1, clientX: 300, clientY: 200 })
  move(303, 202)
  up(303, 202)
  expect(container.querySelector('.workspace-petstage-drag')).toBeTruthy()
  expect(document.body.querySelector('.workspace-petfloat')).toBeNull()
  fireEvent.click(stage)
  expect(document.querySelector('.workspace-pet-bubble')).toBeTruthy()
})

test('拖回左栏范围松手：自动召回', () => {
  const { container } = renderPage()
  const stage = container.querySelector('.workspace-petstage-drag') as HTMLElement
  stage.getBoundingClientRect = () => ({ left: 260, top: 120, right: 460, bottom: 332, x: 260, y: 120, width: 200, height: 212, toJSON: () => ({}) }) as DOMRect
  const rail = container.querySelector('.workspace-rail') as HTMLElement
  rail.getBoundingClientRect = () => ({ left: 244, top: 0, right: 500, bottom: 800, x: 244, y: 0, width: 256, height: 800, toJSON: () => ({}) }) as DOMRect

  fireEvent.pointerDown(stage, { button: 0, pointerId: 1, clientX: 300, clientY: 200 })
  move(430, 160)
  expect(document.body.querySelector('.workspace-petfloat')).toBeTruthy()

  // 拖回左栏范围内松手
  move(320, 220)
  up(320, 220)
  expect(container.querySelector('.workspace-petstage-drag')).toBeTruthy()
  expect(document.body.querySelector('.workspace-petfloat')).toBeNull()
  expect(localStorage.getItem(PET_STORAGE_KEY)).toContain('"mode":"rail"')
})
