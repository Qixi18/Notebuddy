import { Extension, Node, mergeAttributes, type AnyExtension } from '@tiptap/core'
import Image from '@tiptap/extension-image'
import { Table, TableCell, TableHeader, TableRow } from '@tiptap/extension-table'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import Mathematics from '@tiptap/extension-mathematics'
import StarterKit from '@tiptap/starter-kit'
import { Placeholder } from '@tiptap/extensions'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { Plugin, TextSelection } from '@tiptap/pm/state'
import type { Node as ProseMirrorNode } from '@tiptap/pm/model'
import { CalloutView } from './CalloutView'
import { newBlockId } from './document'

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    notebookBlocks: {
      moveBlockUp: () => ReturnType
      moveBlockDown: () => ReturnType
      setCallout: (attrs?: { tone?: string; title?: string }) => ReturnType
      setExample: (attrs?: { title?: string }) => ReturnType
      insertImage: (attrs: { src: string; attachmentId: string; alt?: string; title?: string }) => ReturnType
    }
  }
}

const BLOCK_TYPES = [
  'paragraph',
  'heading',
  'bulletList',
  'orderedList',
  'taskList',
  'blockquote',
  'codeBlock',
  'table',
]

export const NotebookBlockIds = Extension.create({
  name: 'notebookBlockIds',
  addGlobalAttributes() {
    return [{
      types: BLOCK_TYPES,
      attributes: {
        blockId: {
          default: null,
          parseHTML: (element) => element.getAttribute('data-block-id'),
          renderHTML: (attributes) => attributes.blockId ? { 'data-block-id': attributes.blockId } : {},
        },
      },
    }]
  },
  addProseMirrorPlugins() {
    return [new Plugin({
      appendTransaction: (transactions, _oldState, newState) => {
        if (!transactions.some((transaction) => transaction.docChanged)) return null
        const updates: Array<{ pos: number; attrs: Record<string, unknown> }> = []
        const used = new Set<string>()
        newState.doc.forEach((node, offset) => {
          if (!BLOCK_TYPES.includes(node.type.name) && node.type.name !== 'callout' && node.type.name !== 'example') return
          const blockId = node.attrs.blockId
          if (typeof blockId === 'string' && blockId && !used.has(blockId)) {
            used.add(blockId)
            return
          }
          updates.push({ pos: offset, attrs: { ...node.attrs, blockId: newBlockId(node.type.name) } })
        })
        if (!updates.length) return null
        const transaction = newState.tr
        for (const update of updates) {
          transaction.setNodeMarkup(update.pos, undefined, update.attrs)
        }
        return transaction
      },
    })]
  },
})

function moveBlock(direction: -1 | 1) {
  return ({ state, dispatch }: { state: import('@tiptap/pm/state').EditorState; dispatch?: (tr: import('@tiptap/pm/state').Transaction) => void }) => {
    const { $from } = state.selection
    if ($from.depth < 1) return false
    const index = $from.index(0)
    const target = index + direction
    if (target < 0 || target >= state.doc.childCount) return false
    if (!dispatch) return true
    const nodes: ProseMirrorNode[] = []
    state.doc.forEach((node) => nodes.push(node))
    const [moved] = nodes.splice(index, 1)
    nodes.splice(target, 0, moved)
    const nextDoc = state.schema.nodeFromJSON({ type: 'doc', content: nodes.map((node) => node.toJSON()) })
    const transaction = state.tr.replaceWith(0, state.doc.content.size, nextDoc.content)
    let position = 0
    for (let cursor = 0; cursor < target; cursor += 1) position += nodes[cursor].nodeSize
    transaction.setSelection(TextSelection.near(transaction.doc.resolve(Math.min(position + 1, transaction.doc.content.size))))
    dispatch(transaction.scrollIntoView())
    return true
  }
}

export const NotebookBlocks = Extension.create({
  name: 'notebookBlocks',
  addCommands() {
    return {
      moveBlockUp: () => moveBlock(-1),
      moveBlockDown: () => moveBlock(1),
    }
  },
  addKeyboardShortcuts() {
    return {
      'Alt-ArrowUp': () => this.editor.commands.moveBlockUp(),
      'Alt-ArrowDown': () => this.editor.commands.moveBlockDown(),
    }
  },
})

