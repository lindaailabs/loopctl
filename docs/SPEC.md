# loopctl 产品与开发规格

> 版本：0.1（MVP）
> 状态：活跃开发中
> 本文档的读者包括人类与 AI 编码 agent。**本文档与 `docs/decisions/` 下的 ADR 共同构成本项目开发的权威依据。**

---

## 0. AI Agent 开发协议

实现本仓库代码时，必须遵守：

1. **实现顺序**：严格按第 8 节里程碑推进（M0 → M1 → M2 → M3），不跳步、不提前实现后续里程碑内容。
2. **决策权限**：第 10 节“已定决策”不可重新决策。本文档未覆盖的设计决策，**不得默默自行决定**——新建 `docs/decisions/adr-XXXX-draft.md` 记录问题与备选方案，等待人工确认后转为正式 ADR。
3. **机器相关路径**（本地目录、token、GitLab id）一律通过配置文件注入（见 6.3），禁止硬编码进源码或提交进仓库。
4. **每个里程碑完成**时：更新本文档对应小节的状态、确保测试通过、按第 9 节规范提交。
5. 遇到规格歧义：选择更保守（更小范围、更少依赖）的解释，并在 PR 描述中注明歧义点。

---

## 1. 产品定位

**loopctl 是基于 LangGraph 的编码 agent 控制平面**：将 Claude Code 等编码引擎作为可插拔执行单元，实现多项目并行、无人值守的「需求 → GitLab MR」闭环，人工介入收敛为两个 gate（计划审批、PR 审查）。

### 1.1 核心价值

1. 无人值守：从确认计划到提交 MR 之间零人工介入，失败自动重试、超界自动升级人工；
2. 多项目并行：跨项目并行调度，项目内互斥串行；
3. 知识沉淀：spec 与决策维护在 git 知识仓库中，任务结束自动蒸馏报告，知识回流是工作流的一环而非人的义务。

### 1.2 一期范围

**做**：单机 CLI、Claude Code 单引擎（接口预留多引擎）、GitLab MR、计划/PR 两个人工 gate、跨项目并行调度、断点恢复、通知推送、成本与成功率统计。

**不做**（写入 roadmap，不得实现）：

| 不做 | 理由 |
|---|---|
| Web 前端 / API 服务 | CLI 层设计为与未来 API 层共享 service 函数即可 |
| 多用户、权限、团队功能 | 二期 |
| 沙箱部署、自动部署验证 | 三期；一期止步于「测试通过 + MR 创建」 |
| iOS/Android 栈 | 一期只支持常规 test_cmd 可命令行执行的项目 |
| RAG / 向量检索 | spec 注入用显式引用，不做检索 |
| Codex / OpenHands 引擎 | 只定义接口，不实现 backend |
| Celery / Redis / 消息队列 | SQLite + asyncio 起步（ADR-0007） |

---

## 2. 术语表

| 术语 | 定义 |
|---|---|
| Task | 一次「需求 → MR」的完整执行单元，全局唯一 id |
| Project | 已注册的业务项目，对应一个 git 仓库与一份 playbook spec |
| Engine | 编码执行引擎（如 claude_code backend），经适配层统一接口调用 |
| Gate | 人工审批点。一期两个：plan gate（计划审批）、pr gate（PR 审查） |
| Checkpoint | LangGraph 状态持久化，用于断点恢复 |
| Trace | 任务执行事件流，逐行 JSONL 落盘 |
| Report | 任务结束后蒸馏生成的 markdown 报告，入 playbook 仓库 |
| Distillation | 从任务过程中提取结构化知识（决策、偏差、踩坑）写入 Report 的动作 |
| Playbook | 知识仓库（私有），存放 spec、ADR（业务侧）、任务报告 |
| Escalation | 无人值守失败后转人工处理的状态与流程 |

---

## 3. CLI 契约

