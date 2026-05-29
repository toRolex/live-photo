# Live Photo Maker

一键生成 Live Photo：输入文字描述或上传图片，经 GPT 图片生成 → 即梦视频生成 → ffmpeg + makelive 转码，输出可在 iPhone 上直接使用的 Live Photo（MOV + HEIC + .pvt 包）。

## 功能

- **两种生成模式**
  - **文生图**：输入描述 → 生成图片 → 确认/调参 → 生成 Live Photo
  - **上传图片**：直接上传图片 → 配置视频参数 → 生成 Live Photo
- **Live Photo 标准输出**：MOV 视频 + HEIC 封面 + `.pvt` 包，AirDrop 传输到 iPhone 自动识别为 Live Photo
- **视频参数可调**：视频提示词、随机种子（可复现）、时长（5s / 10s）、尾帧图片
- **双引擎支持**：CLI 模式（dreamina_cli）或 API 模式（火山引擎 Seedance 3.0）
- **实时进度显示**：三步骤指示器 + 进度条 + 预计剩余时间 + 事件日志
- **图片自动压缩**：超过 2MB 的图片自动压缩到 1280x720，确保 API 兼容性
- **任务恢复**：页面刷新自动恢复未完成的轮询任务
- **输入校验**：空输入拦截、500 字符限制、IP + prompt 5 分钟去重

## 快速开始

### 1. 安装系统依赖

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg
```

### 2. 安装 Python 依赖

```bash
uv sync
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入你的 API Key
```

**CLI 模式**（推荐，需即梦账号）：
```bash
curl -fsSL https://jimeng.jianying.com/cli | bash
dreamina login
```

**API 模式**（需火山引擎 AK/SK）：
在 `.env` 中设置 `SEEDANCE_MODE=api` 并填入 `SEEDANCE_ACCESS_KEY` / `SEEDANCE_SECRET_KEY`

### 4. 启动服务

```bash
uv run uvicorn main:app --reload
```

打开 http://localhost:8000 使用。

## API 接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/generate-image` | POST | 文本生成图片（返回 task_id，异步执行） |
| `/api/upload-image` | POST | 上传图片（返回 task_id，状态为 IMAGE_READY） |
| `/api/generate-video` | POST | 基于已有图片继续生成 Live Photo |
| `/api/generate` | POST | 旧版一键接口：文本 → 图片 → 视频（兼容保留） |
| `/api/status/{task_id}` | GET | 查询任务进度（含 progress_pct、estimated_remaining） |
| `/api/download/{task_id}` | GET | 下载 Live Photo ZIP 包 |

## 前置验证

```bash
# 验证 CLI + ffmpeg
uv run python preflight/verify_cli.py

# 验证 Live Photo 格式转换
uv run python preflight/verify_livephoto.py
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.12+ · FastAPI · httpx |
| 图片生成 | OpenAI GPT-image-2 |
| 视频生成 | 即梦 Seedance 3.0（CLI 或 API） |
| Live Photo 转码 | ffmpeg + makelive + pillow-heif |
| 前端 | HTML + CSS + JS（无框架） |
