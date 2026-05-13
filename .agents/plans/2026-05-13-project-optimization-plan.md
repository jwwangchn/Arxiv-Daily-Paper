# 项目优化计划：日历、存储布局与抓取语义

创建日期：2026-05-13

## 范围

本计划涵盖静态 arXiv 每日论文指南的下一轮本地优化。此文件仅做规划，不包含实现代码。

需求如下：

1. 添加"回到顶部"控件。
2. 将历史日期列表替换为完整的日历视图，并添加"今天"按钮。
3. 按月组织 JSON 和 HTML 文件，避免单个文件夹内文件过多。
4. 抓取结果为空时不写入 JSON 文件。
5. 重新运行同一日期时，将新抓取的论文追加到之前的结果中，而非替换。

## 当前架构要点

- 论文元数据长期存储在 `data/archive/papers.jsonl`。
- 分析结果长期存储在 `data/archive/analyses.jsonl`。
- SPA 前端消费 `docs/data/dates.json` 和 `docs/data/by-month/YYYY-MM.json`。
- 兼容性的每日页面目前生成为 `docs/daily/YYYY-MM-DD.html`。
- 遗留的原始数据和分析数据目前是扁平文件：
  - `data/raw/YYYY-MM-DD.json`
  - `data/analyzed/YYYY-MM-DD.json`
- 当前 SPA 已支持懒加载月度站点数据及 `?date=YYYY-MM-DD` 参数。

## 假设

- `data/archive/*.jsonl` 保持为规范的长期数据源。
- `docs/data/by-month/*.json` 保持为前端消费格式。
- 现有每日 URL 应通过重定向保持可用，除非我们显式决定破坏兼容性。
- 空抓取不应创建或更新每日原始 JSON 文件，但日志仍应记录未找到论文。
- 重新运行应仅追加新的 `arxiv_id`，并保留已有分析。

## 实施阶段

### 第一阶段：前端导航体验

目标：让长日期范围更易于浏览，不改变数据语义。

计划变更：

- 在 SPA 中添加固定/粘性"回到顶部"按钮。
- 仅在页面滚动到足够距离后显示该按钮。
- 点击后平滑滚动回页面顶部。
- 使用真实的 button 元素和清晰的 focus 样式，保持键盘可访问性。
- 将当前扁平的历史日期列表替换为按月分组的日历 UI。
- 在日历控件附近添加"今天"按钮。
- 如果 `docs/data/dates.json` 中存在今天的日期，"今天"按钮选中它。
- 如果不存在，"今天"按钮应：
  - 选中今天之前最新的可用日期，或
  - 显示为不可用/禁用状态。

涉及文件：

- `scripts/build_site.py`
- `docs/assets/app.js`
- `docs/assets/style.css`
- 重新生成的 `docs/index.html`

验证：

- 运行 `python scripts/build_site.py`
- 打开本地站点验证：
  - `?date=2026-05-03` 仍能正常加载。
  - 日历日期切换能加载正确的月度数据包。
  - "今天"按钮行为符合下方决策。
  - "回到顶部"按钮在滚动后出现并能返回顶部。

### 第二阶段：按月输出布局

目标：防止扁平目录过大，同时保持现有链接可用。

目标布局：

```text
data/
├── raw/
│   └── YYYY-MM/
│       └── YYYY-MM-DD.json
└── analyzed/
    └── YYYY-MM/
        └── YYYY-MM-DD.json

docs/
├── daily/
│   └── YYYY-MM/
│       └── YYYY-MM-DD.html
└── data/
    └── by-month/
        └── YYYY-MM.json
```

兼容性方案：

- 在过渡期内保留旧的 `docs/daily/YYYY-MM-DD.html` 重定向存根，指向 `../index.html?date=YYYY-MM-DD`。
- 新的规范每日重定向页面变为 `docs/daily/YYYY-MM/YYYY-MM-DD.html`。

涉及文件：

- `scripts/utils.py`
- `scripts/fetch_arxiv.py`
- `scripts/analyze_deepseek.py`
- `scripts/run_daily.py`
- `scripts/build_site.py`
- `tests/` 下的测试

验证：

- 新运行写入 `data/raw/YYYY-MM/YYYY-MM-DD.json`。
- 新分析写入 `data/analyzed/YYYY-MM/YYYY-MM-DD.json`。
- `build_site.py` 在迁移期间能同时读取新的月度路径和遗留扁平路径。
- 仅在生成的每日输出目录内清理过期页面。
- 现有 `docs/daily/YYYY-MM-DD.html` 链接在过渡期内继续重定向。

