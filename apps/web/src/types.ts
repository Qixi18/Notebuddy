export type Course = {
  id: string
  name: string
  description: string | null
  created_at: string
  deleted_at?: string | null
  last_opened_at?: string | null
}

export type Material = {
  asset_id?: string | null
  notebook_id: string
  chapter_order?: number
  id: string
  course_id: string | null
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

export type CourseOverviewMaterial = {
  id: string
  title: string
  filename: string
  status: string
  page_count: number
  asset_id: string | null
  parse_run_id: string | null
  quality_status: string | null
  generation_allowed: boolean
  quality_reason: string | null
  deleted_at: string | null
}

export type CourseOverview = {
  course_id: string
  name: string
  counts: {
    notebooks: number
    sections: number
    materials: number
    materials_needing_attention: number
    generation_running: number
    generation_failed: number
  }
  notebooks: Array<{ id: string; title: string; revision: number; sections: number; updated_at: string }>
  materials: CourseOverviewMaterial[]
  generation_jobs: Array<{ id: string; notebook_id: string; status: string; error_code: string | null; error_message: string | null; generator: string; created_at: string; finished_at: string | null }>
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
  upload_batch_id?: string | null
}

export type NotebookGenerationInputStatus = {
  asset_id: string
  parse_job_id: string | null
  parse_result_fingerprint: string | null
  generation_job_id: string | null
  status: 'waiting_parse' | 'parsing' | 'parse_failed' | 'ready' | 'generating' | 'generation_failed' | 'completed'
  error_code: string | null
  error_message: string | null
  retry_count: number
}

export type NotebookUploadBatch = {
  id: string
  notebook_id: string
  status: 'open' | 'waiting_parse' | 'parsing' | 'generating' | 'partial_failure' | 'completed'
  created_at: string
  updated_at: string
  closed_at: string | null
  inputs: NotebookGenerationInputStatus[]
  generation_jobs: Array<{ id: string; status: string }>
}

export type AssetResource = {
  id: string
  source_type: string
  media_type: string
  mime_type: string
  original_name: string
  byte_size: number
  sha256: string | null
  state: string
  role: string
  content_url: string
  created_at: string
}

export type DocumentParseRunSummary = {
  id: string; asset_id: string; status: string; is_current: boolean
  page_count: number; text_chars: number; quality_status: string
  quality: {
    status: string
    issues?: Array<{ code: string; severity: string; message: string; page_numbers?: number[] }>
    generation_allowed?: boolean
    generation_block_reason?: string | null
    [key: string]: unknown
  }
  created_at: string; error_code?: string | null; error_message?: string | null
}
export type DocumentPage = {
  page_number: number; status: string; extraction: string; confidence: number | null
  warnings: string[]; text_chars: number; render_url: string | null
}
export type DocumentBlock = {
  block_id: string; page_number: number; type: string; level: number; text: string
  latex: string | null; confidence: number | null; extraction: string; warnings: string[]
  figure?: { kind: string; description: string | null; nodes: string[]; edges: string[];
    latex?: string | null; uncertain: boolean; image_key?: string | null } | null
}
export type AssetDocument = {
  run: DocumentParseRunSummary; pages: DocumentPage[]
  sections: Array<{ section_id: string; title: string; level: number; page_start: number; page_end: number; block_ids: string[] }>
}
export type DocumentCoverage = {
  asset_id: string; asset_name: string; parse_run_id: string; total_blocks: number; cited_blocks: number
  pages: Array<{ page_number: number; total: number; cited: number }>
  blocks: Array<{ block_id: string; page_number: number; quote: string; citations: Array<{ notebook_id: string; notebook_title: string; block_id: string; page_number: number }> }>
}

export type AssetProcessingJob = {
  id: string
  asset_id: string
  status: string
  attempt_count: number
  error_code: string | null
  error_message: string | null
  created_at: string
  finished_at: string | null
}

export type NotebookGenerationCandidate = {
  id: string
  job_id: string
  notebook_id: string
  document: DocNode
  status: string
  created_at: string
  expires_at: string | null
}

export type NotebookGenerationJob = {
  id: string
  notebook_id: string
  status: string
  base_document_revision: number
  model: string
  prompt_version: string
  attempt_count: number
  error_code: string | null
  error_message: string | null
  created_at: string
  updated_at: string
  finished_at: string | null
  generator?: string | null
  parse_run_ids?: string[]
  plan?: { new_count?: number; extend_count?: number; skip_count?: number; batches?: number } | null
  candidate: NotebookGenerationCandidate | null
}

export type AssistantSource = {
  source_type: 'course_material' | 'notebook' | 'web'
  source_status?: 'active' | 'stale' | 'unavailable'
  source_ref_id?: string | null
  material_id?: string | null
  asset_id?: string | null
  lecture_title?: string | null
  page_number?: number | null
  page_numbers?: number[]
  document_block_ids?: string[]
  snippet: string
  title?: string | null
  url?: string | null
  site_name?: string | null
  retrieved_at?: string | null
  published_at?: string | null
  location_label?: string | null
  support_level?: string
  score_source?: string | null
  notebook_id?: string | null
  notebook_title?: string | null
  notebook_revision?: number | null
  block_id?: string | null
  document_block_id?: string | null
  parse_run_id?: string | null
  locator?: Record<string, unknown> | null
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

export type NotebookSection = Pick<Note, 'id' | 'knowledge_node_id' | 'material_id' | 'section_key' | 'section_order' | 'title' | 'revision_number' | 'user_locked' | 'updated_at'> & { block_id?: string }
export type NotebookChapter = { id: string; title: string; chapter_order: number; status: string; deleted_at: string | null; sections: NotebookSection[] }
export type Notebook = { course_id: string; title: string; order_revision: number; chapters: NotebookChapter[]; historical_sections: NotebookSection[]; removed_chapters: NotebookChapter[] }

// Keep legacy types compatible until their consumers switch to scoped routes.
export type SectionRead = NotebookSection & { notebook_id: string; tree_slot: number }
export type ChapterRead = Omit<NotebookChapter, 'sections'> & { sections: SectionRead[] }
export type NotebookRead = Omit<Notebook, 'chapters' | 'historical_sections' | 'removed_chapters'> & {
  processing?: boolean
  id: string; tree_slot: number; chapters: ChapterRead[]
  historical_sections: SectionRead[]; removed_chapters: ChapterRead[]
}
  export type NotebookSummary = {
    id: string; course_id: string; title: string; tree_slot: number
  display_order: number; order_revision: number; is_default: boolean
    created_at: string; updated_at: string; cover_url?: string | null
}
export type NotebookDocumentBlock = { id: string; type: 'h1' | 'h2' | 'p' | 'bullet'; text: string }
export type NotebookDocument = { blocks: NotebookDocumentBlock[]; revision: number; updated_at: string }

/** Tiptap / ProseMirror document tree persisted by the notebook editor (schema v2). */
export type DocMark = {
  type: 'bold' | 'italic' | 'underline' | 'strike' | 'link' | 'code' | 'highlight' | string
  attrs?: Record<string, unknown>
}
export type DocNode = {
  type: string
  attrs?: Record<string, unknown>
  content?: DocNode[]
  marks?: DocMark[]
  text?: string
}
export type NotebookDocumentResponse = {
  schema_version: number
  content: DocNode
  blocks: NotebookDocumentBlock[]
  revision: number
  updated_at: string
  warning?: string | null
}
export type NotebookEditOperation = {
  op: 'append' | 'insert_after_heading' | 'replace_section' | 'remove_section'
  anchor?: string
  content?: string
}
export type NotebookEditSuggestion = {
  id: string
  notebook_id: string
  notebook_title?: string
  base_revision: number
  rationale: string
  operations: NotebookEditOperation[]
  proposed_content: DocNode | null
  status: string
  created_at: string
  reviewed_at: string | null
}
export type NotebookAttachment = {
  id: string
  url: string
  original_filename: string
  mime: string
  size_bytes: number
  created_at: string
}
export type NotebookRevisionSummary = { revision: number; origin: string; created_at: string }
export type NotebookRevision = NotebookRevisionSummary & { schema_version: number; content: DocNode }
export type OutlineItem = { id: string; level: number; text: string }
export type CourseTree = { course_id: string; notebooks: NotebookRead[] }
export type NotebookReadingPosition = {
  notebook_id: string; chapter_id: string | null; note_id: string | null; block_id: string | null
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
  /** 会话归属：course=整门课程 / global=跨课程 / note=锁定笔记（后端 B1 落地后可用） */
  scope?: 'course' | 'global' | 'note' | null
  note_id?: string | null
  note_title?: string | null
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
  /** 首条问题触发后由后端回写的会话标题；用于即时刷新历史列表（替代「新对话」） */
  conversation_title?: string
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
