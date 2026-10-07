# 前端 API 契约

前端通过 `VITE_API_BASE_URL` 选择后端模式；未配置时使用本地 deterministic adapter，仅用于界面联调，不代表 Codex 已执行。

## 图片上传

`POST /api/repair/assets`，前端发送原始图片字节，并带 `content-type` 与 `x-filename` 请求头；后端同时兼容带 `file` 字段的 multipart 请求。返回：

```json
{"id":"asset-…","name":"page.png","width":1600,"height":1000,"sha256":"…","versionId":"v0","src":"/api/repair/assets/…"}
```

`src`/`url` 可省略；前端会保留本地 object URL 作为预览。

## 任务

`POST /api/repair/jobs` 使用当前 `RepairSubmission` 字段，并同时发送 `Idempotency-Key` 请求头和 `idempotencyKey` 字段。`imageId` 可选，以兼容内置示例页。`GET /api/repair/jobs/{id}` 返回同一任务的最新执行状态，前端会在 `queued`/`running` 时轮询。

`RepairJob` 需要包含 `executionStatus`、`reviewStatus` 和可选 `preview`：

```json
{"status":"review","executionStatus":"preview_ready","reviewStatus":"pending","preview":{"available":true,"origin":"…","provider":"…","codexVerified":false,"applied":false,"previewUrl":"/…"}}
```

`POST /api/repair/jobs/{id}/accept` 和 `/reject` 返回更新后的完整任务对象；接受时如已形成正式版本，可返回 `acceptedVersionId`。取消使用 `/cancel`，返回 `executionStatus: "cancelled"`。
