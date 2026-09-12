# ADR-0009 (draft): MR 创建与 PR 第二个人工 gate

- 状态：草案（待人工确认）
- 提出：M2 实现期间
- 关联：SPEC §5.1、§5.2、§8 M2

## 背景

M2 需要在「测试通过」之后创建 GitLab MR，并收敛为「两个 gate」（plan gate + pr gate，见 ADR-0005）。
SPEC §5.1 状态机给出 `creating_mr → awaiting_pr_review → done`，§1.2 明确一期止步于「测试通过 + MR 创建」，
且 §1.1 强调「从确认计划到提交 MR 之间零人工介入」。

## 决策选项

1. **开 MR 后直接 `done`**：自动化闭环在 MR 创建即结束，`awaiting_pr_review` 仅作为瞬时状态。
2. **开 MR 后进入 `awaiting_pr_review`（interrupt gate），人类 `approve` 才 `done`**（本草案采用）。
3. **轮询 GitLab 合并事件**自动判定 done —— 超出一期范围（属「自动部署验证」，三期）。

## 决策

采用 **选项 2**：`creating_mr` 节点推送分支并调用 GitLab API 开 MR，随后 `interrupt` 进入
`awaiting_pr_review`；人类在 GitLab 审查后运行 `loopctl approve <id>`（或 `loopctl resume <id>`）
将任务标记为 `done`。这严格贴合 SPEC 的「两个 gate」模型与 §5.1 状态机，且不引入轮询/部署逻辑。

分支策略：`creating_mr` 优先使用引擎产出的 `task.branch`，缺失时回退到 `loopctl/<task-id>`；
推送通过 `git push -u origin <branch>` 触发 GitLab 自动建分支（无需先调 GitLab 建分支 API）。
token 取自 `GITLAB_TOKEN`，base URL 取自 `GITLAB_URL`（默认 `https://gitlab.com`），均在运行时注入，不进仓库。

## 影响

- `cli/commands.py` 的 `approve` 现同时服务 plan gate 与 pr gate。
- 新增 `mr <id>` 命令查看 MR url；`status` 增加 `mr` 列。
- 所有 GitLab 交互经 `GitLabClient` 协议注入，`HttpGitLabClient` 为生产实现，单测用 fake。

## 待确认

- 是否接受「第二个 gate 需显式 `approve`」而非「开 MR 即 done」？如否决则改为选项 1（图接线简化）。
