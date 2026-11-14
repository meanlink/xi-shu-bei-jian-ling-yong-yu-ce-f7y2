from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import Dataset, Quarantine
from src.schemas.quarantine import QuarantineInput, ReplacementInput
from src.middlewares.auth import current_user, admin_only
from src.services import quarantine
from src.services.audit import record
router=APIRouter(prefix='/quarantines')
@router.get('')
def listing(db=Depends(get_db),u=Depends(current_user)):
    return [quarantine.summary(db,q) for q in db.scalars(select(Quarantine).order_by(Quarantine.id.desc()))]
@router.get('/{id}')
def detail(id:int,db=Depends(get_db),u=Depends(current_user)):
    q=db.get(Quarantine,id)
    if not q:raise HTTPException(404,'隔离处置不存在')
    return quarantine.summary(db,q)
@router.post('',status_code=201)
def create(data:QuarantineInput,db=Depends(get_db),u=Depends(admin_only)):
    d=db.get(Dataset,data.dataset_id)
    if not d:raise HTTPException(404,'数据批次不存在')
    q,created=quarantine.create(db,d,data.reason,u.email)
    if created:
        affected=quarantine.summary(db,q)['affected']
        record(db,u.email,'dataset.quarantine',{'dataset':d.id,'quarantine':q.id,'reason':q.reason,'jobs':len(affected['jobs']),'reports':len(affected['reports']),'deliveries':len(affected['deliveries'])})
    # A repeated request (retry after a lost reply) reuses the committed record
    # and does not write another dataset.quarantine audit entry.
    db.commit()
    return quarantine.summary(db,q)
@router.post('/{id}/replacement')
def link_replacement(id:int,data:ReplacementInput,db=Depends(get_db),u=Depends(admin_only)):
    q=db.get(Quarantine,id)
    if not q:raise HTTPException(404,'隔离处置不存在')
    d=db.get(Dataset,data.dataset_id)
    if not d:raise HTTPException(404,'修正批次不存在')
    if quarantine.set_replacement(db,q,d):
        record(db,u.email,'quarantine.replacement',{'quarantine':q.id,'dataset':d.id})
        db.commit()
    return quarantine.summary(db,q)
