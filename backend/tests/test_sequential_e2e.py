"""端到端剧本：以内存假 Redis 替换限流/队列，覆盖完整 HTTP 链路与前端页面所需的全部数据形态。"""
import os
import pytest
os.environ.setdefault('DATABASE_URL','sqlite+pysqlite:////tmp/seq_e2e.db')
os.environ.setdefault('REDIS_URL','redis://fake:6379/0')
os.environ.setdefault('JWT_SECRET','e2e-secret')

class FakeRedis:
    def __init__(self): self.kv={}
    def incr(self,k): self.kv[k]=self.kv.get(k,0)+1;return self.kv[k]
    def expire(self,*a): pass
    def ping(self): return True
    def rpush(self,*a): return 1
    def blpop(self,*a,**k): return None

import src.middlewares.rate_limit as rl
rl.redis=FakeRedis()
import src.main as main_mod
main_mod.Redis.from_url=lambda *a,**k:FakeRedis()
from fastapi.testclient import TestClient
from src.config.database import Base,engine,Session
from src.models import user,study,observation,run,review,audit,sequential  # noqa: F401
from src.models.user import User
from src.models.study import Study
from src.main import app
from src.utils.security import hash_password

client=TestClient(app)

@pytest.fixture()
def token():
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    with Session() as db:
        db.add_all([
            User(email='admin@demo.local',role='admin',password_hash=hash_password('pw')),
            User(email='analyst@demo.local',role='analyst',password_hash=hash_password('pw')),
            User(email='viewer@demo.local',role='viewer',password_hash=hash_password('pw')),
            Study(name='E2E研究',source_filename='e2e.csv',description=''),
        ]);db.commit()
    def login(email):
        r=client.post('/auth/login',json={'email':email,'password':'pw'})
        return {'Authorization':'Bearer '+r.json()['token']}
    return login

def test_full_daily_script(token):
    admin,analyst,viewer=token('admin@demo.local'),token('analyst@demo.local'),token('viewer@demo.local')

    # 健康检查与总览（原样本预算功能不受影响）
    assert client.get('/health').status_code==200
    ov=client.get('/overview',headers=viewer).json()
    assert 'studies' in ov and 'runs' in ov

    # 1) 分析师注册分阶段方案：两次查看，额度 0.02 + 0.03 = 上限 0.05
    plan=client.post('/sequential/plans',headers=analyst,json={
        'study_id':1,'name':'E2E·冬季分阶段','alpha_total':0.05,'looks':[
            {'stage':1,'reach_a':1000,'reach_b':1000,'alpha_k':0.02},
            {'stage':2,'reach_a':2000,'reach_b':2000,'alpha_k':0.03}]}).json()
    pid=plan['id']
    assert plan['alpha_remaining_value']==0.05

    # 2) 未达门槛揭盲被拒，额度不动
    r=client.post(f'/sequential/plans/{pid}/looks/1/unblind',headers=analyst,
                  json={'reach_a':800,'click_a':80,'reach_b':800,'click_b':90})
    assert r.status_code==409
    assert client.get(f'/sequential/plans/{pid}',headers=viewer).json()['alpha_spent_value']==0

    # 3) 达门槛第一次揭盲（构造不显著：10.0% vs 11.2%）
    r=client.post(f'/sequential/plans/{pid}/looks/1/unblind',headers=analyst,
                  json={'reach_a':1000,'click_a':100,'reach_b':1000,'click_b':112})
    d=r.json()
    assert d['unblindings'][0]['result']['significant'] is False
    assert d['alpha_spent_value']==0.02 and d['alpha_remaining_value']==0.03
    assert d['next_stage']==2

    # 4) 重试同版数据：幂等，不重复扣额（管理员身份重试，模拟并发/刷新）
    r2=client.post(f'/sequential/plans/{pid}/looks/1/unblind',headers=admin,
                   json={'reach_a':1000,'click_a':100,'reach_b':1000,'click_b':112})
    assert len(r2.json()['unblindings'])==1 and r2.json()['alpha_spent_value']==0.02

    # 5) 异版重试被拒
    r3=client.post(f'/sequential/plans/{pid}/looks/1/unblind',headers=analyst,
                   json={'reach_a':1000,'click_a':101,'reach_b':1000,'click_b':112})
    assert r3.status_code==409

    # 6) 更正与揭盲交错：先更正第1次（诊断），再揭第2次
    c=client.post(f'/sequential/plans/{pid}/looks/1/correct',headers=analyst,
                  json={'reach_a':1000,'click_a':105,'reach_b':1000,'click_b':110,'note':'上游修订'})
    assert c.status_code==200 and len(c.json()['corrections'])==1
    assert c.json()['alpha_spent_value']==0.02  # 额度不退

    # 7) 第二次揭盲，构造显著：10% vs 15%，n=2000，alpha_k=.03
    r=client.post(f'/sequential/plans/{pid}/looks/2/unblind',headers=admin,
                  json={'reach_a':2000,'click_a':200,'reach_b':2000,'click_b':300})
    final=r.json()
    assert final['status']=='stopped' and final['stop_reason']=='significant'
    assert final['alpha_spent_value']==0.05

    # 8) 停试竞争：任何后续揭盲（迟归）一律拒绝，研究不重开
    late=client.post(f'/sequential/plans/{pid}/looks/3/unblind',headers=analyst,
                     json={'reach_a':3000,'click_a':300,'reach_b':3000,'click_b':450})
    assert late.status_code==409 and '不得重开' in late.json()['detail']

    # 9) 迟归数据只能更正诊断，原结论保留
    c2=client.post(f'/sequential/plans/{pid}/looks/2/correct',headers=analyst,
                   json={'reach_a':2000,'click_a':260,'reach_b':2000,'click_b':265,'note':'迟归补录'})
    d2=c2.json()
    assert d2['status']=='stopped' and d2['stop_reason']=='significant'
    assert d2['unblindings'][1]['data_version']['click_b']==300  # 原版不动
    assert d2['corrections'][1]['diagnostic']['rate_a']==0.13

    # 10) 观察员只读可见全部依据；写操作被拒
    view=client.get(f'/sequential/plans/{pid}',headers=viewer).json()
    assert len(view['looks'])==2 and len(view['unblindings'])==2 and len(view['corrections'])==2
    assert view['stop_note']
    forbidden=client.post(f'/sequential/plans/{pid}/looks/1/correct',headers=viewer,
                          json={'reach_a':1000,'click_a':1,'reach_b':1000,'click_b':2})
    assert forbidden.status_code==403

    # 11) 列表页与审计留痕
    listed=client.get('/sequential/plans',headers=viewer).json()
    assert listed[0]['unblinded_count']==2
    audits=client.get('/audits',headers=admin).json()
    actions={a['action'] for a in audits}
    assert {'seq.plan.lock','seq.unblind','seq.correct'} <= actions
