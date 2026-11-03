import { useEffect } from 'react'

import { useSettingsDraft } from './useSettingsDraft'
import { SIDEBAR_QUOTE_MAX_LENGTH } from '../features/navigation/sidebarQuote'

type SettingsPanelProps = {
  onClose: () => void
}

function connectionLabel(status: string | undefined): string {
  switch (status) {
    case 'connected': return '连接成功'
    case 'authentication_failed': return '认证失败（Key 无效）'
    case 'rate_limited': return '触发限流，请稍后再试'
    case 'timeout': return '连接超时'
    case 'unavailable': return '服务不可达'
    case 'configured_untested': return '已保存，尚未验证'
    case 'unconfigured': return '未配置 Key，无法测试'
    default: return status ?? '未知状态'
  }
}

function isFailure(status: string | undefined): boolean {
  return status === 'authentication_failed' || status === 'rate_limited'
    || status === 'timeout' || status === 'unavailable'
}

/** 设置面板：展示脱敏状态 + 写入白名单内的安全配置项。 */
export function SettingsPanel({ onClose }: SettingsPanelProps) {
  const {
    status, draft, secrets, token, setToken, loading, saving, testing, testResults,
    visionPreflightResult,
    error, setError, notice, changeCount, secretTouched, secretWriteReady,
    handleSave, handleTest, handleVisionPreflight, update, updateSecret,
    sidebarQuote, setSidebarQuote,
  } = useSettingsDraft()

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  return (
    <div className="settings-backdrop" onClick={onClose} role="presentation">
      <aside
        className="settings-panel"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="设置"
      >
        <header className="settings-header">
          <div>
            <span className="eyebrow">SETTINGS</span>
            <h3>本地配置</h3>
          </div>
          <button className="settings-close" onClick={onClose} aria-label="关闭设置">×</button>
        </header>

        <div className="settings-body">
          {loading && <div className="muted-block">正在读取配置…</div>}

          {error && (
            <div className="alert settings-alert" role="alert">
              <span>{error}</span>
              <button onClick={() => setError(undefined)}>关闭</button>
            </div>
          )}
          {notice && <div className="settings-notice">{notice}</div>}

          <section className="settings-section">
            <div className="settings-section-heading"><span>个性化</span><small>保存到当前浏览器</small></div>
            <label className="field">
              <span>侧边栏寄语</span>
              <textarea
                value={sidebarQuote}
                onChange={(event) => setSidebarQuote(event.target.value)}
                maxLength={SIDEBAR_QUOTE_MAX_LENGTH}
                rows={3}
                disabled={saving}
                aria-describedby="sidebar-quote-hint"
              />
            </label>
            <p className="field-hint" id="sidebar-quote-hint">显示在左下角，支持换行，最多 {SIDEBAR_QUOTE_MAX_LENGTH} 个字符。留空保存可恢复默认寄语。</p>
          </section>

          {status && draft && (
            <>
              <section className="settings-section">
                <div className="settings-section-heading"><span>文档处理</span><small>用于新上传的资料</small></div>
                <label className="field">
                  <span>默认文档处理路线</span>
                  <select aria-label="默认文档处理路线" value={draft.NOTEBOOK_DOCUMENT_PROCESSING_ROUTE}
                    disabled={saving} onChange={event => update('NOTEBOOK_DOCUMENT_PROCESSING_ROUTE', event.target.value)}>
                    <option value="standard">标准处理</option>
                    <option value="llm">全程 AI</option>
                  </select>
                </label>
                <p className="settings-hint">标准处理使用本地解析，再生成笔记。全程 AI 通过当前模型读取页面、组织笔记和知识联系，会增加 API 用量。切换仅影响新上传，已有任务和重试保持原路线。</p>
              </section>
              <section className="settings-section">
                <div className="settings-section-heading">
                  <span>能力状态</span>
                  <small>密钥仅显示掩码</small>
                </div>
                <div className="status-grid">
                  <div className={`status-card ${status.deepseek.configured ? 'status-on' : 'status-off'}`}>
                    <div className="status-card-top">
                      <strong>DeepSeek</strong>
                      <span className="status-pill">{status.deepseek.configured ? '已启用' : '未配置'}</span>
                    </div>
                    <small>{status.deepseek.configured ? `Key ${status.deepseek.masked_key}` : '当前走本地规则降级'}</small>
                  </div>
                  <div className={`status-card ${status.embedding.configured ? 'status-on' : 'status-off'}`}>
                    <div className="status-card-top">
                      <strong>Embedding</strong>
                      <span className="status-pill">{status.embedding.configured ? '已启用' : '未配置'}</span>
                    </div>
                    <small>{status.embedding.configured ? `Key ${status.embedding.masked_key}` : '当前仅关键词检索'}</small>
                  </div>
                  <div className={`status-card ${status.limits.secret_write_enabled ? 'status-on' : 'status-off'}`}>
                    <div className="status-card-top">
                      <strong>密钥写入</strong>
                      <span className="status-pill">
                        {status.limits.secret_write_enabled ? '已开启' : '已关闭'}
                      </span>
                    </div>
                    <small>
                      {status.limits.secret_write_enabled
                        ? status.limits.token_required
                          ? '填入口令后可写入 API Key'
                          : '可直接在页面写入 DeepSeek / Embedding Key'
                        : '需在 .env 中开启开关'}
                    </small>
                  </div>
                </div>
              </section>

              <section className="settings-section">
                <div className="settings-section-heading">
                  <span>视觉模型</span>
                  <small>仅用于文档页面图片识别</small>
                </div>
                <label className="field">
                  <span>视觉服务地址</span>
                  <input value={draft.NOTEBOOK_VISION_BASE_URL}
                    onChange={event => update('NOTEBOOK_VISION_BASE_URL', event.target.value)}
                    placeholder="https://api.example.com/v1" disabled={saving} />
                </label>
                <label className="field">
                  <span>视觉模型 ID</span>
                  <input value={draft.NOTEBOOK_VISION_MODEL}
                    onChange={event => update('NOTEBOOK_VISION_MODEL', event.target.value)}
                    placeholder="填写支持图片输入的模型 ID" disabled={saving} />
                </label>
                <label className="field">
                  <span>视觉请求超时（秒）</span>
                  <input value={draft.NOTEBOOK_VISION_TIMEOUT_SECONDS}
                    onChange={event => update('NOTEBOOK_VISION_TIMEOUT_SECONDS', event.target.value)}
                    inputMode="decimal" placeholder="60" disabled={saving} />
                </label>
                <label className="field">
                  <span>视觉 API Key{status.vision.masked_key && <em className="field-existing">当前：{status.vision.masked_key}</em>}</span>
                  <input type="password" value={secrets.NOTEBOOK_VISION_API_KEY}
                    onChange={event => updateSecret('NOTEBOOK_VISION_API_KEY', event.target.value)}
                    placeholder="留空表示不修改" autoComplete="new-password" spellCheck={false} disabled={saving} />
                </label>
                <div className="field actions-row">
                  <button className="secondary-button" type="button" disabled={testing !== null}
                    onClick={() => void handleVisionPreflight()}>
                    {testing === 'vision' ? '图片预检中…' : '预检图片输入能力'}
                  </button>
                  <span className="actions-hint">
                    {visionPreflightResult?.message ?? (status.vision.image_capability.supports_image_input
                      ? `已通过图片输入预检（${status.vision.image_capability.model ?? '当前模型'}）`
                      : '全程 AI 上传前必须先通过；预检会发送一张极小测试图片')}
                  </span>
                  {visionPreflightResult && <em className={visionPreflightResult.supports_image_input ? 'field-existing' : 'field-existing test-bad'}>
                    {visionPreflightResult.supports_image_input ? '图片输入可用' : `预检未通过：${visionPreflightResult.status}`}
                  </em>}
                </div>
                <p className="field-hint">视觉配置独立于文本模型。预检使用当前表单值；用于上传前请保存同一组配置。更换地址、模型或 Key 后需重新预检；未确认图片能力时，后端会拒绝全程 AI 上传。</p>
              </section>

              <section className="settings-section">
                <div className="settings-section-heading">
                  <span>模型服务</span>
                  <small>写入 .env 并立即生效</small>
                </div>
                <label className="field">
                  <span>DeepSeek 服务地址</span>
                  <input
                    value={draft.DEEPSEEK_BASE_URL}
                    onChange={(event) => update('DEEPSEEK_BASE_URL', event.target.value)}
                    placeholder="https://api.deepseek.com"
                  />
                </label>
                <label className="field">
                  <span>DeepSeek 模型</span>
                  <input
                    value={draft.DEEPSEEK_MODEL}
                    onChange={(event) => update('DEEPSEEK_MODEL', event.target.value)}
                    placeholder="deepseek-chat"
                  />
                </label>
                <label className="field">
                  <span>请求超时（秒）</span>
                  <input
                    value={draft.DEEPSEEK_TIMEOUT_SECONDS}
                    onChange={(event) => update('DEEPSEEK_TIMEOUT_SECONDS', event.target.value)}
                    placeholder="60"
                    inputMode="decimal"
                  />
                </label>
                <label className="field">
                  <span>
                    DeepSeek API Key
                    {status.deepseek.masked_key && (
                      <em className="field-existing">当前：{status.deepseek.masked_key}</em>
                    )}
                  </span>
                  <input
                    type="password"
                    value={secrets.DEEPSEEK_API_KEY}
                    onChange={(event) => updateSecret('DEEPSEEK_API_KEY', event.target.value)}
                    placeholder="留空表示不修改"
                    autoComplete="new-password"
                    spellCheck={false}
                  />
                </label>
                <div className="field actions-row">
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={testing !== null}
                    onClick={() => void handleTest('deepseek')}
                  >
                    {testing === 'deepseek' ? '测试中…' : '测试连接'}
                  </button>
                  <span className="actions-hint">按当前表单值测，支持在 DeepSeek / Embedding 间分别测试，无需先保存</span>
                  {testResults.deepseek && (
                    <em className={isFailure(testResults.deepseek.status) ? 'field-existing test-bad' : 'field-existing'}>
                      测试结果：{testResults.deepseek.message ?? connectionLabel(testResults.deepseek.status)}
                    </em>
                  )}
                </div>
              </section>
              <section className="settings-section">
                <div className="settings-section-heading"><span>文件处理预算</span><small>每个 Asset 累计上限 ¥10.00</small></div>
                <p className="field-hint">付费文件处理仅在价格和汇率快照完整时放行。请按供应商公开价格填写 USD / 百万 Token；视觉模型另填每张图片的 Token 上界。共享一次请求给多个文件时，会对每个文件分别预留整次费用，确保不借用其他文件额度。</p>
                <div className="settings-status-note">文本价格：{status.budget?.text?.ready ? `已配置 · ${status.budget?.text?.tariff_version}` : `未就绪 · ${status.budget?.text?.reason ?? '请补齐价格信息'}`}</div>
                <div className="settings-status-note">视觉价格：{status.budget?.vision?.ready ? `已配置 · ${status.budget?.vision?.tariff_version}` : `未就绪 · ${status.budget?.vision?.reason ?? '请补齐价格信息'}`}</div>
                {([
                  ['DEEPSEEK_INPUT_COST_PER_MILLION', '文本输入价（USD / 百万 Token）'],
                  ['DEEPSEEK_OUTPUT_COST_PER_MILLION', '文本输出价（USD / 百万 Token）'],
                  ['DEEPSEEK_PRICE_VERSION', '文本价格版本'],
                  ['DEEPSEEK_PRICE_SOURCE', '文本价格来源 URL'],
                  ['NOTEBOOK_VISION_INPUT_COST_PER_MILLION', '视觉输入价（USD / 百万 Token）'],
                  ['NOTEBOOK_VISION_OUTPUT_COST_PER_MILLION', '视觉输出价（USD / 百万 Token）'],
                  ['NOTEBOOK_VISION_MAX_IMAGE_TOKENS', '每张图片最大计价 Token'],
                  ['NOTEBOOK_VISION_PRICE_VERSION', '视觉价格版本'],
                  ['NOTEBOOK_VISION_PRICE_SOURCE', '视觉价格来源 URL'],
                  ['NOTEBOOK_BUDGET_USD_CNY_RATE', 'USD/CNY 汇率快照'],
                  ['NOTEBOOK_BUDGET_FX_RATE_SOURCE', '汇率来源 URL'],
                  ['NOTEBOOK_BUDGET_FX_RATE_AS_OF', '汇率日期（YYYY-MM-DD）'],
                  ['NOTEBOOK_BUDGET_FX_BUFFER_PERCENT', '汇率安全缓冲百分比'],
                ] as const).map(([key, label]) => <label className="field" key={key}>
                  <span>{label}</span>
                  <input value={draft[key]} onChange={event => update(key, event.target.value)} disabled={saving}
                    inputMode={key.includes('COST') || key.includes('RATE') || key.includes('TOKENS') || key.includes('BUFFER') ? 'decimal' : undefined} />
                </label>)}
              </section>

              <section className="settings-section">
                <div className="settings-section-heading">
                  <span>语义检索（可选）</span>
                  <small>三项需同时具备才生效</small>
                </div>
                <label className="field">
                  <span>Embedding 服务地址</span>
                  <input
                    value={draft.EMBEDDING_BASE_URL}
                    onChange={(event) => update('EMBEDDING_BASE_URL', event.target.value)}
                    placeholder="留空则使用关键词检索"
                  />
                </label>
                <label className="field">
                  <span>Embedding 模型</span>
                  <input
                    value={draft.EMBEDDING_MODEL}
                    onChange={(event) => update('EMBEDDING_MODEL', event.target.value)}
                    placeholder="例如 text-embedding-3-small"
                  />
                </label>
                <label className="field">
                  <span>
                    Embedding API Key
                    {status.embedding.masked_key && (
                      <em className="field-existing">当前：{status.embedding.masked_key}</em>
                    )}
                  </span>
                  <input
                    type="password"
                    value={secrets.EMBEDDING_API_KEY}
                    onChange={(event) => updateSecret('EMBEDDING_API_KEY', event.target.value)}
                    placeholder="留空表示不修改"
                    autoComplete="new-password"
                    spellCheck={false}
                  />
                </label>
                <div className="field actions-row">
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={testing !== null}
                    onClick={() => void handleTest('embedding')}
                  >
                    {testing === 'embedding' ? '测试中…' : '测试连接'}
                  </button>
                  {testResults.embedding && (
                    <em className={isFailure(testResults.embedding.status) ? 'field-existing test-bad' : 'field-existing'}>
                      测试结果：{testResults.embedding.message ?? connectionLabel(testResults.embedding.status)}
                    </em>
                  )}
                </div>
                <p className="field-hint">
                  三项（地址 / 密钥 / 模型）齐全后语义检索才会生效，否则自动回退为关键词检索。
                </p>
              </section>

              <section className="settings-section">
                <div className="settings-section-heading">
                  <span>本地存储</span>
                  <small>只读</small>
                </div>
                <label className="field">
                  <span>数据目录</span>
                  <input value={status.storage.data_dir} readOnly />
                </label>
                <label className="field">
                  <span>单文件上传上限（MB）</span>
                  <input
                    value={draft.NOTEBOOK_MAX_UPLOAD_MB}
                    onChange={(event) => update('NOTEBOOK_MAX_UPLOAD_MB', event.target.value)}
                    placeholder="50"
                    inputMode="numeric"
                  />
                </label>
                <label className="field">
                  <span>支持格式</span>
                  <input value={status.limits.allowed_extensions.join('、')} readOnly />
                </label>
              </section>

              <section className="settings-section">
                <div className="settings-section-heading">
                  <span>安全策略</span>
                  <small>运行时状态</small>
                </div>
                <div className="policy-list">
                  <div>
                    <span className={`policy-dot ${status.limits.secret_write_enabled ? 'dot-on' : 'dot-off'}`} />
                    密钥写入：{status.limits.secret_write_enabled ? '已允许' : '已禁用'}
                  </div>
                  <div>
                    <span className={`policy-dot ${status.limits.token_required ? 'dot-on' : 'dot-off'}`} />
                    设置口令：{status.limits.token_required ? '已配置' : '未配置'}
                  </div>
                  <div>
                    <span className="policy-dot dot-on" />
                    配置文件：{status.source.env_exists ? status.source.env_path : '尚未创建 .env'}
                  </div>
                </div>
                <details className="settings-details">
                  <summary>可修改的配置项（白名单）</summary>
                  <div className="key-chips">
                    {[...status.limits.editable_keys, 'DEEPSEEK_API_KEY', 'EMBEDDING_API_KEY', 'NOTEBOOK_VISION_API_KEY'].map((key) => (
                      <span className="key-chip" key={key}>{key}</span>
                    ))}
                  </div>
                </details>
                {status.limits.secret_write_enabled && status.limits.token_required ? (
                  <label className="field">
                    <span>设置口令（写入密钥必需）</span>
                    <input
                      type="password"
                      value={token}
                      onChange={(event) => setToken(event.target.value)}
                      placeholder="在 .env 的 NOTEBOOK_SETTINGS_TOKEN 中配置"
                      autoComplete="off"
                    />
                  </label>
                ) : status.limits.secret_write_enabled ? (
                  <p className="field-hint">
                    本地模式已默认允许密钥写入：在上方直接填入 DeepSeek / Embedding Key 并保存即可，
                    无需编辑 .env。如需加固，可在 .env 中配置{' '}
                    <code>NOTEBOOK_SETTINGS_TOKEN</code> 开启口令校验。
                  </p>
                ) : (
                  <p className="field-hint">
                    要开启密钥写入，请在 .env 中设置 NOTEBOOK_ALLOW_SECRET_WRITE=true 与
                    NOTEBOOK_SETTINGS_TOKEN，重启后端后在 <code>data/backups/</code> 可找到每次写入前的备份。
                  </p>
                )}
              </section>
            </>
          )}
        </div>

        <footer className="settings-footer">
          <span className="settings-dirty">
            {changeCount > 0
              ? `${changeCount} 项待保存${secretTouched.length > 0 ? '（含密钥）' : ''}`
              : '暂无改动'}
          </span>
          <div>
            <button className="ghost-button" onClick={onClose}>取消</button>
            <button
              className="primary-button"
              onClick={() => void handleSave()}
              disabled={saving || changeCount === 0}
            >
              {saving ? '保存中…' : '保存配置'}
            </button>
          </div>
        </footer>
      </aside>
    </div>
  )
}
