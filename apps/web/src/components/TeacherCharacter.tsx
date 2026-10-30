import { teacherPersonaMeta } from '../features/persona/personas'

export type TeacherStatus = 'idle' | 'thinking' | 'explaining' | 'error'

const statusLabels: Record<TeacherStatus, string> = {
  idle: 'AI 教师',
  thinking: '正在思考…',
  explaining: '正在讲解',
  error: '暂时遇到问题',
}

/**
 * 桌宠 / 教师形象：全站只保留沃雅妮莎一个形象。
 * 待机、思考、讲解、出错、行礼等动作由 /assets/pet/*.webp 提供，
 * 播放哪一段由 features/pet/usePetAction 决定，本组件只负责渲染。
 */
export function TeacherCharacter({ status = 'idle', compact = false, pet = false, src = '/assets/pet/idle.webp' }: {
  status?: TeacherStatus
  compact?: boolean
  /** 桌面宠模式：额外的尺寸与贴边适配（命中层由父容器负责）。 */
  pet?: boolean
  /** 当前动作的动画 webp；默认待机 */
  src?: string
}) {
  const name = teacherPersonaMeta().name
  const label = status === 'idle' ? name : statusLabels[status]

  return (
    <div
      className={`teacher-character${compact ? ' teacher-character-compact' : ''}${pet ? ' teacher-character-pet' : ''}`}
      role="img"
      aria-label={pet ? `NoteBuddy 桌宠：${name}` : `NoteBuddy AI 教师：${label}`}
    >
      <div className="teacher-character-stage" aria-hidden="true">
        <img
          className="teacher-character-image"
          src={src}
          alt=""
          loading="lazy"
          decoding="async"
          draggable={false}
        />
      </div>
    </div>
  )
}
