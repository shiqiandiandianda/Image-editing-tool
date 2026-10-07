# Codex CLI 图像编辑探针

后端默认使用 deterministic adapter，保证本地可测试且不会伪称 Codex 结果。设置 `FRAME_REPAIR_ADAPTER=codex_cli` 后，上传图片任务会通过同一个 CLI 适配器执行，预览只有在收到并校验真实图片产物时才标记 `codexVerified=true`。

适配器调用以下 CLI 能力：

- `codex exec --image ... --json --ephemeral`
- 每个任务使用独立临时工作目录和一张输入 PNG
- 解析 JSONL 中的 `image_generation_call.result`（raw base64 或 data URI）
- 兼容显式声明的 `artifact_path`/`output_path`
- 拒绝输入图片、工作区外路径、缺失产物和多个不同产物
- 不扫描默认生成目录中的“最新 PNG”

本地探针示例：

```powershell
python scripts/probe_codex_cli.py `
  --input .\input\crop.png `
  --output .\output\edited.png `
  --instruction "修复框选区域的手部结构，保持其他区域不变" `
  --codex "C:\Users\cantou\AppData\Local\OpenAI\Codex\bin\5ea220ae823df3d7\codex.exe"
```

成功只表示 CLI 返回了一个可解码图片产物，不表示它已经通过框外像素检查或正式版本审阅。`CODEX_UNREACHABLE`、`CODEX_CLI_FAILED`、`CODEX_ARTIFACT_MISSING` 和 `CODEX_ARTIFACT_AMBIGUOUS` 需要分别记录。

真实请求前应确认账号登录、图片能力、网络和额度；真实请求可能消耗额度。HTTP 服务启动示例：

```powershell
$env:FRAME_REPAIR_ADAPTER = "codex_cli"
uvicorn backend.app.main:app --reload --port 8000
```

接受预览会通过版本 CAS 写入正式 PNG 和 SQLite 状态。