### 第三阶段：空抓取处理

目标：避免产生误导性的空 JSON 文件。

计划行为：

- 指定日期的直接抓取命令：
  - 如果未抓取到论文，不写入 `data/raw/...json`；
  - 日志记录 `No papers found for YYYY-MM-DD`；
  - 成功退出，除非用户后续显式要求严格失败行为。
- 最新日期发现：
  - 继续像现在一样向前回溯查找；
  - 仅持久化选中的非空日期。
- 回填：
  - 如果某天返回零篇论文，不向 archive 追加任何内容；
  - 不创建原始 JSON；
  - 计为成功的空日期，而非失败日期。

涉及文件：

- `scripts/fetch_arxiv.py`
- `scripts/run_daily.py`
- `tests/`

验证：

- 运行已知空日期不会创建原始 JSON。
- 现有原始 JSON 不会因为后续对该日期的抓取返回空而被删除。
- 回填日志记录空日期而不导致整个范围失败。

### 第四阶段：追加式重新运行语义

目标：当 arXiv 首次返回不完整页面时，使同一日期的重复运行具有累加性。

计划行为：

- 加载目标日期已有的原始论文（如有）。
- 重新抓取同一日期的论文。
- 按 `arxiv_id` 合并。
- 当 ID 冲突时保留已有记录，除非新抓取的记录填补了缺失的元数据。
- 写入合并后的非空原始数据包。
- 仅将新 ID 追加到 `data/archive/papers.jsonl`。
- 仅分析缺少当前分析版本的论文。

合并规则建议：

- 已有论文的已有字段优先。
- 新抓取的论文可填充缺失或空字段。
- `updated`、`categories` 和 URL 字段仅在已有值为空时刷新。
- 原始 JSON、archive JSONL 或前端月度包中不重复出现同一 `arxiv_id`。

涉及文件：

- `scripts/archive_store.py`
- `scripts/fetch_arxiv.py`
- `scripts/run_daily.py`
- `scripts/analyze_deepseek.py`
- `tests/`

验证：

- 对同一日期运行两次，论文列表部分重叠。
- 第二次运行仅对新 ID 增加原始/归档计数。
- 已分析的论文被跳过。
- 新追加的论文被分析并出现在 `docs/data/by-month/YYYY-MM.json` 中。

### 第五阶段：迁移与清理

目标：迁移到按月布局，不丢失现有本地数据。

计划迁移：

- 首先添加读取兼容性：代码能同时读取扁平和月度路径。
- 其次添加按月写入行为。
- 可选添加迁移脚本，将现有扁平文件移动或复制到月度文件夹。
- 旧每日 HTML 页面的兼容性重定向保留至显式移除。

可能的迁移命令：

```bash
python scripts/migrate_monthly_layout.py --dry-run
python scripts/migrate_monthly_layout.py
```

验证：

- `python -m py_compile scripts/*.py`
- `python scripts/build_site.py`
- 本地浏览器检查 2026 年 4 月和 5 月的多个日期。
- 确认 `docs/data/by-month/*.json` 中无重复论文。

## 待决问题

1. "今天"按钮行为：如果今天的日期还没有论文，是跳转到今天之前最新的可用日期，还是保持禁用状态？
2. HTML 兼容性：旧的 `docs/daily/YYYY-MM-DD.html` 重定向存根是永久保留，还是仅在迁移周期内保留？
3. 原始/分析数据迁移：现有的扁平 `data/raw/*.json` 和 `data/analyzed/*.json` 应该移动到月度文件夹，还是保留旧文件不动、仅将新文件写入按月布局？
4. 空抓取重新运行：如果已有非空原始文件存在，而后续抓取返回空，命令是静默保留旧文件继续运行，还是应该更明显地警告，因为这可能表示抓取失败？
5. 按 ID 合并冲突：当新元数据与同一 `arxiv_id` 的已有元数据不同时，是已有元数据始终优先，还是应该刷新 `updated` 和 `categories` 等特定字段？

## 最低验收标准

- SPA 具备可用的"回到顶部"控件。
- 历史日期导航为日历形式，并包含"今天"按钮行为。
- 新的原始数据、分析数据和每日 HTML 输出可写入月度文件夹。
- 空抓取不会创建新的空 JSON 文件。
- 同一日期的重复运行追加新发现的论文，不重复已有 ID。
- 站点仍可本地构建，并能浏览所有已分析的日期。
