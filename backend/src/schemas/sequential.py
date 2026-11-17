from pydantic import BaseModel,Field

class LookSpec(BaseModel):
    stage:int=Field(ge=1,le=20)
    reach_a:int=Field(gt=0,le=10_000_000)
    reach_b:int=Field(gt=0,le=10_000_000)
    alpha_k:float=Field(gt=0,lt=1)

class SequentialPlanInput(BaseModel):
    study_id:int=Field(gt=0)
    name:str=Field(min_length=2,max_length=120)
    alpha_total:float=Field(gt=0,le=1)
    looks:list[LookSpec]=Field(min_length=1,max_length=20)

class UnblindingInput(BaseModel):
    reach_a:int=Field(ge=0,le=10_000_000)
    click_a:int=Field(ge=0,le=10_000_000)
    reach_b:int=Field(ge=0,le=10_000_000)
    click_b:int=Field(ge=0,le=10_000_000)

class CorrectionInput(UnblindingInput):
    note:str=Field(default='',max_length=2000)
