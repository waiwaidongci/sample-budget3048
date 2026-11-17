from sqlalchemy import Column,Integer,String,JSON,Text,ForeignKey,UniqueConstraint
from src.config.database import Base

class SequentialPlan(Base):
    """预注册分阶段检验方案：开始前锁定各次查看的双组累计触达门槛与显著性额度。"""
    __tablename__='sequential_plans'
    id=Column(Integer,primary_key=True)
    study_id=Column(Integer,ForeignKey('studies.id'),nullable=False)
    name=Column(String(120),unique=True,nullable=False)
    status=Column(String(20),default='active',nullable=False)
    # 研究总显著性上限，预注册后不可修改
    alpha_total=Column(Integer,nullable=False)
    # 已消耗额度（整数百万分位），与揭盲结论在同一事务内扣减
    alpha_spent=Column(Integer,default=0,nullable=False)
    # 锁定内容：[{"stage":1,"reach_a":..,"reach_b":..,"alpha_k":0.02,...}]
    looks=Column(JSON,nullable=False)
    stop_reason=Column(String(30),default='',nullable=False)
    stop_stage=Column(Integer,default=0,nullable=False)
    stop_note=Column(Text,default='',nullable=False)
    created_by=Column(String(120),nullable=False)
    created_at=Column(String(40),nullable=False)

class SequentialUnblinding(Base):
    """每次揭盲采用的数据版本与检验结论；同次查看唯一，重试不重复扣额。"""
    __tablename__='sequential_unblindings'
    __table_args__=(UniqueConstraint('plan_id','stage'),)
    id=Column(Integer,primary_key=True)
    plan_id=Column(Integer,ForeignKey('sequential_plans.id'),nullable=False)
    stage=Column(Integer,nullable=False)
    # 当次采用的同版数据（累计口径）
    data_version=Column(JSON,nullable=False)
    data_checksum=Column(String(64),nullable=False)
    alpha_used=Column(Integer,nullable=False)
    result=Column(JSON,nullable=False)
    significant=Column(Integer,default=0,nullable=False)
    author=Column(String(120),nullable=False)
    created_at=Column(String(40),nullable=False)

class SequentialCorrection(Base):
    """数据更正重算仅作诊断：原揭盲结论与已扣额度保留不退。"""
    __tablename__='sequential_corrections'
    id=Column(Integer,primary_key=True)
    plan_id=Column(Integer,ForeignKey('sequential_plans.id'),nullable=False)
    stage=Column(Integer,nullable=False)
    corrected_version=Column(JSON,nullable=False)
    data_checksum=Column(String(64),nullable=False)
    diagnostic=Column(JSON,nullable=False)
    note=Column(Text,default='',nullable=False)
    author=Column(String(120),nullable=False)
    created_at=Column(String(40),nullable=False)
