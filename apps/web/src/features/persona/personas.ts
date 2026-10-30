export type TeacherPersonaMeta = {
  id: 'vodyanitsa'
  /** 角色真名，与后端 app/ai/personas.py 中的字典保持一致 */
  name: string
  title: string
  style: string
  /** 进入会话时该老师的开场白 */
  greeting: string
}

/** 全站唯一的教师形象：沃雅妮莎（至冬水妖 / 剧团女高音）。 */
export const TEACHER_PERSONA: TeacherPersonaMeta = {
  id: 'vodyanitsa',
  name: '沃雅妮莎',
  title: '至冬水妖 · 剧团女高音',
  style: '温柔细腻，擅长用旋律、节奏与呼吸作类比',
  greeting: '你好，我是沃雅妮莎。先在你手头的课程资料里找依据，再陪你一点点把这段弄清楚。♪',
}

export function teacherPersonaMeta(): TeacherPersonaMeta {
  return TEACHER_PERSONA
}
