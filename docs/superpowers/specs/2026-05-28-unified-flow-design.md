# 统一图片来源 + 共用视频生成流程 设计文档

> 状态：已确认 | 2026-05-28

## 目标

将"文生图"和"上传图片"两个独立 Tab 合并为单一页面，两种图片来源汇聚到同一个 `IMAGE_READY` 状态后，复用完全相同的视频生成流程。同时融入上一轮计划的进度面板重构。

## 架构概览

```
用户输入
  ├── A. AI 生成图片 → /api/generate-image → GPT → IMAGE_READY
  └── B. 上传本地图片  → /api/upload-image   → 直接 IMAGE_READY

IMAGE_READY（统一状态）
  └── 用户点击"生成 Live Photo" → /api/generate-video
        ├── Seedance 视频生成（API/CLI）
        ├── FFmpeg 格式转换（HEIC + MOV）
        └── 打包 ZIP → DONE
```

## 后端变更

### 端点

| 端点 | 方法 | 变更 |
|------|------|------|
| `/api/generate-image` | POST | 不变 |
| `/api/upload-image` | POST | **新增** — 上传图片，存入 base64，直接设 IMAGE_READY |
| `/api/generate-video` | POST | 不变 |
| `/api/upload-and-generate` | POST | **删除** |
| `/api/status/{task_id}` | GET | 增强 — 返回 progress_timeline、elapsed_seconds |
| `/api/download/{task_id}` | GET | 不变 |

### `/api/upload-image` 规格

- 接收 `multipart/form-data`，字段 `file`（图片，最大 20MB）
- 创建 Task，将图片 base64 编码存入 `image_base64`
- 直接设 `TaskStatus.IMAGE_READY`，无后台任务
- 返回 `{task_id, dedup: false}`

### Task 模型扩展（融入上一轮进度面板设计）

新增字段：
- `progress_timeline: list[dict]` — 事件日志，每项 `{ts, message}`
- `elapsed_seconds: float` — 当前步骤耗时
- `step_started_at: float` — 当前步骤开始时间戳

### Pipeline 进度事件

在 `run_image_only`、`run_video_pipeline` 各关键节点写入 timeline_event：
- 图片生成开始/完成
- 视频提交到 Seedance
- 每次 poll 轮询（API 模式）
- 视频下载完成
- 格式转换/打包开始与完成

### Seedance API poll 进度回调

`APIMode.poll()` 新增 `on_progress` 回调参数，每次轮询后调用，通知当前耗时和轮询次数。

## 前端变更

### 布局（单页面，无 Tab）

```
┌─ Mode Toggle (API / CLI) ─────────────────┐
│                                            │
│  ┌─ A. AI 生成图片 ────────────────────┐  │
│  │  [textarea] [生成图片]              │  │
│  └──────────────────────────────────────┘  │
│                                            │
│              ——— 或 ———                    │
│                                            │
│  ┌─ B. 上传图片 ───────────────────────┐  │
│  │  📁 点击或拖拽上传                   │  │
│  └──────────────────────────────────────┘  │
│                                            │
│  ┌─ C. 图片预览 + 视频设置 ────────────┐  │
│  │  (IMAGE_READY 后显示)                │  │
│  │  [预览图] [视频提示词] [设置] [生成] │  │
│  └──────────────────────────────────────┘  │
│                                            │
│  ┌─ D. 进度面板 ───────────────────────┐  │
│  │  (生成中显示)                        │  │
│  │  步骤指示器 ①→②→③                   │  │
│  │  进度条 + 耗时                       │  │
│  │  事件日志                            │  │
│  └──────────────────────────────────────┘  │
└────────────────────────────────────────────┘
```

### 删除的 UI 组件

- `.tab-bar` / `.tab` — Tab 切换
- `#panel-upload` — 上传 Tab 面板
- `#upload-preview-card` — 上传预览卡片（复用 `#preview-card`）
- `#upload-video-settings` — 上传视频设置（复用 `#video-settings`）
- `#preview-progress` — 旧的预览进度（替换为 `#progress-panel`）
- `#status-area` — 旧的状态区（替换为 `#progress-panel`）
- `#upload-btn` — 上传按钮（图片上传后直接进入预览）
- `showUploadSettings()` 函数

### 删除的 JS 变量

- `selectedFile` — 上传后直接设 IMAGE_READY，无需保持文件引用
- `uploadLastFrameB64` — 复用 `lastFrameB64`
- `imagePrompt` — 仅在文生图路径使用局部 prompt 变量

### 交互流程

1. **AI 生成图片：** 输入 prompt → 点击"生成图片" → 显示进度面板 → IMAGE_READY → 显示 C 区预览
2. **上传图片：** 选择文件 → 直接 POST `/api/upload-image` → IMAGE_READY → 显示 C 区预览
3. **生成视频：** 在 C 区设置参数 → 点击"生成 Live Photo" → `/api/generate-video` → 显示 D 区进度面板 → 轮询 → DONE → 下载
4. **Session 恢复：** 刷新页面后，根据 localStorage 中保存的 task_id 恢复轮询

## 与进度面板重构的关系

本设计直接融入上一轮 `2026-05-28-progress-ui-redesign.md` 计划的进度面板设计（步骤指示器、事件日志、耗时徽章）。区别在于：

- 进度面板不再需要区分 `startImagePolling` / `startVideoPolling` 两套函数 — 统一为一个带 mode 参数的轮询函数
- 请求信息区域显示内容根据来源自动适配：文生图显示 prompt，上传显示文件名

## 不变的部分

- `run_image_only`、`run_video_pipeline` 核心流程
- Seedance 双模式（API / CLI）
- Live Photo 格式转换（makelive）
- ZIP 打包与下载
- 去重逻辑（dedup）
- 并发限制（MAX_CONCURRENT = 10）
- Session 恢复机制
