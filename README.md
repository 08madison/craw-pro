# Craw Pro · 智能爬虫

输入网址 + 用自然语言描述想要的内容，系统用大模型（DeepSeek、通义千问、Kimi、智谱、OpenAI、Claude 等均可）理解需求、自动生成字段，逐页抓取并提取结构化数据；网页界面实时显示进度和结果，可导出 Word 报告、PPT 演示文稿、CSV、JSON。

## 功能

- **自然语言需求** → 大模型生成抓取计划（每条记录代表什么、有哪些字段、该跟随哪些链接）
- **多页抓取**：按页面数 / 链接深度限制，由大模型挑选值得继续抓取的链接（分页、详情页等）
- **实时进度**：Server-Sent Events 推送日志、进度条、Token 用量
- **结果表格**：动态列、筛选、图片/链接预览，导出结构化 Word 报告、PPT 演示文稿、CSV（Excel 友好）、JSON
- **历史任务**：SQLite 持久化
- **安全**：可选访问密码；阻止访问内网地址（SSRF 防护）；默认遵守 robots.txt
- **基础模式**：未配置任何大模型 Key 时仍可运行，只抓取标题和正文
- **可选 JS 渲染**：使用 `Dockerfile`（内置 Playwright + Chromium）部署即可启用

## 本地运行

```bash
pip install -r requirements.txt
export LLM_API_KEY=sk-...                     # 例如 DeepSeek 的 Key
export LLM_BASE_URL=https://api.deepseek.com
export LLM_MODEL=deepseek-chat
uvicorn app.main:app --reload
# 打开 http://localhost:8000
```

## 部署到 Render

方式一（推荐）：Render 控制台 → **New → Blueprint** → 选择本仓库，Render 会读取 `render.yaml` 创建 Web Service，然后在环境变量里填写 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` 和 `APP_PASSWORD`。

方式二：需要 JS 渲染时，新建 Web Service 并选择 **Docker** 运行时（使用仓库里的 `Dockerfile`，建议 ≥1GB 内存的套餐）。

> 免费套餐的磁盘是临时的，服务重启后历史任务会丢失；如需保留，可挂载 Persistent Disk 并把 `DATA_DIR` 指向挂载路径。

## 选择大模型

支持任何 **OpenAI 兼容接口**，设置三个变量即可：`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。

| 服务商 | `LLM_BASE_URL` | `LLM_MODEL` 示例 |
| --- | --- | --- |
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| 通义千问（阿里云百炼） | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| Kimi（月之暗面） | `https://api.moonshot.cn/v1` | `moonshot-v1-32k` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| 硅基流动 | `https://api.siliconflow.cn/v1` | 控制台中的模型名 |
| OpenRouter | `https://openrouter.ai/api/v1` | 控制台中的模型名 |
| OpenAI | `https://api.openai.com/v1` | 控制台中的模型名 |

> 模型名称会随服务商更新而变化，以对应控制台/文档为准。建议选上下文 ≥32K 的模型，网页内容较长。

也可以使用 Claude：设置 `ANTHROPIC_API_KEY`（不设 `LLM_API_KEY`），默认模型 `claude-opus-5`。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_API_KEY` | – | OpenAI 兼容接口的 API Key |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容接口地址 |
| `LLM_MODEL` | – | 模型名称（使用 Claude 时默认 `claude-opus-5`） |
| `LLM_PROVIDER` | 自动 | `openai` / `anthropic`；不填则按设置了哪个 Key 自动判断 |
| `LLM_MAX_TOKENS` | `8192` | 单次输出最大 Token 数 |
| `LLM_JSON_MODE` | `1` | 是否发送 `response_format=json_object`（不支持的服务商会自动关闭） |
| `ANTHROPIC_API_KEY` | – | 使用 Claude 时填写 |
| `LLM_EFFORT` / `LLM_FALLBACKS` | – | 仅 Claude：推理强度 / 拒绝时自动切换备用模型 |
| `APP_PASSWORD` | – | 访问密码，公网部署强烈建议设置 |
| `MAX_PAGES_LIMIT` | `50` | 单任务最大页面数上限 |
| `MAX_DEPTH_LIMIT` | `3` | 最大链接深度上限 |
| `CRAWL_CONCURRENCY` | `2` | 单任务并发抓取数 |
| `REQUEST_DELAY_MS` | `500` | 每次请求后的等待时间 |
| `MAX_PAGE_CHARS` | `120000` | 单页发送给模型的最大字符数（超出会在日志中提示截断） |
| `MAX_CONCURRENT_JOBS` | `3` | 同时运行的任务数 |
| `DATA_DIR` | `./data` | SQLite 数据目录 |
| `ENABLE_BROWSER` | `1` | 安装了 Playwright 时是否允许 JS 渲染 |

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/jobs` | 创建任务 `{urls, description, max_pages, max_depth, same_domain, respect_robots, render_js}` |
| `GET` | `/api/jobs` | 任务列表 |
| `GET` | `/api/jobs/{id}` | 任务详情（计划、记录、页面） |
| `GET` | `/api/jobs/{id}/events` | SSE 进度流 |
| `GET` | `/api/jobs/{id}/export?format=docx\|pptx\|csv\|json` | 导出结果（Word / PPT / CSV / JSON） |
| `POST` | `/api/jobs/{id}/cancel` | 取消任务 |
| `DELETE` | `/api/jobs/{id}` | 删除任务 |

设置了 `APP_PASSWORD` 时，请求需带 `X-App-Password` 请求头（或 `?pw=` 查询参数）。

## 项目结构

```
app/
  main.py     FastAPI 路由、SSE、导出
  jobs.py     任务存储（SQLite）与抓取调度
  fetcher.py  HTTP/浏览器抓取、SSRF 防护、HTML → 文本
  llm.py      大模型：需求解析 + 每页结构化提取（OpenAI 兼容 / Claude）
  config.py   环境变量
static/       前端（原生 HTML/CSS/JS）
render.yaml   Render Blueprint
Dockerfile    含 Chromium 的镜像（可选）
```
