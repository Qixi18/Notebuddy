import {
  forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState,
  type ChangeEvent,
} from 'react'
import { EditorContent, useEditor, type Editor } from '@tiptap/react'
import { BubbleMenu } from '@tiptap/react/menus'
import type { JSONContent } from '@tiptap/core'
import { DragHandle } from '@tiptap/extension-drag-handle-react'
import { filterSlashCommands, type SlashCommand, type SlashContext } from './slashCommands'
import { SlashCommandMenu } from './SlashCommandMenu'
import { buildExtensions } from './extensions'
import { markdownToNodes, newBlockId, type DocNode } from './document'

export type AIAction = 'explain' | 'summarize' | 'expand' | 'example'

export type SelectionAnchor = { from: number; to: number; text: string }

export type NotebookEditorHandle = {
  editor: Editor | null
  getContent: () => DocNode
  replaceContent: (doc: DocNode) => void
  focusBlock: (blockId: string) => void
  getSelection: () => SelectionAnchor | null
  insertMarkdown: (text: string, position?: number) => void
  replaceRange: (text: string, from: number, to: number) => boolean
  undo: () => void
  redo: () => void
  focus: () => void
}

type SlashState = {
  query: string
  from: number
  to: number
  left: number
  top: number
  index: number
}

type BlockMenuState = { pos: number; size: number; left: number; top: number }

