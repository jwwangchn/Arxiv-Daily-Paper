# arXiv Daily Paper

每天从 arXiv 抓取最新论文 metadata，调用 DeepSeek 生成中文导读，通过 Cloudflare Worker API 和 GitHub Pages 提供在线浏览。

## 功能

- 通过 OAI-PMH 协议从 arXiv 抓取指定日期、指定分类（cs.CV / cs.AI / cs.CL / cs.LG）的论文 metadata
- 基于 `title + abstract` 调用 DeepSeek 生成中文导读（TL;DR、研究动机、解决问题、现象分析、主要方法、实验信息、贡献与局限）
- 基于 ICLR 2026 分类体系自动标注 primary_area / category
- 数据存储在 Cloudflare D1（生产）/ SQLite（本地开发），SPA 从 Worker API 实时加载
- 前端 SPA 支持搜索、分类导航、日历切换、优先级/标签过滤

## 架构

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  GitHub Actions   │────▶│  Cloudflare       │◀────│  GitHub Pages    │
│  (daily.yml)      │     │  Worker + D1      │     │  (SPA frontend)  │
│                   │     │                   │     │                   │
│  fetch_arxiv.py   │     │  GET /api/*       │     │  index.html      │
│  analyze_*.py     │     │  POST /api/*      │     │  assets/app.js   │
│  export_to_worker │     │                   │     │  assets/style.css│
└──────────────────┘     └──────────────────┘     └──────────────────┘
```

**两层数据存储**：

| 层 | 位置 | 用途 |
|---|---|---|
| Cloudflare D1 | 远程数据库 | 生产环境权威数据源，Worker API 查询 |
| 本地 SQLite | `data/archive/papers.db` | 本地开发，D1 schema 镜像 |

## 目录结构

```
.
├── config.yaml                    # 站点配置（分类、max_papers、主题关键词）
├── scripts/
│   ├── fetch_arxiv.py             # arXiv OAI-PMH 抓取入口
│   ├── analyze_deepseek.py        # DeepSeek 分析入口
│   ├── export_to_worker.py        # 将 SQLite 数据同步到 Worker API
│   ├── lib/                       # 共享模块
│   │   ├── db.py                  # SQLite 本地数据库层（唯一数据层）
│   │   ├── config.py              # 配置加载
│   │   └── progress.py            # 进度条
│   └── commands/                  # 核心命令模块
│       ├── fetch.py               # OAI-PMH 抓取逻辑
│       ├── analyze.py             # DeepSeek 分析逻辑
│       └── daily.py               # 完整 pipeline（fetch → analyze）
├── worker/
│   ├── src/index.ts               # Cloudflare Worker（Hono API）
│   ├── package.json
│   └── tsconfig.json
├── migrations/
│   └── 0001_create_papers_table.sql  # D1 数据库 schema
├── wrangler.toml                  # Cloudflare 部署配置
├── tools/
│   └── dev-server.js              # 本地开发服务器（SPA + Worker 代理）
├── data/
│   ├── archive/
│   │   └── papers.db              # 本地 SQLite（gitignored）
│   └── iclr_taxonomy.json         # ICLR 2026 分类体系
├── docs/
│   ├── index.html                 # SPA 入口
│   └── assets/
│       ├── app.js                 # SPA 前端逻辑
│       └── style.css              # 样式
├── tests/                         # 单元测试
└── .github/workflows/daily.yml    # GitHub Actions 定时任务
```

## 本地开发

### 安装依赖

```bash
pip install -r requirements.txt
cd worker && npm install && cd ..
```

### 初始化本地数据库

```bash
npx wrangler d1 execute arxiv-daily-db --local --file migrations/0001_create_papers_table.sql
```

### 启动服务

```bash
# 终端 1: 本地 Worker（端口 8787）
cd worker && npx wrangler dev

# 终端 2: Dev server（端口 3000，代理 /api 到 Worker）
node tools/dev-server.js
```

访问 `http://127.0.0.1:3000`

### 运行 Pipeline

```bash
export DEEPSEEK_API_KEY="your_api_key_here"

# 抓取指定日期的论文
python scripts/fetch_arxiv.py --date 2026-05-14 --max-papers 30

# DeepSeek 分析
python scripts/analyze_deepseek.py --date 2026-05-14 --concurrency 2

# 同步单日数据到 Worker API
python scripts/export_to_worker.py --url http://127.0.0.1:8787 --token your_token --date 2026-05-14

# 全量同步
python scripts/export_to_worker.py --url http://127.0.0.1:8787 --token your_token --full
```

### 运行测试

```bash
PYTHONPATH=scripts pytest tests/ -v --cov=scripts --cov-report=term-missing
```

### 部署 Worker

```bash
cd worker && npx wrangler deploy
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

每天北京时间 04:00 自动运行（默认处理过去 3 个工作日）：

1. 计算目标日期（跳过周六日），逐个日期执行 pipeline
2. 通过 OAI-PMH 抓取 arXiv 论文 → 自动跳过已存在于数据库的论文，仅插入新数据
3. DeepSeek 分析 → 自动跳过已有分析结果的论文，仅分析未分析的
4. 同步新数据到 Worker API → 写入远程 D1

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

## Worker API

| 端点 | 说明 |
|---|---|
| `GET /api/dates` | 日期索引（论文数） |
| `GET /api/papers?date=YYYY-MM-DD` | 指定日期论文 |
| `GET /api/papers?month=YYYY-MM` | 指定月份论文 |
| `GET /api/papers?id=arxiv_id` | 单篇论文 |
| `GET /api/papers?source=all` | 所有来源论文 |
| `GET /api/facets?date=&month=&source=` | 分面统计（优先级、标签、领域） |
| `GET /api/search?q=query` | 全文搜索 |
| `GET /api/stats` | 总体统计 |
| `POST /api/papers` | 批量写入论文（需 token） |
| `POST /api/analyses` | 批量写入分析（需 token） |

## 已知限制

1. 只基于 `title + abstract` 分析，不读取 PDF
2. 前端搜索仅在当前加载的论文中完成
3. SPA 依赖 Worker API 可用性
4. OAI-PMH 是唯一抓取方式，失败即报错，无 fallback

## 参考

- [JenniferZhao0531/ICLR2026-Guide-CN](https://github.com/JenniferZhao0531/ICLR2026-Guide-CN) — ICLR 2026 论文中文导读参考
- [papers.cool](https://papers.cool/) — 学术论文阅读与检索工具参考