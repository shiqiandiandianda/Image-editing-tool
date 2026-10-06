# 后端第一阶段架构

## 已落地的核心闭环

`VersionStore` 保存规范化底图快照、版本 ID 和像素 SHA-256。`JobManager.submit` 在快照上校验矩形边界、三种比例、说明和上下文扩边，并把目标框、参考框、输入哈希、底图版本和幂等键冻结到任务。

`JobManager.run_next` 以串行方式取一个任务，从冻结版本裁切参考图，经 `ImageEditorAdapter` 生成候选，严格检查候选与实际 `context_rect` 的比例，然后缩放回上下文尺寸、按 context 到 target 的偏移裁出目标子块，生成整页预览，并逐像素确认目标框外未改变。预览只写入任务对象，`accept` 通过底图版本 ID 与哈希条件检查后才创建新版本；版本变化会进入 `version_conflict`。

`UnconfiguredCodexAdapter` 是真实接入的明确阻塞点；`DeterministicTestAdapter` 仅供测试，结果来源始终标记为 `mock`。适配器边界为后续 app-server JSON-RPC、取消、事件和产物回收保留替换位置。

## 计划中的持久化接入

当前 milestone 的 `SQLiteStateStore` 已提供任务状态、幂等键、版本哈希和快照的事务性元数据保存，并保留按 `job_id/attempt_id` 隔离文件的替换位置。`JobManager` 的内存协调器仍是可替换的 worker 外壳；接入完整 SQLite worker 时，提交和幂等索引必须在同一事务中，不能把模型执行等待放在数据库事务内。生产图片编解码通过 Pillow 适配器提供，核心合成契约不改变。
