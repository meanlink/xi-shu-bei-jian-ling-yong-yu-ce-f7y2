import time, json, logging
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report
from src.services.business import analyze
from src.services.reports import deliver
from src.services import quarantine
from src.services.audit import record
logging.basicConfig(level=logging.INFO)
def execute(job_id):
    with Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        j.status='running'; db.commit()
        try:
            d=db.get(Dataset,j.dataset_id)
            result=analyze(d.records,j.params)
            json.dumps(result,allow_nan=False)
            # Publish under the dataset lock. If quarantine committed while
            # this analysis was running, the result must not reopen the job.
            quarantine.lock_dataset(db,j.dataset_id)
            db.refresh(j)
            dataset=db.get(Dataset,j.dataset_id)
            if (dataset is not None and dataset.quarantined) or quarantine.for_dataset(db,j.dataset_id):
                _freeze(db,j,result=None)
                return
            if j.status!='running':
                db.rollback()
                return
            j.result=result;j.status='completed';j.finished_at=time.time()
            record(db,'worker','job.completed',{'id':j.id})
        except Exception as e:
            logging.exception('Analysis failed')
            db.rollback()
            quarantine.lock_dataset(db,j.dataset_id)
            db.refresh(j)
            dataset=db.get(Dataset,j.dataset_id)
            if (dataset is not None and dataset.quarantined) or quarantine.for_dataset(db,j.dataset_id):
                _freeze(db,j,result=None)
                return
            if j.status!='running':
                db.rollback()
                return
            j.status='failed';j.error=str(e)[:990];j.finished_at=time.time()
            record(db,'worker','job.failed',{'id':j.id,'error':j.error})
        db.commit()


def _freeze(db, job, result):
    """Stop a job whose batch was quarantined mid-computation.

    The result is deliberately not published; the job is fenced as
    quarantined so it cannot be approved later.
    """
    job.status='quarantined'
    job.quarantined=True
    job.result={}
    job.approved=False
    job.finished_at=time.time()
    record(db,'worker','job.quarantined',{'id':job.id})
    db.commit()
def tick():
    with Session() as db:
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
    for job_id in queued:execute(job_id)
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled==True,Report.next_run<=time.time())):
            d=deliver(db,r)
            if d:record(db,'worker','report.delivered',{'id':r.id,'delivery':d.id})
        db.commit()
def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status=='running')):
            if quarantine.for_dataset(db,j.dataset_id):
                j.status='quarantined';j.quarantined=True;j.result={};j.approved=False
                j.finished_at=time.time();record(db,'worker','job.quarantined',{'id':j.id})
            else:
                j.status='queued';record(db,'worker','job.recovered',{'id':j.id})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop('analysis:queue',timeout=1)
            if item:execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
if __name__=='__main__':main()
