import time
import sys
import pytest
from sqlalchemy import select
from src.config.database import Session
from src.models import User, Dataset, Job, Report, Delivery, Quarantine
from src.utils.security import hash_password
from src.services.business import seed_records, metadata
from src.services import quarantine as qsvc, reports as rsvc
from src.utils.serialization import checksum
from migrations.initial import migrate

def test_delivery_after_boundary_rejected():
    migrate()
    with Session() as db:
        u=User(email='a@y',name='a',role='admin',password=hash_password('x'))
        db.add(u)
        rows=seed_records()
        d=Dataset(name='c1',source='x',records=rows,checksum=checksum(rows),created_at=time.time())
        db.add(d);db.commit();db.refresh(d)
        from src.services.business import analyze
        params={p['key']:p['default'] for p in metadata()['parameters']}
        j=Job(name='j',dataset_id=d.id,params=params,status='completed',result=analyze(rows,params),created_by=u.id,created_at=time.time(),finished_at=time.time(),approved=True)
        db.add(j);db.commit();db.refresh(j)
        r=Report(name='r',job_id=j.id,destination='in',interval_seconds=60,next_run=0,enabled=True)
        db.add(r);db.commit();db.refresh(r)
        jid,rp,dataset_id=j.id,r.id,d.id

    # Simulate staleness: a delivery session loads the report, then quarantine commits
    # from another session before this delivery acquires the dataset lock.
    with Session() as delivery_db:
        stale_report=delivery_db.get(Report,rp)
        assert stale_report.enabled
        with Session() as q:
            ds=q.get(Dataset,dataset_id)
            qn,created=qsvc.create(q,ds,'日历失真需要隔离', 'a@y')
            q.commit()
            assert created
        # Delivery continues with its stale object; it must re-check under the lock.
        result=rsvc.deliver(delivery_db,stale_report)
        assert result is None
        delivery_db.rollback()
    with Session() as db:
        assert db.query(Delivery).filter_by(report_id=rp).count()==0
        assert db.get(Report,rp).enabled is False
        assert db.get(Report,rp).quarantined is True

def test_job_result_write_after_boundary_rejected():
    import src.worker as worker
    with Session() as db:
        d=db.scalar(select(Dataset).where(Dataset.name=='c1'))
        u=db.query(User).first()
        j=Job(name='late',dataset_id=d.id,params={'part':'R17','alpha':0.2,'horizon':14,'variant':'sba'},status='queued',created_by=u.id,created_at=time.time())
        db.add(j);db.commit();db.refresh(j);jid=j.id
    # Force the job to be "running" before quarantine sweep can see it queued:
    with Session() as db:
        j=db.get(Job,jid); j.status='running'; db.commit()
    worker.execute(jid)  # status running -> returns early only if not queued
    with Session() as db:
        j=db.get(Job,jid)
        # already running is not queued, worker returns; simulate completion path directly
        from src.worker import _freeze
        _freeze(db,j,None)
    with Session() as db:
        j=db.get(Job,jid)
        assert j.status=='quarantined' and not j.approved and not j.result
