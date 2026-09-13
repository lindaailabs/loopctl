# loopctl Agent 测评方案

> 状态：草案
> 目标：为 loopctl 作为编码 agent 控制平面建立可重复、可隔离、可进 CI 的测评体系。

---

## 1. 测评定位

loopctl 不是问答型 agent，而是一个“需求 -> 计划 -> 执行 -> 测试 -> 修复 -> 报告 -> MR/PR gate”的编码 agent 控制平面。因此测评重点不是自然语言回答质量，而是无人值守工程闭环的可靠性、安全性和可观测性。

测评回答三个问题：

1. 控制流是否稳定：任务能否到达正确 gate 或正确 escalated。
2. 工程结果是否可靠：代码改动、测试、报告、统计是否符合预期。
3. 运行是否安全：是否隔离工作区，是否避免无关提交，是否不污染真实项目。

---

## 2. 测评分层

### 2.1 Offline Control Eval

一期优先实现并默认执行。

特点：

- 使用 fake engine、fake GitHub/GitLab client。
- 使用 fixture repo 和临时目录。
- 不访问网络，不调用真实模型，不开真实 MR/PR。
- 适合本机和 CI 高频运行。

覆盖范围：

- 状态机路径：queued、planning、gate、executing、testing、fixing、reporting、creating_mr、done、escalated。
- 人工 gate：plan approval、plan rejection、PR review resume。
- 失败分类：engine_timeout、agent_stuck、engine_error、test_failure、budget_exceeded、api_error、environment_error。
- 持久化：SQLite task store、LangGraph checkpoint、trace、stats、report。
- 调度：跨项目并行、项目内互斥、queued task claim。
- 安全：自动提交只提交 engine 报告文件，未报告脏工作树升级。

### 2.2 Sandbox Coding Eval

第二阶段引入。

特点：

- 使用真实 engine，例如 `claude_code`。
- 目标仓库是临时 clone、fixture repo 或专用 sandbox repo。
- MR/PR client 默认 dry-run，不直接写生产远端。
- 会消耗模型额度和本机执行时间。

覆盖范围：

- 真实模型能否理解需求并修改代码。
- 测试是否通过。
- diff 是否最小、是否存在无关变更。
- report 是否对人类 review 有用。
- token、cost、duration、fix loops 是否可接受。

### 2.3 Production-like Eval

第三阶段再做。

特点：

- 接真实 GitHub/GitLab，但只针对测试组织或 sandbox repo。
- 验证真实 push、MR/PR 创建、token、网络失败恢复。
- 不用于日常 CI。

---

## 3. 本机隔离策略

所有 eval runner 必须在独立运行目录中执行：

```text
/tmp/loopctl-evals/<run-id>/
  data/
  projects/
  runs/
  repos/
  results/
```

每次运行设置独立环境变量：

```bash
LOOPCTL_DATA_DIR=/tmp/loopctl-evals/<run-id>/data
LOOPCTL_PROJECTS_ROOT=/tmp/loopctl-evals/<run-id>/projects
LOOPCTL_RUNS_ROOT=/tmp/loopctl-evals/<run-id>/runs
```

约束：

- 不在 loopctl 仓库本身执行 agent 修改任务。
- 不在真实业务 repo 的 `main` / `master` 上执行。
- 每个任务使用独立 repo clone 或 git worktree。
- 默认不 push，不开真实 MR/PR。
- eval 产物只写入临时目录或未提交的 `evals/reports/`，不进入代码仓库。

---

## 4. 建议目录结构

```text
evals/
  README.md
  runner.py
  scoring.py
  suites/
    offline.yaml
    sandbox.yaml
  cases/
    python_calculator/
      repo/
      tasks.yaml
      expected/
  reports/        # gitignored
```

`docs/evals.md` 记录稳定测评设计；`evals/` 存放可执行 harness、case 和套件定义。

---

## 5. Case 定义

Offline case 示例：

```yaml
id: py_calc_validation
suite: offline
project: python_calculator
requirement: "Add validation so divide(x, 0) raises ValueError"
engine: fake
provider: gitlab
expected:
  terminal_state: awaiting_pr_review
  tests_pass: true
  report_generated: true
  trace_generated: true
  stats_recorded: true
  max_fix_loops: 1
  changed_files:
    - calculator.py
  disallow_untracked_side_effects: true
```

Sandbox case 可以增加人工或半自动 rubric：

```yaml
rubric:
  correctness: 0-5
  minimal_diff: 0-5
  test_quality: 0-5
  report_quality: 0-5
  safety: 0-5
```

---

## 6. 核心指标

必须记录：

- `task_success_rate`
- `mr_gate_rate`
- `escalation_rate`
- `wrong_escalation_rate`
- `tests_pass_rate`
- `report_generated_rate`
- `trace_generated_rate`
- `stats_recorded_rate`
- `unexpected_file_change_rate`
- `avg_duration_s`
- `avg_cost_usd`
- `avg_fix_loops`
- `avg_interventions`

Offline eval 的首要通过标准：

- 所有 case 到达预期状态。
- terminal task 均写入 stats。
- report / trace 生成率为 100%。
- safety case 中没有无关提交。
- 不产生主仓库未预期改动。

---

## 7. 一期落地计划

### M1: 文档与现有测试基线

- 落档本方案。
- 将当前单元测试作为临时 Offline Control Eval 基线。
- 每次评估至少运行：

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

### M2: Offline Eval Harness

- 新增 `evals/runner.py`。
- 新增 `evals/suites/offline.yaml`。
- 新增 5-10 个 fixture cases。
- runner 输出：
  - `eval-results.jsonl`
  - `summary.md`
  - 每个 task 的 trace/report/stats 路径
  - 必要时输出 diff 摘要

建议命令：

```bash
uv run loopctl-eval --suite offline
```

### M3: Sandbox Coding Eval

- 支持真实 engine。
- 每个 case 创建临时 clone/worktree。
- 默认使用 dry-run MR/PR client。
- 记录 token、cost、duration、fix loops、diff size。

建议命令：

```bash
uv run loopctl-eval --suite sandbox --engine claude_code --max-tasks 5
```

---

## 8. 当前可执行测评映射

在正式 `evals/runner.py` 落地前，以下测试构成当前可执行的 Offline Control Eval：

| 测评主题 | 当前覆盖 |
|---|---|
| 状态机闭环、gate、resume、失败升级 | `tests/unit/test_graph.py` |
| 调度并发与项目互斥 | `tests/unit/test_scheduler.py` |
| 自动提交安全、runtime 可用性 | `tests/unit/test_usability.py` |
| GitHub/GitLab dry-run 与 API 失败 | `tests/unit/test_github.py`, `tests/unit/test_gitlab.py` |
| task store、trace、stats 聚合 | `tests/unit/test_store.py`, `tests/unit/test_stats_enriched.py` |
| CLI smoke 与配置加载 | `tests/test_smoke.py`, `tests/unit/test_config.py`, `tests/unit/test_doctor_global.py` |

当前基线通过标准：

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

三者均通过，视为本机 offline control eval 通过。
