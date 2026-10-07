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

## 当前边界

- 未设置 `VITE_API_BASE_URL` 时使用浏览器内存适配器，提交任务会明确显示“本地演示任务”，不会伪称 Codex 已执行。
- 设置 `VITE_API_BASE_URL` 后，适配器调用预留的 `/api/repair/jobs`、`POST /api/repair/jobs/:id/accept` 和 `POST /api/repair/jobs/:id/reject`；字段采用技术方案里的 `frameRepair` 任务快照命名。
- “接受预览”和“导出 PNG”目前只更新前端状态/导出当前底图，正式版本合成仍等待 FastAPI Worker 和 Codex RPC 接入。
- 框坐标以规范化底图像素为世界坐标；拖拽完成后按所选比例量化为整数尺寸。上下文扩边只改变参考矩形，不改变写入矩形。

## 目录

- `src/main.tsx`：画布、标注与面板交互
- `src/api.ts`：后端适配边界和本地安全占位
- `src/types.ts`：任务/矩形/页面类型
- `src/styles.css`：工作台视觉样式
