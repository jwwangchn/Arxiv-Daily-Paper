# scripts 目录重构计划

创建时间：2026-05-13

## 目标

重构 `scripts/` 目录，让主流程入口、批处理工具和公共库模块分层更清晰，同时保持现有 pipeline 行为不变：

```text
arXiv metadata -> fetch -> archive -> analyze -> archive -> build_site -> docs/
```

本次重构的成功标准不是“拆得越细越好”，而是：

- 主入口一眼可见；
- 公共依赖集中在 `scripts/lib/`；
- 批量工具与日常入口分开；
- 外部命令、GitHub Actions、测试和旧脚本路径有明确切换策略；
- 不改变抓取、分析、归档、建站的数据语义。

## 当前结构和依赖

当前主要依赖关系：

```text
run_daily.py
├── fetch_arxiv.py
│   ├── archive_store.py
│   ├── progress.py
│   └── utils.py
├── analyze_deepseek.py
│   ├── archive_store.py
│   ├── progress.py
│   └── utils.py
├── build_site.py
│   ├── archive_store.py
│   └── utils.py
└── utils.py

analyze_archive.py
├── analyze_deepseek.py
├── archive_store.py
├── build_site.py
└── utils.py

backfill_arxiv.py
├── fetch_arxiv.py
└── utils.py
```

已确认的外部引用点：

- `README.md` 和 `AGENTS.md` 中有大量 `python scripts/run_daily.py`、`fetch_arxiv.py`、`analyze_deepseek.py`、`build_site.py` 示例。
- `.github/workflows/daily.yml` 当前执行 `python scripts/run_daily.py`。
- `tests/` 直接 import 旧模块名，例如 `from fetch_arxiv import ...`、`from archive_store import ...`。
- `analyze_deepseek.py` 与 `build_site.py` 都包含 taxonomy 相关逻辑，存在重复和职责混杂。

## 关键设计约束

### 1. 不建议让数字前缀文件承担可导入模块职责

`scripts/01_daily.py` 这类名字适合命令行排序和直接执行：

```bash
python scripts/01_daily.py
```

但它不是合法的普通 Python import 标识符，不能写：

```python
from scripts.01_daily import main
```

因此推荐策略是：

- 数字前缀文件只作为 CLI wrapper；
- 真正可 import 的实现放在合法模块名中；
- 旧脚本路径不作为长期入口，README、测试、workflow 和内部 import 一次性切到新结构。

### 2. 先稳定公共库，再迁移入口

`PROJECT_ROOT`、JSON 读写、日志、配置和 archive JSONL 是所有脚本的底层依赖。迁移顺序必须从底层到上层，避免循环依赖和半迁移状态。

### 3. 重构不改变数据行为

本计划只调整脚本组织和 import，不顺手修改：

- 抓取策略；
- DeepSeek prompt；
- analysis version；
- archive JSONL schema；
- `docs/data/by-month/*.json` schema；
- site UI 行为。

如需结合“按月份组织文件、空抓取不写 JSON、重复运行追加”等需求，应作为独立功能分支或后续阶段执行。

## 推荐目标结构

推荐采用“可导入实现模块 + 数字 CLI wrapper”的结构，并一次性把项目入口切到新路径：

```text
scripts/
├── 01_daily.py                  # CLI wrapper: 调用 commands.daily.main
├── 02_fetch.py                  # CLI wrapper: 调用 commands.fetch.main
├── 03_analyze.py                # CLI wrapper: 调用 commands.analyze.main
├── 04_build.py                  # CLI wrapper: 调用 commands.build.main
│
├── batch/
│   ├── __init__.py
│   ├── analyze_archive.py       # 批量分析 archive
│   └── backfill_arxiv.py        # 批量回填 metadata
│
├── commands/
│   ├── __init__.py
│   ├── daily.py                 # 原 run_daily.py 的主体实现
│   ├── fetch.py                 # 原 fetch_arxiv.py 的主体实现
│   ├── analyze.py               # 原 analyze_deepseek.py 的主体实现
│   └── build.py                 # 原 build_site.py 的主体实现
│
└── lib/
    ├── __init__.py
    ├── config.py                # 原 utils.py: paths/config/json/logging
    ├── archive.py               # 原 archive_store.py
    ├── progress.py              # 原 progress.py
    └── taxonomy.py              # taxonomy 加载、索引、规范化工具
```

