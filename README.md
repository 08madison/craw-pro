# Craw Pro · 智能爬虫

输入网址 + 用自然语言描述想要的内容，系统用大模型（DeepSeek、通义千问、Kimi、智谱、OpenAI、Claude 等均可）理解需求、自动生成字段，逐页抓取并提取结构化数据；网页界面实时显示进度和结果，可导出 Word 报告、PPT 演示文稿、CSV、JSON。

## 功能

- **自然语言需求** → 大模型生成抓取计划（每条记录代表什么、有哪些字段、该跟随哪些链接）
- **多页抓取**：按页面数 / 链接深度限制，由大模型挑选值得继续抓取的链接（分页、详情页等）
- **实时进度**：Server-Sent Events 推送日志、进度条、Token 用量
- **结果表格**：动态列、筛选、图片/链接预览，导出结构化 Word 报告、PPT 演示文稿、CSV（Excel 友好）、JSON
- **批量任务**：把一个任务结果中的网址（如各学系的教师名单页）一键批量建任务，统一字段、自动合并去重导出
- **自动去重**：按邮箱 / 详情链接 / 同名且信息不冲突合并重复记录，多人共用的邮箱标记为「公共邮箱」
- **历史任务**：SQLite 持久化
- **安全**：可选访问密码；阻止访问内网地址（SSRF 防护）；默认遵守 robots.txt
- **基础模式**：未配置任何大模型 Key 时仍可运行，只抓取标题和正文
- **可选 JS 渲染**：使用 `Dockerfile`（内置 Playwright + Chromium）部署即可启用

## 在自己电脑上运行

先下载代码（GitHub 仓库页面 → Code → Download ZIP，解压），然后任选一种方式。
配置都写在 `.env` 文件里（参考 `.env.example`），任务历史保存在 `data/` 文件夹，重启不会丢失。

### 方式一：Docker（推荐，包含浏览器渲染）

1. 安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/) 并启动它
2. 把 `.env.example` 复制为 `.env`，填写 `LLM_API_KEY`
3. 在代码文件夹中打开终端，运行：
   ```bash
   docker compose up -d --build
   ```
4. 浏览器打开 http://localhost:8000

常用命令：`docker compose logs -f`（看日志）、`docker compose down`（停止）、更新代码后再次 `docker compose up -d --build`。
默认只有本机能访问；要让局域网其他电脑访问，把 `docker-compose.yml` 里的 `127.0.0.1:8000:8000` 改成 `8000:8000`，并设置 `APP_PASSWORD`。

### 方式二：直接用 Python（不装 Docker）

需要 Python 3.10+（Windows 安装时勾选 “Add python.exe to PATH”）。

- **Windows**：双击 `start-windows.bat`。第一次会打开 `.env` 让你填写 Key，保存后再双击一次。
- **macOS / Linux**：终端运行 `./start.sh`。

依赖默认从清华 PyPI 镜像安装。这种方式不包含浏览器渲染；需要的话运行
`pip install playwright && playwright install chromium`（国内可先设置 `PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright`）。

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

## 抓取整所大学的老师信息（两步法）

1. **找名单页**：网址填大学主页，点「① 找教师名单页」模板（深度 2、约 100 页），得到每个学系的名单页网址。
2. **批量抓取**：在结果页点「用这些网址批量建任务」，勾选学系，确认描述（默认模板：名单页有邮箱就不进个人主页，没有才进），创建后每个学系一个任务。
3. **合并导出**：在批次卡片中导出 Word / PPT / CSV / JSON，所有学系的结果合并去重，并带「所属名单」列。

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
| `POST` | `/api/batches` | 批量建任务 `{items:[{url,label}], name, description, max_pages, max_depth, batch_size}` |
| `GET` | `/api/batches/{group}` | 批次进度 |
| `POST` | `/api/batches/{group}/cancel` | 取消整个批次 |
| `GET` | `/api/batches/{group}/export?format=docx\|pptx\|csv\|json` | 批次合并去重导出 |
| `DELETE` | `/api/jobs/{id}` | 删除任务 |

设置了 `APP_PASSWORD` 时，请求需带 `X-App-Password` 请求头（或 `?pw=` 查询参数）。

## 项目结构

```
app/
  main.py     FastAPI 路由、SSE、导出
  jobs.py     任务存储（SQLite）、批次与抓取调度
  dedupe.py   去重合并、公共邮箱标记
  exporters.py Word / PPT 导出
  fetcher.py  HTTP/浏览器抓取、SSRF 防护、HTML → 文本
  llm.py      大模型：需求解析 + 每页结构化提取（OpenAI 兼容 / Claude）
  config.py   环境变量
static/       前端（原生 HTML/CSS/JS）
render.yaml   Render Blueprint
Dockerfile    含 Chromium 的镜像（可选）
```
