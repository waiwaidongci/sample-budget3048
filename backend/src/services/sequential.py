from fastapi import HTTPException
from sqlalchemy import select,func
from sqlalchemy.exc import IntegrityError
from src.models.sequential import SequentialPlan,SequentialUnblinding,SequentialCorrection
from src.services import studies
from src.services.sequential_plans import validate_plan_spec,units_to_alpha
from src.services.sequential_stats import two_proportion_z_test,validate_stage_counts
from src.services.audits import log
from src.utils.serializers import record,now,checksum

# 揭盲在单事务内完成：行级锁串行化同方案并发 -> 幂等检查 -> 门槛/停试校验
# -> 同版数据检验 -> 扣额与结论同时提交。并发请求不会重复扣额。

def _plan_or_404(db,plan_id):
    plan=db.get(SequentialPlan,plan_id)
    if not plan: raise HTTPException(404,'分阶段检验方案不存在')
    return plan

def create_plan(db,data,user):
    studies.require(db,data.study_id)
    if db.scalar(select(SequentialPlan).where(SequentialPlan.name==data.name)):
        raise HTTPException(409,'方案名称已存在')
    raw=[l.model_dump() for l in data.looks]
    try:
        alpha_total,total_units,locked=validate_plan_spec(data.alpha_total,raw)
    except (ValueError,TypeError) as e:
        raise HTTPException(422,str(e))
    plan=SequentialPlan(
        study_id=data.study_id,name=data.name,status='active',
        alpha_total=total_units,alpha_spent=0,looks=locked,
        stop_reason='',stop_stage=0,stop_note='',
        created_by=user.email,created_at=now(),
    )
    db.add(plan);db.flush()
    log(db,user,'seq.plan.lock',f'{plan.id}: {len(locked)}次查看, 总额度{alpha_total:g}')
    db.commit()
    return detail(db,plan.id)

def list_plans(db):
    rows=[]
    for p in db.scalars(select(SequentialPlan).order_by(SequentialPlan.id)):
        x=record(p)
        x['unblinded_count']=db.scalar(select(func.count()).select_from(SequentialUnblinding)
                                       .where(SequentialUnblinding.plan_id==p.id))
        rows.append(_decorate(p,x))
    return rows

def _decorate(plan,x):
    x['alpha_total_value']=units_to_alpha(plan.alpha_total)
    x['alpha_spent_value']=units_to_alpha(plan.alpha_spent)
    x['alpha_remaining_value']=units_to_alpha(max(0,plan.alpha_total-plan.alpha_spent))
    return x

def detail(db,plan_id):
    plan=_plan_or_404(db,plan_id)
    x=record(plan);x=_decorate(plan,x)
    unblindings=[record(u) for u in db.scalars(
        select(SequentialUnblinding).where(SequentialUnblinding.plan_id==plan_id)
        .order_by(SequentialUnblinding.stage))]
    corrections=[record(c) for c in db.scalars(
        select(SequentialCorrection).where(SequentialCorrection.plan_id==plan_id)
        .order_by(SequentialCorrection.id))]
    spent_by_stage={u['stage']:u['alpha_used'] for u in unblindings}
    for look in x['looks']:
        look['alpha_k_value']=units_to_alpha(look['alpha_units'])
        look['spent']=look['alpha_units'] if look['stage'] in spent_by_stage else 0
        look['unblinded']=look['stage'] in spent_by_stage
    x['unblindings']=unblindings
    x['corrections']=corrections
    x['next_stage']=len(unblindings)+1 if plan.status=='active' else None
    x['study']=record(studies.require(db,plan.study_id))
    return x

