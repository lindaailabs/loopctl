# ADR-0005: 人工介入收敛为两个 gate

- 状态：已接受
- 日期：2026-09-12

## 背景

无人值守闭环需界定“何处必须人工介入”，以避免人在回路中处处卡点，又保留必要控制。

## 决策

**人工介入收敛为两个 gate**：plan gate（计划审批）与 pr gate（PR 审查）。

## 理由

- plan gate 在编码前确认方向，避免错误投入。
- pr gate 在交付前确认质量，保证可合并性。
- 其余环节（执行、测试、修复、报告）全自动，实现无人值守。

## 影响

- 状态机含 `awaiting_plan_approval` 与 `awaiting_pr_review` 两个 interrupt 点。
- 通知仅在 gate 等待与 escalated 时触发。
