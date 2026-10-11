import type { TeacherCharacterId } from '../../components/TeacherCharacter'

export type TeacherPersonaMeta = {
  id: TeacherCharacterId
  /** 角色真名，与后端 app/ai/personas.py 中的字典保持一致 */
  name: string
  title: string
  style: string
  /** 进入会话时该老师的开场白，随人设切换 */
  greeting: string
}

export const TEACHER_PERSONAS: Record<TeacherCharacterId, TeacherPersonaMeta> = {
  elf: {
    id: 'elf',
    name: '莉艾尔',
    title: '白发精灵学者',
    style: '知性温柔学术型',
    greeting: '你好，我是莉艾尔。我会先在当前课程已解析的页面中寻找依据，再陪你一步步把原理梳理清楚。',
  },
  doubao: {
    id: 'doubao',
    name: '豆包',
    title: '黑红哥特洛丽塔',
    style: '甜酷傲娇干练型',
    greeting: '来了？我是豆包。直说问题就好——重点、考点、难点，我会帮你挑出来讲清楚。',
  },
  feiyu: {
    id: 'feiyu',
    name: '肥鱼',
    title: '蓝发鲸娘女仆',
    style: '元气治愈陪伴型',
    greeting: '你好呀，我是肥鱼！我们会先从当前课程的页面里找答案，慢慢来，没弄懂的地方我陪你反复过～',
  },
}

/** 首页 ⇄ 按钮的轮换顺序，三个形象循环切换 */
export const TEACHER_PERSONA_ORDER: readonly TeacherCharacterId[] = ['elf', 'doubao', 'feiyu']

export const DEFAULT_TEACHER_PERSONA: TeacherCharacterId = 'elf'

export function teacherPersonaMeta(id: TeacherCharacterId | undefined): TeacherPersonaMeta {
  return TEACHER_PERSONAS[id ?? DEFAULT_TEACHER_PERSONA] ?? TEACHER_PERSONAS[DEFAULT_TEACHER_PERSONA]
}