def unblind(db,plan_id,stage,data,user):
    try:
        reach_a,click_a,reach_b,click_b=validate_stage_counts(
            data.reach_a,data.click_a,data.reach_b,data.click_b)
    except (ValueError,TypeError) as e:
        raise HTTPException(422,str(e))
    payload={'reach_a':reach_a,'click_a':click_a,'reach_b':reach_b,'click_b':click_b}
    version_hash=checksum(payload)

    # 行级锁：PostgreSQL 下 SELECT ... FOR UPDATE 串行化同方案的并发揭盲。
    locked=db.execute(select(SequentialPlan).where(SequentialPlan.id==plan_id)
                      .with_for_update()).scalar_one_or_none()
    if not locked: raise HTTPException(404,'分阶段检验方案不存在')
    plan=locked

    existing=db.scalar(select(SequentialUnblinding)
                       .where(SequentialUnblinding.plan_id==plan_id,
                              SequentialUnblinding.stage==stage))
    if existing:
        # 重试/并发揭盲幂等：同版数据返回原结论，不重复扣额；异版数据明确拒绝。
        if existing.data_checksum!=version_hash:
            raise HTTPException(409,f'第 {stage} 次查看已按锁定数据版本揭盲，'
                                   '同次检验只能采用同版数据；如需更正请走数据更正诊断')
        db.rollback()
        return detail(db,plan_id)

    if plan.status!='active':
        raise HTTPException(409,f'研究已停试（{plan.stop_reason}），迟归结果不得重开研究；'
                               '数据更正仅可重算诊断')
    done=db.scalar(select(func.count()).select_from(SequentialUnblinding)
                   .where(SequentialUnblinding.plan_id==plan_id))
    if stage!=done+1:
        raise HTTPException(409,f'下一次可揭盲的是第 {done+1} 次查看，必须依次揭盲，不得跳次')
    look=next((l for l in plan.looks if l['stage']==stage),None)
    if not look: raise HTTPException(409,'该查看未在预注册方案中锁定')
    if reach_a<look['reach_a'] or reach_b<look['reach_b']:
        raise HTTPException(409,
            f"未达第 {stage} 次查看门槛：要求双组累计触达均不少于 "
            f"A {look['reach_a']} / B {look['reach_b']}，当前 A {reach_a} / B {reach_b}")

    alpha_k=units_to_alpha(look['alpha_units'])
    stats_result=two_proportion_z_test(reach_a,click_a,reach_b,click_b,alpha_k)
    significant=1 if stats_result['significant'] else 0

    # 扣额与结论在同一事务一起生效。
    plan.alpha_spent=plan.alpha_spent+look['alpha_units']
    row=SequentialUnblinding(
        plan_id=plan_id,stage=stage,data_version=payload,data_checksum=version_hash,
        alpha_used=look['alpha_units'],result=stats_result,significant=significant,
        author=user.email,created_at=now(),
    )
    db.add(row);db.flush()

    final_stage=stage>=len(plan.looks)
    if significant:
        plan.status='stopped';plan.stop_reason='significant';plan.stop_stage=stage
        plan.stop_note=(f'第 {stage} 次查看双侧检验显著（p={stats_result["p_value"]:.6g} '
                        f'< 当次额度 {alpha_k:g}），按预注册立即停试')
    elif final_stage:
        plan.status='stopped';plan.stop_reason='looks_exhausted';plan.stop_stage=stage
        plan.stop_note='已用完全部预注册查看次数（显著性额度同步耗尽），未达显著，按方案停试'
    log(db,user,'seq.unblind',
        f'{plan_id}#{stage}: 额度{alpha_k:g} 显著={bool(significant)} 状态={plan.status}')
    try:
        db.commit()
    except IntegrityError:
        # 并发下唯一 (plan_id, stage) 约束兜底：回滚后按幂等重读，绝不重复扣额。
        db.rollback()
        return detail(db,plan_id)
    return detail(db,plan_id)

def correct(db,plan_id,stage,data,user):
    plan=_plan_or_404(db,plan_id)
    if not any(l['stage']==stage for l in plan.looks):
        raise HTTPException(404,'该查看未在预注册方案中锁定')
    original=db.scalar(select(SequentialUnblinding)
                       .where(SequentialUnblinding.plan_id==plan_id,
                              SequentialUnblinding.stage==stage))
    if not original:
        raise HTTPException(409,'该次查看尚未揭盲，无需更正；请先按门槛完成揭盲')
    try:
        reach_a,click_a,reach_b,click_b=validate_stage_counts(
            data.reach_a,data.click_a,data.reach_b,data.click_b)
    except (ValueError,TypeError) as e:
        raise HTTPException(422,str(e))
    payload={'reach_a':reach_a,'click_a':click_a,'reach_b':reach_b,'click_b':click_b}
    version_hash=checksum(payload)
    if version_hash==original.data_checksum:
        raise HTTPException(422,'更正数据与当次采用版本完全相同，无需重算')
    look=next(l for l in plan.looks if l['stage']==stage)
    # 诊断沿用当次锁定额度作临界参照，但结论不回写、额度不退。
    diagnostic=two_proportion_z_test(reach_a,click_a,reach_b,click_b,
                                     units_to_alpha(look['alpha_units']))
    row=SequentialCorrection(
        plan_id=plan_id,stage=stage,corrected_version=payload,data_checksum=version_hash,
        diagnostic=diagnostic,note=data.note or '',author=user.email,created_at=now(),
    )
    db.add(row)
    log(db,user,'seq.correct',
        f'{plan_id}#{stage}: 诊断显著={diagnostic["significant"]}，原结论与已扣额度保留')
    db.commit()
    return detail(db,plan_id)
