# 多来源论文 Fetch 支持计划

创建时间：2026-05-13

参考文档：

- `/Users/jwwangchn/Documents/03-Resources/01-Codes/daily-paper-reader/paper_fetching_architecture.md`

参考代码：/Users/jwwangchn/Documents/03-Resources/01-Codes/daily-paper-reader

## 背景

当前项目主要围绕 arXiv 每日论文工作流：

```text
arXiv -> fetch -> data/archive/papers.jsonl -> analyze -> data/archive/analyses.jsonl -> docs/data/by-month/*.json -> SPA
```

新目标是在不引入数据库、不引入后端服务的前提下，扩展到其他顶会论文来源，例如：

- OpenReview 系：NeurIPS、ICLR、ICML；
- ACL Anthology 系：ACL、EMNLP；
- AAAI OJS；
- 后续可扩展：CVPR、ICCV、ECCV、COLM、KDD、WWW、SIGIR、AAAI/IJCAI 等。

## 对参考架构的分析

`daily-paper-reader` 的参考设计有几个值得复用的点：

1. 多来源 fetcher 分离  
   每个来源有独立 fetcher，避免把 OpenReview、ACL Anthology、AAAI OJS、arXiv 的页面/API 细节混在一个大脚本里。

2. 统一论文 schema  
   所有来源最终归一到统一字段，后续分析、展示、去重就不需要关心来源细节。

3. 来源内增量去重  
   arXiv 用 `seen.json`，OpenReview/ACL/AAAI 用各自稳定 ID。这个思想可以迁移到当前 `data/archive/papers.jsonl` 的 append-only 去重逻辑。

4. 失败隔离  
   单个来源、单个时间窗口、单个 volume 失败，不应拖垮全部 pipeline。

5. 时间窗口/会议维度分片  
   arXiv 适合按日期窗口抓；OpenReview 适合按 conference + year 抓；ACL/EMNLP 适合按 volume 抓；AAAI 适合按 issue 抓。

但不建议直接搬入的部分：

- Supabase / PostgreSQL / pgvector；
- BM25 和 embedding pipeline；
- 多 GPU embedding；
- 每来源独立数据库表；
- “优先读库回退抓取”的数据库逻辑。

这些能力超出当前静态站 MVP，会明显增加维护成本。当前项目应继续坚持：

- JSONL archive 作为长期源数据；
- `docs/data/by-month/*.json` 作为前端消费数据；
- 静态 HTML/CSS/JS；
- 不引入数据库和后端。

## 设计原则

1. 来源无关的数据模型  
   不能继续让 `arxiv_id` 成为唯一论文 ID。需要引入统一 `paper_id`，同时保留来源原始 ID。

2. fetcher 插件化  
   每个来源实现同一接口，主 pipeline 只调度 fetcher，不理解页面/API 细节。

3. archive 仍然唯一长期源数据  
   所有来源的论文元信息仍写入 `data/archive/papers.jsonl`。

4. analysis 与来源解耦  
   DeepSeek 分析仍只看 `title + abstract`，不关心论文来自 arXiv、OpenReview、ACL 还是 AAAI。

5. 先支持高价值顶会，后扩展预印本  
   本轮重点是顶会论文，不急着支持 bioRxiv、medRxiv、ChemRxiv。

## 推荐统一 Schema

当前 `papers.jsonl` 第一版以 arXiv 为中心：

```json
{
  "arxiv_id": "2605.07926",
  "title": "...",
  "authors": ["..."],
  "abstract": "...",
  "categories": ["cs.AI"],
  "primary_category": "cs.AI",
  "published": "...",
  "updated": "...",
  "entry_url": "...",
  "pdf_url": "...",
  "source_date": "2026-05-08",
  "fetched_at": "..."
}
```

建议扩展为来源无关 schema，同时短期保留 `arxiv_id` 兼容字段：

```json
{
  "paper_id": "openreview-iclr-2026-abc123",
  "source": "openreview",
  "venue": "ICLR",
  "year": 2026,
  "track": "Conference",
  "status": "accepted",
  "source_paper_id": "abc123",
  "arxiv_id": "",
  "doi": "",
  "title": "...",
  "authors": ["..."],
  "abstract": "...",
  "categories": ["ICLR 2026"],
  "primary_category": "ICLR",
  "published": "2026-01-22T00:00:00Z",
  "updated": "2026-01-22T00:00:00Z",
  "entry_url": "https://openreview.net/forum?id=abc123",
  "pdf_url": "https://openreview.net/pdf?id=abc123",
  "source_date": "2026-01-22",
  "fetched_at": "2026-05-13T00:00:00Z",
  "raw_source": {
    "invitation": "...",
    "decision": "Accept"
  }
}
```

