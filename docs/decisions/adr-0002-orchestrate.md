# ADR-0002: 编排而非自建编码 agent

- 状态：已接受
- 日期：2026-09-12

## 背景

闭环核心是把“需求”变成“MR”。存在两种路径：自行训练/实现编码 agent，或把现成编码引擎（如 Claude Code）作为可插拔执行单元来编排。

## 决策

**编排而非自建编码 agent**。编码引擎经统一接口（`engines/base.py` 的 `EngineBackend`）集成，一期仅实现 `claude_code` backend，其余引擎（Codex / OpenHands 等）只定义接口、不实现 backend。

## 理由

- 自有编码能力非本项目核心差异化，且维护成本高。
- 统一接口保证未来可插拔多引擎，一期聚焦控制平面本身。

## 影响

`engines/` 仅含 `base.py` 接口与 `claude_code.py`；prompt 组装收敛在 `knowledge/`，`engines/` 不做业务判断。
