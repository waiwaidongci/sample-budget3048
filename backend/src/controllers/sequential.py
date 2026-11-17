from src.services import sequential as seq

def list_plans(db): return seq.list_plans(db)
def create_plan(db,data,user): return seq.create_plan(db,data,user)
def plan_detail(db,plan_id): return seq.detail(db,plan_id)
def unblind(db,plan_id,stage,data,user): return seq.unblind(db,plan_id,stage,data,user)
def correct(db,plan_id,stage,data,user): return seq.correct(db,plan_id,stage,data,user)
