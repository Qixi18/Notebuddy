import { useEffect, useState } from 'react'

import { api } from '../../api'
import type { AssetDocument, DocumentBlock, DocumentCoverage, DocumentParseRunSummary, Page, WebSource } from '../../types'

export function DocumentSourcePreview({ assetId, notebookId, materialId, initialPage, fileName, mimeType, originalUrl, onClose }: {
  assetId: string
  notebookId: string
  materialId?: string
  initialPage?: number
  fileName?: string
  mimeType?: string
  originalUrl?: string
  onClose: () => void
}) {
  const [runs, setRuns] = useState<DocumentParseRunSummary[]>([])
  const [runId, setRunId] = useState<string>()
  const [document, setDocument] = useState<AssetDocument>()
  const [pageNumber, setPageNumber] = useState(initialPage ?? 1)
  const [blocks, setBlocks] = useState<DocumentBlock[]>([])
  const [coverage, setCoverage] = useState<DocumentCoverage>()
  const [webSources, setWebSources] = useState<WebSource[]>([])
  const [legacyPages, setLegacyPages] = useState<Page[]>([])
  const [ocrBusy, setOcrBusy] = useState(false)
  const [ocrNotice, setOcrNotice] = useState<string>()
  const [error, setError] = useState<string>()
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let active = true
    void api.listAssetParseRuns(assetId, notebookId).then((items) => {
      if (!active) return
      setRuns(items)
      const current = items.find((item) => item.is_current && item.status === 'completed')
      setRunId(current?.id ?? items.find((item) => item.status === 'completed')?.id)
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : '读取解析版本失败')
    })
    return () => { active = false }
  }, [assetId, notebookId])

  useEffect(() => {
    if (!materialId) { setWebSources([]); return }
    let active = true
    void api.listMaterialWebSources(materialId).then((items) => { if (active) setWebSources(items) })
      .catch(() => { if (active) setWebSources([]) })
    return () => { active = false }
  }, [materialId])

  useEffect(() => {
    if (!materialId) { setLegacyPages([]); return }
    let active = true
    void api.listPages(materialId).then((items) => { if (active) setLegacyPages(items) })
      .catch(() => { if (active) setLegacyPages([]) })
    return () => { active = false }
  }, [materialId])

  useEffect(() => {
    if (!runId) return
    let active = true
    setLoading(true)
    setError(undefined)
    void Promise.all([
      api.getAssetDocument(assetId, notebookId, runId),
      api.getAssetCoverage(assetId, notebookId, runId).catch(() => undefined),
    ]).then(([data, report]) => {
      if (!active) return
      setDocument(data)
      setCoverage(report)
      const requested = initialPage && data.pages.some((page) => page.page_number === initialPage)
        ? initialPage : data.pages[0]?.page_number ?? 1
      setPageNumber((current) => data.pages.some((page) => page.page_number === current) ? current : requested)
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : '读取资料解析结果失败')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [assetId, notebookId, runId, initialPage])

  useEffect(() => {
    if (!runId || !pageNumber) return
    let active = true
    void api.getAssetPageEvidence(assetId, notebookId, pageNumber, runId)
      .then((items) => { if (active) setBlocks(items) })
      .catch(() => { if (active) setBlocks([]) })
    return () => { active = false }
  }, [assetId, notebookId, pageNumber, runId])

  const page = document?.pages.find((item) => item.page_number === pageNumber)
  const legacyPage = legacyPages.find((item) => item.page_number === pageNumber)
  const run = document?.run
  const renderUrl = api.assetPageRenderUrl(assetId, notebookId, pageNumber, runId)
  const isPdf = (mimeType ?? '').toLowerCase().includes('pdf') || (fileName ?? '').toLowerCase().endsWith('.pdf')

  return <div className="document-source-backdrop" role="presentation" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose()
  }}>
    <section className="document-source-dialog" role="dialog" aria-modal="true" aria-label="资料来源预览">
      <header className="document-source-header">
        <div><small>Notebook 资料来源</small><h2>{fileName ?? document?.run.asset_id ?? '资料预览'}</h2></div>
        <button type="button" onClick={onClose} aria-label="关闭资料预览">×</button>
      </header>
      {error && <p className="document-source-error" role="alert">{error}</p>}
      {runs.length > 1 && <label className="document-source-run">解析版本
        <select value={runId ?? ''} onChange={(event) => setRunId(event.target.value)}>
          {runs.map((item) => <option key={item.id} value={item.id} disabled={item.status !== 'completed'}>
            {new Date(item.created_at).toLocaleString('zh-CN')} · {item.is_current ? '当前版本' : item.status}
          </option>)}
        </select>
      </label>}
      {run && <div className="document-source-quality">
        <p>解析质量：{run.quality_status} · {run.page_count} 页 · {run.text_chars.toLocaleString('zh-CN')} 字</p>
        {run.quality_status === 'partial' && run.quality?.generation_allowed &&
          <p role="status">部分页面未能完整解析；生成内容仅依据已识别页面，请先检查下方页码状态与提示。</p>}
        {run.quality_status === 'partial' && !run.quality?.generation_allowed &&
          <p role="alert">解析不完整，当前已阻止生成；请先检查失败页面或重新运行 OCR。</p>}
        {run.quality?.generation_block_reason && <p role="alert">{run.quality.generation_block_reason}</p>}
        {run.quality?.issues?.filter((issue) => issue.severity === 'blocking' || issue.severity === 'warning')
          .map((issue) => <p key={issue.code}>{issue.message}</p>)}
      </div>}
      {loading && <p role="status">正在读取解析内容…</p>}
      {document && <div className="document-source-body">
        <nav className="document-source-pages" aria-label="资料页码">
          {document.pages.map((item) => <button key={item.page_number} type="button"
            className={pageNumber === item.page_number ? 'is-active' : ''}
            onClick={() => setPageNumber(item.page_number)}>
            第 {item.page_number} 页 {item.confidence !== null ? `· ${Math.round(item.confidence * 100)}%` : ''}
          </button>)}
        </nav>
        <main className="document-source-page">
          <div className="document-source-page-heading">
            <h3>第 {pageNumber} 页</h3>
            {page?.extraction && <small>{page.extraction}{page.status !== 'parsed' ? ` · ${page.status}` : ''}</small>}
          </div>
          {page?.warnings.length ? <p className="document-source-warning">{page.warnings.join('；')}</p> : null}
          {legacyPage?.parse_status === 'ocr_candidate' && <div className="document-source-ocr">
            <span>{legacyPage.warning ?? '此页未提取到可靠文字，可尝试 OCR。'}</span>
            <button type="button" disabled={!materialId || ocrBusy} onClick={() => {
              if (!materialId) return
              setOcrBusy(true); setOcrNotice(undefined)
              void api.requestOCR(materialId).then(() => setOcrNotice('OCR 任务已加入队列。'))
                .catch((cause: unknown) => setOcrNotice(cause instanceof Error ? cause.message : 'OCR 请求失败'))
                .finally(() => setOcrBusy(false))
            }}>{ocrBusy ? '提交中…' : '请求 OCR'}</button>
            {ocrNotice && <small role="status">{ocrNotice}</small>}
          </div>}
          {page?.render_url ? isPdf
            ? <img className="document-source-render" src={renderUrl} alt={`${fileName ?? '资料'} 第 ${pageNumber} 页`} />
            : <a className="document-source-original" href={renderUrl} target="_blank" rel="noreferrer">在新标签打开原始文件</a>
            : <p className="document-source-warning">此解析版本没有保存页面预览；可查看下方解析块。{originalUrl && <> <a href={originalUrl} target="_blank" rel="noreferrer">打开原始文件</a></>}</p>}
          <section className="document-source-evidence">
            <h4>本页解析块 · {blocks.length}</h4>
            {blocks.length ? blocks.map((block) => {
              const citations = coverage?.blocks.find((item) => item.block_id === block.block_id)?.citations ?? []
              return <article key={block.block_id}>
                <small>{block.type}{block.confidence !== null ? ` · 置信度 ${Math.round(block.confidence * 100)}%` : ''}</small>
                <p>{block.text || block.latex || '该块没有可展示文本。'}</p>
                {block.figure?.image_key && <img className="document-source-render"
                  src={block.figure.image_key} alt={block.figure.description || '解析出的图像区域'} />}
                {block.warnings.length > 0 && <small className="document-source-warning">{block.warnings.join('；')}</small>}
                {citations.length > 0 && <small>关联 Notebook：{citations.map((citation) => citation.notebook_title).join('、')}</small>}
              </article>
            }) : <p>此版本没有可展示的页面块；原始页仍可查看。</p>}
          </section>
          {coverage && <section className="document-source-coverage" aria-label="资料来源覆盖">
            <h4>来源覆盖 · {coverage.cited_blocks}/{coverage.total_blocks} 个解析块已关联</h4>
            {coverage.pages.length > 0 ? <div className="document-source-coverage-pages">
              {coverage.pages.map((item) => <button key={item.page_number} type="button"
                className={pageNumber === item.page_number ? 'is-active' : ''}
                onClick={() => setPageNumber(item.page_number)}>
                第 {item.page_number} 页 · {item.cited}/{item.total}
              </button>)}
            </div> : <p>当前解析版本没有可统计的页级来源覆盖。</p>}
          </section>}
          <details className="document-source-web-sources"><summary>联网补充来源 · {webSources.length}</summary>
            {webSources.length ? webSources.map((source) => <a key={source.id} href={source.url} target="_blank" rel="noreferrer">
              <strong>{source.title}</strong><small>{source.site_name} · {source.snippet}</small>
            </a>) : <p>这份资料没有保存联网补充来源。</p>}
          </details>
        </main>
      </div>}
    </section>
  </div>
}
