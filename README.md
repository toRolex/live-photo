# Live Photo Maker

一键生成 Live Photo：输入文字描述，自动经过 GPT 图片生成 → 即梦视频生成 → ffmpeg 转码，最终输出可在 iPhone 上直接使用的 Live Photo 文件。

## 功能

- **一键生成**：输入描述 → 等待 → 下载 Live Photo（MOV + HEIC 打包为 ZIP）
- **双模式支持**：前端可切换 CLI 模式（dreamina_cli）或 API 模式（火山引擎）
- **状态轮询**：3 步进度条实时展示生成状态
- **任务恢复**：页面刷新自动恢复未完成的轮询任务
- **输入校验**：空输入拦截、500 字符限制、IP+prompt 5 分钟去重

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置环境变量

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

### 3. 启动服务

```bash
uv run uvicorn main:app --reload
```

打开 http://localhost:8000 使用。

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
| 视频生成 | 即梦 Seedance 2.0（CLI 或 API） |
| 格式转换 | ffmpeg + pillow-heif |
| 前端 | HTML + CSS + JS（无框架） |