这样做的好处：

- 用户仍能看到 `01_daily.py` 到 `04_build.py` 的顺序化主流程。
- `commands/*.py` 提供合法、稳定、可测试的 Python 模块名。
- README、AGENTS、workflow、tests 全部指向新入口，避免长期维护两套命令。
- `lib/taxonomy.py` 可以同时服务分析和建站，减少重复逻辑。

## 文件映射

| 当前路径 | 推荐新职责 | 处理方式 |
| --- | --- | --- |
| `scripts/utils.py` | `scripts/lib/config.py` | 迁移实现，旧入口删除 |
| `scripts/archive_store.py` | `scripts/lib/archive.py` | 迁移实现，旧入口删除 |
| `scripts/progress.py` | `scripts/lib/progress.py` | 迁移实现，旧入口删除 |
| `scripts/analyze_deepseek.py` | `scripts/commands/analyze.py` | 主体迁移，taxonomy 逻辑抽出，旧入口删除 |
| `scripts/fetch_arxiv.py` | `scripts/commands/fetch.py` | 主体迁移，旧入口删除 |
| `scripts/build_site.py` | `scripts/commands/build.py` | 主体迁移，旧入口删除 |
| `scripts/run_daily.py` | `scripts/commands/daily.py` | 主体迁移，旧入口删除 |
| 无 | `scripts/01_daily.py` | 新增 CLI wrapper |
| 无 | `scripts/02_fetch.py` | 新增 CLI wrapper |
| 无 | `scripts/03_analyze.py` | 新增 CLI wrapper |
| 无 | `scripts/04_build.py` | 新增 CLI wrapper |
| `scripts/analyze_archive.py` | `scripts/batch/analyze_archive.py` | 迁移为批处理工具，旧入口删除 |
| `scripts/backfill_arxiv.py` | `scripts/batch/backfill_arxiv.py` | 迁移为批处理工具，旧入口删除 |

## import 规范

迁移后内部代码优先使用绝对 import：

```text
from lib.config import PROJECT_ROOT, ensure_dirs, load_config
from lib.archive import append_new_papers, papers_for_date
from lib.progress import progress_bar
from lib.taxonomy import load_taxonomy_prompt, taxonomy_indexes
from commands.analyze import analyze_date
from commands.build import build_site
from commands.fetch import fetch_papers, save_raw
```

保留 `scripts/lib/__init__.py` 的轻量 re-export，但只导出特别常用且稳定的符号，例如：

- `PROJECT_ROOT`
- `ensure_dirs`
- `load_config`
- `read_json`
- `write_json`
- `progress_bar`

不建议在 `lib/__init__.py` 导出过多业务函数，否则会重新制造隐式依赖。

## taxonomy 拆分范围

`scripts/lib/taxonomy.py` 建议承接：

- `TAXONOMY_PATH`
- taxonomy JSON 加载；
- taxonomy prompt 文本生成；
- area/category/sub-area 索引构建；
- label normalize；
- canonical area/category 校验工具。

`commands/analyze.py` 继续负责：

- DeepSeek prompt 模板；
- API 调用；
- response JSON 解析；
- score normalization；
- analysis archive 写入。

`commands/build.py` 继续负责：

- site data merge；
- HTML/CSS/JS 生成；
- `docs/data/dates.json` 和 `docs/data/by-month/*.json` 输出；
- daily redirect 页面生成。

如发现 `build.py` 与 `analyze.py` 仍需要不同的 taxonomy 映射，可在 `lib/taxonomy.py` 中提供两个明确命名的函数，而不是让两个脚本各自复制一份。

## 切换策略

### 旧脚本路径

旧主入口不长期保留，迁移完成后删除：

```text
scripts/run_daily.py
scripts/fetch_arxiv.py
scripts/analyze_deepseek.py
scripts/build_site.py
scripts/analyze_archive.py
scripts/backfill_arxiv.py
scripts/utils.py
scripts/archive_store.py
scripts/progress.py
```

其中 `utils.py`、`archive_store.py`、`progress.py` 也不保留 re-export。当前已知引用都在仓库内，测试和内部代码全部改用 `lib.*`。

### README / AGENTS / workflow

迁移完成后统一更新：

