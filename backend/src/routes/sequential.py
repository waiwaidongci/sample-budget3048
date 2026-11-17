from fastapi import APIRouter,Depends
from src.config.database import get_db
from src.middlewares.auth import current_user,writer
from src.schemas.sequential import SequentialPlanInput,UnblindingInput,CorrectionInput
from src.controllers import sequential as ctrl
router=APIRouter()

@router.get('/sequential/plans')
def list_plans(db=Depends(get_db),user=Depends(current_user)):
    return ctrl.list_plans(db)

@router.post('/sequential/plans')
def create_plan(data:SequentialPlanInput,db=Depends(get_db),user=Depends(writer)):
    return ctrl.create_plan(db,data,user)

@router.get('/sequential/plans/{plan_id}')
def plan_detail(plan_id:int,db=Depends(get_db),user=Depends(current_user)):
    return ctrl.plan_detail(db,plan_id)

@router.post('/sequential/plans/{plan_id}/looks/{stage}/unblind')
def unblind(plan_id:int,stage:int,data:UnblindingInput,db=Depends(get_db),user=Depends(writer)):
    return ctrl.unblind(db,plan_id,stage,data,user)

@router.post('/sequential/plans/{plan_id}/looks/{stage}/correct')
def correct(plan_id:int,stage:int,data:CorrectionInput,db=Depends(get_db),user=Depends(writer)):
    return ctrl.correct(db,plan_id,stage,data,user)