包名/仓库名/命令名统一为 `loopctl`。所有命令支持全局 `--json` 输出机器可读格式（为未来 API 层预留）。

```
loopctl run "<requirement>" --project <slug> [--base <branch>] [--branch-name <english>] [--fg]
loopctl status                                  # 全部任务看板
loopctl watch <task-id>                         # 实时跟随事件流
loopctl approve <task-id>                       # 通过计划，继续执行
loopctl reject <task-id> --feedback "<text>"    # 驳回计划，注入反馈回到规划
loopctl report <task-id>                        # 查看任务报告
loopctl projects                                # 列出已注册项目
loopctl stats                                   # 汇总：成功率/介入/成本/按项目
loopctl resume <task-id>                        # 恢复中断/升级的任务
loopctl init <slug> [--display-name] [--engine] [--git-remote] [--gitlab-project-id] [--default-branch] [--test-cmd] [--spec-refs ...] [--repo-path]   # 注册项目（M4；slug 为 [A-Za-z0-9_-]）
loopctl engines                                 # 列出已注册引擎及其实现状态（M4）
loopctl doctor --project <slug>                 # 运行前检查路径、引擎、测试与 GitLab
loopctl mr <task-id>                            # 查看任务对应的 GitLab MR url（M2）
loopctl serve [--concurrency N] [--watch]       # 后台监督器：执行队列中的任务（M3）
```

行为定义：

- `run`：默认将 Task 入队，由 `loopctl serve` 后台执行；`--fg` 前台阻塞到首个 gate。即使中断（Ctrl-C），checkpoint 已持久化，可 `resume`。
- 真实编码前从 `default_branch`（或单次 `--base`）创建 `<英文需求>_<yyyyMMdd_HHmmss>` 特性分支；非英文需求用 `--branch-name` 提供英文标识。`default_branch` 默认 `main`，初始化时可设为 `master` 或其他分支。
- `status`：rich 表格，列：task-id、project、state、age、engine、cost、最后事件。
- `approve`：对 `awaiting_plan_approval` 状态的任务生效；其他状态报错退出。
- `reject`：feedback 文本注入图状态，任务回到 planning 节点重新规划。
- `stats`：聚合 `data/stats.jsonl`（字段见 6.2）。

---

## 4. 架构

```
┌─ cli/          typer 命令层（薄）
├─ scheduler/    任务队列、并发控制、项目互斥锁、预算控制
├─ graph/        LangGraph 工作流：状态机、节点、gate（interrupt）
├─ engines/      执行引擎适配层：base 接口 + claude_code backend
├─ knowledge/    spec 加载、上下文组装、蒸馏、报告生成
├─ integrations/ gitlab.py、notify.py
├─ store/        SQLite、checkpointer 封装、trace 写入
└─ models/       pydantic 数据模型（Task、Project、Plan、Report 等）
```

依赖方向（严格单向，禁止反向 import）：`cli → scheduler → graph → {engines, knowledge, integrations} → store → models`。

### 4.1 engines/base.py 接口（多引擎抽象的唯一凭证）

```python
class EngineBackend(Protocol):
    name: str

    async def execute(self, ctx: EngineContext) -> EngineResult: ...

    # EngineContext: 工作目录、需求与计划全文、注入的 spec 上下文、
    #               超时、预算上限、（M2+）允许的 git 操作
    # EngineResult: 成功/失败、分支名、改动文件列表、stdout 摘要、
    #               token 用量与成本、耗时
```

`claude_code.py` backend 通过子进程调用 `claude -p`（headless，`--output-format stream-json`），负责进程生命周期、流解析、超时与心跳检测。**引擎调用的所有 prompt 组装在 knowledge/ 中完成，engines/ 不做业务判断。**

---

## 5. 工作流状态机

### 5.1 TaskState

```
queued → clarifying → planning → awaiting_plan_approval
  → executing → testing → (fixing ⇄ executing, ≤N 轮)
  → reporting → creating_mr → awaiting_pr_review → done

任意状态可达：failed / escalated / cancelled
驳回：awaiting_plan_approval --reject--> planning（携带 feedback）
```

