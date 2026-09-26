# Craw Pro · 智能爬虫

输入网址 + 用自然语言描述想要的内容，系统用 Claude 理解需求、自动生成字段，逐页抓取并提取结构化数据；网页界面实时显示进度和结果，可导出 CSV / JSON。

## 功能

- **自然语言需求** → Claude 生成抓取计划（每条记录代表什么、有哪些字段、该跟随哪些链接）
- **多页抓取**：按页面数 / 链接深度限制，由 Claude 挑选值得继续抓取的链接（分页、详情页等）
- **实时进度**：Server-Sent Events 推送日志、进度条、Token 用量
- **结果表格**：动态列、筛选、图片/链接预览，导出 CSV（Excel 友好）/ JSON
- **历史任务**：SQLite 持久化
- **安全**：可选访问密码；阻止访问内网地址（SSRF 防护）；默认遵守 robots.txt
- **基础模式**：未配置 `ANTHROPIC_API_KEY` 时仍可运行，只抓取标题和正文
- **可选 JS 渲染**：使用 `Dockerfile`（内置 Playwright + Chromium）部署即可启用

## 本地运行

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
uvicorn app.main:app --reload
# 打开 http://localhost:8000
```

## 部署到 Render

方式一（推荐）：Render 控制台 → **New → Blueprint** → 选择本仓库，Render 会读取 `render.yaml` 创建 Web Service，然后在环境变量里填写 `ANTHROPIC_API_KEY` 和 `APP_PASSWORD`。

方式二：需要 JS 渲染时，新建 Web Service 并选择 **Docker** 运行时（使用仓库里的 `Dockerfile`，建议 ≥1GB 内存的套餐）。

> 免费套餐的磁盘是临时的，服务重启后历史任务会丢失；如需保留，可挂载 Persistent Disk 并把 `DATA_DIR` 指向挂载路径。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | – | Claude API Key，不填则为基础模式 |
| `APP_PASSWORD` | – | 访问密码，公网部署强烈建议设置 |
| `LLM_MODEL` | `claude-opus-5` | 使用的 Claude 模型 |
| `LLM_EFFORT` | 模型默认 | `low` / `medium` / `high` / `xhigh` / `max`，越低越省 Token |
| `LLM_FALLBACKS` | `default` | 模型拒绝时自动切换备用模型；`off` 关闭 |
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
| `GET` | `/api/jobs/{id}/export?format=csv\|json` | 导出结果 |
| `POST` | `/api/jobs/{id}/cancel` | 取消任务 |
| `DELETE` | `/api/jobs/{id}` | 删除任务 |

设置了 `APP_PASSWORD` 时，请求需带 `X-App-Password` 请求头（或 `?pw=` 查询参数）。

## 项目结构

```
app/
  main.py     FastAPI 路由、SSE、导出
  jobs.py     任务存储（SQLite）与抓取调度
  fetcher.py  HTTP/浏览器抓取、SSRF 防护、HTML → 文本
  llm.py      Claude：需求解析 + 每页结构化提取
  config.py   环境变量
static/       前端（原生 HTML/CSS/JS）
render.yaml   Render Blueprint
Dockerfile    含 Chromium 的镜像（可选）
```
