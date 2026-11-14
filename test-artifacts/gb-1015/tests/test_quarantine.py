import os, sys, json, time
import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.config.database import Session
from src.models import User, Dataset, Job, Report, Delivery, Audit, Quarantine
from src.utils.security import hash_password
from src.services.business import seed_records, analyze, metadata
from src.services.reports import deliver
from src.utils.serialization import checksum
from src.worker import execute
from migrations.initial import migrate

@pytest.fixture(scope='module')
def client():
    with TestClient(app) as c: yield c

def auth(client, role):
    r=client.post('/auth/login',json={'email':role+'@x.local','password':'Passw0rd!'})
    assert r.status_code==200, r.text
    return {'Authorization':'Bearer '+r.json()['access_token']}

def make_job(dataset_id, name, approved=True):
    with Session() as db:
        d=db.get(Dataset,dataset_id)
        params={p['key']:p['default'] for p in metadata()['parameters']}
        result=analyze(d.records,params)
        u=db.query(User).filter_by(role='admin').first()
        j=Job(name=name,dataset_id=dataset_id,params=params,status='completed',result=result,created_by=u.id,created_at=time.time(),finished_at=time.time(),approved=approved)
        db.add(j);db.commit();db.refresh(j);return j.id

def setup_module(module):
    migrate()
    with Session() as db:
        for role in ('admin','analyst','viewer'):
            db.add(User(email=role+'@x.local',name=role,role=role,password=hash_password('Passw0rd!')))
        rows=seed_records()
        d=Dataset(name='原始批次',source='seed',records=rows,checksum=checksum(rows),created_at=time.time())
        db.add(d);db.commit();db.refresh(d)
        module.original_id=d.id

def test_01_permissions(client):
    a=auth(client,'admin'); ana=auth(client,'analyst'); v=auth(client,'viewer')
    r=client.post('/quarantines',json={'dataset_id':original_id,'reason':'日历缺零需求日'},headers=ana)
    assert r.status_code==403, r.text
    r=client.post('/quarantines',json={'dataset_id':original_id,'reason':'日历缺零需求日'},headers=v)
    assert r.status_code==403
    r=client.get('/quarantines',headers=v)
    assert r.status_code==200 and isinstance(r.json(),list)

def test_02_quarantine_and_blocks(client):
    global job_id, report_id, delivery_id
    job_id=make_job(original_id,'原始试算')
    with Session() as db:
        r=Report(name='每日归档',job_id=job_id,destination='收件箱',interval_seconds=86400,next_run=0,enabled=True)
        db.add(r);db.commit();db.refresh(r);report_id=r.id
        dl=deliver(db,r);db.commit();delivery_id=dl.id
        assert os.path.exists(os.path.join(os.environ['ARTIFACT_DIR'],dl.filename))
    a=auth(client,'admin')
    r=client.post('/quarantines',json={'dataset_id':original_id,'reason':'太短'},headers=a)
    assert r.status_code==422
    r=client.post('/quarantines',json={'dataset_id':original_id,'reason':'领用日历缺失零需求日，日均高估'},headers=a)
    assert r.status_code==201, r.text
    body=r.json()
    assert body['reason'].startswith('领用日历')
    globals()['quarantine_id']=body['id']
    assert body['counts']['jobs']==1 and body['counts']['reports']==1 and body['counts']['deliveries']==1
    assert body['progress']['steps'][0]['done'] is True
    # new trial
    r=client.post('/jobs',json={'name':'隔离后新试算','dataset_id':original_id,'params':{}},headers=auth(client,'analyst'))
    assert r.status_code==409, r.text
    # approve
    r=client.post(f'/jobs/{job_id}/approve',headers=a)
    assert r.status_code==409
    # new report
    r=client.post('/reports',json={'name':'新计划','job_id':job_id},headers=a)
    assert r.status_code==409
    # toggle existing plan back on
    r=client.post(f'/reports/{report_id}/toggle',headers=a)
    assert r.status_code==409
    # download blocked for all roles incl viewer
    for h in (a,auth(client,'analyst'),auth(client,'viewer')):
        r=client.get(f'/deliveries/{delivery_id}/download?format=csv',headers=h)
        assert r.status_code==409, r.text
    # archive still listed/traceable
    r=client.get('/deliveries',headers=a)
    assert any(d['id']==delivery_id and d['quarantined'] for d in r.json())

