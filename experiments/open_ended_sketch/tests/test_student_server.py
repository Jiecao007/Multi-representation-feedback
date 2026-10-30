"""HTTP boundary tests without paid API calls."""
import base64
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
from PIL import Image

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE/'app'))
spec=importlib.util.spec_from_file_location('student_server',HERE/'app/server.py')
server=importlib.util.module_from_spec(spec);spec.loader.exec_module(server)
from compact import pack

class FakeResponse:
    status='completed'
    output_parsed=pack(json.loads((HERE/'results/20260923T042443334511Z/prisms.scene.json').read_text())) if server.PROFILE=='fast' else server.Sketch.model_validate(json.loads((HERE/'results/20260923T042443334511Z/prisms.scene.json').read_text()))
    model='test-stub-not-gpt6'
    id='test-only'
    usage=None
    def model_dump(self,**kwargs):return {'id':self.id,'status':self.status}

class BoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.base='http://127.0.0.1:'+str(cls.http.server_port)
        threading.Thread(target=cls.http.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):cls.http.shutdown();cls.http.server_close()
    def request(self,path,body=None,headers=None):
        raw=json.dumps(body).encode() if body is not None else None
        req=Request(self.base+path,data=raw,headers={'Content-Type':'application/json',**(headers or {})})
        try:
            with urlopen(req) as r:return r.status,json.load(r)
        except HTTPError as e:return e.code,json.load(e)
    def test_boundaries(self):
        for path in ('/.env','/../.env','/server.py','/runs/','/api/examples/missing'):
            self.assertEqual(self.request(path)[0],404)
        self.assertEqual(self.request('/api/examples',headers={'Host':'attacker.example'})[0],403)
        self.assertEqual(self.request('/api/reconstruct',{},headers={'Origin':'https://attacker.example'})[0],403)
        self.assertEqual(self.request('/api/reconstruct',{'image':'https://remote.example/image.png'})[0],400)
        self.assertEqual(self.request('/api/chat',{'scene':{},'message':'hello'})[0],400)
        status,catalog=self.request('/catalog.json')
        self.assertEqual(status,200);self.assertEqual(len(catalog['topics']),5)
    def test_upload_job_success_and_failure(self):
        image=io.BytesIO();Image.new('RGB',(10,10),'white').save(image,format='PNG')
        body={'image':'data:image/png;base64,'+base64.b64encode(image.getvalue()).decode(),'task':'A test image'}
        fake=type('Client',(),{})();fake.responses=type('Responses',(),{'parse':lambda *a,**kw:FakeResponse()})()
        with tempfile.TemporaryDirectory() as tmp,patch.object(server,'ARTIFACTS',Path(tmp)),patch.object(server,'client',return_value=fake),patch.dict(server.os.environ,{'OPENAI_API_KEY':'test-only'}):
            status,result=self.request('/api/reconstruct',body);self.assertEqual(status,202)
            for _ in range(100):
                _,job=self.request('/api/jobs/'+result['id'])
                if job['status']!='running':break
                time.sleep(.02)
            self.assertEqual(job['status'],'completed');self.assertEqual(len(job['payload']['scene']['objects']),4)
            self.assertTrue((Path(tmp)/result['id']/'drawing.response.json').exists())
            self.assertTrue((Path(tmp)/result['id']/'drawing.timing.json').exists())
            self.assertEqual(job['payload']['provenance']['profile'],server.PROFILE)
            if server.PROFILE=='fast':self.assertTrue((Path(tmp)/result['id']/'drawing.compact.json').exists())
            _,available=self.request('/api/examples')
            self.assertIn(result['id'],[entry['id'] for entry in available])
            _,restored=self.request('/api/examples/'+result['id'])
            self.assertEqual(restored['scene'],job['payload']['scene'])
        with tempfile.TemporaryDirectory() as tmp,patch.object(server,'ARTIFACTS',Path(tmp)),patch.object(server,'client',side_effect=RuntimeError('secret must not leak')),patch.dict(server.os.environ,{'OPENAI_API_KEY':'test-only'}):
            _,result=self.request('/api/reconstruct',body)
            for _ in range(100):
                _,job=self.request('/api/jobs/'+result['id'])
                if job['status']!='running':break
                time.sleep(.02)
            self.assertEqual(job['status'],'failed');self.assertNotIn('secret',job['error'])

if __name__=='__main__':unittest.main()
