import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Image as KonvaImage, Layer, Line, Rect as KonvaRect, Stage, Text as KonvaText } from 'react-konva'
import type Konva from 'konva'
import './styles.css'
import { apiConfigured, isMockAdapter, repairApi, resolveApiUrl } from './api'
import type { PageAsset, Ratio, Rect, RepairJob, RepairSubmission, UploadedAsset } from './types'

const ratioOptions: Array<{ value: Ratio; label: string; hint: string }> = [
  { value: '1:1', label: '1 : 1', hint: '正方形' },
  { value: '16:9', label: '16 : 9', hint: '横向' },
  { value: '9:16', label: '9 : 16', hint: '竖向' },
]

const sampleSvg = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000" viewBox="0 0 1600 1000"><defs><linearGradient id="g" x2="1" y2="1"><stop stop-color="#202b46"/><stop offset="1" stop-color="#101827"/></linearGradient></defs><rect width="1600" height="1000" fill="url(#g)"/><circle cx="420" cy="440" r="205" fill="#efb583"/><path d="M250 790c95-220 470-225 575 0" fill="#7f93d8"/><path d="M960 250h370v460H960z" fill="#182237" stroke="#6077c5" stroke-width="5"/><path d="M1030 600c100-210 190-170 250-70 35 57 90 22 120-40" fill="none" stroke="#f4c47c" stroke-width="18" stroke-linecap="round"/><text x="70" y="100" fill="#e9efff" font-size="44" font-family="sans-serif">画框框 / SAMPLE PAGE</text><text x="70" y="150" fill="#91a2cc" font-size="24" font-family="sans-serif">导入图片后，在画布上拖出需要返修的区域</text></svg>`)} `

function useImage(src: string | null) {
  const [image, setImage] = useState<HTMLImageElement | null>(null)
  useEffect(() => {
    if (!src) { setImage(null); return }
    const next = new window.Image()
    next.onload = () => setImage(next)
    next.src = src
  }, [src])
  return image
}

function parseRatio(ratio: Ratio) {
  const [w, h] = ratio.split(':').map(Number)
  return w / h
}

function constrainRect(startX: number, startY: number, endX: number, endY: number, ratio: Ratio, imageW: number, imageH: number): Rect {
  const aspect = parseRatio(ratio)
  const directionX = endX >= startX ? 1 : -1
  const directionY = endY >= startY ? 1 : -1
  let width = Math.max(24, Math.abs(endX - startX))
  let height = width / aspect
  if (height > Math.abs(endY - startY)) {
    height = Math.max(24, Math.abs(endY - startY))
    width = height * aspect
  }
  width = Math.min(width, imageW)
  height = Math.min(height, imageH)
  let x = directionX > 0 ? startX : startX - width
  let y = directionY > 0 ? startY : startY - height
  x = Math.max(0, Math.min(imageW - width, x))
  y = Math.max(0, Math.min(imageH - height, y))
  return { x, y, w: width, h: height }
}

function integerRect(rect: Rect, ratio: Ratio, imageW: number, imageH: number): Rect {
  const [rw, rh] = ratio.split(':').map(Number)
  let k = Math.max(1, Math.round(Math.min(rect.w / rw, rect.h / rh)))
  k = Math.max(1, Math.min(k, Math.floor(imageW / rw), Math.floor(imageH / rh)))
  const w = rw * k
  const h = rh * k
  return {
    x: Math.max(0, Math.min(imageW - w, Math.round(rect.x))),
    y: Math.max(0, Math.min(imageH - h, Math.round(rect.y))),
    w,
    h,
  }
}

function expandRect(rect: Rect, margin: number, imageW: number, imageH: number): Rect {
  const x = Math.max(0, Math.floor(rect.x - margin))
  const y = Math.max(0, Math.floor(rect.y - margin))
  const right = Math.min(imageW, Math.ceil(rect.x + rect.w + margin))
  const bottom = Math.min(imageH, Math.ceil(rect.y + rect.h + margin))
  return { x, y, w: right - x, h: bottom - y }
}

