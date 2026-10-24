import { ForestDialog } from './ForestDialog'
import { stateLabels, type ForestCourse } from './types'
import { HOME_COURSE_LIMIT } from '../workspace/homeCourses'

export function HomeCoursesDialog({ courses, busyCourseId, error, onToggle, onClose }: {
  courses: ForestCourse[]; busyCourseId?: string; error?: string
  onToggle: (course: ForestCourse) => void; onClose: () => void
}) {
  const count = courses.filter(course => course.learning_state === 'learning').length
  const sorted = [...courses].sort((a, b) => Number(b.learning_state === 'learning') - Number(a.learning_state === 'learning') || a.position - b.position)
  return <ForestDialog title="选择首页课程" onClose={onClose}>
    <p className="forest-dialog-intro">首页正在学 {count}/{HOME_COURSE_LIMIT}。放到首页即设为正在学；移出后设为未开始，笔记、资料和阅读进度都保留。</p>
    {count >= HOME_COURSE_LIMIT && <p className="forest-home-limit">首页已满，先移出一门课程即可更换。</p>}
    {error && <p className="forest-error" role="alert">{error}</p>}
    <div className="forest-home-course-list">{sorted.map(course => {
      const active = course.learning_state === 'learning'
      return <div key={course.course_id} className={`forest-home-course-row${active ? ' is-on-home' : ''}`}>
        <div><strong>{course.name}</strong><small>{active ? '正在学 · 已在首页' : stateLabels[course.learning_state]}</small></div>
        <button type="button" className={active ? '' : 'forest-action'} disabled={Boolean(busyCourseId) || (!active && count >= HOME_COURSE_LIMIT)} aria-label={`${active ? '移出首页' : '放到首页'}：${course.name}`} onClick={() => onToggle(course)}>{busyCourseId === course.course_id ? '保存中…' : active ? '移出首页' : '放到首页'}</button>
      </div>
    })}</div>
    {!courses.length && <p>创建课程后，就可以选择首页的树了。</p>}
  </ForestDialog>
}
