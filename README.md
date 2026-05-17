# arXiv Daily Paper

每天从 arXiv 抓取最新论文 metadata，调用 DeepSeek 生成中文导读，通过 Cloudflare Worker API 和 GitHub Pages 提供在线浏览。

## 功能

- 从 arXiv Atom API 抓取指定日期、指定分类（cs.CV / cs.AI / cs.CL / cs.LG）的论文 metadata
- arXiv API 限流时自动降级到 browse 页面抓取
- 基于 `title + abstract` 调用 DeepSeek 生成中文导读（TL;DR、研究动机、解决问题、现象分析、主要方法、实验信息、贡献与局限）
- 基于 ICLR 2026 分类体系自动标注 primary_area / category
- 数据双写：本地 JSONL archive + SQLite（开发） + Cloudflare D1（生产）
- 前端 SPA 从 Worker API 实时加载数据，支持搜索、分类导航、日历切换、优先级/标签过滤

## 架构

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  GitHub Actions   │────▶│  Cloudflare       │────▶│  GitHub Pages    │
│  (daily.yml)      │     │  Worker + D1      │     │  (SPA frontend)  │
│                   │     │  (API)            │     │  (static docs/)  │
│  fetch_arxiv.py   │     │                   │     │                  │
│  analyze_*.py     │     │  arxiv-daily-api  │     │  index.html      │
│  export_to_worker │     │  .workers.dev     │     │  assets/app.js   │
└──────────────────┘     └──────────────────┘     └──────────────────┘
         │                         │                        ▲
         ▼                         │                        │
   data/archive/                   └────────────────────────┘
   *.jsonl (git-tracked)              all data from API
```

**三层数据存储**（保持同步）：

| 层 | 位置 | 用途 |
|---|---|---|
| JSONL archive | `data/archive/` | 权威数据源，git 追踪 |
| 本地 SQLite | `data/archive/papers.db` | 本地开发，D1 schema 镜像 |
| Cloudflare D1 | 远程数据库 | 生产环境，Worker API 查询 |

## 目录结构

```
.
├── config.yaml                    # 站点配置（分类、max_papers、主题关键词）
├── scripts/
│   ├── fetch_arxiv.py             # arXiv 元数据抓取（双写 JSONL + SQLite）
│   ├── analyze_deepseek.py        # DeepSeek 分析（双写 JSONL + SQLite）
│   ├── export_to_worker.py        # 将新数据同步到 Worker API
│   ├── 01_daily.py ~ 05_*.py      # 旧版入口脚本（部分兼容）
│   ├── lib/                       # 共享模块
│   │   ├── archive.py             # JSONL archive 读写
│   │   ├── db.py                  # SQLite 本地数据库层
│   │   ├── config.py              # 配置加载
│   │   ├── progress.py            # 进度条
│   │   ├── taxonomy.py            # 分类体系
│   │   └── source_archive.py      # 非 arXiv 数据源存储
│   ├── fetchers/                  # 多源抓取插件（AAAI, ACL, CVF, OpenReview）
│   ├── commands/                  # 旧版命令模块（部分兼容）
│   └── batch/                     # 批量维护脚本
├── worker/
│   ├── src/index.ts               # Cloudflare Worker（Hono API）
│   ├── package.json
│   └── tsconfig.json
├── migrations/
│   └── 0001_create_papers_table.sql  # D1 数据库 schema
├── wrangler.toml                  # Cloudflare 部署配置
├── data/
│   └── archive/
│       ├── papers.jsonl           # 所有论文元数据
│       ├── analyses.jsonl         # 所有分析结果
│       └── papers.db              # 本地 SQLite 镜像
├── docs/
│   ├── index.html                 # SPA 入口
│   ├── assets/
│   │   ├── app.js                 # SPA 前端逻辑
│   │   └── style.css              # 样式
│   └── data/                      # 静态数据缓存（向后兼容）
├── dev-server.js                  # 本地开发服务器（SPA + Worker 代理）
└── .github/workflows/daily.yml    # GitHub Actions 定时任务
```

## 本地开发

### 安装依赖

```bash
pip install -r requirements.txt
cd worker && npm install && cd ..
```

### 启动服务

```bash
# 1. 本地 Worker（端口 8787）
cd worker && npx wrangler dev

# 2. Dev server（端口 3000，代理 /api 到 Worker）
node dev-server.js
```

访问 `http://127.0.0.1:3000`

### 运行 Pipeline

```bash
export DEEPSEEK_API_KEY="your_api_key_here"

# 抓取指定日期的论文
python scripts/fetch_arxiv.py --date 2026-05-14 --max-papers 30

# DeepSeek 分析
python scripts/analyze_deepseek.py --date 2026-05-14 --concurrency 2

# 同步到 Worker API
python scripts/export_to_worker.py --url http://127.0.0.1:8787 --token your_token
```

### D1 本地操作

```bash
# 应用迁移到本地数据库
npx wrangler d1 execute arxiv-daily-db --local --file migrations/0001_create_papers_table.sql

# 查询本地数据
npx wrangler d1 execute arxiv-daily-db --local --command "SELECT COUNT(*) FROM papers"
```

### 部署 Worker

```bash
cd worker
npx wrangler deploy
```

## GitHub 配置

### Secrets

| 名称 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `ARXIV_DAILY_WORKER_URL` | Worker URL，如 `https://arxiv-daily-api.jwwangchn.workers.dev` |
| `ARXIV_DAILY_WORKER_TOKEN` | Worker API 认证 token |

### GitHub Pages

```
Settings → Pages → Source: main 分支, Folder: /docs
```

### GitHub Actions

每天北京时间 04:00 自动运行：

1. 抓取 arXiv 论文 → JSONL + SQLite
2. DeepSeek 分析 → JSONL + SQLite
3. 同步新数据到 Worker API
4. Commit 并 push `data/` 变更

## config.yaml

```yaml
arxiv:
  categories:
    - cs.CV
    - cs.AI
    - cs.CL
    - cs.LG
  max_papers: 2000
```

## 已知限制

1. 只基于 `title + abstract` 分析，不读取 PDF
2. 不下载 arXiv source 或提取图片
3. 前端搜索仅在当前加载的论文中完成
4. SPA 依赖 Worker API 可用性

## Worker API

| 端点 | 说明 |
|---|---|
| `GET /api/dates` | 日期索引（论文数） |
| `GET /api/papers?date=YYYY-MM-DD` | 指定日期论文 |
| `GET /api/papers?id=arxiv_id` | 单篇论文 |
| `GET /api/search?q=query` | 全文搜索 |
| `POST /api/papers` | 批量写入论文（需 token） |
| `POST /api/analyses` | 批量写入分析（需 token） |

## 参考

- [JenniferZhao0531/ICLR2026-Guide-CN](https://github.com/JenniferZhao0531/ICLR2026-Guide-CN) — ICLR 2026 论文中文导读参考
- [papers.cool](https://papers.cool/) — 学术论文阅读与检索工具参考
