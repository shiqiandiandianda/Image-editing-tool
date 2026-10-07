import type { RepairJob, RepairSubmission, UploadedAsset } from './types'

/**
 * Typed HTTP boundary for the FastAPI image-repair API.
 *
 * The browser can run in local mode when VITE_API_BASE_URL is absent. Local mode
 * is deliberately marked synthetic and never claims a Codex image result. Set
 * VITE_API_BASE_URL (for example http://127.0.0.1:8000) to use the upload,
 * task, preview, and review endpoints.
 */
export interface RepairApi {
  uploadImage(file: File): Promise<UploadedAsset>
  submitRepair(payload: RepairSubmission): Promise<RepairJob>
  listJobs(includeRejected?: boolean): Promise<RepairJob[]>
  getJob(jobId: string): Promise<RepairJob>
  acceptJob(jobId: string): Promise<RepairJob>
  rejectJob(jobId: string): Promise<RepairJob>
  cancelJob(jobId: string): Promise<RepairJob>
}

const configuredApiBase = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim()
const useLocalAdapter = configuredApiBase === 'local' || configuredApiBase === 'mock'
const apiBase = (configuredApiBase && !useLocalAdapter ? configuredApiBase : 'http://127.0.0.1:8000').replace(/\/$/, '')
const localJobs: RepairJob[] = []

function newId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`
}

/** Resolve an API-returned relative preview/asset URL for the browser. */
export function resolveApiUrl(value: string | undefined): string | undefined {
  if (!value || /^(blob:|data:|https?:\/\/)/i.test(value) || !apiBase) return value
  return `${apiBase}${value.startsWith('/') ? '' : '/'}${value}`
}

function localAsset(file: File): Promise<UploadedAsset> {
  return new Promise((resolve, reject) => {
    const src = URL.createObjectURL(file)
    const image = new Image()
    image.onload = async () => {
      try {
        const bytes = new Uint8Array(await file.arrayBuffer())
        // The local adapter only needs a stable identity. SHA-256 is still
        // computed so the local payload has the same shape as HTTP uploads.
        const digest = await crypto.subtle.digest('SHA-256', bytes)
        const sha256 = Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, '0')).join('')
        resolve({ id: newId('asset'), name: file.name, width: image.naturalWidth, height: image.naturalHeight, sha256, versionId: 'local-current', src })
      } catch (error) {
        URL.revokeObjectURL(src)
        reject(error)
      }
    }
    image.onerror = () => { URL.revokeObjectURL(src); reject(new Error('图片无法读取')) }
    image.src = src
  })
}

const localAdapter: RepairApi = {
  async uploadImage(file) { return localAsset(file) },
  async submitRepair(payload) {
    const now = new Date().toISOString()
    const job: RepairJob = {
      id: newId('local'),
      annotationId: newId('annotation'),
      status: 'review',
      executionStatus: 'preview_ready',
      reviewStatus: 'pending',
      ratio: payload.targetRatio,
      targetRect: payload.targetRect,
      contextRect: payload.contextRect,
      createdAt: now,
      issueText: payload.issueText,
      pageId: payload.pageId,
      baseVersionId: payload.baseVersionId,
      adapter: 'local-deterministic',
      preview: { available: false, origin: 'deterministic_adapter', provider: 'local-deterministic', codexVerified: false, applied: false, message: '本地演示任务未执行 Codex 图片编辑。' },
      idempotencyKey: payload.idempotencyKey,
    }
    localJobs.unshift(job)
    return job
  },
  async listJobs(includeRejected = false) { return localJobs.filter((job) => includeRejected || job.status !== 'rejected').map((job) => ({ ...job })) },
  async getJob(jobId) {
    const job = localJobs.find((item) => item.id === jobId)
    if (!job) throw new Error('任务不存在')
    return { ...job }
  },
  async acceptJob(jobId) {
    const job = localJobs.find((item) => item.id === jobId)
    if (!job) throw new Error('任务不存在')
    job.status = 'accepted'; job.reviewStatus = 'accepted'; job.acceptedAt = new Date().toISOString()
    return { ...job }
  },
  async rejectJob(jobId) {
    const job = localJobs.find((item) => item.id === jobId)
    if (!job) throw new Error('任务不存在')
    job.status = 'rejected'; job.reviewStatus = 'rejected'; job.rejectedAt = new Date().toISOString()
    return { ...job }
  },
  async cancelJob(jobId) {
    const job = localJobs.find((item) => item.id === jobId)
    if (!job) throw new Error('任务不存在')
    job.status = 'cancelled'; job.executionStatus = 'cancelled'
    return { ...job }
  },
}

async function parseError(response: Response, fallback: string): Promise<Error> {
  let detail = ''
  try {
    const body = await response.json() as { detail?: { message?: string } | string }
    detail = typeof body.detail === 'string' ? body.detail : body.detail?.message ?? ''
  } catch { /* non-JSON error */ }
  return new Error(`${fallback} (${response.status})${detail ? `: ${detail}` : ''}`)
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, init)
  if (!response.ok) throw await parseError(response, '请求失败')
  return await response.json() as T
}

const httpAdapter: RepairApi = {
  async uploadImage(file) {
    return requestJson<UploadedAsset>('/api/repair/assets', {
      method: 'POST',
      headers: { 'content-type': file.type || 'application/octet-stream', 'x-filename': file.name },
      body: file,
    })
  },
  async submitRepair(payload) {
    const idempotencyKey = payload.idempotencyKey ?? newId('request')
    return requestJson<RepairJob>('/api/repair/jobs', {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ ...payload, idempotencyKey }),
    })
  },
  async listJobs(includeRejected = false) {
    return requestJson<RepairJob[]>(`/api/repair/jobs${includeRejected ? '?include_rejected=true' : ''}`)
  },
  async getJob(jobId) { return requestJson<RepairJob>(`/api/repair/jobs/${encodeURIComponent(jobId)}`) },
  async acceptJob(jobId) { return requestJson<RepairJob>(`/api/repair/jobs/${encodeURIComponent(jobId)}/accept`, { method: 'POST' }) },
  async rejectJob(jobId) { return requestJson<RepairJob>(`/api/repair/jobs/${encodeURIComponent(jobId)}/reject`, { method: 'POST' }) },
  async cancelJob(jobId) { return requestJson<RepairJob>(`/api/repair/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' }) },
}

export const repairApi: RepairApi = useLocalAdapter ? localAdapter : httpAdapter
export const isMockAdapter = useLocalAdapter
export const apiConfigured = !useLocalAdapter
