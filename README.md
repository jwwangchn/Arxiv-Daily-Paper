# arXiv Daily Paper Guide

每天从 arXiv 抓取最新论文 metadata，调用 DeepSeek 生成中文论文导读，并输出可部署到 GitHub Pages 的静态网站。第一版 MVP 不使用数据库、不需要后端服务，所有数据都保存为 JSON。

## 功能

- 从 arXiv Atom API 抓取指定日期、指定分类的论文 metadata。
- 基于 `title + abstract` 调用 DeepSeek OpenAI-compatible API 生成中文导读。
- 支持断点续跑，已分析论文不会重复请求 API。
- 生成 `docs/` 静态网站，包含首页、历史日期页、日期索引和静态资源。
- 前端支持实时搜索、tag 过滤、priority 过滤、分类过滤和折叠 abstract。
- 提供 mock 模式，无需 API key 即可预览页面。
- 提供 GitHub Actions 定时任务，每天北京时间 08:00 运行。

## 目录结构

```text
.
├── README.md
├── requirements.txt
├── config.yaml
├── scripts/
│   ├── run_daily.py
│   ├── fetch_arxiv.py
│   ├── analyze_deepseek.py
│   ├── build_site.py
│   └── utils.py
├── data/
│   ├── raw/
│   ├── analyzed/
│   └── mock/
├── docs/
│   ├── index.html
│   ├── daily/
│   ├── data/
│   └── assets/
│       ├── style.css
│       └── app.js
└── .github/
    └── workflows/
        └── daily.yml
```

## 本地运行

```bash
pip install -r requirements.txt
export DEEPSEEK_API_KEY="your_api_key_here"
python scripts/run_daily.py --date 2026-05-10
```

可选参数：

```bash
python scripts/run_daily.py --date 2026-05-10 --max-papers 30
python scripts/fetch_arxiv.py --date 2026-05-10 --max-papers 30
python scripts/analyze_deepseek.py --date 2026-05-10
python scripts/build_site.py
```

## Mock 模式

无需 `DEEPSEEK_API_KEY`，直接生成可预览网站：

```bash
python scripts/run_daily.py --mock
```

也可以只构建静态页面：

```bash
python scripts/build_site.py --mock
```

生成后打开：

```text
docs/index.html
```

## GitHub Secrets

在仓库中添加 DeepSeek API key：

```text
Settings → Secrets and variables → Actions → New repository secret
Name: DEEPSEEK_API_KEY
```

不要把真实 API key 写入代码、README、日志或任何生成文件。

## GitHub Pages

配置 Pages 从 `/docs` 部署：

```text
Settings → Pages → Build and deployment
Source: Deploy from a branch
Branch: main
Folder: /docs
```

`docs/index.html` 使用 `assets/style.css` 和 `assets/app.js`；历史页使用 `../assets/style.css` 和 `../assets/app.js`，适配 GitHub Pages 相对路径。

## GitHub Actions

workflow 位于 `.github/workflows/daily.yml`：

- 每天北京时间 08:00 运行，cron 为 `0 0 * * *`。
- 支持 `workflow_dispatch` 手动触发。
- 使用 Python 3.11。
- 安装 `requirements.txt`。
- 执行 `python scripts/run_daily.py`。
- 将 `data/` 和 `docs/` 的变化 commit 并 push。
- 如果没有变化，会输出 `No changes`，不会报错。

手动触发：

```text
Actions → Daily arXiv Guide → Run workflow
```

如果 push 失败，请确认 workflow permissions 包含 `contents: write`，并检查仓库 Actions 设置是否允许 GitHub Actions 写入。

## config.yaml

`config.yaml` 控制站点标题、arXiv 分类、每日最大论文数和主题关键词。

- `site.title`：页面标题。
- `site.subtitle`：页面副标题。
- `arxiv.categories`：默认抓取分类，例如 `cs.CV`、`cs.CL`。
- `arxiv.max_papers`：默认每日最多论文数。
- `topics`：用于后续筛选、prompt 优化和 tags 对齐的主题关键词配置。

## 常见问题

**没有 API key**

使用 `python scripts/run_daily.py --mock` 预览网站。正式分析需要设置 `DEEPSEEK_API_KEY`。

**DeepSeek 返回非 JSON**

脚本要求模型输出 JSON，并使用 `response_format={"type": "json_object"}`。如果仍然解析失败，该论文会保留原始信息，并记录 `analysis_error` 和可用的原始响应信息。

**当天没有论文**

`fetch_arxiv.py` 仍会写出合法 JSON，`papers` 为空；页面会显示空状态。

**GitHub Pages 路径问题**

本项目所有站内资源使用相对路径。首页资源为 `assets/...`，历史页资源为 `../assets/...`。

**GitHub Actions 没有权限 push**

确认 workflow 中有 `permissions: contents: write`，并在仓库 Settings 的 Actions 权限中允许 workflow 写入。

## 已知限制

1. 只基于 `title + abstract` 分析，不读取 PDF 全文。
2. 不下载 arXiv source。
3. 不提取主图。
4. 不使用数据库。
5. 搜索和过滤只在当前静态页面前端完成。
6. GitHub Actions 定时任务不保证秒级准时。
7. DeepSeek 输出可能不是严格 JSON，因此代码中做了容错。
8. 论文筛选质量依赖 prompt 和配置关键词，后续可以优化。

## 后续可扩展方向

- 提取 arXiv source。
- 提取论文主图。
- 使用 Cloudflare R2 存图片。
- RSS / 邮件推送。
- 更复杂的论文筛选。
- PDF 全文分析。

