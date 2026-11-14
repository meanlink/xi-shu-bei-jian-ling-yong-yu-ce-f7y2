import os, sys, tempfile
_tmp=tempfile.mkdtemp()
os.environ['DATABASE_URL']='sqlite:///'+os.path.join(_tmp,'test.db')
os.environ['REDIS_URL']='redis://127.0.0.1:6399/0'
os.environ['ARTIFACT_DIR']=os.path.join(_tmp,'artifacts')
os.environ['SEED_DEMO']='false'
os.environ['JWT_SECRET']='test'
sys.path.insert(0,'/workspace/backend')
