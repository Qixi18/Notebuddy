import { useId } from 'react'

import { teacherPersonaMeta } from '../features/persona/personas'

export type TeacherStatus = 'idle' | 'thinking' | 'explaining' | 'error'
export type TeacherCharacterId = 'elf' | 'doubao' | 'feiyu'

const statusLabels: Record<TeacherStatus, string> = {
  idle: 'AI 教师',
  thinking: '正在思考…',
  explaining: '正在讲解',
  error: '暂时遇到问题',
}

/* 四态静态立绘目前只有莉艾尔一套 */
const statusAssets: Record<TeacherStatus, string> = {
  idle: '/assets/teacher/teacher-idle.png',
  thinking: '/assets/teacher/teacher-thinking.png',
  explaining: '/assets/teacher/teacher-explaining.png',
  error: '/assets/teacher/teacher-error.png',
}

/* 莉艾尔有四态静态立绘；豆包与肥鱼是精灵图交付，没有静态立绘。
   非首页(答疑页头像、悬浮答疑坞)改用待机雪碧图的首帧，
   这样切换老师时画面跟着换，而不再是三个人共用莉艾尔的脸。 */
const STATUS_ART_CHARACTER: TeacherCharacterId = 'elf'

/* 特效坐标全部使用立绘源图像素(1024×1536),与 SVG viewBox 一一对应,
   因此舞台层无论以哪种断点尺寸显示,特效都能对准立绘的同一位置 */
const sparkleSeeds = [
  { x: 150, y: 300, r: 15, delay: 0 },
  { x: 305, y: 168, r: 10, delay: -1.1 },
  { x: 92, y: 565, r: 12, delay: -2.2 },
  { x: 872, y: 150, r: 13, delay: -0.6 },
  { x: 962, y: 360, r: 9, delay: -1.7 },
  { x: 772, y: 92, r: 8, delay: -2.6 },
  { x: 128, y: 1205, r: 11, delay: -0.9 },
  { x: 938, y: 1075, r: 9, delay: -2.0 },
]

const bubbleSeeds = [
  { x: 700, y: 195, r: 30, delay: 0 },
  { x: 792, y: 150, r: 38, delay: -1.15 },
  { x: 852, y: 215, r: 24, delay: -2.3 },
]

/* 四角星光:两条过中心的二次贝塞尔构成凹边菱形 */
function sparklePath(cx: number, cy: number, r: number) {
  return [
    `M ${cx} ${cy - r}`,
    `Q ${cx} ${cy} ${cx + r} ${cy}`,
    `Q ${cx} ${cy} ${cx} ${cy + r}`,
    `Q ${cx} ${cy} ${cx - r} ${cy}`,
    `Q ${cx} ${cy} ${cx} ${cy - r} Z`,
  ].join(' ')
}

export function TeacherCharacter({ status = 'idle', compact = false, animated = false, character = 'elf' }: {
  status?: TeacherStatus
  compact?: boolean
  animated?: boolean
  character?: TeacherCharacterId
}) {
  const rawId = useId()
  const gradientId = `tfx-glow-${rawId.replace(/[^a-zA-Z0-9]/g, '')}`
  /* animated 表示"这一处用连续帧动画呈现"：首页待机与侧边答疑坞都走动画雪碧图，
     因此没有状态帧的老师(豆包/肥鱼)也不会退化成静帧；只有出错态才回落到静态立绘 */
  const useAnimatedSprite = animated && status !== 'error'
  const useStaticSprite = !useAnimatedSprite && character !== STATUS_ART_CHARACTER
  const useSprite = useAnimatedSprite || useStaticSprite
  const idleLabel = teacherPersonaMeta(character).name

  return (
    <div className={`teacher-character teacher-character-${status}${compact ? ' teacher-character-compact' : ''}`} role="img" aria-label={`NoteBuddy AI 教师：${status === 'idle' ? idleLabel : statusLabels[status]}`}>
      <div className="teacher-character-halo" aria-hidden="true" />
      <div className="teacher-character-stage" aria-hidden="true">
        {useSprite ? (
          <div className={`teacher-character-sprite teacher-character-sprite-${character}${useStaticSprite ? ' teacher-character-sprite-static' : ''}`} />
        ) : (
          <img className="teacher-character-image" src={statusAssets[status]} alt="" loading="lazy" decoding="async" />
        )}
        <svg className="teacher-character-fx" viewBox="0 0 1024 1536" preserveAspectRatio="xMidYMax meet" focusable="false">
          {status !== 'error' && !useAnimatedSprite &&
            sparkleSeeds.map((seed, index) => (
              <path
                key={index}
                className="tfx-sparkle"
                d={sparklePath(seed.x, seed.y, seed.r)}
                fill="#d7ecfb"
                style={{ animationDelay: `${seed.delay}s` }}
              />
            ))}
          {status === 'thinking' &&
            bubbleSeeds.map((seed, index) => (
              <g key={index} className="tfx-bubble" style={{ animationDelay: `${seed.delay}s` }}>
                <circle cx={seed.x} cy={seed.y} r={seed.r} fill="rgba(255,255,255,.93)" stroke="#bcd9ef" strokeWidth={3} />
                <text className="tfx-bubble-mark" x={seed.x} y={seed.y + seed.r * 0.42} textAnchor="middle" fontSize={seed.r * 1.25}>
                  ?
                </text>
              </g>
            ))}
          {status === 'explaining' && (
            <g className="tfx-orb">
              <defs>
                <radialGradient id={gradientId}>
                  <stop offset="0%" stopColor="rgba(255,255,255,.95)" />
                  <stop offset="45%" stopColor="rgba(193,223,248,.55)" />
                  <stop offset="100%" stopColor="rgba(193,223,248,0)" />
                </radialGradient>
              </defs>
              <circle className="tfx-orb-halo" cx={795} cy={195} r={110} fill={`url(#${gradientId})`} />
              <circle className="tfx-orb-ring" cx={795} cy={195} r={72} />
              <circle className="tfx-orb-ring tfx-orb-ring-slow" cx={795} cy={195} r={112} />
              <g className="tfx-orbit">
                <circle cx={795} cy={83} r={10} fill="#ffffff" opacity={0.95} />
                <circle cx={903} cy={251} r={7} fill="#dceefb" />
                <circle cx={687} cy={251} r={8} fill="#eaf5fd" />
              </g>
            </g>
          )}
          {status === 'error' && (
            <g className="tfx-warn">
              <circle cx={700} cy={185} r={38} fill="#fff4ef" stroke="#e2a58c" strokeWidth={3.5} />
              <text className="tfx-warn-mark" x={700} y={203} textAnchor="middle">
                !
              </text>
            </g>
          )}
        </svg>
      </div>
      <span className="teacher-character-label" aria-live="polite">{status === 'idle' ? idleLabel : statusLabels[status]}</span>
    </div>
  )
}
