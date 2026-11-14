import time, os, csv, io, hashlib, json
from fastapi import HTTPException
from src.models import Dataset, Job, Report, Delivery
from src.config.settings import ARTIFACT_DIR
from src.services import quarantine


def dataset_id_for_report(db, report):
    if not report:return None
    job=db.get(Job, report.job_id)
    return job.dataset_id if job else None


def is_blocked(db, report):
    dataset_id=dataset_id_for_report(db, report)
    return bool(report and (report.quarantined or (dataset_id is not None and quarantine.is_blocked(db,dataset_id))))


def lock_dataset(db, dataset_id):
    quarantine.lock_dataset(db, dataset_id)


def create(db, data):
    j=db.get(Job,data.job_id)
    dataset_id=j.dataset_id if j else None
    if dataset_id is not None:lock_dataset(db,dataset_id)
    if j:db.refresh(j)
    if not j or j.status!='completed' or not j.approved:
        raise HTTPException(409,'请先选择已完成且获批准的分析结果')
    if j.quarantined or quarantine.is_blocked(db, j.dataset_id):
        raise HTTPException(409,'该数据批次已隔离处置，不能再为其安排分发计划')
    r=Report(name=data.name, job_id=j.id, destination=data.destination, interval_seconds=data.interval_seconds, next_run=time.time()+data.delay_seconds, enabled=True)
    db.add(r); db.flush()
    return r


def deliver(db, report):
    """Write one archive, refusing if the quarantine boundary has been crossed.

    The dataset row lock plus a refresh after acquiring it means a delivery
    that was already in flight when the quarantine committed cannot write a
    fresh archive afterwards, and its unsaved rows are rolled back by the caller.
    """
    j=db.get(Job,report.job_id)
    if not j: return None
    lock_dataset(db, j.dataset_id)
    db.refresh(report)
    dataset=db.get(Dataset, j.dataset_id)
    if dataset is not None and dataset.quarantined:
        return None
    if report.quarantined or quarantine.for_dataset(db, j.dataset_id):
        return None
    db.refresh(j)
    if not j.approved or j.status!='completed': return None
    out=io.StringIO()
    out.write('\ufeff')
    table=j.result.get('table',{})
    cols=table.get('columns',[])
    writer=csv.writer(out)
    def safe(v):
        if isinstance(v,(int,float)) and not isinstance(v,bool): return v
        text=str(v)
        return "'"+text if text.startswith(('=','+','-','@','\t','\r')) else text
    writer.writerow([safe(c['label']) for c in cols])
    for row in table.get('rows',[]): writer.writerow([safe(row.get(c['key'],'')) for c in cols])
    data=out.getvalue().encode('utf-8')
    delivery=Delivery(report_id=report.id, created_at=time.time(), checksum=hashlib.sha256(data).hexdigest(), filename='', destination=report.destination)
    db.add(delivery); db.flush()
    delivery.filename=f'report-{report.id}-delivery-{delivery.id}.csv'
    os.makedirs(ARTIFACT_DIR,exist_ok=True)
    with open(os.path.join(ARTIFACT_DIR,delivery.filename),'wb') as f:f.write(data)
    with open(os.path.join(ARTIFACT_DIR,delivery.filename+'.json'),'w') as f: json.dump({'job':j.name,'params':j.params,'result':j.result,'checksum':delivery.checksum},f,ensure_ascii=False,allow_nan=False)
    report.next_run=time.time()+report.interval_seconds
    return delivery