字段说明：

- `paper_id`：当前项目内部唯一 ID，所有来源必须有。
- `source`：来源类型，如 `arxiv`、`openreview`、`acl_anthology`、`aaai_ojs`。
- `venue`：会议名，如 `ICLR`、`NeurIPS`、`ICML`、`ACL`、`EMNLP`、`AAAI`。
- `year`：会议年份。
- `track`：Main、Findings、Long、Short、Technical Track 等。
- `status`：accepted、rejected、withdrawn、public、unknown 等。
- `source_paper_id`：来源站点原始 ID。
- `entry_url`：论文页面。
- `pdf_url`：PDF。
- `source_date`：用于前端日期分组。对会议论文，需要定义为发布日期、会议 release date、fetch date 或人工指定 collection date。
- `raw_source`：只保留轻量调试信息，不保存过大原始 HTML。

## archive 层改造

需要把 archive 层从 arXiv-only 改为 source-agnostic。

计划改动：

- `paper_id(paper)` 优先读取 `paper_id`，兼容回退 `arxiv_id`。
- `append_new_papers` 按 `paper_id` 去重。
- `papers_for_date` 仍按 `source_date` 查询。
- 新增按来源/会议查询：
  - `papers_for_source(source)`
  - `papers_for_venue(venue, year=None)`
  - `papers_for_collection(source, venue, year, track=None)`
- `analyses.jsonl` 的去重键从 `arxiv_id + analysis_version` 改为 `paper_id + analysis_version`。
- 短期兼容旧分析记录：如果没有 `paper_id`，从 `arxiv_id` 推导 `paper_id = "arxiv-{arxiv_id}"` 或直接兼容旧键。

风险点：

- 现有分析缓存里已经使用 `arxiv_id`。
- 前端 JSON 里很多地方可能默认 `arxiv_id` 存在。
- 需要一次性梳理 `analyze_deepseek.py`、`build_site.py`、`docs/assets/app.js` 中的 ID 显示和链接逻辑。

## Fetcher 架构

建议新增来源 fetcher 子目录：

```text
scripts/
└── fetchers/
    ├── __init__.py
    ├── base.py
    ├── arxiv.py
    ├── openreview.py
    ├── acl_anthology.py
    ├── aaai_ojs.py
    └── registry.py
```

如果 scripts 目录重构计划已经执行，则放入：

```text
scripts/
└── lib/
    └── fetchers/
        ├── __init__.py
        ├── base.py
        ├── arxiv.py
        ├── openreview.py
        ├── acl_anthology.py
        ├── aaai_ojs.py
        └── registry.py
```

统一接口建议：

```python
class FetchRequest:
    source: str
    venue: str | None
    year: int | None
    start_date: str | None
    end_date: str | None
    track: str | None
    max_papers: int | None
    options: dict

class FetchResult:
    papers: list[dict]
    warnings: list[str]
    source_stats: dict

class PaperFetcher:
    name: str
    def fetch(self, request: FetchRequest) -> FetchResult:
        ...
```

主调度命令不直接 import 每个 fetcher 的细节，而是通过 registry：

```text
fetch_source("openreview", venue="ICLR", year=2026)
fetch_source("acl_anthology", venue="ACL", year=2025)
fetch_source("aaai_ojs", venue="AAAI", year=2025)
```

## 来源一：OpenReview 顶会

覆盖：

- ICLR
- NeurIPS
- ICML
- 后续可扩展 COLM、ICLR Workshop 等。

参考实现要点：

- 使用 `openreview-py`。
- 构造 `venue_id`，如：
  - `ICLR.cc/2026/Conference`
  - `NeurIPS.cc/2025/Conference`
  - `ICML.cc/2025/Conference`
- 从 venue group 中读取 submission invitation。
- `get_all_notes(invitation=..., details="replies")` 获取 submissions 和 replies。
- 从 replies 中解析 decision。
- 默认只保留公开可见论文。

当前项目适配策略：

- 默认只导入 `accepted` 或公开 accepted 论文。
- `status` 记录 accepted/rejected/withdrawn/unknown，但默认前端只展示 accepted。
- `paper_id = "openreview-{venue_lower}-{year}-{note_id}"`。
- `source_date` 默认使用 decision/release 日期；如果 API 无明确日期，则使用 fetch 日期或 CLI 指定 `--source-date`。

