import { useEffect, useRef, useState, type ComponentProps } from 'react'
import type { WatercolorTree } from './WatercolorTree'
import type { CourseCanopy as CanopyGeometry } from './courseCanopyGeometry'
import { CourseCanopy, type LeafPreview } from './CourseCanopy'
import { TreeAction } from './TreeAction'
import { detailInteraction, operationSize } from './treeInteraction'
import { HomeNotePreview } from '../home/HomeNotePreview'
import { FOREST_ROOT_CAPTION_Y } from './forestGroveLayout'

export function ForestBotanicalTree({ tree, canopy, branches, zoom, growingBooks, growingNotes, pins, search, onRoot, onNotebook, onNote, onExpandBooks, onFocus, onReveal, viewKey, onToggleHome, homeBusy }: ComponentProps<typeof WatercolorTree> & { canopy: CanopyGeometry; viewKey: string; onToggleHome?: () => void; homeBusy?: boolean }) {
  const [preview, setPreview] = useState<LeafPreview>()
  const hideTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const keep = () => clearTimeout(hideTimer.current)
  const dismiss = () => { keep(); setPreview(undefined) }
  const leave = () => { keep(); hideTimer.current = setTimeout(() => setPreview(undefined), 180) }
  useEffect(() => () => clearTimeout(hideTimer.current), [])
  useEffect(() => { setPreview(undefined) }, [viewKey])
  const { course } = tree
  const previewId = `forest-preview-${course.course_id}`
  const detail = detailInteraction(zoom)
  const size = detail ? operationSize(zoom) : 44
  const captionActive = detail || zoom >= .3
  const titleSize = Math.max(17, Math.min(30, 14 / zoom, 520 / Math.max(1, course.name.length)))
  const titleGlyphs = Array.from(course.name)
  const titleLimit = Math.floor(260 / titleSize)
  const displayName = titleGlyphs.length > titleLimit ? `${titleGlyphs.slice(0, titleLimit - 1).join('')}…` : course.name
  const titleWidth = Math.min(580, Math.max(360, titleSize * Math.min(titleGlyphs.length, titleLimit) / .46, captionActive ? operationSize(zoom) : 44))
  const titleHitHeight = Math.max(70, captionActive ? operationSize(zoom) : 44)
  const actionsY = titleHitHeight - 30 + size / 2 + 12
  const highlighted = new Set([...pins, ...canopy.items.flatMap(item => item.leaves.filter(leaf => search && leaf.section.title.toLocaleLowerCase().includes(search.toLocaleLowerCase())).map(leaf => leaf.section.id))])
  return <g transform={`translate(${tree.x},${tree.y})`} className={`kt-tree kt-forest-botanical kt-tree-${course.learning_state}`} data-course-id={course.course_id}>
    <CourseCanopy canopy={canopy} empty={!branches.length} forest zoom={zoom} growingBooks={growingBooks} growingNotes={growingNotes} highlighted={highlighted} previewId={previewId} previewNoteId={preview?.leaf.section.id}
      onPreview={next => { keep(); setPreview(next); if (document.activeElement?.contains(next.target)) onReveal(next.leaf) }} onLeave={leave} onNotebook={onNotebook} onNote={onNote} />
    <g className="kt-forest-course-info" transform={`translate(0,${(tree.captionY ?? tree.y + FOREST_ROOT_CAPTION_Y) - tree.y})`}>
    <TreeAction disabled={!captionActive} label={`${detail ? '课程菜单' : '聚焦课程'}：${course.name}`} onActivate={detail ? onRoot : onFocus} onFocus={detail ? onFocus : undefined} className="kt-root">
      <title>{course.name} · 新建或扩充笔记本</title>
      <image className="kt-course-stone" href={`/assets/forest/course-garden-stone-${tree.seed % 2 ? 'b' : 'a'}.png`} x={-titleWidth / 2} y={-titleHitHeight * .6} width={titleWidth} height={titleHitHeight * 1.2} preserveAspectRatio="none" pointerEvents="none" aria-hidden="true" />
      <rect x={-titleWidth / 2} y={-titleHitHeight * .6} width={titleWidth} height={titleHitHeight * 1.2} fill="transparent" />
      <text y="0" textAnchor="middle" className="kt-course-title" style={{ fontSize: titleSize, fontWeight: 700 }}>{displayName}</text>
      {detail && <path d="M-5 28H5M0 23V33" fill="none" stroke="#71825c" strokeWidth="1.5" />}
    </TreeAction>
    {detail && onToggleHome && <TreeAction disabled={homeBusy} label={`${course.learning_state === 'learning' ? '移出首页' : '放到首页'}：${course.name}`} onActivate={onToggleHome} transform={`translate(-56,${actionsY})`} className="kt-home-course-action">
      <title>{course.learning_state === 'learning' ? '移出首页并设为未开始，保留笔记和阅读进度' : '放到首页并设为正在学，最多三棵树'}</title>
      <circle r="18" fill={course.learning_state === 'learning' ? '#365a40' : '#faf9f0'} stroke="#8d9c78" />
      <path d="M-10-1 0-9 10-1M-8-2V9H8V-2M-3 9V2H3V9" fill="none" stroke={course.learning_state === 'learning' ? '#f7f5ea' : '#526a46'} strokeWidth="1.7" strokeLinejoin="round" strokeLinecap="round" />
      <rect x={-size / 2} y={-size / 2} width={size} height={size} fill="transparent" />
    </TreeAction>}
    {detail && branches.length > 0 && <TreeAction label={branches.length > 6 ? `展开${course.name}的全部${branches.length}本笔记本` : `查看${course.name}的完整目录`} onActivate={onExpandBooks} className="kt-course-directory" transform={`translate(56,${actionsY})`}>
      <title>查看全部笔记本和知识点</title>
      <circle r="18" fill="#faf9f0" stroke="#b8bda0" />
      <path d="M-9-6Q-5-9 0-6Q5-9 9-6V7Q4 4 0 7Q-5 4-9 7ZM0-6V7" fill="none" stroke="#526a46" strokeWidth="1.5" />
      <rect x={-size / 2} y={-size / 2} width={size} height={size} fill="transparent" />
    </TreeAction>}
    </g>
    {preview && <HomeNotePreview id={previewId} preview={preview} courseId={course.course_id} onEnter={keep} onLeave={leave} onDismiss={dismiss} />}
  </g>
}