- README 主推 `python scripts/01_daily.py`、`02_fetch.py`、`03_analyze.py`、`04_build.py`。
- AGENTS 中的 Important Paths、Commands、Lightweight checks 全部改为新路径。
- `.github/workflows/daily.yml` 改为执行 `python scripts/01_daily.py`。
- cron 保持 `"0 20 * * *"` 不变。

## 分阶段实施计划

### 阶段 0：建立保护网

目标：确保重构前行为有可回归的基线。

动作：

1. 记录当前 `git status --short`，确认已有未提交改动范围。
2. 跑轻量检查：
   - `python -m py_compile scripts/*.py`
   - `pytest` 或至少跑现有 `tests/`
   - `python scripts/build_site.py`
3. 记录当前可用命令：
   - `python scripts/run_daily.py --mock`
   - `python scripts/build_site.py`

验收：

- 重构前测试结果清楚。
- 若已有失败，记录为 baseline，不在重构中顺手修 unrelated bug。

### 阶段 1：创建 package 骨架

目标：先创建目录，不迁移业务逻辑。

动作：

1. 新增：
   - `scripts/lib/__init__.py`
   - `scripts/commands/__init__.py`
   - `scripts/batch/__init__.py`
2. 暂不改旧脚本。

验收：

- `python -m py_compile scripts/*.py scripts/lib/*.py scripts/commands/*.py scripts/batch/*.py` 通过。

### 阶段 2：迁移底层公共模块

目标：先搬最底层依赖。

动作：

1. `utils.py` 主体迁移到 `lib/config.py`。
2. `archive_store.py` 主体迁移到 `lib/archive.py`。
3. `progress.py` 主体迁移到 `lib/progress.py`。
4. 删除旧公共模块入口，不保留临时 re-export。
5. 更新所有直接 import 到 `lib.*`。

验收：

- 新 import 可用：
  - `from lib.config import PROJECT_ROOT`
  - `from lib.archive import append_new_papers`
  - `from lib.progress import progress_bar`
- 现有 tests 中 config/archive 相关测试通过。

### 阶段 3：抽出 taxonomy 公共逻辑

目标：减少 `analyze_deepseek.py` 和 `build_site.py` 中重复 taxonomy 逻辑。

动作：

1. 新增 `lib/taxonomy.py`。
2. 从分析脚本迁出 prompt taxonomy 文本和索引构建。
3. 从建站脚本迁出 area/category mapping。
4. 保持输出字段不变：
   - `primary_area_en`
   - `primary_area`
   - `category`
   - `sub_area`

验收：

- 同一篇已有分析数据经 `build_site.py` 生成的分类展示不变化。
- `python scripts/analyze_deepseek.py --date YYYY-MM-DD --cache-only` 的缓存路径仍工作。

### 阶段 4：迁移主流程实现到 commands

目标：把四个主流程脚本的真实实现放到合法模块名中。

动作：

1. `run_daily.py` 主体迁移到 `commands/daily.py`。
2. `fetch_arxiv.py` 主体迁移到 `commands/fetch.py`。
3. `analyze_deepseek.py` 主体迁移到 `commands/analyze.py`。
4. `build_site.py` 主体迁移到 `commands/build.py`。
5. 删除旧主入口文件，避免长期混用。

验收：

- 新模块可 import：
  - `from commands.daily import main`
  - `from commands.fetch import fetch_papers`
  - `from commands.analyze import analyze_date`
  - `from commands.build import build_site`

### 阶段 5：新增数字顺序 CLI wrapper

目标：提供用户想要的顺序化入口，但不让它们承担 import 责任。

动作：

1. 新增 `scripts/01_daily.py`。
2. 新增 `scripts/02_fetch.py`。
3. 新增 `scripts/03_analyze.py`。
4. 新增 `scripts/04_build.py`。
5. 每个 wrapper 只负责调用对应 `commands/*.py` 的 `main()`。

验收：

- 新命令可运行：
  - `python scripts/01_daily.py --mock`
  - `python scripts/02_fetch.py --help`
  - `python scripts/03_analyze.py --help`
  - `python scripts/04_build.py --mock`

### 阶段 6：迁移 batch 工具

目标：把不属于日常主链路的工具放入 `batch/`。

动作：

1. `analyze_archive.py` 主体迁移到 `batch/analyze_archive.py`。
2. `backfill_arxiv.py` 主体迁移到 `batch/backfill_arxiv.py`。
3. 删除旧批处理入口文件。

