import type { RepairJob, RepairSubmission } from './types'

/**
 * Boundary for the eventual FastAPI frameRepair/* API.
 *
 * The current API is intentionally a local adapter: it never claims that a
 * Codex edit happened. When VITE_API_BASE_URL is set, submit/poll calls are
 * forwarded to the backend contract; otherwise jobs are kept in this browser
 * session and settle in `review` so the UI can be exercised safely.
 */
export interface RepairApi {
  submitRepair(payload: RepairSubmission): Promise<RepairJob>
  listJobs(): Promise<RepairJob[]>
  acceptJob(jobId: string): Promise<void>
  rejectJob(jobId: string): Promise<void>
}

const apiBase = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '')
const localJobs: RepairJob[] = []

const localAdapter: RepairApi = {
  async submitRepair(payload) {
    const now = new Date().toISOString()
    const job: RepairJob = {
      id: `local-${crypto.randomUUID()}`,
      annotationId: `annotation-${crypto.randomUUID()}`,
      status: 'review',
      ratio: payload.targetRatio,
      targetRect: payload.targetRect,
      contextRect: payload.contextRect,
      createdAt: now,
      issueText: payload.issueText,
    }
    localJobs.unshift(job)
    return job
  },
  async listJobs() {
    return [...localJobs]
  },
  async acceptJob(jobId) {
    const job = localJobs.find((item) => item.id === jobId)
    if (job) job.status = 'accepted'
  },
  async rejectJob(jobId) {
    const index = localJobs.findIndex((item) => item.id === jobId)
    if (index >= 0) localJobs.splice(index, 1)
  },
}

const httpAdapter: RepairApi = {
  async submitRepair(payload) {
    const response = await fetch(`${apiBase}/api/repair/jobs`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!response.ok) throw new Error(`提交失败 (${response.status})`)
    return (await response.json()) as RepairJob
  },
  async listJobs() {
    const response = await fetch(`${apiBase}/api/repair/jobs`)
    if (!response.ok) throw new Error(`任务读取失败 (${response.status})`)
    return (await response.json()) as RepairJob[]
  },
  async acceptJob(jobId) {
    const response = await fetch(`${apiBase}/api/repair/jobs/${encodeURIComponent(jobId)}/accept`, { method: 'POST' })
    if (!response.ok) throw new Error(`接受失败 (${response.status})`)
  },
  async rejectJob(jobId) {
    const response = await fetch(`${apiBase}/api/repair/jobs/${encodeURIComponent(jobId)}/reject`, { method: 'POST' })
    if (!response.ok) throw new Error(`撤销失败 (${response.status})`)
  },
}

export const repairApi: RepairApi = apiBase ? httpAdapter : localAdapter
export const isMockAdapter = !apiBase
