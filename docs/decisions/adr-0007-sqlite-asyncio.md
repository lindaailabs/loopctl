# ADR-0007: 调度用 SQLite + asyncio

- 状态：已接受
- 日期：2026-09-12

## 背景

需要持久化任务状态、checkpoint 与并发调度。是否引入 Celery / Redis 等分布式组件需决策。

## 决策

**一期采用 SQLite + asyncio（单机）**。明确**不上 Celery / Redis** 的触发条件：当出现多机部署或常驻服务需求时再复议。

## 理由

- 一期为单机 CLI，SQLite + asyncio 足够，零额外运维。
- 避免过度工程；分布式组件仅在确有需求时引入。

## 影响

- checkpointer 用 langgraph `SqliteSaver`。
- scheduler 在 M3 才充实队列与互斥；当前不影响架构。