验收：

- 新命令可用：
  - `python scripts/batch/analyze_archive.py --help`
  - `python scripts/batch/backfill_arxiv.py --help`

### 阶段 7：迁移测试和文档

目标：让测试覆盖新模块，并移除旧路径依赖。

动作：

1. 将测试主体 import 迁移到新模块：
   - `commands.fetch`
   - `commands.analyze`
   - `commands.build`
   - `commands.daily`
   - `lib.config`
   - `lib.archive`
2. 删除旧路径兼容测试，不保留旧 import 合约。
3. 更新 README / AGENTS 中的结构说明和命令示例。
4. `.github/workflows/daily.yml` 本轮切到 `scripts/01_daily.py`。

验收：

- `pytest` 通过。
- README 和 AGENTS 中的命令与实际入口一致。
- workflow 只改执行入口，不改 cron。

### 阶段 8：最终验证

目标：确认重构没有影响数据流和站点产物。

动作：

1. `python -m py_compile scripts/*.py scripts/lib/*.py scripts/commands/*.py scripts/batch/*.py`
2. `pytest`
3. `python scripts/04_build.py`
4. `python scripts/01_daily.py --mock`
5. 本地浏览器检查：
   - `http://localhost:8000/?date=2026-05-11`
   - 任意 2026-04 日期
   - 最新日期

验收：

- 站点可正常加载。
- `docs/data/dates.json` 和 `docs/data/by-month/*.json` schema 不变。
- 新命令、测试和 workflow 引用一致。
- 没有由重构引入的数据文件 schema 改动。

## 风险和缓解

### 风险 1：数字文件名导致 import 问题

缓解：数字文件只做 CLI wrapper，所有可 import 逻辑放到 `commands/*.py`。

### 风险 2：运行脚本时 `sys.path` 与 package import 不一致

缓解：保持 `scripts/` 为脚本执行根目录下的 import root，内部使用 `from lib...`、`from commands...`，并用直接脚本执行方式逐个验证。

### 风险 3：旧测试依赖旧模块名

缓解：测试与代码同一轮迁移到新模块名；不保留旧路径兼容测试，避免暗示旧 API 仍受支持。

### 风险 4：taxonomy 抽取改变分析或展示结果

缓解：抽取时不改 prompt 文本、不改 normalization 规则、不改 fallback 类别，只移动代码位置。

### 风险 5：workflow 和文档切换后本地遗漏旧引用

缓解：使用 `rg` 全仓检查旧脚本名和旧 import，确保 README、AGENTS、workflow、tests、scripts 内部引用全部切到新结构。

## 建议的提交拆分

如果后续要提交，建议分成 3 到 4 个 commit：

1. `refactor: add script package skeleton and move shared libs`
2. `refactor: move pipeline commands under scripts/commands`
3. `refactor: add ordered CLI wrappers and batch scripts`
4. `docs: switch docs and workflow to new script entrypoints`

## 已确认决策

1. 数字入口作为最终推荐命令。  
   README、AGENTS、workflow 全部切到 `scripts/01_daily.py` 等新入口。

2. GitHub Actions 本轮一起改。  
   只改执行文件名，不改 cron 和 secret 逻辑。

3. 旧脚本路径不长期保留。  
   迁移完成后删除旧主入口和批处理入口，避免双入口维护。

4. 接受新增 `scripts/commands/`。  
   数字文件只做 CLI wrapper，真实实现放在合法模块名中。

5. taxonomy 本轮只做代码搬迁。  
   不改 prompt、不改分类规则、不改 fallback 行为。

## 推荐执行顺序

如果你确认以上问题，我建议按下面顺序执行：

1. 创建 `lib/commands/batch` 骨架。
2. 迁移 `utils/archive_store/progress` 到 `lib/` 并删除旧入口。
3. 抽 `lib/taxonomy.py`，只搬迁不改规则。
4. 迁移四个主脚本实现到 `commands/`。
5. 添加 `01_daily.py` 到 `04_build.py` wrapper。
6. 迁移两个批处理脚本到 `batch/`。
7. 更新测试 import，不添加旧路径兼容测试。
8. 本地跑 py_compile、pytest、build_site、mock daily。
9. 更新 README、AGENTS 和 GitHub Actions 到新入口。
10. 全仓 `rg` 检查旧入口和旧 import，确认没有残留引用。
