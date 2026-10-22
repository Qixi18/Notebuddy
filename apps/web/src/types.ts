export type Course = {
  id: string
  name: string
  description: string | null
  created_at: string
  deleted_at?: string | null
  last_opened_at?: string | null
}

export type Material = {
  notebook_id?: string | null
  chapter_order?: number
  id: string
  course_id: string
  lecture_title: string
  topic_title: string | null
  original_filename: string
  media_type: string | null
  size_bytes: number
  status: string
  page_count: number
  created_at: string
  parser_version?: string | null
  document_warning?: string | null
  deleted_at?: string | null
}

export type Job = {
  id: string
  material_id: string
  kind: string
  status: string
  progress: number
  error_message: string | null
  phase: string
  web_search_status: string
  created_at: string
  updated_at: string
  error_code?: string | null
  attempt_count?: number
}

export type DeletionPreview = {
  course_id: string
  material_id: string | null
  materials: number
  pages: number
  source_refs: number
  knowledge_nodes_touched: number
  user_notes_protected: number
  original_bytes: number
  active_jobs: number
  action: string
}

export type Page = {
  id: string
  material_id: string
  page_number: number
  title: string | null
  raw_text: string
  parse_status: string
  warning: string | null
  location_type: string
  location_label: string | null
  stable_location_key: string | null
  extraction_method: string
  confidence: number | null
}

export type PageBlock = {
  id: string
  page_id: string
  block_type: string
  content: string
  position: number
  font_size: number | null
  is_bold: boolean
  object_id: string | null
  location_label: string | null
  extraction_method: string
  confidence: number | null
  warning: string | null
  note_ids: string[]
  note_titles: string[]
}

export type PageEvidence = Page & {
  blocks: PageBlock[]
  note_ids: string[]
  note_titles: string[]
}

export type CoverageLocation = {
  page_id: string
  page_number: number
  location_type: string
  location_label: string
  stable_location_key: string | null
  status: 'cited' | 'review'
  citation_count: number
  note_ids: string[]
  note_titles: string[]
  warning: string | null
}

export type Coverage = {
  material_id: string
  total_locations: number
  cited_locations: number
  review_locations: number
  locations: CoverageLocation[]
}

export type UploadResponse = {
  material: Material
  job: Job
}

export type AssistantSource = {
  source_type: 'course_material' | 'web'
  source_ref_id?: string | null
  material_id?: string | null
  lecture_title?: string | null
  page_number?: number | null
  snippet: string
  title?: string | null
  url?: string | null
  site_name?: string | null
  retrieved_at?: string | null
  published_at?: string | null
  location_label?: string | null
  support_level?: string
  score_source?: string | null
}

export type WebSource = {
  id: string
  title: string
  url: string
  site_name: string
  snippet: string
  search_query: string
  score: number | null
  published_at: string | null
  retrieved_at: string
}

export type TermExplanationSource = {
  material_id: string
  lecture_title: string
  page_number: number
  location_label?: string | null
  snippet: string
}

export type TermExplanation = {
  original: string
  common_translations: string[]
  discipline: string | null
  explanation: string
  source_note: string
  uncertain: boolean
  sources: TermExplanationSource[]
}

export type Note = {
  notebook_id?: string | null
  tree_slot?: number
  material_id: string | null
  section_key: string | null
  section_order: number
  id: string
  course_id: string
  knowledge_node_id: string
  title: string
  content_markdown: string
  content_origin: string
  user_locked: boolean
  revision_number: number
  created_at: string
  updated_at: string
}

export type NotebookSection = Pick<Note, 'id' | 'knowledge_node_id' | 'material_id' | 'section_key' | 'section_order' | 'title' | 'revision_number' | 'user_locked' | 'updated_at'>
export type NotebookChapter = { id: string; title: string; chapter_order: number; status: string; deleted_at: string | null; sections: NotebookSection[] }
export type Notebook = { course_id: string; title: string; order_revision: number; chapters: NotebookChapter[]; historical_sections: NotebookSection[]; removed_chapters: NotebookChapter[] }