function App() {
  const [pages, setPages] = useState<PageAsset[]>([
    { id: 'sample-page', name: 'sample-page.svg', width: 1600, height: 1000, src: sampleSvg, status: 'ready' },
  ])
  const [activePageId, setActivePageId] = useState('sample-page')
  const [ratio, setRatio] = useState<Ratio>('1:1')
  const [targetRect, setTargetRect] = useState<Rect>({ x: 430, y: 250, w: 300, h: 300 })
  const [contextEnabled, setContextEnabled] = useState(false)
  const [contextMargin, setContextMargin] = useState(80)
  const [issueText, setIssueText] = useState('')
  const [instruction, setInstruction] = useState('')
  const [preserveText, setPreserveText] = useState('保留原有画风、光影与构图')
  const [jobs, setJobs] = useState<RepairJob[]>([])
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [isDrawing, setIsDrawing] = useState(false)
  const drawOrigin = useRef<{ x: number; y: number } | null>(null)
  const canvasWrapRef = useRef<HTMLDivElement>(null)
  const [canvasSize, setCanvasSize] = useState({ width: 800, height: 580 })
  const fileInputRef = useRef<HTMLInputElement>(null)
  const activePage = pages.find((page) => page.id === activePageId) ?? pages[0]
  const activeJob = jobs.find((job) => job.id === activeJobId)
  const activePreviewUrl = resolveApiUrl(activeJob?.preview?.previewUrl ?? activeJob?.preview?.artifactUrl)
  const image = useImage(activePage?.src ?? null)
  const contextRect = useMemo(() => expandRect(targetRect, contextEnabled ? contextMargin : 0, activePage?.width ?? 1, activePage?.height ?? 1), [targetRect, contextEnabled, contextMargin, activePage])
  const scale = useMemo(() => Math.min((canvasSize.width - 40) / (activePage?.width ?? 1), (canvasSize.height - 40) / (activePage?.height ?? 1)), [canvasSize, activePage])
  const stageWidth = (activePage?.width ?? 1) * scale
  const stageHeight = (activePage?.height ?? 1) * scale

  useEffect(() => {
    if (!canvasWrapRef.current) return
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect
      if (rect) setCanvasSize({ width: Math.max(380, rect.width), height: Math.max(380, rect.height) })
    })
    observer.observe(canvasWrapRef.current)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    repairApi.listJobs().then(setJobs).catch(() => undefined)
  }, [])

  // A real worker may finish after the POST response. Poll only the selected
  // job and stop once it reaches a terminal execution/review state.
  useEffect(() => {
    if (!activeJobId || isMockAdapter) return
    let cancelled = false
    let timer: number | undefined
    const poll = async () => {
      try {
        const latest = await repairApi.getJob(activeJobId)
        if (cancelled) return
        setJobs((previous) => previous.map((item) => item.id === latest.id ? latest : item))
        if (latest.executionStatus === 'queued' || latest.executionStatus === 'running') {
          timer = window.setTimeout(poll, 1500)
        }
      } catch {
        if (!cancelled) timer = window.setTimeout(poll, 2500)
      }
    }
    void poll()
    return () => { cancelled = true; if (timer !== undefined) window.clearTimeout(timer) }
  }, [activeJobId])

  const toWorld = useCallback((event: Konva.KonvaEventObject<MouseEvent>) => {
    const stage = event.target.getStage()
    const pointer = stage?.getPointerPosition()
    if (!pointer) return null
    return { x: Math.max(0, Math.min(activePage.width, pointer.x / scale - 20 / scale)), y: Math.max(0, Math.min(activePage.height, pointer.y / scale - 20 / scale)) }
  }, [activePage, scale])

  const onCanvasDown = (event: Konva.KonvaEventObject<MouseEvent>) => {
    // Start a new selection on the stage or source image. Existing overlays
    // keep their own drag behavior and should not also start a new selection.
    const className = event.target.getClassName()
    if (className === 'Rect' || className === 'Text') return
    const world = toWorld(event)
    if (!world) return
    drawOrigin.current = world
    setIsDrawing(true)
  }
  const onCanvasMove = (event: Konva.KonvaEventObject<MouseEvent>) => {
    if (!isDrawing || !drawOrigin.current) return
    const world = toWorld(event)
    if (world) setTargetRect(constrainRect(drawOrigin.current.x, drawOrigin.current.y, world.x, world.y, ratio, activePage.width, activePage.height))
  }
  const onCanvasUp = () => {
    if (!isDrawing) return
    setIsDrawing(false)
    drawOrigin.current = null
    setTargetRect((rect) => integerRect(rect, ratio, activePage.width, activePage.height))
  }

  const onMoveRect = (event: Konva.KonvaEventObject<DragEvent>) => {
    const node = event.target
    const x = Math.max(0, Math.min(activePage.width - targetRect.w, node.x() / scale - 20 / scale))
    const y = Math.max(0, Math.min(activePage.height - targetRect.h, node.y() / scale - 20 / scale))
    setTargetRect((rect) => ({ ...rect, x: Math.round(x), y: Math.round(y) }))
  }

  const onFile = async (file: File) => {
    if (!file.type.startsWith('image/')) { setNotice('请选择 PNG、JPEG 或 WebP 图片'); return }
    const src = URL.createObjectURL(file)
    const probe = new window.Image()
    probe.onload = async () => {
      let uploaded: UploadedAsset
      try {
        setNotice(`正在上传 ${file.name}…`)
        uploaded = await repairApi.uploadImage(file)
      } catch (error) {
        URL.revokeObjectURL(src)
        setNotice(error instanceof Error ? error.message : '图片上传失败')
        return
      }
      const displaySrc = resolveApiUrl(uploaded.src ?? uploaded.url) ?? src
      if (displaySrc !== src) URL.revokeObjectURL(src)
      const page: PageAsset = {
        id: uploaded.id,
        imageId: uploaded.id,
        versionId: uploaded.versionId,
        sha256: uploaded.sha256,
        name: uploaded.name || file.name,
        width: uploaded.width || probe.naturalWidth,
        height: uploaded.height || probe.naturalHeight,
        src: displaySrc,
        status: 'ready',
      }
      setPages((previous) => [...previous, page])
      setActivePageId(page.id)
      setTargetRect({ x: Math.round(page.width * 0.3), y: Math.round(page.height * 0.3), w: Math.max(24, Math.round(Math.min(page.width, page.height) * 0.2)), h: Math.max(24, Math.round(Math.min(page.width, page.height) * 0.2)) })
      setNotice(`已载入 ${file.name}`)
    }
    probe.src = src
  }

  const submit = async () => {
    if (!issueText.trim() || !instruction.trim()) { setNotice('请填写问题说明和修改要求后再提交'); return }
    setIsSubmitting(true)
    setNotice(null)
    const payload: RepairSubmission = { pageId: activePage.id, imageId: activePage.imageId, baseVersionId: activePage.versionId ?? 'local-current', targetRatio: ratio, targetRect, contextExpansionEnabled: contextEnabled, contextMarginPx: contextEnabled ? contextMargin : 0, contextRect, issueText: issueText.trim(), instruction: instruction.trim(), preserveText: preserveText.trim() }
    try {
      const job = await repairApi.submitRepair(payload)
      setJobs((previous) => [job, ...previous.filter((item) => item.id !== job.id)])
      setActiveJobId(job.id)
      setNotice(isMockAdapter ? '已创建本地演示任务，等待真实 Codex RPC 接入' : '任务已提交')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '任务提交失败')
    } finally { setIsSubmitting(false) }
  }

  const accept = async () => {
    if (!activeJobId) return
    try {
      const accepted = await repairApi.acceptJob(activeJobId)
      setJobs((previous) => previous.map((item) => item.id === activeJobId ? accepted : item))
      if (accepted.acceptedVersionId && accepted.pageId) {
        const currentSrc = apiConfigured ? resolveApiUrl(`/api/repair/assets/${accepted.pageId}/current`) : undefined
        setPages((previous) => previous.map((page) => page.id === accepted.pageId || page.imageId === accepted.pageId
          ? { ...page, versionId: accepted.acceptedVersionId, ...(currentSrc ? { src: currentSrc } : {}) }
          : page))
      }
      setNotice('已接受预览，正式版本已由后端记录')
    } catch (error) { setNotice(error instanceof Error ? error.message : '接受失败') }
  }
  const reject = async () => {
    if (!activeJobId) return
    try {
      const current = jobs.find((item) => item.id === activeJobId)
      const rejected = current?.executionStatus === 'queued' || current?.executionStatus === 'running'
        ? await repairApi.cancelJob(activeJobId)
        : await repairApi.rejectJob(activeJobId)
      setJobs((previous) => previous.map((item) => item.id === activeJobId ? rejected : item))
      setNotice(rejected.status === 'cancelled' ? '已取消任务' : '已撤销当前预览')
    } catch (error) { setNotice(error instanceof Error ? error.message : '撤销失败') }
  }
  const exportPage = () => {
    if (!image) return
    const canvas = document.createElement('canvas')
    canvas.width = activePage.width; canvas.height = activePage.height
    const context = canvas.getContext('2d')
    if (!context) return
    context.drawImage(image, 0, 0)
    const anchor = document.createElement('a')
    anchor.href = canvas.toDataURL('image/png')
    anchor.download = `${activePage.name.replace(/\.[^/.]+$/, '')}-preview.png`
    anchor.click()
    setNotice('已导出当前页面预览（未应用 AI 补丁）')
  }

  return <div className="app-shell">
    <header className="topbar">
      <div className="brand"><span className="brand-mark">▱</span><div><strong>画框框</strong><span>局部返修工作台</span></div></div>
      <div className="topbar-meta"><span className="connection-dot" /> <span>本地工作区</span><span className="version-chip">MVP · 0.1</span></div>
    </header>
    <div className="workspace">
      <aside className="sidebar">
        <div className="sidebar-heading"><div><span className="eyebrow">项目 / 第 21 话</span><h2>分镜返修</h2></div><button className="icon-button" aria-label="项目设置">•••</button></div>
        <button className="upload-button" onClick={() => fileInputRef.current?.click()}><span>＋</span> 导入图片</button>
        <input ref={fileInputRef} type="file" hidden accept="image/png,image/jpeg,image/webp,image/svg+xml" onChange={(event) => { const file = event.target.files?.[0]; if (file) onFile(file); event.currentTarget.value = '' }} />
        <div className="page-list-label">页面 <span>{pages.length}</span></div>
        <div className="page-list">{pages.map((page, index) => <button className={`page-card ${page.id === activePageId ? 'active' : ''}`} key={page.id} onClick={() => setActivePageId(page.id)}><img src={page.src} alt="" /><span><b>P{String(index + 1).padStart(2, '0')}</b>{page.name}</span><small>{page.width} × {page.height}</small></button>)}</div>
        <div className="sidebar-footer"><div className="runtime-status"><span className="status-icon">✓</span><div><b>运行状态</b><span>等待编辑任务</span></div></div><div className="runtime-status muted"><span className="status-icon">⌘</span><div><b>Codex 图片能力</b><span>待接入 / 未探测</span></div></div></div>
      </aside>
      <main className="main-column">
        <div className="canvas-toolbar"><div className="breadcrumb">第 21 话 <span>/</span> <b>{activePage.name}</b></div><div className="toolbar-actions"><button className="ghost-button">适应窗口</button><button className="ghost-button">100%</button><span className="divider" /><button className="ghost-button">↶ 撤销</button></div></div>
        <div className="canvas-wrap" ref={canvasWrapRef}><div className="canvas-stage" style={{ width: stageWidth, height: stageHeight }}><Stage width={stageWidth + 40} height={stageHeight + 40} onMouseDown={onCanvasDown} onMouseMove={onCanvasMove} onMouseUp={onCanvasUp} onMouseLeave={onCanvasUp}><Layer><KonvaImage image={image ?? undefined} x={20} y={20} width={stageWidth} height={stageHeight} /><KonvaRect x={20 + contextRect.x * scale} y={20 + contextRect.y * scale} width={contextRect.w * scale} height={contextRect.h * scale} stroke="#8c9bba" strokeWidth={1} dash={[6, 5]} opacity={contextEnabled ? 0.75 : 0} listening={false} /><KonvaRect x={20 + targetRect.x * scale} y={20 + targetRect.y * scale} width={targetRect.w * scale} height={targetRect.h * scale} fill="rgba(93, 116, 221, 0.12)" stroke="#7c91ff" strokeWidth={2} draggable dragBoundFunc={(position) => ({ x: Math.max(20, Math.min(20 + stageWidth - targetRect.w * scale, position.x)), y: Math.max(20, Math.min(20 + stageHeight - targetRect.h * scale, position.y)) })} onDragEnd={onMoveRect} /><KonvaRect x={20 + targetRect.x * scale} y={20 + targetRect.y * scale - 24} width={58} height={21} fill="#7488ed" cornerRadius={4} listening={false} /><KonvaText x={28 + targetRect.x * scale} y={20 + targetRect.y * scale - 20} text="框 01" fontSize={12} fill="#fff" listening={false} /></Layer></Stage></div><div className="canvas-hint"><span className="crosshair">＋</span> 拖拽画框 · 拖动边框调整位置</div></div>
        <div className="bottom-status"><div><span className="pulse" />当前页已载入 <b>{activePage.width} × {activePage.height}</b></div><div>坐标 <b>{Math.round(targetRect.x)}, {Math.round(targetRect.y)}</b> · 区域 <b>{Math.round(targetRect.w)} × {Math.round(targetRect.h)}</b></div></div>
      </main>
      <aside className="inspector">
        <div className="inspector-title"><div><span className="eyebrow">当前标注</span><h2>框 01</h2></div><span className="draft-pill">草稿</span></div>
        <section className="panel-section"><label className="section-label">目标比例 <span>锁定裁切比例</span></label><div className="ratio-grid">{ratioOptions.map((item) => <button key={item.value} className={ratio === item.value ? 'selected' : ''} onClick={() => { setRatio(item.value); setTargetRect((rect) => integerRect(rect, item.value, activePage.width, activePage.height)) }}><b>{item.label}</b><small>{item.hint}</small></button>)}</div></section>
        <section className="panel-section context-section"><div className="toggle-row"><div><label className="section-label">上下文扩边</label><span className="helper-text">扩大模型参考范围，不改变写入区域</span></div><button className={`toggle ${contextEnabled ? 'on' : ''}`} onClick={() => setContextEnabled((value) => !value)} aria-pressed={contextEnabled}><span /></button></div>{contextEnabled && <div className="margin-row"><label>扩边像素</label><input type="number" min="0" max="800" value={contextMargin} onChange={(event) => setContextMargin(Math.max(0, Number(event.target.value) || 0))} /><span>px</span></div>}<div className="rect-summary"><span className="legend target" />写入区域 <b>{Math.round(targetRect.w)} × {Math.round(targetRect.h)}</b><span className="legend context" />参考区域 <b>{Math.round(contextRect.w)} × {Math.round(contextRect.h)}</b></div></section>
        <section className="panel-section form-section"><label className="section-label" htmlFor="issue">问题说明 <em>*</em></label><textarea id="issue" value={issueText} onChange={(event) => setIssueText(event.target.value)} placeholder="例如：右手手指结构异常" rows={3} /><label className="section-label" htmlFor="instruction">修改要求 <em>*</em></label><textarea id="instruction" value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="描述希望如何修改" rows={3} /><label className="section-label" htmlFor="preserve">必须保留</label><textarea id="preserve" value={preserveText} onChange={(event) => setPreserveText(event.target.value)} rows={2} /></section>
        <div className="submit-area"><button className="primary-button" onClick={submit} disabled={isSubmitting}>{isSubmitting ? '提交中…' : '提交返修任务'} <span>⌘ ↵</span></button><p>提交后将冻结当前底图版本，生成结果需人工接受后才会应用。</p></div>
        {notice && <div className="notice" role="status">{notice}</div>}
        {activePreviewUrl && activeJob?.preview?.available && <div className="preview-card">
          <div className="jobs-heading"><label className="section-label">生成预览</label><span>{activeJob.preview.codexVerified ? 'Codex' : activeJob.preview.provider}</span></div>
          <img src={activePreviewUrl} alt="返修结果预览" />
        </div>}
        <section className="panel-section jobs-section"><div className="jobs-heading"><label className="section-label">任务状态</label><span>{jobs.length} 个任务</span></div>{jobs.length === 0 ? <div className="empty-jobs">提交后，任务会出现在这里</div> : <div className="jobs-list">{jobs.slice(0, 4).map((job) => <button className={`job-row ${job.id === activeJobId ? 'active' : ''}`} key={job.id} onClick={() => setActiveJobId(job.id)}><span className={`job-dot ${job.status}`} /><div><b>{job.issueText || '未命名修复'}</b><small>{job.ratio} · {new Date(job.createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</small></div><span className="job-status">{({ queued: '排队', running: '执行中', review: '待审阅', accepted: '已接受', failed: '失败', rejected: '已撤销', cancelled: '已取消', interrupted: '中断', version_conflict: '版本冲突' } as Record<string, string>)[job.status]}</span></button>)}</div>}</section>
        <div className="review-actions"><button className="secondary-button" disabled={!activeJobId || activeJob?.status === 'accepted' || activeJob?.status === 'rejected' || activeJob?.status === 'cancelled'} onClick={reject}>撤销</button><button className="secondary-button" disabled={!activeJobId || activeJob?.status !== 'review' || (!isMockAdapter && !activeJob?.preview?.available)} onClick={accept}>接受预览</button><button className="export-button" onClick={exportPage}>导出 PNG ↗</button></div>
      </aside>
    </div>
  </div>
}

export default App
