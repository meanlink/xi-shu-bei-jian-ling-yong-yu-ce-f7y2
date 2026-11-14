import time
from fastapi.testclient import TestClient
from src.main import app
from src.config.database import Session
from src.models import Delivery, Report, Job, Dataset
from src.worker import tick
def test_seed_and_tick():
    import os
    os.environ['SEED_DEMO']='true'
    with TestClient(app) as c:
        r=c.post('/auth/login',json={'email':'admin@demo.local','password':'Demo123!'})
        assert r.status_code==200,r.text
        h={'Authorization':'Bearer '+r.json()['access_token']}
        datasets=c.get('/datasets',headers=h).json()
        assert datasets and not datasets[0]['quarantined']
        jobs=c.get('/jobs',headers=h).json()
        body=c.post('/quarantines',json={'dataset_id':datasets[0]['id'],'reason':'演示：领用日历缺失零需求日导致日均失真'},headers=h)
        assert body.status_code==201,body.text
        dataset_id=datasets[0]['id']
        before=body.json()['counts']['deliveries']
        assert before>=1
        tick()
        with Session() as db:
            assert db.query(Job).filter(Job.dataset_id==dataset_id,Job.approved==True).count()==0
        # quarantined archive download refused, viewer included
        r=c.get('/deliveries',headers=h).json()
        q=[d for d in r if d['quarantined']]
        assert q
        assert c.get(f"/deliveries/{q[0]['id']}/download",headers=h).status_code==409
        ov=c.get('/overview',headers=h).json()
        assert ov['jobs']>=1
