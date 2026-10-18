/**
 * 笔记建议的行级 diff（LCS）与变更块分组：纯函数、零依赖，node:test 可直测。
 *
 * 交互语义：每个变更块（hunk）可独立勾选；跳过某块 = 该区域保持原文
 * （removed 行保留、added 行丢弃），选中 = 应用该块的全部行。
 */

export type DiffRowType = 'same' | 'added' | 'removed'

export type DiffRow = {
  type: DiffRowType
  text: string
  /** 所属变更块 key；same 行没有 */
  hunk?: string
}

export type DiffHunk = { key: string; rows: DiffRow[] }

/** 超大笔记退化处理阈值：超过则不做逐行对齐，整篇按"全删全增"展示 */
const MAX_CELLS = 1_000_000

export function diffRows(current: string, proposed: string): DiffRow[] {
  const a = current.length ? current.split('\n') : []
  const b = proposed.length ? proposed.split('\n') : []
  if (a.length * b.length > MAX_CELLS) {
    return assignHunks([
      ...a.map((text) => ({ type: 'removed' as const, text })),
      ...b.map((text) => ({ type: 'added' as const, text })),
    ])
  }
  const width = b.length + 1
  const table = new Int32Array((a.length + 1) * width)
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      table[i * width + j] = a[i] === b[j]
        ? table[(i + 1) * width + (j + 1)] + 1
        : Math.max(table[(i + 1) * width + j], table[i * width + (j + 1)])
    }
  }
  const rows: Array<Omit<DiffRow, 'hunk'>> = []
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      rows.push({ type: 'same', text: a[i] })
      i += 1
      j += 1
    } else if (table[(i + 1) * width + j] >= table[i * width + (j + 1)]) {
      rows.push({ type: 'removed', text: a[i] })
      i += 1
    } else {
      rows.push({ type: 'added', text: b[j] })
      j += 1
    }
  }
  while (i < a.length) {
    rows.push({ type: 'removed', text: a[i] })
    i += 1
  }
  while (j < b.length) {
    rows.push({ type: 'added', text: b[j] })
    j += 1
  }
  return assignHunks(rows)
}

/** 给相邻的非 same 行分配同一个变更块 key */
function assignHunks(rows: Array<Omit<DiffRow, 'hunk'>>): DiffRow[] {
  const out: DiffRow[] = []
  let current: string | null = null
  let count = 0
  for (const row of rows) {
    if (row.type === 'same') {
      current = null
      out.push({ type: row.type, text: row.text })
      continue
    }
    if (!current) {
      current = `h${count}`
      count += 1
    }
    out.push({ type: row.type, text: row.text, hunk: current })
  }
  return out
}

/** 按出现顺序提取变更块 */
export function hunksOf(rows: DiffRow[]): DiffHunk[] {
  const hunks: DiffHunk[] = []
  const byKey = new Map<string, DiffHunk>()
  for (const row of rows) {
    if (!row.hunk) continue
    let hunk = byKey.get(row.hunk)
    if (!hunk) {
      hunk = { key: row.hunk, rows: [] }
      byKey.set(row.hunk, hunk)
      hunks.push(hunk)
    }
    hunk.rows.push(row)
  }
  return hunks
}

/** 把选中块应用到原文。
 * 同一变更块内 removed（旧文本）与 added（新文本）互为替代：
 * 选中 → 取 added 行；跳过 → 保留 removed 行；same 行始终保留。 */
export function applySelected(rows: DiffRow[], selectedKeys: Set<string>): string {
  const out: string[] = []
  for (const row of rows) {
    if (row.type === 'same') {
      out.push(row.text)
    } else if (row.hunk && selectedKeys.has(row.hunk)) {
      if (row.type === 'added') out.push(row.text)
    } else if (row.type === 'removed') {
      out.push(row.text)
    }
  }
  return out.join('\n')
}
