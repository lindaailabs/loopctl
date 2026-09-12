# ADR-0001: 项目命名

- 状态：已接受
- 日期：2026-09-12

## 背景

需要为“基于 LangGraph 的编码 agent 控制平面”确定项目/命令/包名。候选：
`loopctl`、`linda-code`、`nightshift`。

## 决策

采用 **`loopctl`**（编成代码循环的控制平面）。

## 理由

- 否决 `linda-code`：定位错位，且口头上与 `claude` 易混淆。
- 否决 `nightshift`：不含任何工程语义，无法传达项目意图。
- `loopctl` 同时作为仓库名、包名与 CLI 命令名，统一且自解释。

## 影响

包名、命令名、仓库名统一为 `loopctl`；无后续兼容负担。
