export type Ratio = '1:1' | '16:9' | '9:16'

export type Rect = { x: number; y: number; w: number; h: number }

export type ExecutionStatus = 'queued' | 'running' | 'preview_ready' | 'failed' | 'cancelled' | 'interrupted' | 'version_conflict'
export type ReviewStatus = 'pending' | 'accepted' | 'rejected'
export type JobStatus = 'queued' | 'running' | 'review' | 'accepted' | 'failed' | 'rejected' | 'cancelled' | 'version_conflict' | 'interrupted'

export type PreviewInfo = {
  state?: 'ready'
  available: boolean
  origin: string
  provider: string
  codexVerified: boolean
  applied: boolean
  message?: string
  targetSize?: [number, number]
  contextSize?: [number, number]
  previewUrl?: string
  artifactUrl?: string
}

export type RepairJob = {
  id: string
  annotationId: string
  status: JobStatus
  executionStatus?: ExecutionStatus
  reviewStatus?: ReviewStatus
  ratio: Ratio
  targetRect: Rect
  contextRect: Rect
  createdAt: string
  issueText: string
  pageId?: string
  baseVersionId?: string
  adapter?: string
  preview?: PreviewInfo | null
  acceptedAt?: string | null
  rejectedAt?: string | null
  acceptedVersionId?: string | null
  errorCode?: string | null
  errorMessage?: string | null
  idempotencyKey?: string
}

export type RepairSubmission = {
  pageId: string
  /** Uploaded asset id. Kept optional for the sample page/local adapter. */
  imageId?: string
  baseVersionId: string
  targetRatio: Ratio
  targetRect: Rect
  contextExpansionEnabled: boolean
  contextMarginPx: number
  contextRect: Rect
  issueText: string
  instruction: string
  preserveText: string
  idempotencyKey?: string
}

export type UploadedAsset = {
  id: string
  name: string
  width: number
  height: number
  sha256: string
  versionId: string
  src?: string
  url?: string
}

export type PageAsset = {
  id: string
  name: string
  width: number
  height: number
  src: string
  status: 'ready' | 'editing' | 'uploading' | 'failed'
  imageId?: string
  versionId?: string
  sha256?: string
}
