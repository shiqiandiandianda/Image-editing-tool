# 画框框 · 局部返修工作台

React + TypeScript + Vite + react-konva 的前端 MVP。当前实现覆盖单张图片载入、三种目标比例框选、默认关闭的上下文扩边、返修说明、任务状态与预览审阅操作。

## 开发

```bash
npm install --cache /tmp/npm-cache
npm run dev
```

生产构建与类型检查：

```bash
npm run typecheck
npm run build
```

## 运行模式

- 未设置 `VITE_API_BASE_URL` 时使用浏览器内存适配器，提交任务会明确显示“本地演示任务”，不会伪称 Codex 已执行。
- 设置 `VITE_API_BASE_URL` 后，适配器调用图片上传、任务提交/轮询、预览、接受、拒绝和取消接口；接受预览会通过版本 CAS 保存正式 PNG 和 SQLite 状态。
- 默认后端使用 deterministic adapter 生成可审阅的本地预览，明确标记 `codexVerified=false`。设置 `FRAME_REPAIR_ADAPTER=codex_cli` 后，上传图片任务会调用 Codex CLI；只有收到并校验真实图片产物时才标记为 Codex 结果。
- 框坐标以规范化底图像素为世界坐标；拖拽完成后按所选比例量化为整数尺寸。上下文扩边只改变参考矩形，不改变写入矩形。

## 目录

- `src/main.tsx`：画布、标注与面板交互
- `src/api.ts`：后端适配边界和本地安全占位
- `src/types.ts`：任务/矩形/页面类型
- `src/styles.css`：工作台视觉样式


## FastAPI 本地 API

后端默认使用本地 deterministic adapter，上传图片后会实际生成 PNG 预览并保存任务状态：

```powershell
python -m pip install -e .
uvicorn backend.app.main:app --reload --port 8000
```

启用 Codex CLI：

```powershell
$env:FRAME_REPAIR_ADAPTER = "codex_cli"
uvicorn backend.app.main:app --reload --port 8000
```

设置 `VITE_API_BASE_URL=http://localhost:8000` 后，前端调用：

- `POST /api/repair/assets`
- `GET/POST /api/repair/jobs`
- `GET /api/repair/jobs/:id`、`GET /api/repair/previews/:id`
- `POST /api/repair/jobs/:id/accept`、`/reject`、`/cancel`

创建上传图片任务会同步执行串行 worker，返回 `status=review`、`executionStatus=preview_ready`、`reviewStatus=pending` 和预览 URL。未上传 `imageId` 的内置示例页仍走元数据兼容路径。

后端测试：

```bash
python -m unittest discover -s backend/tests -v
```