新增配置建议：

```yaml
sources:
  openreview:
    enabled: true
    public_only: true
    default_statuses: ["accepted"]
    venues:
      - name: ICLR
        years: [2026]
      - name: NeurIPS
        years: [2025]
      - name: ICML
        years: [2025]
```

凭证：

- OpenReview 某些数据需要 `OPENREVIEW_USERNAME` 和 `OPENREVIEW_PASSWORD`。
- 计划中不写入、不打印、不提交凭证。
- 如果 public API 足够，优先无凭证模式。

## 来源二：ACL Anthology

覆盖：

- ACL
- EMNLP
- Findings of ACL
- Findings of EMNLP

参考实现要点：

- volume URL：
  - `https://aclanthology.org/volumes/{year}.acl-long/`
  - `https://aclanthology.org/volumes/{year}.acl-short/`
  - `https://aclanthology.org/volumes/{year}.findings-acl/`
  - `https://aclanthology.org/volumes/{year}.emnlp-main/`
  - `https://aclanthology.org/volumes/{year}.findings-emnlp/`
- 从单篇页面 meta 标签提取：
  - `citation_title`
  - `citation_author`
  - `citation_pdf_url`
  - `citation_publication_date`
  - abstract DOM。

当前项目适配策略：

- `paper_id = "acl-{paper_slug}"` 或 `anthology-{paper_slug}`。
- `source = "acl_anthology"`。
- `venue = "ACL"` / `"EMNLP"`。
- `track = "Long"` / `"Short"` / `"Findings"` / `"Main"`。
- `source_date` 使用 `citation_publication_date`，缺失时用 volume 年份的人工默认日期或 fetch 日期。
- 并发抓取单篇页面，但 worker 默认保守，例如 8，而不是参考项目里的 32。

## 来源三：AAAI OJS

覆盖：

- AAAI Technical Track。

参考实现要点：

- 从归档页 `https://ojs.aaai.org/index.php/AAAI/issue/archive` 找目标年份 issue。
- 匹配 `AAAI-25 Technical Tracks` 一类标题。
- issue 页面中解析文章摘要列表。
- 单篇详情页提取：
  - `citation_title`
  - `citation_author`
  - `citation_pdf_url`
  - `citation_doi`
  - `DC.Description`

当前项目适配策略：

- `paper_id = "aaai-{year}-{article_id}"`。
- `source = "aaai_ojs"`。
- `venue = "AAAI"`。
- `track = "Technical Track"`。
- `status = "accepted"`。
- `source_date` 使用 OJS publication date，缺失时用 fetch date 或 CLI 指定日期。
- worker 默认保守，例如 6 到 8。

## 可选后续来源

这些来源不在参考文档中，但对“顶会论文”很重要：

- CVPR / ICCV / ECCV：通常可从 CVF Open Access 页面抓取。
- KDD / WWW / SIGIR / MM：可能需要 ACM DL 或会议官网，抓取难度和版权限制更高。
- IJCAI：会议官网或 proceedings 页面。
- COLM：可能走 OpenReview。

建议本轮先不做这些，只在 fetcher registry 预留扩展点。

## CLI 设计

如果 scripts 重构计划已执行，建议新增或扩展：

```bash
python scripts/02_fetch.py --source arxiv --date 2026-05-11
python scripts/02_fetch.py --source openreview --venue ICLR --year 2026
python scripts/02_fetch.py --source openreview --venue NeurIPS --year 2025 --status accepted
python scripts/02_fetch.py --source acl_anthology --venue ACL --year 2025
python scripts/02_fetch.py --source acl_anthology --venue EMNLP --year 2025 --track main
python scripts/02_fetch.py --source aaai_ojs --venue AAAI --year 2025
```

也可以新增批量命令：

```bash
python scripts/batch/backfill_sources.py --config config.yaml
```

不建议在第一版把所有来源塞进每日自动 run：

- arXiv 是每日更新；
- 顶会 proceedings 是按年份/发布批次更新；
- OpenReview 会议数据量大，不适合每天全量反复抓；
- ACL/AAAI 页面抓取对站点压力更敏感。

## config.yaml 扩展

建议新增 `sources` 段，不破坏原 `arxiv` 段：

