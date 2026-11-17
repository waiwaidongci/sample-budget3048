import os
import pytest
os.environ.setdefault('DATABASE_URL','sqlite+pysqlite:////tmp/seq_api_test_2.db')
os.environ.setdefault('REDIS_URL','redis://localhost:6379/0')
os.environ.setdefault('JWT_SECRET','test-secret')

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from src.config.database import Base,engine,Session
from src.models import user,study,observation,run,review,audit,sequential  # noqa: F401
from src.models.user import User
from src.models.study import Study
from src.models.audit import Audit
from src.models.sequential import SequentialPlan
from src.routes import auth,sequential as sequential_routes,research
from src.middlewares.errors import ErrorMiddleware
from src.utils.security import hash_password

# 测试装配不启用依赖 Redis 的限流中间件，其余与生产路由一致。
app=FastAPI()
app.add_middleware(ErrorMiddleware)
app.include_router(auth.router)
app.include_router(research.router)
app.include_router(sequential_routes.router)
client=TestClient(app)

@pytest.fixture()
def ctx():
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    with Session() as db:
        db.add_all([
            User(email='admin@demo.local',role='admin',password_hash=hash_password('pw')),
            User(email='analyst@demo.local',role='analyst',password_hash=hash_password('pw')),
            User(email='viewer@demo.local',role='viewer',password_hash=hash_password('pw')),
            Study(name='API研究',source_filename='api.csv',description=''),
        ]);db.commit()
    def login(email):
        r=client.post('/auth/login',json={'email':email,'password':'pw'})
        return {'Authorization':'Bearer '+r.json()['token']}
    yield {'admin':login('admin@demo.local'),
           'analyst':login('analyst@demo.local'),
           'viewer':login('viewer@demo.local')}

PLAN={'study_id':1,'name':'API分阶段方案','alpha_total':0.05,'looks':[
    {'stage':1,'reach_a':1000,'reach_b':1000,'alpha_k':0.02},
    {'stage':2,'reach_a':2000,'reach_b':2000,'alpha_k':0.03}]}

def test_auth_required(ctx):
    assert client.get('/sequential/plans').status_code==401

def test_viewer_cannot_create_plan(ctx):
    r=client.post('/sequential/plans',json=PLAN,headers=ctx['viewer'])
    assert r.status_code==403

def test_full_lifecycle_over_http(ctx):
    r=client.post('/sequential/plans',json=PLAN,headers=ctx['analyst'])
    assert r.status_code==200,r.text
    p=r.json()
    assert p['alpha_total_value']==0.05
    assert p['looks'][0]['alpha_k_value']==0.02

    # 门槛不足
    bad=client.post('/sequential/plans/1/looks/1/unblind',
                    json={'reach_a':900,'click_a':90,'reach_b':900,'click_b':90},headers=ctx['analyst'])
    assert bad.status_code==409 and '未达' in bad.json()['detail']

    # 正常揭盲（不显著）
    ok=client.post('/sequential/plans/1/looks/1/unblind',
                   json={'reach_a':1000,'click_a':100,'reach_b':1000,'click_b':105},headers=ctx['analyst'])
    assert ok.status_code==200
    body=ok.json()
    assert body['alpha_remaining_value']==0.03
    assert body['unblindings'][0]['result']['significant'] is False

    # 重试幂等：同版数据
    again=client.post('/sequential/plans/1/looks/1/unblind',
                      json={'reach_a':1000,'click_a':100,'reach_b':1000,'click_b':105},headers=ctx['admin'])
    assert again.status_code==200
    assert len(again.json()['unblindings'])==1

    # 第二次揭盲，显著 -> 停试
    stop=client.post('/sequential/plans/1/looks/2/unblind',
                     json={'reach_a':2000,'click_a':200,'reach_b':2000,'click_b':290},headers=ctx['admin'])
    assert stop.json()['status']=='stopped'
    assert stop.json()['stop_reason']=='significant'

    # 迟归揭盲被拒
    late=client.post('/sequential/plans/1/looks/3/unblind',
                     json={'reach_a':3000,'click_a':300,'reach_b':3000,'click_b':300},headers=ctx['analyst'])
    assert late.status_code==409

    # 更正诊断
    corr=client.post('/sequential/plans/1/looks/1/correct',
                     json={'reach_a':1000,'click_a':110,'reach_b':1000,'click_b':112,'note':'口径修订'},
                     headers=ctx['analyst'])
    assert corr.status_code==200
    assert len(corr.json()['corrections'])==1
    # 已扣额度不退
    assert corr.json()['alpha_spent_value']==0.05

    # 页面查询：列表与详情均可读，含停试依据
    listed=client.get('/sequential/plans',headers=ctx['viewer']).json()
    assert listed[0]['stop_reason']=='significant'
    detail=client.get('/sequential/plans/1',headers=ctx['viewer']).json()
    assert detail['stop_note']
    assert detail['unblindings'][0]['data_version']['click_b']==105

def test_plan_over_cap_rejected(ctx):
    bad=dict(PLAN,name='超额方案',looks=[
        {'stage':1,'reach_a':100,'reach_b':100,'alpha_k':0.03},
        {'stage':2,'reach_a':200,'reach_b':200,'alpha_k':0.025}])
    r=client.post('/sequential/plans',json=bad,headers=ctx['admin'])
    assert r.status_code==422 and '超过研究上限' in r.json()['detail']

def test_validation_rejects_bad_counts(ctx):
    client.post('/sequential/plans',json=PLAN,headers=ctx['admin'])
    r=client.post('/sequential/plans/1/looks/1/unblind',
                  json={'reach_a':1000,'click_a':2000,'reach_b':1000,'click_b':1},headers=ctx['admin'])
    assert r.status_code==422

def test_audit_trail_written(ctx):
    client.post('/sequential/plans',json=PLAN,headers=ctx['admin'])
    client.post('/sequential/plans/1/looks/1/unblind',
                json={'reach_a':1000,'click_a':100,'reach_b':1000,'click_b':155},headers=ctx['admin'])
    with Session() as db:
        actions=[a.action for a in db.scalars(select(Audit))]
    assert 'seq.plan.lock' in actions
    assert 'seq.unblind' in actions