export const NotebookEditor = forwardRef<NotebookEditorHandle, {
  initialContent: DocNode
  editable?: boolean
  onChange: (doc: DocNode) => void
  onSelectionChange?: (selection: SelectionAnchor | null) => void
  onRequestAI?: (action: AIAction, text: string) => void
  onUploadImage: (file: File) => Promise<{ src: string; attachmentId?: string; assetId?: string } | null>
  onSaveShortcut?: () => void
  onReady?: (editor: Editor) => void
}>(function NotebookEditor({
  initialContent, editable = true, onChange, onSelectionChange, onRequestAI,
  onUploadImage, onSaveShortcut, onReady,
}, ref) {
  const callbacks = useRef({ onChange, onSelectionChange, onRequestAI, onSaveShortcut, onReady, onUploadImage })
  callbacks.current = { onChange, onSelectionChange, onRequestAI, onSaveShortcut, onReady, onUploadImage }

  const [slash, setSlash] = useState<SlashState | null>(null)
  const slashRef = useRef<SlashState | null>(null)
  slashRef.current = slash
  const items = slash ? filterSlashCommands(slash.query) : []
  const itemsRef = useRef<SlashCommand[]>(items)
  itemsRef.current = items

  const [blockMenu, setBlockMenu] = useState<BlockMenuState | null>(null)
  const [activeNode, setActiveNode] = useState<{ pos: number; size: number } | null>(null)
  const [tableActive, setTableActive] = useState(false)
  const [math, setMath] = useState<{ block: boolean; latex: string } | null>(null)
  const [aiOpen, setAiOpen] = useState(false)
  const [imageInsertError, setImageInsertError] = useState<string>()
  const [selectionTick, setSelectionTick] = useState(0)
  const fileInput = useRef<HTMLInputElement>(null)
  const pendingImage = useRef<{ from: number; doc: Editor['state']['doc'] } | null>(null)

  const editor = useEditor({
    extensions: buildExtensions(),
    content: initialContent as JSONContent,
    editable,
    immediatelyRender: false,
    editorProps: {
      attributes: {
        class: 'nb-prosemirror',
        spellcheck: 'true',
        'aria-label': '笔记正文编辑器',
      },
      handleKeyDown: (_view, event) => {
        const current = slashRef.current
        if (current) {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault()
            const length = itemsRef.current.length
            if (!length) return true
            const delta = event.key === 'ArrowDown' ? 1 : -1
            setSlash((state) => state ? { ...state, index: (state.index + delta + length) % length } : state)
            return true
          }
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            const command = itemsRef.current[current.index]
            if (command) runSlashRef.current(command)
            return true
          }
          if (event.key === 'Escape') {
            event.preventDefault()
            closeSlash()
            return true
          }
        }
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
          event.preventDefault()
          callbacks.current.onSaveShortcut?.()
          return true
        }
        return false
      },
    },
    onUpdate: ({ editor: instance }) => {
      callbacks.current.onChange(instance.getJSON() as DocNode)
      updateSlash(instance)
    },
    onSelectionUpdate: ({ editor: instance }) => {
      updateSlash(instance)
      setTableActive(instance.isActive('table'))
      const { from, to, empty } = instance.state.selection
      if (empty) callbacks.current.onSelectionChange?.(null)
      else callbacks.current.onSelectionChange?.({
        from, to, text: instance.state.doc.textBetween(from, to, '\n'),
      })
      setSelectionTick((value) => value + 1)
    },
  })

  const editorRef = useRef<Editor | null>(editor)
  editorRef.current = editor

  useEffect(() => {
    if (editor) callbacks.current.onReady?.(editor)
  }, [editor])

  useEffect(() => {
    if (!editor) return
    editor.setEditable(editable)
  }, [editable, editor])

  useEffect(() => {
    if (!blockMenu) return
    function close(event: PointerEvent) {
      const target = event.target as HTMLElement | null
      if (target?.closest('.nb-block-menu')) return
      setBlockMenu(null)
    }
    window.addEventListener('pointerdown', close)
    return () => window.removeEventListener('pointerdown', close)
  }, [blockMenu])

  function closeSlash() {
    setSlash(null)
  }

  function updateSlash(instance: Editor) {
    if (!instance.isEditable) { closeSlash(); return }
    const { from, to, empty, $from } = instance.state.selection
    if (!empty) { closeSlash(); return }
    if ($from.parent.type.name !== 'paragraph') { closeSlash(); return }
    const before = $from.parent.textBetween(0, $from.parentOffset, undefined, '\0')
    const match = /(?:^|\s)\/([^\s/]*)$/.exec(before)
    if (!match) { closeSlash(); return }
    const query = match[1]
    const start = from - query.length - 1
    const coords = instance.view.coordsAtPos(start)
    const left = Math.max(12, Math.min(coords.left, window.innerWidth - 336))
    const menuHeight = 420
    const top = coords.bottom + 8 + menuHeight > window.innerHeight
      ? Math.max(12, coords.top - menuHeight - 8)
      : coords.bottom + 8
    setSlash((state) => ({
      query,
      from: start,
      to,
      left,
      top,
      index: state && state.query === query ? Math.min(state.index, Math.max(0, filterSlashCommands(query).length - 1)) : 0,
    }))
  }

  const runSlash = useCallback((command: SlashCommand) => {
    const instance = editorRef.current
    const state = slashRef.current
    if (!instance || !state) return
    closeSlash()
    instance.chain().focus().deleteRange({ from: state.from, to: state.from + state.query.length + 1 }).run()
    const context: SlashContext = {
      pickImage: () => {
        pendingImage.current = { from: instance.state.selection.from, doc: instance.state.doc }
        setImageInsertError(undefined)
        fileInput.current?.click()
      },
      insertMath: (block) => setMath({ block, latex: '' }),
      insertTable: () => { instance.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run() },
    }
    command.run(instance, context)
  }, [])
  const runSlashRef = useRef(runSlash)
  runSlashRef.current = runSlash

  async function handleImageFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !editorRef.current) return
    const targetEditor = editorRef.current
    const anchor = pendingImage.current ?? { from: targetEditor.state.selection.from, doc: targetEditor.state.doc }
    pendingImage.current = null
    const uploaded = await callbacks.current.onUploadImage(file)
    if (!uploaded) return
    if (editorRef.current !== targetEditor || targetEditor.state.doc !== anchor.doc) {
      setImageInsertError('上传期间正文发生了变化，图片未自动插入。请重新选择插入位置后再试。')
      return
    }
    const chain = targetEditor.chain().focus().setTextSelection(anchor.from)
    chain.insertImage({ src: uploaded.src, attachmentId: uploaded.attachmentId, assetId: uploaded.assetId, alt: file.name }).run()
  }

  function confirmMath() {
    if (!math || !editorRef.current) return
    const latex = math.latex.trim()
    if (!latex) { setMath(null); return }
    if (math.block) editorRef.current.chain().focus().insertBlockMath({ latex }).run()
    else editorRef.current.chain().focus().insertInlineMath({ latex }).run()
    setMath(null)
  }

  function setLink() {
    const instance = editorRef.current
    if (!instance) return
    const previous = String(instance.getAttributes('link').href ?? '')
    const href = window.prompt('链接地址（http:// 或 https://）', previous)
    if (href === null) return
    if (!href.trim()) { instance.chain().focus().extendMarkRange('link').unsetLink().run(); return }
    if (!/^(https?:\/\/|mailto:)/i.test(href.trim())) {
      window.alert('只支持 http、https 或 mailto 链接。')
      return
    }
    instance.chain().focus().extendMarkRange('link').setLink({ href: href.trim() }).run()
  }

  function askAI(action: AIAction) {
    const instance = editorRef.current
    if (!instance) return
    const { from, to } = instance.state.selection
    const text = instance.state.doc.textBetween(from, to, '\n')
    if (!text.trim()) return
    setAiOpen(false)
    callbacks.current.onRequestAI?.(action, text)
  }

  useImperativeHandle(ref, () => ({
    editor,
    getContent: () => (editor?.getJSON() as DocNode) ?? { type: 'doc', content: [] },
    replaceContent: (doc: DocNode) => {
      editor?.commands.setContent(doc as JSONContent, { emitUpdate: false })
    },
    focusBlock: (blockId: string) => {
      if (!editor) return
      let target: number | null = null
      editor.state.doc.forEach((node, offset) => {
        if (target === null && node.attrs.blockId === blockId) {
          target = offset + 1
        }
      })
      if (target === null) return
      editor.chain().focus().setTextSelection(Math.min(target, editor.state.doc.content.size)).scrollIntoView().run()
    },
    getSelection: () => {
      if (!editor) return null
      const { from, to, empty } = editor.state.selection
      if (empty) return null
      return { from, to, text: editor.state.doc.textBetween(from, to, '\n') }
    },
    insertMarkdown: (text: string, position?: number) => {
      if (!editor || !text.trim()) return
      const nodes = markdownToNodes(text).map((node) => node.attrs?.blockId ? node : { ...node, attrs: { ...(node.attrs ?? {}), blockId: newBlockId(node.type) } })
      const at = position ?? editor.state.selection.to
      editor.chain().focus().insertContentAt(at, nodes as JSONContent[]).run()
    },
    replaceRange: (text: string, from: number, to: number) => {
      if (!editor) return false
      const current = editor.state.doc.textBetween(from, to, '\n')
      if (!current.trim()) return false
      const nodes = markdownToNodes(text)
      editor.chain().focus().insertContentAt({ from, to }, nodes as JSONContent[]).run()
      return true
    },
    undo: () => { editorRef.current?.chain().focus().undo().run() },
    redo: () => { editorRef.current?.chain().focus().redo().run() },
    focus: () => { editorRef.current?.commands.focus() },
  }), [editor])

  if (!editor) {
    return <div className="nb-editor-loading" role="status">正在准备编辑器…</div>
  }

  const { from, to, empty } = editor.state.selection
  const selectionText = empty ? '' : editor.state.doc.textBetween(from, to, '\n')

  return <div className={`nb-editor${editable ? '' : ' is-readonly'}`} data-tick={selectionTick}>
    <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden onChange={(event) => void handleImageFile(event)} aria-label="上传笔记图片" />

    {editable && <BubbleMenu
      editor={editor}
      shouldShow={({ state }) => state.selection.from !== state.selection.to && !editor.isActive('codeBlock')}
      className="nb-selection-menu"
    >
      <button type="button" className={editor.isActive('bold') ? 'is-active' : ''} onClick={() => editor.chain().focus().toggleBold().run()} aria-label="加粗" title="加粗（Ctrl+B）"><strong>B</strong></button>
      <button type="button" className={editor.isActive('italic') ? 'is-active' : ''} onClick={() => editor.chain().focus().toggleItalic().run()} aria-label="斜体" title="斜体（Ctrl+I）"><em>I</em></button>
      <button type="button" className={editor.isActive('underline') ? 'is-active' : ''} onClick={() => editor.chain().focus().toggleUnderline().run()} aria-label="下划线" title="下划线（Ctrl+U）"><u>U</u></button>
      <button type="button" className={editor.isActive('strike') ? 'is-active' : ''} onClick={() => editor.chain().focus().toggleStrike().run()} aria-label="删除线" title="删除线"><s>S</s></button>
      <button type="button" className={editor.isActive('code') ? 'is-active' : ''} onClick={() => editor.chain().focus().toggleCode().run()} aria-label="行内代码" title="行内代码">‹›</button>
      <button type="button" className={editor.isActive('link') ? 'is-active' : ''} onClick={setLink} aria-label="链接" title="链接">↗</button>
      {editor.isActive('image') && <>
        <span className="nb-menu-divider" aria-hidden="true" />
        <button type="button" onClick={() => {
          const width = Number(editor.getAttributes('image').width) || 100
          editor.chain().focus().updateAttributes('image', { width: Math.max(25, width - 10) }).run()
        }} aria-label="缩小图片" title="缩小图片">−</button>
        <span className="nb-image-size" aria-live="polite">{Number(editor.getAttributes('image').width) || 100}%</span>
        <button type="button" onClick={() => {
          const width = Number(editor.getAttributes('image').width) || 100
          editor.chain().focus().updateAttributes('image', { width: Math.min(150, width + 10) }).run()
        }} aria-label="放大图片" title="放大图片">＋</button>
        <button type="button" onClick={() => editor.chain().focus().updateAttributes('image', { width: 100 }).run()} aria-label="恢复图片原始宽度" title="恢复宽度">100%</button>
      </>}
      <span className="nb-menu-divider" aria-hidden="true" />
      <button type="button" className={editor.isActive('heading', { level: 1 }) ? 'is-active' : ''} onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()} aria-label="一级标题" title="一级标题">H1</button>
      <button type="button" className={editor.isActive('heading', { level: 2 }) ? 'is-active' : ''} onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()} aria-label="二级标题" title="二级标题">H2</button>
      <button type="button" className={editor.isActive('blockquote') ? 'is-active' : ''} onClick={() => editor.chain().focus().toggleBlockquote().run()} aria-label="引用" title="引用">❝</button>
      <span className="nb-menu-divider" aria-hidden="true" />
      <div className="nb-ai-menu-wrap">
        <button type="button" className="nb-ai-trigger" onClick={() => setAiOpen((value) => !value)} aria-expanded={aiOpen} aria-label="AI 快捷操作" title="AI 快捷操作">✦ AI</button>
        {aiOpen && <div className="nb-ai-menu" role="menu">
          <button type="button" onClick={() => askAI('explain')} role="menuitem">解释这段内容</button>
          <button type="button" onClick={() => askAI('summarize')} role="menuitem">总结要点</button>
          <button type="button" onClick={() => askAI('expand')} role="menuitem">扩写内容</button>
          <button type="button" onClick={() => askAI('example')} role="menuitem">生成例题</button>
        </div>}
      </div>
      <span className="nb-selection-count">{selectionText.replace(/\s/g, '').length} 字</span>
    </BubbleMenu>}

    {editable && <DragHandle
      editor={editor}
      className="nb-drag-handle"
      onNodeChange={({ pos, node }) => setActiveNode(node ? { pos, size: node.nodeSize } : null)}
    >
      <button
        type="button"
        className="nb-block-plus"
        aria-label="打开内容块菜单"
        title="插入、复制、删除或移动内容块"
        onClick={(event) => {
          if (!activeNode) return
          const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
          setBlockMenu({ ...activeNode, left: rect.right + 8, top: rect.bottom + 4 })
        }}
      >＋</button>
      <span className="nb-block-grip" aria-hidden="true">⠿</span>
    </DragHandle>}

    {blockMenu && <div className="nb-block-menu" style={{ left: blockMenu.left, top: blockMenu.top }} role="menu" aria-label="内容块操作">
      <button type="button" role="menuitem" onClick={() => { editor.chain().focus().insertContentAt(blockMenu.pos, { type: 'paragraph' }).run(); setBlockMenu(null) }}>在上方插入</button>
      <button type="button" role="menuitem" onClick={() => { editor.chain().focus().insertContentAt(blockMenu.pos + blockMenu.size, { type: 'paragraph' }).run(); setBlockMenu(null) }}>在下方插入</button>
      <span className="nb-menu-divider" aria-hidden="true" />
      <button type="button" role="menuitem" onClick={() => { const node = editor.state.doc.nodeAt(blockMenu.pos); if (node) editor.chain().focus().insertContentAt(blockMenu.pos + blockMenu.size, node.toJSON()).run(); setBlockMenu(null) }}>复制此块</button>
      <button type="button" role="menuitem" onClick={() => { editor.chain().focus().setTextSelection(blockMenu.pos + 1).setParagraph().run(); setBlockMenu(null) }}>转为正文</button>
      <button type="button" role="menuitem" onClick={() => { editor.chain().focus().setTextSelection(blockMenu.pos + 1).setHeading({ level: 1 }).run(); setBlockMenu(null) }}>转为一级标题</button>
      <button type="button" role="menuitem" onClick={() => { editor.chain().focus().setTextSelection(blockMenu.pos + 1).setHeading({ level: 2 }).run(); setBlockMenu(null) }}>转为二级标题</button>
      <button type="button" role="menuitem" onClick={() => { editor.chain().focus().setTextSelection(blockMenu.pos + 1).run(); editor.commands.moveBlockUp(); setBlockMenu(null) }}>上移（Alt+↑）</button>
      <button type="button" role="menuitem" onClick={() => { editor.chain().focus().setTextSelection(blockMenu.pos + 1).run(); editor.commands.moveBlockDown(); setBlockMenu(null) }}>下移（Alt+↓）</button>
      <span className="nb-menu-divider" aria-hidden="true" />
      <button type="button" role="menuitem" onClick={() => { editor.chain().focus().setNodeSelection(blockMenu.pos).deleteSelection().run(); setBlockMenu(null) }} className="is-danger">删除此块</button>
    </div>}

    {tableActive && <div className="nb-table-bar" role="toolbar" aria-label="表格操作">
      <span>表格</span>
      <button type="button" onClick={() => editor.chain().focus().addRowAfter().run()}>下方加行</button>
      <button type="button" onClick={() => editor.chain().focus().addColumnAfter().run()}>右侧加列</button>
      <button type="button" onClick={() => editor.chain().focus().deleteRow().run()}>删行</button>
      <button type="button" onClick={() => editor.chain().focus().deleteColumn().run()}>删列</button>
      <button type="button" className="is-danger" onClick={() => editor.chain().focus().deleteTable().run()}>删除表格</button>
    </div>}

    {imageInsertError && <p className="notebook-document-error" role="alert">{imageInsertError}</p>}
    <EditorContent editor={editor} />

    {editable && <SlashCommandMenu
      items={items}
      activeIndex={slash?.index ?? 0}
      position={slash ? { left: slash.left, top: slash.top } : null}
      onHover={(index) => setSlash((state) => state ? { ...state, index } : state)}
      onSelect={(command) => runSlash(command)}
    />}

    {math && <div className="nb-modal-backdrop" role="dialog" aria-modal="true" aria-label="插入公式">
      <div className="nb-modal">
        <h2>{math.block ? '插入公式块' : '插入行内公式'}</h2>
        <p>输入 LaTeX，例如 <code>F = ma</code> 或 <code>\int_0^1 f(x)\,dx</code>。</p>
        <textarea
          autoFocus
          value={math.latex}
          onChange={(event) => setMath({ ...math, latex: event.target.value })}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); confirmMath() }
            if (event.key === 'Escape') setMath(null)
          }}
          rows={3}
          aria-label="LaTeX 源码"
        />
        <div className="nb-modal-actions">
          <button type="button" onClick={() => setMath(null)}>取消</button>
          <button type="button" className="primary-button" onClick={confirmMath} disabled={!math.latex.trim()}>插入</button>
        </div>
      </div>
    </div>}
  </div>
})
