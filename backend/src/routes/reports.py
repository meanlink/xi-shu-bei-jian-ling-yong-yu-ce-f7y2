import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from src.config.database import get_db
from src.config.settings import ARTIFACT_DIR
from src.models import Report, Delivery
from src.schemas.report import ReportInput
from src.middlewares.auth import current_user, admin_only
from src.services import reports, quarantine
from src.services.audit import record
from src.utils.serialization import report_dict, delivery_dict
router=APIRouter()
@router.get('/reports')
def listing(db=Depends(get_db),u=Depends(current_user)):
    return [report_dict(r) for r in db.scalars(select(Report).order_by(Report.id.desc()))]
@router.post('/reports',status_code=201)
def create(data:ReportInput,db=Depends(get_db),u=Depends(admin_only)):
    r=reports.create(db,data); record(db,u.email,'report.schedule',{'id':r.id,'destination':r.destination}); db.commit()
    return report_dict(r)
@router.post('/reports/{id}/toggle')
def toggle(id:int,db=Depends(get_db),u=Depends(admin_only)):
    r=db.get(Report,id)
    if not r:raise HTTPException(404,'分发计划不存在')
    dataset_id=reports.dataset_id_for_report(db,r)
    if dataset_id is not None:quarantine.lock_dataset(db,dataset_id)
    if r:db.refresh(r)
    if r.quarantined or reports.is_blocked(db,r):
        raise HTTPException(409,'该分发计划关联的数据批次已隔离处置，不能重新启用')
    r.enabled=not r.enabled;record(db,u.email,'report.toggle',{'id':id,'enabled':r.enabled});db.commit()
    return report_dict(r)
@router.get('/deliveries')
def deliveries(db=Depends(get_db),u=Depends(current_user)):
    return [delivery_dict(d) for d in db.scalars(select(Delivery).order_by(Delivery.id.desc()).limit(100))]
@router.get('/deliveries/{id}/download')
def download(id:int,format:str='csv',db=Depends(get_db),u=Depends(current_user)):
    d=db.get(Delivery,id)
    if not d:raise HTTPException(404,'归档不存在')
    if format not in ('csv','json'):raise HTTPException(422,'支持 CSV 或 JSON')
    # Same dataset lock as the quarantine sweep: a download already admitted
    # before the boundary may complete; one arriving after it is refused.
    r=db.get(Report,d.report_id)
    dataset_id=reports.dataset_id_for_report(db,r)
    if dataset_id is not None:quarantine.lock_dataset(db,dataset_id)
    db.refresh(d)
    if r:db.refresh(r)
    if d.quarantined or reports.is_blocked(db,r):
        db.rollback()
        raise HTTPException(409,'该归档所属数据批次已隔离处置，归档保留追查但停止下载')
    # Release the boundary lock before streaming the file: this download was
    # admitted inside the boundary, so it may complete.
    db.commit()
    filename=d.filename+('.json' if format=='json' else '')
    p=os.path.join(ARTIFACT_DIR,filename)
    if not os.path.exists(p):raise HTTPException(404,'归档文件不存在，请重新安排分发')
    return FileResponse(p,filename=filename,media_type='application/json' if format=='json' else 'text/csv; charset=utf-8')
