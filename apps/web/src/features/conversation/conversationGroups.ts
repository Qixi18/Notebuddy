import type { Conversation, Course } from '../../types'

/**
 * 会话历史的时间分组：今天 / 昨天 / 更早。
 * 纯函数，供答疑页左栏的会话列表使用；时间取 updated_at，缺了退回 created_at。
 */

export type ConversationGroupKey = 'today' | 'yesterday' | 'earlier'

export type ConversationGroup<T> = {
  key: ConversationGroupKey
  label: string
  items: T[]
}

const GROUP_LABELS: Record<ConversationGroupKey, string> = {
  today: '今天',
  yesterday: '昨天',
  earlier: '更早',
}

export type GroupableConversation = Pick<Conversation, 'updated_at' | 'created_at'>

/** 会话的排序时间戳；解析失败按 0 处理，沉到分组末尾 */
export function conversationTime(item: GroupableConversation): number {
  const raw = item.updated_at || item.created_at
  if (!raw) return 0
  const time = Date.parse(raw)
  return Number.isNaN(time) ? 0 : time
}

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
}

/** 今天 → HH:MM；昨天 → 「昨天」；更早 → 本年 MM-DD，跨年带年份 */
export function conversationTimeLabel(item: GroupableConversation, now = new Date()): string {
  const time = conversationTime(item)
  if (!time) return ''
  const date = new Date(time)
  const day = startOfDay(now)
  const clock = `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
  if (time >= day) return clock
  if (time >= new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1).getTime()) return '昨天'
  const monthDay = `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
  return date.getFullYear() === now.getFullYear() ? monthDay : `${date.getFullYear()}-${monthDay}`
}

/** 按时间倒序分组；只返回非空组，保持 今天 → 昨天 → 更早 的顺序 */
export function groupConversations<T extends GroupableConversation>(
  items: readonly T[],
  now = new Date(),
): Array<ConversationGroup<T>> {
  const sorted = [...items].sort((a, b) => conversationTime(b) - conversationTime(a))
  const day = startOfDay(now)
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1).getTime()
  const buckets: Record<ConversationGroupKey, T[]> = { today: [], yesterday: [], earlier: [] }
  for (const item of sorted) {
    const time = conversationTime(item)
    if (time >= day) buckets.today.push(item)
    else if (time >= yesterday) buckets.yesterday.push(item)
    else buckets.earlier.push(item)
  }
  return (Object.keys(buckets) as ConversationGroupKey[])
    .filter((key) => buckets[key].length > 0)
    .map((key) => ({ key, label: GROUP_LABELS[key], items: buckets[key] }))
}

/* ============================================================
   结构分组：课程 → 整门课程 / 各篇笔记
   ============================================================ */

export type HistoryNoteGroup = {
  id: string
  title: string
  items: Conversation[]
}

export type HistorySection = {
  id: string
  kind: 'global' | 'course'
  title: string
  /** 副标题：跨课程 · n / n 段会话 */
  meta: string
  /** 整门课程范围的会话 */
  items: Conversation[]
  notes: HistoryNoteGroup[]
  latest: number
}

function conversationScope(item: Conversation): 'course' | 'global' | 'note' {
  if (item.scope === 'global' || item.scope === 'note') return item.scope
  /* 历史字段只有 course / material / page；后两者都属于"整门课程"这一档 */
  return item.default_scope === 'global' ? 'global' : 'course'
}

function latestOf(items: Conversation[]): number {
  return items.reduce((max, item) => Math.max(max, conversationTime(item)), 0)
}

function sortByRecent(items: Conversation[]): Conversation[] {
  return [...items].sort((a, b) => conversationTime(b) - conversationTime(a))
}

/**
 * 把会话按「全局 / 课程 → 整门课程 + 笔记」归组。
 *
 * 后端还没有 scope / note_id 时，所有会话都会落到默认课程的「整门课程」里，
 * 组件仍然按同一套结构渲染，等字段到位就自动亮出笔记与全局两层。
 */
export function buildHistory(
  conversations: readonly Conversation[],
  courses: readonly Course[],
): HistorySection[] {
  const courseNames = new Map(courses.map((course) => [course.id, course.name]))
  const globalItems: Conversation[] = []
  const courseBuckets = new Map<string, { items: Conversation[]; notes: Map<string, { title: string; items: Conversation[] }> }>()

  for (const item of conversations) {
    const scope = conversationScope(item)
    if (scope === 'global') {
      globalItems.push(item)
      continue
    }
    let bucket = courseBuckets.get(item.course_id)
    if (!bucket) {
      bucket = { items: [], notes: new Map() }
      courseBuckets.set(item.course_id, bucket)
    }
    if (scope === 'note' && item.note_id) {
      const note = bucket.notes.get(item.note_id) ?? { title: item.note_title ?? '未命名笔记', items: [] }
      note.items.push(item)
      bucket.notes.set(item.note_id, note)
    } else {
      bucket.items.push(item)
    }
  }

  const sections: HistorySection[] = []

  if (globalItems.length > 0) {
    const items = sortByRecent(globalItems)
    sections.push({
      id: 'global',
      kind: 'global',
      title: '全局可查',
      meta: `跨课程 · ${items.length}`,
      items,
      notes: [],
      latest: latestOf(items),
    })
  }

  for (const [courseId, bucket] of courseBuckets) {
    const items = sortByRecent(bucket.items)
    const notes = [...bucket.notes.entries()]
      .map(([id, note]) => ({ id, title: note.title, items: sortByRecent(note.items) }))
      .sort((a, b) => latestOf(b.items) - latestOf(a.items))
    const total = items.length + notes.reduce((sum, note) => sum + note.items.length, 0)
    sections.push({
      id: `course-${courseId}`,
      kind: 'course',
      title: courseNames.get(courseId) ?? '未命名课程',
      meta: `${total} 段会话`,
      items,
      notes,
      latest: Math.max(latestOf(items), ...notes.map((note) => latestOf(note.items)), 0),
    })
  }

  const globalSection = sections.find((section) => section.kind === 'global')
  const courseSections = sections
    .filter((section) => section.kind === 'course')
    .sort((a, b) => b.latest - a.latest)

  return globalSection ? [globalSection, ...courseSections] : courseSections
}
