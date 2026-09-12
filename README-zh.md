# loopctl

> 基于 LangGraph 的编码 agent 控制平面。

`loopctl` 将 Claude Code 等编码引擎作为可插拔的执行单元，跨多个项目驱动大体无人值守的「需求 → GitLab MR」闭环。人工介入被收敛为两个 gate：计划审批（plan gate）与 PR 审查（pr gate）。

本仓库是**工具**（开源）。项目专属知识（spec、决策、任务报告）存放在独立的私有 *playbook* 仓库。

## 状态

活跃开发中 —— MVP（v0.1）。权威规格见 [`docs/SPEC.md`](docs/SPEC.md)，架构决策见 [`docs/decisions/`](docs/decisions/)。

## 快速开始

```bash
# 安装（uv 负责管理环境与依赖）
uv sync

# 查看任务看板（在没有任何任务之前为空）
uv run loopctl status

# 列出已注册的项目
uv run loopctl projects

# 注册新项目（在你的 playbook 下生成 project.toml 与 spec.md 桩）
uv run loopctl init my-project --repo-path /path/to/repo

# 列出可用的执行引擎
uv run loopctl engines
```

机器相关配置（仓库路径、token、GitLab 项目 id）通过配置文件与环境变量注入，**绝不**提交进仓库。详见 `docs/SPEC.md` 第 6 节配置模型。

## 开发

```bash
uv sync                  # 安装依赖（含 dev 分组）
uvx ruff check .         # lint
uvx ruff format .        # 格式化
uv run pytest            # 运行测试
```

## 许可证

MIT —— 见 [`LICENSE`](LICENSE)。
