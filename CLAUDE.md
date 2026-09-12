# loopctl — Agent 开发纪律摘要

本文件供编码 agent 在每次会话自动加载。完整权威规格见 [`docs/SPEC.md`](docs/SPEC.md)；架构决策见 [`docs/decisions/`](docs/decisions/)。

## 必读协议（来自 SPEC 第 0 节）

1. **实现顺序**：严格按 SPEC 第 8 节里程碑推进（M0 → M4），不跳步。开始工作时，从**当前里程碑第一个未勾选项**入手。
2. **决策权限**：SPEC 第 10 节“已定决策”不可重新决策。规格未覆盖的设计问题，**不得默默自决**——新建 `docs/decisions/adr-XXXX-draft.md` 记录问题与备选方案，等待人工确认。
3. **机器相关路径**：本地目录、token、GitLab id 一律通过配置文件/环境变量注入，禁止硬编码或提交。
4. **里程碑收尾**：更新 SPEC 对应小节状态、确保测试通过、按第 9 节规范提交。
5. **歧义处理**：取更保守（更小范围、更少依赖）的解释，并在 PR 描述注明。

## 工程规范（来自 SPEC 第 9 节）

- Conventional Commits；里程碑拆多个可独立 review 的小 PR。
- 全量类型注解；`uv run ruff check .` 与 `ruff format --check .` 零告警。
- 外部交互（子进程、GitLab、通知）全部接口注入，单测不依赖网络。
- 每 PR 同步更新 `docs/SPEC.md` 受影响小节。

## 启动检查

- 环境：`uv sync` 安装依赖；`uv run loopctl status` 应正常退出。
- 当前里程碑状态以 `docs/SPEC.md` 第 8 节勾选框为准。
