import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'

import { parseCitations } from '../src/features/assistant/citations'
import { CitationText } from '../src/features/assistant/CitationText'
import type { AssistantSource } from '../src/types'

afterEach(cleanup)

const sources: AssistantSource[] = [
  { source_type: 'course_material', material_id: 'm1', lecture_title: '第 3 讲 树与二叉树', page_number: 18, snippet: '插入只会破坏性质 4', support_level: 'direct' },
  { source_type: 'course_material', material_id: 'm1', lecture_title: '第 3 讲 树与二叉树', page_number: 19, snippet: '情形 2 与情形 3', support_level: 'related' },
  { source_type: 'web', url: 'https://example.org/rbt', title: 'Red–black tree', site_name: 'Wikipedia', snippet: '等价于 2-3-4 树', support_level: 'supplement' },
]

test('课程标记按 讲次+页码 精确匹配，角标按首次引用顺序编号', () => {
  const { paragraphs } = parseCitations(
    '插入最多两次旋转即可恢复。[课程资料：第 3 讲 树与二叉树 | 第 18 页]',
    sources,
  )
  expect(paragraphs).toHaveLength(1)
  expect(paragraphs[0].text).toBe('插入最多两次旋转即可恢复。')
  expect(paragraphs[0].refs).toEqual([
    { no: 1, kind: 'course', sourceIndex: 0, title: '第 3 讲 树与二叉树', page: 18 },
  ])
})

test('匹配不到的标记只删除、不编号', () => {
  const { paragraphs } = parseCitations(
    '没有出处的句子。[课程资料：不存在的讲次 | 第 3 页] 后续内容照常。',
    sources,
  )
  expect(paragraphs[0].refs).toEqual([])
  expect(paragraphs[0].text).toContain('后续内容照常')
  expect(paragraphs[0].text).not.toContain('课程资料')
})

test('网络标记按序号匹配 web 来源，越界退回未用来源，重复去重', () => {
  const { paragraphs } = parseCitations(
    '等价于 2-3-4 树。[网络来源 1] 又见同一来源。[网络来源 1] 超出的引用。[网络来源 5]',
    sources,
  )
  const webRefs = paragraphs[0].refs.filter((ref) => ref.kind === 'web')
  expect(webRefs).toHaveLength(1)
  /* 该来源是全文里第一个被引用的，因此编号为 1（不再沿用它在 sources 里的位置 3） */
  expect(webRefs[0].no).toBe(1)
})

test('编号按首次引用顺序连续，与来源在数组中的位置无关', () => {
  /* 先引用 sources[2]（网络来源），再引用 sources[0]（第 3 讲 p.18） */
  const { paragraphs } = parseCitations(
    '先看外部资料。[网络来源 1]\n\n再看讲义。[课程资料：第 3 讲 树与二叉树 | 第 18 页]',
    sources,
  )
  expect(paragraphs[0].refs[0].no).toBe(1)
  expect(paragraphs[0].refs[0].sourceIndex).toBe(2)
  expect(paragraphs[1].refs[0].no).toBe(2)
  expect(paragraphs[1].refs[0].sourceIndex).toBe(0)
})

test('同一来源多处引用复用同一个编号', () => {
  const { paragraphs } = parseCitations(
    '第一处。[课程资料：第 3 讲 树与二叉树 | 第 18 页]\n\n第二处。[课程资料：第 3 讲 树与二叉树 | 第 18 页]',
    sources,
  )
  expect(paragraphs[0].refs[0].no).toBe(1)
  expect(paragraphs[1].refs[0].no).toBe(1)
})

test('通用解释 / 模型推断 摘成段落标记，不占角标', () => {
  const { paragraphs } = parseCitations(
    '这是补充说明。[通用解释] 这是推断。[模型推断]',
    sources,
  )
  expect(paragraphs[0].flags).toEqual(['通用解释', '模型推断'])
  expect(paragraphs[0].refs).toEqual([])
  expect(paragraphs[0].text).toBe('这是补充说明。 这是推断。')
})

