# 问题批次隔离 · 测试记录

日期：2026-11-14 · 结论以本文件列出的实际执行结果为准，未执行的项不写成通过。

## 环境

- 未启动 Docker Compose（本机无 Docker）；后端以 FastAPI `TestClient` + SQLite 临时库运行，
  `SEED_DEMO`、`ARTIFACT_DIR`、`REDIS_URL` 指向本地临时路径。
- 前端页面以 Node ESM 导入页面模块、模拟 API 响应做渲染检查，未做真实浏览器截图。
- 依赖：fastapi 0.115.12、SQLAlchemy 2.0.41、redis 5.2.1、PyJWT 2.10.1、httpx、pytest。

## 执行

```bash
cd test-artifacts/gb-1015/tests && python3 -m pytest -q
```

```
8 passed, 1 warning in 0.90s
```

## 覆盖点与结果

| 检查 | 用例 | 结果 |
|---|---|---|
| 分析员/观察员调用隔离接口返回 403，观察员可读取空列表 | test_01_permissions | 通过 |
| 隔离后拒绝新试算、批准、新建分发计划、重新启用计划 | test_02_quarantine_and_blocks | 通过 |
| 隔离后归档对 admin/analyst/viewer 下载均返回 409，仍出现在归档列表 | test_02_quarantine_and_blocks | 通过 |
| 原因少于 5 个字符返回 422 | test_02_quarantine_and_blocks | 通过 |
| 同一批次重复提交隔离不新增处置记录、不重复写审计 | test_03_retry_idempotent | 通过 |
| 隔离时仍在排队的 worker 任务完成写入被拒绝，任务冻结为 quarantined 且无结果 | test_04_worker_cannot_reopen | 通过 |
| 修正批次须在隔离生效后另建，旧批次不能充当修正去向 | test_05_correction_batch | 通过 |
| 修正批次重新试算、批准、分发、下载成功；原批次持续拒绝；进度四步走完 | test_05_correction_batch | 通过 |
| 分发会话持有隔离前读到的计划对象，隔离提交后才写归档时被拒绝，不产生新归档 | test_delivery_after_boundary_rejected | 通过 |
| 隔离时正在写结果的任务被冻结，不重新开放 | test_job_result_write_after_boundary_rejected | 通过 |
| 旧库结构（缺新列）执行迁移后新增列、历史行默认未隔离 | 手工 SQLite 旧表 + migrate 脚本 | 通过 |
| seed 演示后隔离，worker tick 不再产生新归档、已批准数为 0 | test_smoke_seed | 通过 |
| 隔离页、结果页、分发页、数据页、工作台对隔离状态渲染正确 | Node 渲染检查 | 通过 |

## 未执行

- 真实 PostgreSQL 下的行锁并发压测（SQLite 下验证的是提交后状态校验与失效对象拒绝逻辑）。
- Docker Compose 五服务启动、Nginx 反代、浏览器端点击与截图。
- Redis 限流与真实 worker 进程循环。
