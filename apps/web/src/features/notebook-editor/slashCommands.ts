import type { Editor } from '@tiptap/react'

export type SlashContext = {
  pickImage: () => void
  insertMath: (block: boolean) => void
  insertTable: () => void
}

export type SlashCommand = {
  id: string
  label: string
  hint: string
  icon: string
  aliases: string[]
  group: '基础' | '列表' | '学习' | '媒体' | '其他'
  run: (editor: Editor, context: SlashContext) => void
}

export const SLASH_COMMANDS: SlashCommand[] = [
  {
    id: 'paragraph', label: '正文', hint: '普通文本段落', icon: '¶', aliases: ['text', 'p', '正文'], group: '基础',
    run: (editor) => editor.chain().focus().setParagraph().run(),
  },
  {
    id: 'heading-1', label: '一级标题', hint: '章节标题', icon: 'H1', aliases: ['h1', '标题', 'chapter'], group: '基础',
    run: (editor) => editor.chain().focus().toggleHeading({ level: 1 }).run(),
  },
  {
    id: 'heading-2', label: '二级标题', hint: '小节标题', icon: 'H2', aliases: ['h2', '小标题'], group: '基础',
    run: (editor) => editor.chain().focus().toggleHeading({ level: 2 }).run(),
  },
  {
    id: 'heading-3', label: '三级标题', hint: '更细的层级', icon: 'H3', aliases: ['h3'], group: '基础',
    run: (editor) => editor.chain().focus().toggleHeading({ level: 3 }).run(),
  },
  {
    id: 'bullet', label: '项目符号', hint: '无序列表', icon: '•', aliases: ['list', 'bullet', 'ul'], group: '列表',
    run: (editor) => editor.chain().focus().toggleBulletList().run(),
  },
  {
    id: 'ordered', label: '有序列表', hint: '按顺序编号', icon: '1.', aliases: ['ordered', 'ol'], group: '列表',
    run: (editor) => editor.chain().focus().toggleOrderedList().run(),
  },
  {
    id: 'task', label: '待办', hint: '可勾选的任务', icon: '☑', aliases: ['todo', 'task', 'check'], group: '列表',
    run: (editor) => editor.chain().focus().toggleTaskList().run(),
  },
  {
    id: 'callout', label: '重点提示', hint: '突出关键结论', icon: '✦', aliases: ['tip', 'callout', '重点'], group: '学习',
    run: (editor) => editor.chain().focus().setCallout({ tone: 'tip', title: '重点提示' }).run(),
  },
  {
    id: 'example', label: '例题', hint: '带标题的例题块', icon: '✎', aliases: ['example', '例题'], group: '学习',
    run: (editor) => editor.chain().focus().setExample({ title: '例题' }).run(),
  },
  {
    id: 'inline-math', label: '行内公式', hint: '在文字中插入 LaTeX', icon: '∑', aliases: ['math', 'latex', '公式'], group: '学习',
    run: (editor, context) => context.insertMath(false),
  },
  {
    id: 'block-math', label: '公式块', hint: '独立的公式段落', icon: '∫', aliases: ['mathblock', '块公式'], group: '学习',
    run: (editor, context) => context.insertMath(true),
  },
  {
    id: 'table', label: '表格', hint: '插入 3×3 表格', icon: '▦', aliases: ['table', '表格'], group: '媒体',
    run: (editor, context) => context.insertTable(),
  },
  {
    id: 'image', label: '图片', hint: '上传笔记附件', icon: '▧', aliases: ['image', 'img', '图片'], group: '媒体',
    run: (editor, context) => context.pickImage(),
  },
  {
    id: 'quote', label: '引用', hint: '引用一段资料', icon: '❝', aliases: ['quote', 'blockquote'], group: '其他',
    run: (editor) => editor.chain().focus().toggleBlockquote().run(),
  },
  {
    id: 'code', label: '代码块', hint: '等宽代码区域', icon: '</>', aliases: ['code', '代码'], group: '其他',
    run: (editor) => editor.chain().focus().toggleCodeBlock().run(),
  },
  {
    id: 'divider', label: '分割线', hint: '分隔内容', icon: '—', aliases: ['hr', 'divider'], group: '其他',
    run: (editor) => editor.chain().focus().setHorizontalRule().run(),
  },
]

export function filterSlashCommands(query: string): SlashCommand[] {
  const value = query.trim().toLowerCase()
  if (!value) return SLASH_COMMANDS
  return SLASH_COMMANDS.filter((command) =>
    command.label.toLowerCase().includes(value)
    || command.id.includes(value)
    || command.aliases.some((alias) => alias.toLowerCase().includes(value)),
  )
}