### 5.2 节点职责

| 节点 | 输入 | 输出 | 失败模式 |
|---|---|---|---|
| clarifying | 需求文本 | 歧义问题清单（无歧义则直接通过） | — |
| planning | 需求 + spec 上下文 | plan.md：目标、改动文件预估、测试计划、风险 | 计划生成失败 → failed |
| **plan gate** | plan.md | approve / reject+feedback | 人长时间不响应 → 保持等待并通知（不超时失败） |
| executing | plan + spec | 分支上的代码改动 | 见 5.3 失败分类 |
| testing | test_cmd | 通过 / 失败详情 | 失败 → fixing 循环 |
| fixing | 失败详情 | 修复性执行指令 | 超 3 轮 → escalated |
| reporting | 全过程 trace | Report.md 写入 playbook | 写入失败 → 任务不失败，本地暂存并告警 |
| creating_mr | 分支 + 报告 + spec 引用 | GitLab MR url | API 失败 → 退避重试 → escalated |

### 5.3 失败分类与处置（无人值守可靠性的核心）

| 失败类别 | 检测方式 | 处置 |
|---|---|---|
| engine_timeout | 子进程超时（默认 30min，可配） | 重试 1 次 → escalated |
| agent_stuck | 心跳：stdout 无输出超 10min | kill → escalated |
| test_failure | test_cmd 非零退出 | fixing 循环（上限 3 轮）→ escalated |
| api_error | GitLab/API 错误 | 指数退避重试（上限 5 次）→ escalated |
| budget_exceeded | token/成本超任务预算（默认 $5） | 立即 cancel → escalated |
| agent_limit | 引擎用量限额 | 暂停任务，通知，等待 resume |

`escalated` 状态动作：推送通知 + 在 trace 标记分类 + 等待 `loopctl resume` 或人工处理。**所有上限值集中定义在 `models/config.py` 的默认配置中，可被项目级配置覆盖。**

---

## 6. 数据设计

### 6.1 仓库拓扑与数据分层

```
# 两个仓库；其本机根目录属于运行时/本地配置，绝不提交进仓库。

loopctl/                         # 工具仓库（本仓库，公开）
├─ src/loopctl/...
├─ docs/SPEC.md                 # 本文档
├─ docs/decisions/              # 工具自身 ADR（公开）
└─ data/                        # gitignore！本机运行时数据
   ├─ loopctl.db                # checkpoint + 任务状态
   ├─ traces/<task-id>.jsonl
   ├─ stats.jsonl
   └─ reports/                 # playbook 写入失败时的报告暂存

playbook/                        # 知识仓库（私有）
├─ projects/<slug>/project.toml
├─ projects/<slug>/spec.md
├─ projects/<slug>/decisions/
├─ runs/<date>/<task-id>-report.md
└─ runs/summary.md

# 本机覆盖配置（绝不提交）：
~/.loopctl/projects/<slug>.local.toml   # 仅含 repo_path 等机器相关字段
```

**规则：git 只承载可 review 的文本知识（进 playbook）；checkpoint、trace、stats 为本机运行数据（gitignore，丢失可重跑）。**

本机路径覆盖：`~/.loopctl/projects/<slug>.local.toml`，仅含 `repo_path` 等机器相关字段，不入任何仓库。

### 6.2 stats.jsonl 字段（统计来源，从 M1 起埋点，一个任务一行）

```json
{"ts": "...", "task_id": "...", "project": "...", "outcome": "done|failed|escalated|rejected",
 "auto_to_mr": true, "interventions": 1, "intervention_reasons": ["plan_rejected"],
 "fix_loops": 2, "tokens": 183000, "cost_usd": 1.24, "duration_s": 1460,
 "failure_class": null}
```