```yaml
sources:
  arxiv:
    enabled: true
    schedule: daily
  openreview:
    enabled: false
    public_only: true
    statuses: ["accepted"]
    venues:
      - name: ICLR
        years: [2026]
      - name: NeurIPS
        years: [2025]
      - name: ICML
        years: [2025]
  acl_anthology:
    enabled: false
    venues:
      - name: ACL
        years: [2025]
        tracks: ["long", "short", "findings-acl"]
      - name: EMNLP
        years: [2025]
        tracks: ["main", "findings-emnlp"]
  aaai_ojs:
    enabled: false
    venues:
      - name: AAAI
        years: [2025]
        tracks: ["technical"]
```

第一版建议默认只启用 arXiv，其他来源通过 CLI 显式触发。

## 前端展示改造

多来源后，前端需要明确展示来源和会议：

- 卡片 meta 行新增 source/venue/year/track。
- 侧栏新增来源过滤：
  - arXiv
  - ICLR
  - NeurIPS
  - ICML
  - ACL
  - EMNLP
  - AAAI
- 日期导航仍按 `source_date`。
- 对会议论文增加 collection 视图的可能：
  - `?venue=ICLR&year=2026`
  - `?source=openreview&venue=ICLR&year=2026`

第一版建议只做最小前端改造：

- 仍按日期浏览；
- 卡片展示 venue/source；
- 搜索和过滤支持 source/venue；
- 不急着做独立 conference collection 页面。

## 分阶段实施计划

### 阶段 0：决策和边界确认

需要先确认：

1. 第一批顶会来源选哪些？
2. OpenReview 是否允许使用账号密码，还是只抓 public 数据？
3. 会议论文按什么日期进入前端：发布日期、decision date、fetch date，还是手工指定 source date？
4. 默认是否只展示 accepted 论文？
5. 是否接受把 archive 主键从 `arxiv_id` 迁移到 `paper_id`？

### 阶段 1：统一 ID 和 archive schema

目标：让现有 arXiv 数据也能走 source-agnostic schema。

动作：

1. 为 arXiv 论文生成 `paper_id = "arxiv-{arxiv_id}"`。
2. `archive_store` 的去重逻辑改为优先 `paper_id`。
3. `analyses.jsonl` 支持 `paper_id + analysis_version`。
4. `build_site.py` 和前端显示兼容 `paper_id`。
5. 保留 `arxiv_id` 字段用于显示和旧数据兼容。

验收：

- 现有 arXiv 日期仍能构建和浏览。
- 不重复生成同一篇 arXiv paper。
- 已有分析缓存仍能命中。

### 阶段 2：fetcher 接口和 registry

目标：建立多来源 fetch 的骨架。

动作：

1. 新增 fetcher base 类型和 request/result 结构。
2. 新增 registry。
3. 把现有 arXiv fetch 适配成 `arxiv` fetcher。
4. `02_fetch.py` 支持 `--source`。

验收：

- `python scripts/02_fetch.py --source arxiv --date YYYY-MM-DD` 行为等价于当前 arXiv fetch。
- fetch result 可以 append 到 archive。

### 阶段 3：OpenReview fetcher

目标：支持 ICLR / NeurIPS / ICML。

动作：

1. 引入 `openreview-py` 依赖。
2. 实现 venue_id builder。
3. 实现 submission invitation 解析。
4. 解析 notes 和 decision replies。
5. 输出统一 schema。
6. 默认过滤 accepted/public papers。

验收：

- 能抓取一个指定会议年份，例如 ICLR 2026。
- 输出 `paper_id/source/venue/year/status/title/authors/abstract/entry_url/pdf_url`。
- 重复运行不重复 append。
- 无凭证或凭证缺失时给出清晰错误或退化到 public-only 模式。

### 阶段 4：ACL Anthology fetcher

目标：支持 ACL / EMNLP。

动作：

1. 实现 volume specs。
2. 抓取 volume 页面。
3. 并发抓取单篇页面。
4. 从 meta 和 abstract DOM 归一化论文记录。
5. 输出统一 schema。

验收：

- 能抓取 ACL 2025 long/short/findings 的样例。
- 能抓取 EMNLP 2025 main/findings 的样例。
- 页面结构变化时记录 warning，不中断整个 volume。

### 阶段 5：AAAI OJS fetcher

目标：支持 AAAI Technical Track。

动作：

1. 抓取 OJS issue archive。
2. 匹配目标年份 Technical Track issue。
3. 解析 issue 下论文列表。
4. 抓取单篇详情并归一化。

验收：