def test_03_retry_idempotent(client):
    a=auth(client,'admin')
    with Session() as db:
        before_q=db.query(Quarantine).count(); before_audit=db.query(Audit).filter(Audit.action=='dataset.quarantine').count()
    r=client.post('/quarantines',json={'dataset_id':original_id,'reason':'领用日历缺失零需求日，日均高估'},headers=a)
    assert r.status_code==201
    r2=client.post('/quarantines',json={'dataset_id':original_id,'reason':'重复提交同一次处置'},headers=a)
    assert r2.status_code==201
    with Session() as db:
        assert db.query(Quarantine).count()==before_q
        assert db.query(Audit).filter(Audit.action=='dataset.quarantine').count()==before_audit

def test_04_worker_cannot_reopen(client):
    with Session() as db:
        u=db.query(User).filter_by(role='admin').first()
        j=Job(name='隔离时仍在计算',dataset_id=original_id,params={'part':'R17'},status='queued',created_by=u.id,created_at=time.time())
        db.add(j);db.commit();db.refresh(j);jid=j.id
    execute(jid)
    with Session() as db:
        j=db.get(Job,jid)
        assert j.status=='quarantined', j.status
        assert not j.result
        assert not j.approved
    r=client.post(f'/jobs/{jid}/approve',headers=auth(client,'admin'))
    assert r.status_code==409

def test_05_correction_batch(client):
    a=auth(client,'admin')
    # replacement must be created after the quarantine boundary
    with Session() as db:
        rows=seed_records()
        old=Dataset(name='旧批次不可作修正',source='x',records=rows,checksum=checksum(rows),created_at=time.time()-99999)
        db.add(old);db.commit();db.refresh(old);old_id=old.id
    r=client.post(f'/quarantines/{quarantine_id}/replacement',json={'dataset_id':old_id},headers=a)
    assert r.status_code==409
    with Session() as db:
        rows=seed_records(); rows[0]={'day':rows[0]['day'],'part':rows[0]['part'],'demand':0}
        fixed=Dataset(name='修正后的领用日历',source='x',records=rows,checksum=checksum(rows),created_at=time.time()+1)
        db.add(fixed);db.commit();db.refresh(fixed);fixed_id=fixed.id
    r=client.post(f'/quarantines/{quarantine_id}/replacement',json={'dataset_id':fixed_id},headers=a)
    assert r.status_code==200, r.text
    assert r.json()['replacement']['dataset_id']==fixed_id
    assert r.json()['progress']['steps'][1]['done'] is True
    # original batch still refused
    r=client.post('/jobs',json={'name':'原批次仍不可试算','dataset_id':original_id,'params':{}},headers=a)
    assert r.status_code==409
    # new batch works end-to-end
    nid=make_job(fixed_id,'修正批次试算',approved=False)
    r=client.post(f'/jobs/{nid}/approve',headers=a)
    assert r.status_code==200, r.text
    r=client.post('/reports',json={'name':'修正后分发','job_id':nid,'delay_seconds':0},headers=a)
    assert r.status_code==201, r.text
    rid=r.json()['id']
    with Session() as db:
        rp=db.get(Report,rid); dl=deliver(db,rp); db.commit(); did=dl.id
    r=client.get(f'/deliveries/{did}/download?format=csv',headers=auth(client,'viewer'))
    assert r.status_code==200, r.text
    r=client.get(f'/quarantines/{quarantine_id}',headers=a)
    body=r.json()
    assert body['progress']['steps'][1]['done'] and body['progress']['steps'][2]['done'] and body['progress']['steps'][3]['done']
    assert body['progress']['current']=='distributed'
    # original archive remains blocked
    r=client.get(f'/deliveries/{delivery_id}/download?format=csv',headers=a)
    assert r.status_code==409