export const Callout = Node.create({
  name: 'callout',
  group: 'block',
  content: 'block+',
  defining: true,
  addAttributes() {
    return {
      blockId: {
        default: null,
        parseHTML: (element) => element.getAttribute('data-block-id'),
        renderHTML: (attributes) => attributes.blockId ? { 'data-block-id': attributes.blockId } : {},
      },
      tone: {
        default: 'tip',
        parseHTML: (element) => element.getAttribute('data-tone') || 'tip',
        renderHTML: (attributes) => ({ 'data-tone': attributes.tone }),
      },
      title: {
        default: '重点提示',
        parseHTML: (element) => element.getAttribute('data-title') || '重点提示',
        renderHTML: (attributes) => ({ 'data-title': attributes.title }),
      },
    }
  },
  parseHTML() {
    return [{ tag: 'div[data-callout]' }]
  },
  renderHTML({ HTMLAttributes }) {
    return ['div', mergeAttributes(HTMLAttributes, { 'data-callout': '', class: 'nb-callout' }), 0]
  },
  addNodeView() {
    return ReactNodeViewRenderer(CalloutView)
  },
  addCommands() {
    return {
      setCallout: (attrs) => ({ commands }) => commands.insertContent({
        type: this.name,
        attrs: { blockId: newBlockId('callout'), tone: attrs?.tone ?? 'tip', title: attrs?.title ?? '重点提示' },
        content: [{ type: 'paragraph' }],
      }),
    }
  },
})

export const Example = Node.create({
  name: 'example',
  group: 'block',
  content: 'block+',
  defining: true,
  addAttributes() {
    return {
      blockId: {
        default: null,
        parseHTML: (element) => element.getAttribute('data-block-id'),
        renderHTML: (attributes) => attributes.blockId ? { 'data-block-id': attributes.blockId } : {},
      },
      title: {
        default: '例题',
        parseHTML: (element) => element.getAttribute('data-title') || '例题',
        renderHTML: (attributes) => ({ 'data-title': attributes.title }),
      },
    }
  },
  parseHTML() {
    return [{ tag: 'div[data-example]' }]
  },
  renderHTML({ HTMLAttributes }) {
    return ['div', mergeAttributes(HTMLAttributes, { 'data-example': '', class: 'nb-example' }), 0]
  },
  addNodeView() {
    return ReactNodeViewRenderer(CalloutView)
  },
  addCommands() {
    return {
      setExample: (attrs) => ({ commands }) => commands.insertContent({
        type: this.name,
        attrs: { blockId: newBlockId('example'), title: attrs?.title ?? '例题' },
        content: [{ type: 'paragraph' }],
      }),
    }
  },
})

export const NotebookImage = Image.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      attachmentId: {
        default: null,
        parseHTML: (element) => element.getAttribute('data-attachment-id'),
        renderHTML: (attributes) => attributes.attachmentId ? { 'data-attachment-id': attributes.attachmentId } : {},
      },
    }
  },
  addCommands() {
    return {
      ...this.parent?.(),
      insertImage: (attrs) => ({ commands }) => commands.insertContent({
        type: 'image',
        attrs: { src: attrs.src, attachmentId: attrs.attachmentId, alt: attrs.alt ?? '', title: attrs.title ?? null },
      }),
    }
  },
}).configure({ inline: false, allowBase64: false })

export function buildExtensions(): AnyExtension[] {
  return [
    StarterKit.configure({
      heading: { levels: [1, 2, 3] },
      link: { openOnClick: false, autolink: true, defaultProtocol: 'https' },
      codeBlock: { languageClassPrefix: 'language-' },
    }),
    NotebookBlockIds,
    NotebookBlocks,
    Callout,
    Example,
    TaskList,
    TaskItem.configure({ nested: true }),
    Table.configure({ resizable: false, allowTableNodeSelection: true }),
    TableRow,
    TableHeader,
    TableCell,
    NotebookImage,
    Mathematics.configure({ katexOptions: { throwOnError: false, strict: false } }),
    Placeholder.configure({
      placeholder: ({ node }) => {
        if (node.type.name === 'heading') return '输入标题'
        if (node.type.name === 'paragraph') return '输入正文，选中文字可使用 AI，输入 / 插入内容块…'
        return ''
      },
    }),
  ]
}