- 能抓取 AAAI 2025 Technical Track。
- 输出 DOI、PDF URL、abstract。
- 单篇失败不影响其他论文。

### 阶段 6：分析与站点集成

目标：让非 arXiv 论文进入现有分析和前端。

动作：

1. `analyze` 使用 `paper_id` 查缓存。
2. prompt 继续只传 `title + abstract`。
3. `build_site` 导出 source/venue/year/track/status。
4. 前端增加 source/venue 显示与过滤。

验收：

- OpenReview/ACL/AAAI 论文可被分析。
- `docs/data/by-month/*.json` 中混合来源数据结构稳定。
- 前端可以浏览、搜索、过滤多来源论文。

### 阶段 7：批量回填和调度

目标：给会议论文提供按年/按 venue 的批量导入入口。

动作：

1. 新增 `scripts/batch/backfill_sources.py`。
2. 支持从 `config.yaml` 读取 enabled sources。
3. 每个来源独立统计 fetched/appended/failed。
4. 默认不接入每日 GitHub Action。

验收：

- 可以一条命令回填指定会议列表。
- 某个来源失败不影响其他来源。
- 本地可重跑且不重复。

## GitHub Actions 策略

第一版不建议把所有会议 fetch 放入每日 workflow。

推荐：

- daily workflow 继续只跑 arXiv + analyze missing + build site。
- 新增手动 workflow 或本地批处理命令用于会议回填。
- 等稳定后，可以给 OpenReview/ACL/AAAI 单独设置低频 workflow，例如每周一次或手动触发。

原因：

- 会议 proceedings 更新不是每日节奏。
- 全量会议抓取可能请求量大。
- OpenReview/ACL/AAAI 页面结构变化会带来不稳定性。
- 手动回填更容易控制 API 和站点压力。

## 测试计划

单元测试：

- `paper_id` 生成和去重。
- arXiv 旧数据兼容。
- OpenReview note -> unified paper。
- ACL meta tags -> unified paper。
- AAAI article page -> unified paper。
- analysis cache 使用 `paper_id`。

集成测试：

- mock fetcher 写入 archive。
- 多来源混合导出 by-month JSON。
- 前端 source/venue 过滤数据结构。

本地验证：

```bash
python -m py_compile scripts/*.py scripts/**/*.py
pytest
python scripts/02_fetch.py --source arxiv --date 2026-05-11 --metadata-only
python scripts/02_fetch.py --source openreview --venue ICLR --year 2026 --metadata-only
python scripts/04_build.py
```

## 风险

1. OpenReview 数据可见性不稳定  
   不同会议、年份、阶段的 invitation 和 decision 字段可能不同。

2. 会议论文缺少明确日期  
   `source_date` 需要统一策略，否则日期浏览会混乱。

3. 当前代码中 `arxiv_id` 假设较多  
   迁移到 `paper_id` 是这项工作的核心风险。

4. 页面爬虫脆弱  
   ACL Anthology 和 AAAI OJS 页面结构变化会导致解析失败。

5. 非 arXiv 论文分类不同  
   当前 categories/primary_category 语义偏 arXiv，需要前端显示成 venue/track 更自然。

6. 数据量和 API 成本  
   顶会全量论文进入分析后会触发大量 DeepSeek 调用，需要默认 metadata-only 或 cache-only，分析分批开启。

## 推荐第一版范围

第一版建议只做：

1. `paper_id` schema 迁移；
2. fetcher base/registry；
3. arXiv fetcher 适配；
4. OpenReview fetcher 支持 ICLR/NeurIPS/ICML accepted papers；
5. metadata-only 导入 archive；
6. 前端最小展示 source/venue；
7. 暂不自动分析全部会议论文，避免 API 成本失控。

ACL Anthology 和 AAAI OJS 放第二版，因为它们是网页爬虫，维护风险更高。

## 需要确认的问题

1. 第一批顶会是否优先做 ICLR / NeurIPS / ICML？
2. 你是否有 OpenReview 账号凭证可在本地环境使用，还是必须只抓 public 数据？
3. 非 arXiv 论文进入日期列表时，`source_date` 用发布日期、fetch 日期，还是手动指定日期？
4. 默认是否只导入 accepted papers？
5. 会议论文是否要立即调用 DeepSeek 分析，还是先 metadata-only 回填，之后按需分析？
6. CVPR/ICCV/ECCV 是否要纳入第一版？参考文档没有覆盖 CVF，需要另写 fetcher。

