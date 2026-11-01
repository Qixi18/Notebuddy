import { expect, test } from 'vitest'
import { compareCurriculum, reviewCurriculum } from '../src/features/forest/curriculumReview'
import type { CurriculumRow } from '../src/features/forest/types'

const row: CurriculumRow = { key: 'a', name: '高等数学', semester: 1, level: 'foundation',
  prerequisites: [], source_label: '第 1 页', source_excerpt: '原文', existing_course_id: null,
  course_code: 'M01', credits: 4, hours: 64, requirement: 'required' }

test('review totals known credits while flagging conflicting codes and missing credits', () => {
  const review = reviewCurriculum([row, { ...row, key: 'b', name: '英语', course_code: 'm01', credits: null }])
  expect(review.credits).toBe(4)
  expect(review.missingCredits).toBe(1)
  expect(review.errors).toContain('课程代码重复：m01')
})

test('comparison uses course codes, exposes changed fields and never treats omissions as deletions', () => {
  const compared = compareCurriculum([{ ...row, name: '高等数学 I', credits: 5 }], [row, { ...row, key: 'b', name: '英语', course_code: 'E01' }])
  expect(compared.added).toHaveLength(0)
  expect(compared.changed[0].fields).toContain('学分')
  expect(compared.changed[0].fields).toContain('名称')
  expect(compared.omitted.map(item => item.name)).toEqual(['英语'])
})

test('legacy rows and code corrections match their existing course before classifying changes', () => {
  const before = { ...row, course_code: null, existing_course_id: 'course-1' }
  const compared = compareCurriculum([{ ...row, existing_course_id: 'course-1' }], [before])
  expect(compared.added).toHaveLength(0)
  expect(compared.omitted).toHaveLength(0)
  expect(compared.changed[0].fields).toEqual(['课程代码'])
})
