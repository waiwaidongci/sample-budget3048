# TESTING

记录预注册分阶段检验功能的实际验证。本地环境无 Docker / PostgreSQL / Redis，后端测试使用 SQLite 文件库（并发用例为多线程真实竞争），Redis 以内存假对象替代；统计量与 SciPy 参考公式独立交叉核对。生产 Postgres 下行锁为 SQLAlchemy `with_for_update()` 生成的标准 `SELECT … FOR UPDATE`，唯一约束与事务语义在两库一致。

## 运行方式

```bash
cd backend
python3 -m pytest tests/ -q
```

测试文件：

| 文件 | 范围 |
|---|---|
| `tests/test_sequential.py` | 服务层 23 例：锁定校验、门槛/次序、双侧 z 检验、幂等、多线程并发扣额、显著/耗尽停试、更正诊断、更正与揭盲交错、迟归拒绝 |
| `tests/test_sequential_api.py` | HTTP 层 6 例：认证与角色权限、完整生命周期、超额/计数校验、审计留痕 |
| `tests/test_sequential_e2e.py` | 端到端剧本 1 例：登录→注册→门槛拒绝→揭盲→重试幂等→异版拒绝→更正交错→显著停试→迟归拒绝→只读视图→审计 |

## 最近一次结果

```
30 passed in 5.87s
```

## 关键场景与需求对应

| 需求 | 验证用例 |
|---|---|
| 总额不超研究上限、整数记账无浮点漂移 | `test_alpha_cap_enforced_in_integer_units`、`test_plan_over_cap_rejected`、统计交叉脚本 |
| 阶段连续、门槛递增 | `test_stages_must_be_continuous`、`test_thresholds_must_be_monotone` |
| 达门槛才可依次揭盲 | `test_below_threshold_rejected`、`test_skip_stage_rejected`、`test_unblind_deducts_alpha_and_records_version` |
| 双侧检验按当次额度 | `test_two_sided_test_math`（对 scipy 参考实现）、`test_zero_variance_does_not_crash` |
| 并发/重试不重复扣额、同版数据 | `test_retry_same_version_is_idempotent`、`test_retry_different_version_rejected`、`test_concurrent_unblind_deducts_once`（8 线程） |
| 扣额与结论一起生效 | 全部揭盲用例在单事务内断言 `alpha_spent` 与 unblinding 记录同时落库 |
| 显著或用完次数即停 | `test_significance_stops_immediately`、`test_looks_exhausted_stops_without_significance`、`test_concurrent_final_look_only_one_wins`（6 线程停试竞争） |
| 更正只诊断、不退额、原结论保留 | `test_correction_keeps_original_and_spend`、`test_identical_correction_rejected`、`test_correction_does_not_reopen_stopped_study` |
| 更正与揭盲交错 | `test_interleaved_correction_and_unblind` |
| 迟归不得重开 | `test_late_data_after_stop_only_diagnostic`、e2e 第 8/9 步 |
| 页面可查数据版本/剩余额度/停试依据 | e2e 第 10 步断言详情字段；前端 `pages/sequential.js` |
| 原样本预算不受影响 | e2e `/overview`、`/health` 与既有路由保持 200；原算法/worker 文件未改 |
| seed 与幂等 | 手工执行 `scripts.seed_demo` 两次，计数稳定为 3 方案、每方案 3 次查看、额度 0.01/0.015/0.025 |

## 前端验证

无 Node 构建步骤；以 `node --check` 对 `frontend/src` 全部 ES module 做语法校验通过。页面数据流与 e2e 接口响应字段一一对应；浏览器人工回归需在 `docker compose up` 后按 README 剧本执行。
