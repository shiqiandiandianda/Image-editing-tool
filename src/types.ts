export type Ratio = '1:1' | '16:9' | '9:16'

export type Rect = { x: number; y: number; w: number; h: number }

export type JobStatus = 'queued' | 'running' | 'review' | 'accepted' | 'failed'

export type RepairJob = {
  id: string
  annotationId: string
  status: JobStatus
  ratio: Ratio
  targetRect: Rect
  contextRect: Rect
  createdAt: string
  issueText: string
}

export type RepairSubmission = {
  pageId: string
  baseVersionId: string
  targetRatio: Ratio
  targetRect: Rect
  contextExpansionEnabled: boolean
  contextMarginPx: number
  contextRect: Rect
  issueText: string
  instruction: string
  preserveText: string
}

export type PageAsset = {
  id: string
  name: string
  width: number
  height: number
  src: string
  status: 'ready' | 'editing'
}
