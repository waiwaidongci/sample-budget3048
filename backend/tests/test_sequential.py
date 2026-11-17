import os
import threading
import pytest

# 本地验证使用 SQLite，不依赖 Postgres/Redis；须在导入应用模块前就绪。
os.environ.setdefault('DATABASE_URL', 'sqlite+pysqlite:////tmp/seq_service_test_2.db')
os.environ.setdefault('REDIS_URL', 'redis://localhost:6379/0')
os.environ.setdefault('JWT_SECRET', 'test-secret')

from sqlalchemy import create_engine,select
from sqlalchemy.orm import sessionmaker
from src.config.database import Base
from src.models import user,study,observation,run,review,audit,sequential  # noqa: F401
from src.models.study import Study
from src.models.sequential import SequentialPlan,SequentialUnblinding,SequentialCorrection
from src.schemas.sequential import SequentialPlanInput,LookSpec,UnblindingInput,CorrectionInput
from src.services import sequential as seq
from src.services.sequential_plans import validate_plan_spec,alpha_to_units,units_to_alpha
from src.services.sequential_stats import two_proportion_z_test
from src.utils.serializers import checksum

engine=create_engine('sqlite+pysqlite:////tmp/seq_service_test_2.db',
                     connect_args={'check_same_thread':False})
Session=sessionmaker(bind=engine,expire_on_commit=False)

class U:
    def __init__(self,email): self.email=email;self.role='admin'
ADMIN=U('admin@demo.local')

@pytest.fixture()
def db():
    Base.metadata.create_all(engine)
    s=Session()
    s.add(Study(name='S-'+threading.current_thread().name,source_filename='demo.csv',description=''))
    s.commit()
    yield s
    s.close()
    Base.metadata.drop_all(engine)

def make_plan(db,alpha_total=0.05,looks=None,study_id=1,name='方案A'):
    looks=looks or [
        LookSpec(stage=1,reach_a=1000,reach_b=1000,alpha_k=0.01),
        LookSpec(stage=2,reach_a=2000,reach_b=2000,alpha_k=0.02),
        LookSpec(stage=3,reach_a=3000,reach_b=3000,alpha_k=0.02),
    ]
    data=SequentialPlanInput(study_id=study_id,name=name,alpha_total=alpha_total,looks=looks)
    return seq.create_plan(db,data,ADMIN)

# ---------- 预注册锁定校验 ----------

def test_alpha_cap_enforced_in_integer_units():
    with pytest.raises(ValueError):
        validate_plan_spec(0.05,[
            {'stage':1,'reach_a':10,'reach_b':10,'alpha_k':0.03},
            {'stage':2,'reach_a':20,'reach_b':20,'alpha_k':0.025}])
    # 合计恰好等于上限可以通过
    _,total,locked=validate_plan_spec(0.05,[
        {'stage':1,'reach_a':10,'reach_b':10,'alpha_k':0.02},
        {'stage':2,'reach_a':20,'reach_b':20,'alpha_k':0.03}])
    assert total==alpha_to_units(0.05)
    assert sum(l['alpha_units'] for l in locked)==total

def test_stages_must_be_continuous():
    with pytest.raises(ValueError,match='连续'):
        validate_plan_spec(0.05,[{'stage':1,'reach_a':10,'reach_b':10,'alpha_k':0.02},
                                 {'stage':3,'reach_a':20,'reach_b':20,'alpha_k':0.01}])

def test_thresholds_must_be_monotone():
    with pytest.raises(ValueError,match='不得低于前次'):
        validate_plan_spec(0.05,[{'stage':1,'reach_a':100,'reach_b':100,'alpha_k':0.02},
                                 {'stage':2,'reach_a':90,'reach_b':100,'alpha_k':0.01}])

def test_plan_is_locked_and_listed(db):
    p=make_plan(db)
    assert p['status']=='active'
    assert p['alpha_total_value']==0.05
    assert p['alpha_remaining_value']==0.05
    assert [l['stage'] for l in p['looks']]==[1,2,3]
    assert len(seq.list_plans(db))==1

