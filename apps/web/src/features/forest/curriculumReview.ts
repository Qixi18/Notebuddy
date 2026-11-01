import type { CurriculumRow } from './types'

const normalize = (value: string) => value.trim().toLocaleLowerCase()
export function reviewCurriculum(rows: CurriculumRow[]) {
  const names = new Set<string>(), codes = new Set<string>(), mapped = new Set<string>()
  const errors: string[] = []
  let credits = 0, missingCredits = 0
  for (const row of rows) {
    const name = normalize(row.name), code = normalize(row.course_code ?? '')
    if (!name || row.name.length > 200) errors.push('课程名称不能为空或超过 200 字')
    if (names.has(name)) errors.push(`课程名称重复：${row.name}`)
    names.add(name)
    if (code && codes.has(code)) errors.push(`课程代码重复：${row.course_code}`)
    if (code) codes.add(code)
    if (row.existing_course_id) {
      if (mapped.has(row.existing_course_id)) errors.push('同一已有课程被多次关联')
      mapped.add(row.existing_course_id)
    }
    for (const [field, label, max] of [['credits', '学分', 100], ['hours', '学时', 10000], ['semester', '学期', 30]] as const) {
      const value = row[field]
      if (value != null && (!Number.isFinite(value) || value < (field === 'semester' ? 1 : 0) || value > max || (field === 'semester' && !Number.isInteger(value)))) errors.push(`${row.name}的${label}无效`)
    }
    if (row.credits == null) missingCredits++
    else credits += row.credits
  }
  return { errors: [...new Set(errors)], credits: Math.round(credits * 100) / 100, missingCredits }
}

const fields = { name: '名称', course_code: '课程代码', credits: '学分', hours: '学时', requirement: '必选修', semester: '学期', level: '层级', prerequisites: '先修课程' } as const
const value = (row: CurriculumRow, field: keyof typeof fields) => field === 'prerequisites' ? [...row.prerequisites].sort().join('|') : row[field] ?? (field === 'requirement' ? 'unspecified' : null)
export function compareCurriculum(rows: CurriculumRow[], previous: CurriculumRow[]) {
  const matched = new Set<CurriculumRow>()
  const changed: { row: CurriculumRow; fields: string[] }[] = [], added: CurriculumRow[] = []
  for (const row of rows) {
    let old: CurriculumRow | undefined
    for (const field of ['existing_course_id', 'course_code', 'name'] as const) {
      const key = row[field] && normalize(row[field])
      if (!key) continue
      const candidates = previous.filter(item => !matched.has(item) && item[field] && normalize(item[field]) === key)
      if (candidates.length === 1) { old = candidates[0]; break }
    }
    if (!old) { added.push(row); continue }
    matched.add(old)
    const changes = (Object.keys(fields) as (keyof typeof fields)[]).filter(field => value(row, field) !== value(old, field)).map(field => fields[field])
    if (changes.length) changed.push({ row, fields: changes })
  }
  return { added, changed, omitted: previous.filter(row => !matched.has(row)) }
}
