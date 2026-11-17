ROLES=('admin','analyst','viewer')
STATES=('queued','running','completed','failed')
# 预注册分阶段方案生命周期：active 可依次揭盲；stopped 后只允许诊断更正，不得重开。
PLAN_STATES=('active','stopped')
# 停试依据：significant 达显著；looks_exhausted 查看次数与额度用完。
STOP_REASONS=('significant','looks_exhausted')