def test_duplicate_plan_name_rejected(db):
    make_plan(db)
    with pytest.raises(Exception):
        make_plan(db)

# ---------- 揭盲门槛与依次揭盲 ----------

def test_below_threshold_rejected(db):
    make_plan(db)
    with pytest.raises(Exception,match='未达'):
        seq.unblind(db,1,1,UnblindingInput(reach_a=999,click_a=10,reach_b=999,click_b=10),ADMIN)
    # 被拒绝时不扣额、不留记录
    plan=db.get(SequentialPlan,1)
    assert plan.alpha_spent==0
    assert db.scalar(select(SequentialUnblinding)) is None

def test_skip_stage_rejected(db):
    make_plan(db)
    with pytest.raises(Exception,match='依次揭盲'):
        seq.unblind(db,1,2,UnblindingInput(reach_a=2000,click_a=10,reach_b=2000,click_b=10),ADMIN)

def test_unblind_deducts_alpha_and_records_version(db):
    p=make_plan(db)
    out=seq.unblind(db,1,1,UnblindingInput(reach_a=1000,click_a=100,reach_b=1000,click_b=120),ADMIN)
    assert out['alpha_spent_value']==0.01
    assert out['alpha_remaining_value']==0.04
    assert out['unblindings'][0]['data_version']=={
        'reach_a':1000,'click_a':100,'reach_b':1000,'click_b':120}
    assert out['unblindings'][0]['data_checksum']==checksum(
        {'reach_a':1000,'click_a':100,'reach_b':1000,'click_b':120})
    assert out['unblindings'][0]['result']['alpha_k']==0.01
    assert out['next_stage']==2

def test_two_sided_test_math():
    r=two_proportion_z_test(1000,100,1000,130,0.01)
    # p1=.10 p2=.13, pooled=.115
    assert abs(r['pooled_rate']-0.115)<1e-12
    assert r['z']>0
    assert abs(r['p_value']-2*(1-__import__('scipy').stats.norm.cdf(abs(r['z']))))<1e-12
    assert r['significant']==(r['p_value']<0.01)

def test_zero_variance_does_not_crash():
    r=two_proportion_z_test(100,0,100,0,0.05)
    assert r['p_value']==1.0 and r['significant'] is False
    r2=two_proportion_z_test(100,100,100,100,0.05)
    assert r2['significant'] is False

def test_clicks_cannot_exceed_reach():
    with pytest.raises(ValueError):
        two_proportion_z_test(10,11,10,1,0.05)

# ---------- 幂等：并发揭盲与重试不重复扣额 ----------

def test_retry_same_version_is_idempotent(db):
    make_plan(db)
    payload=UnblindingInput(reach_a=1000,click_a=100,reach_b=1000,click_b=105)
    seq.unblind(db,1,1,payload,ADMIN)
    again=seq.unblind(db,1,1,payload,ADMIN)
    assert len(again['unblindings'])==1
    assert again['alpha_spent_value']==0.01
    assert db.query(SequentialUnblinding).count()==1

def test_retry_different_version_rejected(db):
    make_plan(db)
    seq.unblind(db,1,1,UnblindingInput(reach_a=1000,click_a=100,reach_b=1000,click_b=105),ADMIN)
    with pytest.raises(Exception,match='同版数据'):
        seq.unblind(db,1,1,UnblindingInput(reach_a=1000,click_a=100,reach_b=1000,click_b=106),ADMIN)
    assert db.get(SequentialPlan,1).alpha_spent==alpha_to_units(0.01)

