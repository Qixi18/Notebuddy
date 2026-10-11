import { memo } from 'react'
import { curveCatmullRom, line } from 'd3-shape'
import type { Notebook, NotebookSection } from '../../types'
import { hashId, treeLeaves, type TreePosition } from './layout'
import { stateLabels } from './types'

const branchLine = line<[number, number]>().curve(curveCatmullRom.alpha(0.65))
const leafPath = 'M0 0 C-17 -8 -26 -23 -9 -39 C7 -39 17 -20 0 0Z'
export const ForestTree = memo(function ForestTree({
  tree,
  book,
  focused,
  expanded,
  endpoints,
  onFocus,
  onOpen,
  search,
}: {
  tree: TreePosition
  book?: Notebook
  focused: boolean
  expanded: Set<string>
  endpoints: Set<string>
  onFocus: () => void
  onOpen: (section: NotebookSection) => void
  search: string
}) {
  const { course, x, y, seed } = tree
  const color =
    course.learning_state === 'completed'
      ? '#326047'
      : course.learning_state === 'learning'
        ? '#719565'
        : '#a1aea0'
  const light =
    course.learning_state === 'completed'
      ? '#95b497'
      : course.learning_state === 'learning'
        ? '#c1d0a7'
        : '#d0d7ca'
  const lean = (seed % 25) - 12
  const chapters = book
    ? [
        ...book.chapters,
        ...(book.historical_sections.length
          ? [{ id: 'history', title: '历史整理', sections: book.historical_sections }]
          : []),
      ]
    : []
  const leaves = book ? treeLeaves(book, focused ? expanded : undefined, endpoints) : []
  const branchCount = Math.max(8, Math.min(12, chapters.length))
  const matches =
    search &&
    (course.name.includes(search) || leaves.some((leaf) => leaf.section.title.includes(search)))
  return (
    <g
      transform={`translate(${x},${y})`}
      className={`forest-tree${focused ? ' forest-tree-focused' : ''}${matches ? ' forest-tree-match' : ''}`}
    >
      <ellipse cx="0" cy="8" rx="113" ry="14" fill="#516443" opacity=".055" />
      <g aria-hidden="true" className="forest-tree-paint">
        {Array.from({ length: 12 }, (_, i) => {
          const variation = hashId(`${course.course_id}:wash:${i}`)
          const px = (variation % 240) - 120
          const py = -290 - ((variation >>> 8) % 200)
          const radius = 55 + (variation % 39)
          return (
            <path
              key={i}
              d={`M${px - radius} ${py} C${px - radius - 8} ${py - radius * 0.8} ${px + 20} ${py - radius - 10} ${px + radius} ${py - 15} S${px + radius - 7} ${py + radius * 0.75} ${px} ${py + radius * 0.6} S${px - radius - 14} ${py + 40} ${px - radius} ${py}Z`}
              fill={i % 3 ? light : color}
              opacity={course.note_count ? 0.13 : 0.065}
            />
          )
        })}
        <path
          d={`M-21 2 C-8 -56 -31 -111 -18 -164 C-9 -197 -25 -232 -16 -263 C-10 -289 ${lean + 5} -312 ${lean + 10} -332 C${lean + 13} -308 -1 -279 -1 -261 C-3 -230 12 -207 8 -176 C0 -126 17 -67 22 2 C7 -5 -5 -5 -21 2Z`}
          fill="#b6a17e"
          stroke="#897654"
          strokeWidth="1.3"
          strokeLinejoin="round"
        />
        <path
          d={`M-7 -6 C3 -69 -18 -117 -5 -176 C5 -211 -10 -243 -3 -274 Q${lean + 9} -308 ${lean + 10} -330 M10 -12 C12 -69 1 -102 4 -134 M-15 -43 Q-20 -95 -14 -130`}
          fill="none"
          stroke="#806b4c"
          strokeWidth=".8"
          opacity=".55"
        />
        <path
          d={
            branchLine([
              [lean + 8, -317],
              [lean - 2, -365],
              [lean + 9, -414],
              [lean - 10, -474],
              [lean + 3, -521],
            ]) ?? ''
          }
          fill="none"
          stroke="#8e7b5a"
          strokeWidth="3.3"
          strokeLinecap="round"
        />
        <path
          d={
            branchLine([
              [lean + 2, -363],
              [-24, -391],
              [-38, -446],
              [-67, -472],
            ]) ?? ''
          }
          fill="none"
          stroke="#988664"
          strokeWidth="2.2"
          strokeLinecap="round"
        />
        {Array.from({ length: branchCount }, (_, index) => {
          const side = index % 2 ? 1 : -1
          const by = -175 - Math.floor(index / 2) * 46
          const endX = side * (140 + ((seed + index * 19) % 42))
          const endY = by - 81 - ((seed + index * 7) % 22)
          return (
            <g key={index}>
              <path
                d={
                  branchLine([
                    [index < 4 ? -6 : lean + 5, by],
                    [side * 33, by - 14],
                    [side * 76, by - 37],
                    [endX, endY],
                  ]) ?? ''
                }
                fill="none"
                stroke="#8e7a56"
                strokeWidth={Math.max(1.3, 5.8 - index * 0.39)}
                strokeLinecap="round"
              />
              <path
                d={
                  branchLine([
                    [side * 48, by - 24],
                    [side * 57, by - 58],
                    [side * 64, by - 90],
                  ]) ?? ''
                }
                fill="none"
                stroke="#9b8767"
                strokeWidth="1.7"
                strokeLinecap="round"
              />
              <path
                d={`M${endX - 8 * side} ${endY + 3} Q${endX + 8 * side} ${endY - 12} ${endX + 20 * side} ${endY - 24}`}
                fill="none"
                stroke={color}
                strokeWidth="1.5"
              />
              {focused && chapters[index] && (
                <text
                  className="forest-branch-label"
                  x={side * 38}
                  y={by - 9}
                  textAnchor={side < 0 ? 'end' : 'start'}
                >
                  {chapters[index].title.length > 13
                    ? `${chapters[index].title.slice(0, 13)}…`
                    : chapters[index].title}
                </text>
              )}
            </g>
          )
        })}
        {Array.from({ length: course.note_count ? 44 : 20 }, (_, index) => {
          const variation = hashId(`${course.course_id}:botanical:${index}`)
          const side = index % 2 ? 1 : -1
          const row = Math.floor(index / 2) % 6
          const px = side * (67 + (variation % 120))
          const py = -240 - row * 44 - ((variation >>> 7) % 36)
          const angle = side * (28 + (variation % 55))
          return (
            <g
              key={`decor-${index}`}
              transform={`translate(${px},${py}) rotate(${angle}) scale(${0.42 + (variation % 22) / 100})`}
              opacity={course.note_count ? 0.42 : 0.21}
            >
              <path d="M0 5Q-3-6-3-15" stroke={color} strokeWidth="1.2" fill="none" />
              <path d={leafPath} fill={index % 3 ? light : color} stroke={color} strokeWidth=".8" />
              <path d="M-1 -3Q-4-21-9-35" fill="none" stroke="#e6edd5" strokeWidth="1" />
            </g>
          )
        })}
        <path
          d="M-16 -4 Q-32 13 -54 15 M-10 -6 Q-21 18 -31 23 M17 -3 Q36 14 54 13 M12 -2 Q18 19 33 22"
          fill="none"
          stroke="#938165"
          strokeWidth="2.2"
          strokeLinecap="round"
        />
        <path
          d="M-76 5q-6-16-5-26m3 15 9-8m135 20q7-13 6-20m-3 10 8-3"
          fill="none"
          stroke="#93a17e"
          strokeWidth="1.6"
          strokeLinecap="round"
        />
      </g>
      {leaves.map((leaf) => (
        <g
          key={leaf.section.id}
          transform={`translate(${leaf.x},${leaf.y}) rotate(${leaf.angle})`}
          role="button"
          tabIndex={0}
          aria-label={`打开笔记：${leaf.section.title}`}
          data-forest-interactive="true"
          className={`forest-leaf${search && leaf.section.title.includes(search) ? ' forest-leaf-match' : ''}`}
          onClick={(event) => {
            event.stopPropagation()
            onOpen(leaf.section)
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              event.stopPropagation()
              onOpen(leaf.section)
            }
          }}
        >
          <title>
            {leaf.chapterTitle} · {leaf.section.title}
            {leaf.section.user_locked ? ' · 已编辑' : ''}
          </title>
          <path d="M0 4q-3-10-1-17" stroke="#7c8962" strokeWidth="1.1" fill="none" />
          <path
            className="forest-leaf-body"
            d={leafPath}
            fill={color}
            stroke="#51694d"
            strokeWidth=".75"
          />
          <path
            d="M-1 -3Q-4-21-9-35M-5-15l10-8m-12 1-8-5"
            fill="none"
            stroke={light}
            strokeWidth=".85"
            opacity=".8"
          />
        </g>
      ))}
      <g
        role="button"
        tabIndex={0}
        data-forest-interactive="true"
        className="forest-course-label"
        aria-label={`聚焦课程：${course.name}`}
        onClick={onFocus}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            onFocus()
          }
        }}
      >
        <rect x="-173" y="27" width="346" height="68" rx="12" fill="#fcfcf5" opacity=".88" />
        <text y="54" textAnchor="middle" className="forest-course-name">
          {course.name.length > 18 ? `${course.name.slice(0, 18)}…` : course.name}
        </text>
        <text y="77" textAnchor="middle" className="forest-course-meta">
          {stateLabels[course.learning_state]} ·{' '}
          {course.note_count ? `${course.note_count} 个笔记小节` : '等待第一讲'}
        </text>
      </g>
    </g>
  )
})
