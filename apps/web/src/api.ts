import { configApi } from './api/config'
import { courseApi } from './api/courses'
import { knowledgeApi } from './api/knowledge'
import { materialApi } from './api/materials'
import { noteApi } from './api/notes'
import { notebookApi } from './api/notebook'
import { conversationApi } from './api/conversations'
import { feedbackApi } from './api/feedback'
import { backupApi } from './api/backup'
import { termsApi } from './api/terms'

export { ApiError } from './api/http'
export type { Capabilities, ConnectivityTestPayload, OCRStatus, ProviderCall, ProviderStatus } from './api/config'

export const api = {
  ...courseApi,
  ...materialApi,
  ...noteApi,
  ...notebookApi,
  ...knowledgeApi,
  ...configApi,
  ...conversationApi,
  ...feedbackApi,
  ...backupApi,
  ...termsApi,
}