def test_concurrent_unblind_deducts_once(tmp_path):
    # 独立文件型 SQLite，多线程真实竞争；唯一约束 + 行锁保证只扣一次。
    url='sqlite+pysqlite:///'+str(tmp_path/'conc.db')
    eng=create_engine(url,connect_args={'check_same_thread':False,'timeout':30})
    S=sessionmaker(bind=eng,expire_on_commit=False)
    Base.metadata.create_all(eng)
    with S() as s:
        s.add(Study(name='并发方案研究',source_filename='c.csv'));s.commit()
        seq.create_plan(s,SequentialPlanInput(study_id=1,name='并发方案',alpha_total=0.05,
            looks=[LookSpec(stage=1,reach_a=500,reach_b=500,alpha_k=0.02),
                   LookSpec(stage=2,reach_a=900,reach_b=900,alpha_k=0.03)]),ADMIN)
    errors=[]
    def worker():
        try:
            with S() as s:
                seq.unblind(s,1,1,UnblindingInput(reach_a=500,click_a=40,reach_b=500,click_b=55),
                            U('analyst@demo.local'))
        except Exception as e:
            errors.append(str(e))
    threads=[threading.Thread(target=worker) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    with S() as s:
        plan=s.get(SequentialPlan,1)
        assert s.query(SequentialUnblinding).count()==1
        assert plan.alpha_spent==alpha_to_units(0.02)
        # 其余并发请求要么幂等返回要么唯一约束冲突，额度绝不重复扣
    assert len(errors)<=7

# ---------- 停试竞争：显著即停 / 次数耗尽即停 ----------

def test_significance_stops_immediately(db):
    make_plan(db)
    # 构造显著差异：10% vs 15.5%，n=1000，alpha_k=.01
    out=seq.unblind(db,1,1,UnblindingInput(reach_a=1000,click_a=100,reach_b=1000,click_b=155),ADMIN)
    assert out['status']=='stopped'
    assert out['stop_reason']=='significant'
    assert out['stop_stage']==1
    assert out['unblindings'][0]['result']['significant'] is True
    # 停试后迟归结果不得重开
    with pytest.raises(Exception,match='不得重开'):
        seq.unblind(db,1,2,UnblindingInput(reach_a=2000,click_a=200,reach_b=2000,click_b=300),ADMIN)

def test_looks_exhausted_stops_without_significance(db):
    make_plan(db)
    seq.unblind(db,1,1,UnblindingInput(reach_a=1000,click_a=100,reach_b=1000,click_b=101),ADMIN)
    seq.unblind(db,1,2,UnblindingInput(reach_a=2000,click_a=200,reach_b=2000,click_b=203),ADMIN)
    out=seq.unblind(db,1,3,UnblindingInput(reach_a=3000,click_a=300,reach_b=3000,click_b=305),ADMIN)
    assert out['status']=='stopped'
    assert out['stop_reason']=='looks_exhausted'
    assert out['alpha_spent_value']==0.05
    assert out['alpha_remaining_value']==0.0

def test_concurrent_final_look_only_one_wins(tmp_path):
    url='sqlite+pysqlite:///'+str(tmp_path/'stop.db')
    eng=create_engine(url,connect_args={'check_same_thread':False,'timeout':30})
    S=sessionmaker(bind=eng,expire_on_commit=False)
    Base.metadata.create_all(eng)
    with S() as s:
        s.add(Study(name='停试研究',source_filename='s.csv'));s.commit()
        seq.create_plan(s,SequentialPlanInput(study_id=1,name='停试方案',alpha_total=0.05,
            looks=[LookSpec(stage=1,reach_a=500,reach_b=500,alpha_k=0.05)]),ADMIN)
    errors=[]
    def worker(i):
        try:
            with S() as s:
                seq.unblind(s,1,1,UnblindingInput(reach_a=500,click_a=50+i,reach_b=500,click_b=52),
                            U(f'a{i}@demo.local'))
        except Exception as e:
            errors.append(str(e))
    threads=[threading.Thread(target=worker,args=(i,)) for i in range(6)]
    for t in threads: t.start()
    for t in threads: t.join()
    with S() as s:
        plan=s.get(SequentialPlan,1)
        assert plan.status=='stopped'
        assert s.query(SequentialUnblinding).count()==1
        assert plan.alpha_spent==alpha_to_units(0.05)

# ---------- 数据更正：重算诊断，额度不退、原结论保留 ----------

def test_correction_keeps_original_and_spend(db):
    make_plan(db)
    seq.unblind(db,1,1,UnblindingInput(reach_a=1000,click_a=100,reach_b=1000,click_b=155),ADMIN)
    before=db.get(SequentialPlan,1)
    spent_before=before.alpha_spent
    original=db.scalar(select(SequentialUnblinding))
    orig_hash=original.data_checksum;orig_result=dict(original.result)
    out=seq.correct(db,1,1,CorrectionInput(reach_a=1000,click_a=110,reach_b=1000,click_b=120,
                                            note='上游修订点击口径'),ADMIN)
    after=db.get(SequentialPlan,1)
    # 额度不退、状态不变、原结论保留
    assert after.alpha_spent==spent_before
    assert after.status=='stopped'
    kept=db.scalar(select(SequentialUnblinding))
    assert kept.data_checksum==orig_hash
    assert kept.result==orig_result
    # 诊断单独存档
    assert db.query(SequentialCorrection).count()==1
    corr=out['corrections'][0]
    assert corr['data_checksum']!=orig_hash
    assert corr['diagnostic']['rate_a']==0.11
    assert 'significant' in corr['diagnostic']

def test_correction_before_unblind_rejected(db):
    make_plan(db)
    with pytest.raises(Exception,match='尚未揭盲'):
        seq.correct(db,1,1,CorrectionInput(reach_a=1000,click_a=1,reach_b=1000,click_b=2),ADMIN)

def test_identical_correction_rejected(db):
    make_plan(db)
    payload=CorrectionInput(reach_a=1000,click_a=100,reach_b=1000,click_b=120)
    seq.unblind(db,1,1,payload,ADMIN)
    with pytest.raises(Exception,match='无需重算'):
        seq.correct(db,1,1,payload,ADMIN)

def test_correction_does_not_reopen_stopped_study(db):
    make_plan(db)
    seq.unblind(db,1,1,UnblindingInput(reach_a=1000,click_a=100,reach_b=1000,click_b=155),ADMIN)
    seq.correct(db,1,1,CorrectionInput(reach_a=1000,click_a=100,reach_b=1000,click_b=100,note='改回无差异'),ADMIN)
    assert db.get(SequentialPlan,1).status=='stopped'
    with pytest.raises(Exception,match='不得重开'):
        seq.unblind(db,1,2,UnblindingInput(reach_a=2000,click_a=200,reach_b=2000,click_b=201),ADMIN)

# ---------- 更正与揭盲交错 ----------

def test_interleaved_correction_and_unblind(db):
    p=make_plan(db)
    seq.unblind(db,1,1,UnblindingInput(reach_a=1000,click_a=100,reach_b=1000,click_b=110),ADMIN)
    seq.correct(db,1,1,CorrectionInput(reach_a=1000,click_a=105,reach_b=1000,click_b=108,note='修订1'),ADMIN)
    # 更正不阻断后续揭盲，门槛按预注册累计值判定
    out=seq.unblind(db,1,2,UnblindingInput(reach_a=2000,click_a=210,reach_b=2000,click_b=225),ADMIN)
    assert out['next_stage']==3
    assert out['alpha_spent_value']==0.03
    seq.correct(db,1,2,CorrectionInput(reach_a=2000,click_a=215,reach_b=2000,click_b=220,note='修订2'),ADMIN)
    out=seq.unblind(db,1,3,UnblindingInput(reach_a=3000,click_a=310,reach_b=3000,click_b=320),ADMIN)
    assert db.query(SequentialCorrection).count()==2
    assert out['status']=='stopped'
    assert out['stop_reason']=='looks_exhausted'
    # 诊断中的显著不改变停试依据
    assert out['stop_stage']==3

def test_late_data_after_stop_only_diagnostic(db):
    make_plan(db)
    seq.unblind(db,1,1,UnblindingInput(reach_a=1000,click_a=100,reach_b=1000,click_b=155),ADMIN)
    # 迟归的第二版数据只能做诊断更正
    out=seq.correct(db,1,1,CorrectionInput(reach_a=1200,click_a=130,reach_b=1200,click_b=140,note='迟归补录'),ADMIN)
    assert len(out['unblindings'])==1
    assert out['status']=='stopped'
