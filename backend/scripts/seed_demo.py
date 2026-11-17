import json
import numpy as np
from sqlalchemy import select,func
from src.config.database import Base,engine,Session
from src.config.domain import DOMAIN
from src.models.user import User
from src.models.study import Study
from src.models.observation import Observation
from src.models.sequential import SequentialPlan
from src.models import run,review,audit
from src.services.sequential_plans import alpha_to_units
from src.utils.security import hash_password
from src.utils.serializers import now as now_iso

def seed():
    Base.metadata.create_all(engine)
    rng=np.random.default_rng(42)
    i=DOMAIN['index']
    with Session() as db:
        for role in ('admin','analyst','viewer'):
            email=role+'@demo.local'
            if not db.scalar(select(User).where(User.email==email)): db.add(User(email=email,role=role,password_hash=hash_password('Research2026!')))
        for k,name in enumerate(DOMAIN['names']):
            study=db.scalar(select(Study).where(Study.name==name))
            if not study:
                study=Study(name=name,source_filename=DOMAIN['slug']+f'-202611-{k+1}.csv',description='独立合成业务观测 / 固定种子42 / 仅用于方法与流程演示');db.add(study);db.flush()
            rows=[]
            if i==0:
                for n in range(120): rows.append({'moisture':round(float(np.clip(rng.normal(5.2+k*.7,.7),0,100)),3),'extract':round(float(np.clip(rng.normal(34+k*2,2.4),0,100)),3)})
            elif i==1:
                rows=[{'group':'A','success':87+k*2,'failure':13-k*2},{'group':'B','success':96-k,'failure':4+k}]
            elif i==2:
                for n in range(24):
                    b=float(rng.uniform(3,6));rows.append({'before':round(b,3),'after':round(max(.1,b+rng.normal(-.45+k*.3,.5)),3)})
            elif i==3:
                for n in range(90):
                    x=round(float(rng.uniform(4,28)),1);rows.append({'porosity':x,'absorption':round(max(0,x*(.18+k*.08)+rng.normal(0,1.5)),2)})
            else: rows=[{'p0':.08+k*.02,'p1':.1+k*.025,'cost_per_contact':.12+k*.04,'budget':3000+k*500}]
            for n,values in enumerate(rows):
                key=f'DEMO-{k+1}-{n+1:04}'
                if not db.scalar(select(Observation.id).where(Observation.study_id==study.id,Observation.source_key==key)):
                    db.add(Observation(study_id=study.id,source_key=key,values=values))
            # 预注册分阶段方案（仅锁定门槛与额度，不预填任何揭盲/点击结果）
            plan_name=name+' · 分阶段预注册'
            if not db.scalar(select(SequentialPlan).where(SequentialPlan.name==plan_name)):
                spec=[
                    {'stage':1,'reach_a':4000,'reach_b':4000,'alpha_k':0.010,'alpha_units':alpha_to_units(0.010)},
                    {'stage':2,'reach_a':8000,'reach_b':8000,'alpha_k':0.015,'alpha_units':alpha_to_units(0.015)},
                    {'stage':3,'reach_a':12000,'reach_b':12000,'alpha_k':0.025,'alpha_units':alpha_to_units(0.025)},
                ]
                db.add(SequentialPlan(study_id=study.id,name=plan_name,status='active',
                    alpha_total=alpha_to_units(0.05),alpha_spent=0,looks=spec,
                    stop_reason='',stop_stage=0,stop_note='',
                    created_by='admin@demo.local',created_at=now_iso()))
        db.commit()
        counts={model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in (User,Study,Observation,SequentialPlan)}
        print(json.dumps(counts));return counts
if __name__=='__main__': seed()