test('空行分段：每段独立解析标记', () => {
  const { paragraphs } = parseCitations(
    '第一段。[课程资料：第 3 讲 树与二叉树 | 第 18 页]\n\n第二段。[课程资料：第 3 讲 树与二叉树 | 第 19 页]',
    sources,
  )
  expect(paragraphs).toHaveLength(2)
  expect(paragraphs[0].refs[0].no).toBe(1)
  expect(paragraphs[1].refs[0].no).toBe(2)
})

test('CitationText 渲染 Markdown + 角标按钮，点击回调编号', () => {
  let cited = 0
  const onCite = (no: number) => { cited = no }
  render(<CitationText
    content={'**结论**：最多两次旋转。[课程资料：第 3 讲 树与二叉树 | 第 18 页]'}
    sources={sources}
    onCite={onCite}
  />)
  expect(screen.getByText('结论').tagName).toBe('STRONG')
  expect(screen.queryByText(/课程资料：/)).toBeNull()
  const badge = screen.getByRole('button', { name: /查看依据 1：第 3 讲 树与二叉树 第 18 页/ })
  fireEvent.click(badge)
  expect(cited).toBe(1)
})

test('无标记的正文不渲染角标；无来源时标记全部剥除', () => {
  render(<CitationText content="普通回答，没有任何标记。" />)
  expect(document.querySelector('.cite-ref')).toBeNull()
  render(<CitationText content="有标记。[课程资料：第 3 讲 树与二叉树 | 第 18 页]" sources={[]} />)
  expect(screen.queryByText(/课程资料：/)).toBeNull()
  expect(document.querySelector('.cite-ref')).toBeNull()
})

const multiPageSources: AssistantSource[] = [
  { source_type: 'course_material', material_id: 'm1', lecture_title: '第 1 讲 绪论', page_number: 2, snippet: '页 2', support_level: 'direct' },
  { source_type: 'course_material', material_id: 'm1', lecture_title: '第 1 讲 绪论', page_number: 3, snippet: '页 3', support_level: 'direct' },
  { source_type: 'course_material', material_id: 'm1', lecture_title: '第 1 讲 绪论', page_number: 5, snippet: '页 5', support_level: 'direct' },
]

test('一个标记列多页时逐个命中来源，各占一个角标', () => {
  const { paragraphs } = parseCitations(
    '结论。[课程资料：第 1 讲 绪论 | 第 2、3、5 页]',
    multiPageSources,
  )
  expect(paragraphs[0].text).toBe('结论。')
  expect(paragraphs[0].refs.map((ref) => ref.page)).toEqual([2, 3, 5])
  expect(paragraphs[0].refs.map((ref) => ref.no)).toEqual([1, 2, 3])
})

test('页码支持区间与连接词写法', () => {
  const ranged = parseCitations('区间。[课程资料：第 1 讲 绪论 | 第 2-3 页]', multiPageSources)
  expect(ranged.paragraphs[0].refs.map((ref) => ref.page)).toEqual([2, 3])
  const linked = parseCitations('连接词。[课程资料：第 1 讲 绪论 | 第 2 到 3 页]', multiPageSources)
  expect(linked.paragraphs[0].refs.map((ref) => ref.page)).toEqual([2, 3])
})

test('多页里夹杂不存在的页码时只标命中的，不虚标', () => {
  const { paragraphs } = parseCitations(
    '部分越界。[课程资料：第 1 讲 绪论 | 第 2、99 页]',
    multiPageSources,
  )
  expect(paragraphs[0].refs.map((ref) => ref.page)).toEqual([2])
})

test('多页标记在正文里渲染出多个角标', () => {
  render(<CitationText
    content={'结论。[课程资料：第 1 讲 绪论 | 第 2、3、5 页]'}
    sources={multiPageSources}
    onCite={() => {}}
  />)
  expect(screen.queryByText(/课程资料：/)).toBeNull()
  expect(document.querySelectorAll('.cite-ref')).toHaveLength(3)
  expect(screen.getByRole('button', { name: /查看依据 2：第 1 讲 绪论 第 3 页/ })).toBeTruthy()
})