### 6.3 project.toml schema

```toml
slug = "billing"
display_name = "Billing Service"
engine = "claude_code"
git_remote = "git@gitlab.com:group/billing.git"
gitlab_project_id = 12345
default_branch = "main"
test_cmd = "pytest -q"
spec_refs = ["spec.md", "decisions/"]   # 相对 playbook/projects/<slug>/
[limits]
engine_timeout_min = 30
fix_loop_max = 3
budget_usd = 5.0
```

### 6.4 任务报告模板（reporting 节点按此生成）

```markdown
# Task <task-id>: <需求一句话摘要>
项目: <slug>  分支: <branch>  引擎: <engine>  时长/成本: <...>
## 结论
## 改动文件
## 测试结果
## 决策与偏差（相对 spec / plan 的偏离及理由）
## 人工介入记录
## 蒸馏（新增知识，待人工 review 后合入 spec/decisions）
```

---

## 7. 技术栈（锁定，不得替换）

Python ≥ 3.11 · uv · asyncio · typer + rich · langgraph（含 SqliteSaver checkpointer）· httpx · pydantic v2 · pytest · ruff。
通知：MVP 用 ntfy（单 HTTP POST）。
**禁止引入**：celery、redis、fastapi/flask/django、langchain 高层封装（仅用 langgraph 核心）、任何数据库服务。

---

## 8. 里程碑与验收

### M0 骨架（当前目标）
- [x] uv 项目初始化、src layout、ruff/pytest 配置、CI（GitHub Actions：lint + test）
- [x] `loopctl --help / projects / status` 可运行（空数据）
- [x] ADR-0001~0008 从 docs/decisions 补齐为正式文件（内容见第 10 节）
- [x] `data/` 写入 .gitignore；CLAUDE.md 建立并引用本 SPEC
- **验收**：clone 后 `uv run loopctl status` 正常退出；CI 绿。

### M1 单任务本地闭环（无 GitLab）
- [x] 配置加载（project.toml + local override 合并）
- [x] LangGraph 图：clarifying → planning → plan gate（interrupt）→ executing → testing → fixing → reporting
- [x] claude_code backend：子进程、流式解析、超时/心跳
- [x] spec 上下文组装（显式引用注入 prompt）
- [x] checkpoint 持久化 + `resume`；trace/stats 埋点
- [x] 通知（plan gate 触发 + escalated 触发）
- **验收**：对 `tests/fixtures/sample_py`（仓库内置的微型 Python 项目）执行 `loopctl run "为 calculator.add 增加负数参数校验并补充测试" --project sample --fg`，产出：分支、代码改动、测试通过、报告写入 playbook `runs/`、stats 落盘；Ctrl-C 后 `resume` 可续跑。

### M2 GitLab MR + 可靠性完整
- [x] gitlab.py：建分支、push、开 MR（MR 描述含 plan 摘要、报告链接、spec 引用）
- [x] 失败分类表全部落地、退避重试、预算控制
- [x] 真实项目上跑 5+ 任务，stats 产出第一批数据（需在具备 `GITLAB_TOKEN` 与 `claude` 二进制的真机环境执行；本仓库以 fake engine + MockTransport 覆盖完整闭环与各类失败路径）
- **验收**：真实需求任务全自动到达 MR；一次人为注入的测试失败被 fix loop 处理并在超限后正确 escalated + 通知。
- 注：`awaiting_pr_review` 作为第二个 interrupt gate，人类 `loopctl approve <id>` 后任务 `done`（见 `docs/decisions/adr-0009-mr-gate.md`）。