// Keep legacy types compatible until their consumers switch to scoped routes.
export type SectionRead = NotebookSection & { notebook_id: string; tree_slot: number }
export type ChapterRead = Omit<NotebookChapter, 'sections'> & { sections: SectionRead[] }
export type NotebookRead = Omit<Notebook, 'chapters' | 'historical_sections' | 'removed_chapters'> & {
  id: string; tree_slot: number; chapters: ChapterRead[]
  historical_sections: SectionRead[]; removed_chapters: ChapterRead[]
}
export type NotebookSummary = {
  id: string; course_id: string; title: string; tree_slot: number
  display_order: number; order_revision: number; is_default: boolean
  created_at: string; updated_at: string
}
export type NotebookDocumentBlock = { id: string; type: 'h1' | 'h2' | 'p' | 'bullet'; text: string }
export type NotebookDocument = { blocks: NotebookDocumentBlock[]; revision: number; updated_at: string }
export type CourseTree = { course_id: string; notebooks: NotebookRead[] }
export type NotebookReadingPosition = {
  notebook_id: string; chapter_id: string | null; note_id: string | null
  mode: 'chapter' | 'book'; section_offset: number; revision: number; updated_at: string
}
export type NoteRevision = {
  id: string
  note_id: string
  revision_number: number
  content_markdown: string
  content_origin: string
  user_locked: boolean
  created_at: string
}

export type NoteSourceRef = {
  id: string
  page_block_id: string
  source_type: string
  quote: string
  material_id: string
  page_number: number
  location_type?: string
  location_label?: string | null
  status?: string
}

export type KnowledgeNode = {
  id: string
  course_id: string
  name: string
  summary: string | null
  status: string
  sources: KnowledgeNodeSource[]
}

export type KnowledgeNodeSource = {
  material_id: string
  lecture_title: string
  topic_title?: string | null
  page_number: number
}

export type KnowledgeEdge = {
  id: string
  course_id: string
  source_node_id: string
  target_node_id: string
  relation_type: string
  confidence: number | null
  created_by: string
}

export type KnowledgeGraph = {
  occurrences?: Array<{ id: string; note_id: string; knowledge_node_id: string; material_id: string | null; section_key: string | null; section_order: number; title: string }>
  nodes: KnowledgeNode[]
  edges: KnowledgeEdge[]
}

export type KnowledgeChange = {
  id: string
  proposal_id: string | null
  node_id: string | null
  change_type: string
  before_json: string
  after_json: string
  reason: string
  created_at: string
}

export type Conversation = {
  id: string
  course_id: string
  title: string
  default_scope: string
  created_at: string
  updated_at: string
}

export type MessageEvidence = {
  id: string
  claim_key: string
  evidence_type: string
  support_level: string
  source_ref_id?: string | null
  web_source_id?: string | null
  snippet?: string | null
  location_label?: string | null
}

export type ConversationMessage = {
  id: string
  conversation_id: string
  role: 'user' | 'assistant'
  content: string
  learning_goal?: string | null
  status: string
  model_version?: string | null
  failure_type?: string | null
  created_at: string
  evidence: MessageEvidence[]
  /** 回答模式，取值与 /assistant 直连回答一致（deepseek-rag / persona-general / …） */
  mode?: string | null
  /** 可点击的来源卡片；由后端从 evidence 反推，与直连回答同结构 */
  sources?: AssistantSource[]
}

export type KnowledgeProposal = {
  id: string
  course_id: string
  material_id?: string | null
  source_node_id?: string | null
  target_node_id?: string | null
  kind: string
  candidate_name: string
  candidate_summary: string
  confidence: number
  rationale: string
  source_ids_json: string
  proposed_delta_json: string
  status: string
  model_version?: string | null
  review_note?: string | null
  created_at: string
  reviewed_at?: string | null
}

export type Feedback = {
  id: string
  course_id: string
  target_type: string
  target_id: string
  category: string
  comment?: string | null
  status: string
  resolution?: string | null
  created_at: string
  updated_at: string
}

export type SettingsStatus = {
  deepseek: { configured: boolean; masked_key: string | null; base_url: string | null; model: string | null; timeout_seconds: number | null }
  embedding: { configured: boolean; masked_key: string | null; base_url: string | null; model: string | null; timeout_seconds: number | null }
  storage: { data_dir: string; database: string; max_upload_mb: number }
  limits: { allowed_extensions: string[]; editable_keys: string[]; secret_write_enabled: boolean; token_required: boolean }
  source: { env_path: string; env_exists: boolean; override_keys: string[] }
}

export type SettingsUpdateResponse = {
  updated: string[]
  backup_path: string | null
  status: SettingsStatus
  warnings: string[]
}
