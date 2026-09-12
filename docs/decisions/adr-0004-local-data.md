# ADR-0004: 运行时数据不入 git

- 状态：已接受
- 日期：2026-09-12

## 背景

任务运行会产生 checkpoint、trace、stats 等数据。是否纳入版本控制需要明确。

## 决策

**checkpoint / trace / stats 为本机运行时数据，不入 git**（loopctl 仓库 `data/` 目录 gitignore）；可 review 的文本知识（报告、蒸馏结论）入 playbook 仓库。

## 理由

- 运行时数据体积大、机器相关、不可 review，提交无意义。
- 知识沉淀应作为可 review 的文本进入 playbook，体现“知识回流是工作流一环”。

## 影响

- `data/` 目录 gitignore；丢失可重跑。
- 报告与蒸馏产物写入 playbook `runs/`，而非工具仓库。
