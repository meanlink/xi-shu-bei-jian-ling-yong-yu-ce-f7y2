import time
from fastapi import HTTPException
from redis import Redis
from src.config.settings import REDIS_URL
from src.models import Dataset, Job
from src.services.business import metadata
from src.services import quarantine


def create(db, data, user):
    d=db.get(Dataset,data.dataset_id)
    if not d: raise HTTPException(404,'数据批次不存在')
    # Take the boundary lock before checking, so a new trial cannot commit
    # after the quarantine boundary with a pre-quarantine read.
    quarantine.lock_dataset(db, d.id)
    if quarantine.is_blocked(db, d.id): raise HTTPException(409,'该数据批次已隔离处置，不能发起新的预测试算')
    allowed={p['key']:p for p in metadata().get('parameters',[])}
    if set(data.params)-set(allowed): raise HTTPException(422,'包含未知分析参数')
    params={k:p['default'] for k,p in allowed.items()}
    params.update(data.params)
    for key,p in allowed.items():
        v=params[key]
        if p['type']=='number':
            try:
                v=float(v)
                if not (p.get('min',-1e9)<=v<=p.get('max',1e9)): raise ValueError()
                params[key]=v
            except (ValueError,TypeError): raise HTTPException(422, f'{p["label"]} 超出范围或非数值')
        elif str(v) not in [str(o['value']) for o in p.get('options',[])]:
            raise HTTPException(422,f'{p["label"]} 不是有效选项')
    j=Job(name=data.name, dataset_id=data.dataset_id, params=params, created_by=user.id, created_at=time.time(), status='queued')
    db.add(j); db.flush()
    return j


def approve(db, job, actor):
    """Approve under the same lock quarantine uses, so the boundary is total."""
    quarantine.lock_dataset(db, job.dataset_id)
    db.refresh(job)
    dataset=db.get(Dataset, job.dataset_id)
    if dataset and (dataset.quarantined or quarantine.for_dataset(db, job.dataset_id)):
        raise HTTPException(409,'该数据批次已隔离处置，不能批准其结果')
    if job.status=='quarantined' or job.status!='completed':
        raise HTTPException(409,'仅已完成结果可以批准')
    job.approved=True
    return job


def enqueue(job_id):
    try:
        r=Redis.from_url(REDIS_URL); r.rpush('analysis:queue',job_id); r.close()
    except Exception:
        pass # SQL queued status is the durable fallback