### M3 并行调度与恢复
- [x] 任务队列、跨项目并行（并发上限可配）、项目内互斥（ADR-0008）
- [x] 后台执行模式（`run` 不加 `--fg` 即后台入队；`loopctl serve` 监督器执行）
- [x] `stats` 汇总报表（按项目分组）
- **验收**：2+ 项目 3+ 任务同时发起，并行推进无冲突；同项目两任务串行（以 fake engine 单测覆盖并发与项目互斥；真机并行需在具备 `claude` 的环境执行）。
- 注：`resume` 断点恢复已在 M1 落地（`checkpoints.sqlite` + `loopctl resume`）。
- checkpoint 按任务隔离为 `data/checkpoints/<task-id>.sqlite`，避免跨项目执行互相阻塞。

### M4 工具内低风险增强（in-tool hardening）

在 CLI 工具内做明确、低风险的能力补全，不触及路线图二期/三期的 Web、多用户与沙箱部署（见 §1.2「不做」）。

- [x] 引擎注册表（`engines/registry.py`）：`project.toml` 的 `engine` 名在运行时经注册表解析为 backend；`load_project` 与 `loopctl init` 校验引擎名（ADR-0010）
- [x] 引擎 backend 桩：`fake`（可用 dry-run 后端）、`codex` / `openhands`（仅声明未实现，触发即 `NotImplementedError`，见 §1.2）
- [x] 项目注册命令 `loopctl init <slug>`：生成 `project.toml` + `spec.md` 桩 + `decisions/` 目录，可选 `--repo-path` 写入本机 local override
- [x] `loopctl engines`：列出已注册引擎及其实现状态
- [x] 配置校验：`slug` 命名约束、`Limits` 正值约束、未知引擎名校验
- [x] 更丰富的 `stats`：新增 `avg_duration_s` / `avg_cost_usd` 及按项目 `success_rate` / `avg_cost_usd` / `avg_duration_s`
- **验收**：`loopctl engines` 列出 claude_code/fake（implemented）与 codex/openhands（stub）；`loopctl init demo --repo-path /tmp/demo` 在 `LOOPCTL_PROJECTS_ROOT` 下生成完整项目骨架且可被 `loopctl projects` 列出；配置校验对非法 slug / 未知引擎 / 负限额报错；stats 聚合产出上述新增指标（均有单测覆盖）。

---

## 9. 工程规范

- Conventional Commits；一个里程碑拆多个小 PR，每个 PR 可独立 review
- 全量类型注解；ruff lint + format 零告警
- scheduler、graph 状态转移、engines 解析层必须有单测（可用录制的 stream-json fixture）
- 所有外部交互（子进程、GitLab、通知）经接口注入，单测不依赖网络
- 每个 PR 更新 `docs/SPEC.md` 中受影响小节（文档与代码同步演进）

---

## 10. 已定决策（浓缩版，正式记录在 ADR）

| ADR | 决策 |
|---|---|
| 0001 | 命名 loopctl（否决 linda-code：定位错位/口头混淆 claude；否决 nightshift：零工程信息） |
| 0002 | 编排而非自建编码 agent；引擎经统一接口集成，一期仅 claude_code |
| 0003 | 工具仓库公开 / playbook 私有；loopctl 自身开发 SPEC 与 ADR 在工具仓库 |
| 0004 | checkpoint/trace/stats 本地不入 git；报告与蒸馏知识入 playbook |
| 0005 | 人工介入收敛为 plan gate + pr gate 两点 |
| 0006 | 知识蒸馏是工作流收尾节点，报告自动生成，人工只 review |
| 0007 | 调度用 SQLite + asyncio，明确不上 Celery 的触发条件（多机/常驻服务需求出现时复议） |
| 0008 | 跨项目并行、项目内互斥串行 |
| 0010 | 引擎经注册表按名解析；codex/openhands 仅声明不实现（M4） |

---

## 11. 本机环境说明（不提交，仅开发参考）

- 工具仓库（loopctl）与知识仓库（playbook）的根目录：本机自定，作为运行时配置，不进仓库。
- 依赖：本机需安装 `claude` CLI（headless 调用）。
- 密钥：`GITLAB_TOKEN`、`NTFY_URL` 走环境变量，不进仓库。
