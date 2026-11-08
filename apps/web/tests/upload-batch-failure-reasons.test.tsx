import { expect, test } from 'vitest'

import { uploadBatchFailureMessage } from '../src/features/notebook-workspace/hooks/useNotebookGeneration'
import type { NotebookGenerationInputStatus, NotebookUploadBatch } from '../src/types'

function input(status: NotebookGenerationInputStatus['status'], error: string, code: string | null = null): NotebookGenerationInputStatus {
  return { asset_id: 'asset', parse_job_id: null, parse_result_fingerprint: null,
    generation_job_id: 'job', status, error_code: code, error_message: error, retry_count: 1 }
}

function batch(inputs: NotebookGenerationInputStatus[]): NotebookUploadBatch {
  return { id: 'batch', notebook_id: 'book', status: 'partial_failure',
    created_at: '', updated_at: '', closed_at: '', inputs, generation_jobs: [] }
}

test('budget configuration failure explains the cause and directs users to settings before retry', () => {
  const result = uploadBatchFailureMessage(batch([input('generation_failed',
    '预算价格来源 DEEPSEEK_PRICE_SOURCE 必须是无凭据的公开 HTTP(S) URL', 'budget_config_missing')]))
  expect(result.errorKind).toBe('generation')
  expect(result.message).toContain('文本价格来源 URL')
  expect(result.message).toContain('设置')
  expect(result.message).toContain('汇率')
  expect(result.message).not.toContain('DEEPSEEK_PRICE_SOURCE')
})

test('parse and generation failure reasons are both retained in a mixed batch', () => {
  const result = uploadBatchFailureMessage(batch([
    input('parse_failed', '第 3 页需要 OCR'), input('generation_failed', '模型请求超时'),
  ]))
  expect(result.errorKind).toBe('parse')
  expect(result.message).toContain('1 份资料解析失败')
  expect(result.message).toContain('1 份笔记生成失败')
  expect(result.message).toContain('第 3 页需要 OCR')
  expect(result.message).toContain('模型请求超时')
})

test('repeated reasons are shown once and batches without details retain an actionable fallback', () => {
  const result = uploadBatchFailureMessage(batch([
    input('generation_failed', '模型请求超时'), input('generation_failed', '模型请求超时'),
  ]))
  expect(result.message.match(/模型请求超时/g)).toHaveLength(1)
  expect(uploadBatchFailureMessage(batch([])).message).toContain('重试')
})
