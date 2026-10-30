"""Local research workspace: GPT-6 uploads + grounded chat; no project-root serving."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
import threading
import time
from urllib.parse import urlsplit
import uuid

from dotenv import load_dotenv
from PIL import Image

HERE=Path(__file__).resolve().parent
EXPERIMENT=HERE.parent
ROOT=EXPERIMENT.parents[1]
sys.path.insert(0,str(EXPERIMENT))
from schema import Sketch, validate_sketch
from run import save
from reconstruction import profile, decode
import feedback
from case_resume import prepare_resume
from transformation_agent import TransformationAgent

MODEL='gpt-6-astra'
ARTIFACTS=HERE/'runs'
JOBS={}
LOCK=threading.Lock()
POOL=ThreadPoolExecutor(max_workers=2)
MAX_BODY=28*1024*1024

for path in [EXPERIMENT/'.env',ROOT/'.env',ROOT/'experiments/sketch_to_interactive/.env']:
    load_dotenv(path,override=False,interpolate=False)

DIALOGUE_MODEL=os.getenv('DIALOGUE_MODEL','gpt-6-sol')
DIALOGUE_EFFORT=os.getenv('DIALOGUE_EFFORT','low')
FAST_DIALOGUE_MODEL=os.getenv('TUTOR_MODEL',os.getenv('FAST_DIALOGUE_MODEL','gpt-6-luna'))
FAST_DIALOGUE_EFFORT=os.getenv('FAST_DIALOGUE_EFFORT','low')
EVALUATION_MODEL=os.getenv('EVALUATION_MODEL',MODEL)
TRANSFORMATION_MODEL=os.getenv('TRANSFORMATION_MODEL',MODEL)
PROFILE=os.getenv('DRAWING_PROFILE','fast')
RECONSTRUCTION=profile(PROFILE)
PROMPT=RECONSTRUCTION['prompt']

def client():
    from openai import OpenAI
    if not os.getenv('OPENAI_API_KEY'):
        raise ValueError('Configure OPENAI_API_KEY in the local .env file and restart the service.')
    return OpenAI(timeout=600,max_retries=0)


def safe_error(exc):
    # Error bodies can contain request details. Keep them out of the UI/logs.
    if isinstance(exc,ValueError):
        return str(exc)[:200]
    status=getattr(exc,'status_code',None)
    return 'GPT-6 request could not finish'+(f' (HTTP {status})' if status else f' ({type(exc).__name__})')+'. Please try again.'


def examples():
    path=HERE/'examples.json'
    items=json.loads(path.read_text()) if path.exists() else []
    # Previously uploaded work remains selectable after a page/server restart.
    for p in sorted(ARTIFACTS.glob('upload_*/payload.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:10]:
        try:
            data=json.loads(p.read_text())
            items.append({'id':p.parent.name,'title':data['scene']['title']+' (uploaded)','upload':p.parent.name})
        except (ValueError,KeyError,OSError):continue
    return items


def read_payload(entry):
    if entry.get('upload'):
        return json.loads((ARTIFACTS/entry['upload']/'payload.json').read_text())
    out=EXPERIMENT/entry['run']
    sid=entry['sample']
    scene=json.loads((out/f'{sid}.scene.json').read_text())
    record=json.loads((out/f'{sid}.input_manifest.json').read_text())
    image=Path(record['original_path'])
    if not image.is_absolute():image=out/image
    original='data:'+(mimetypes.guess_type(image.name)[0] or 'image/png')+';base64,'+base64.b64encode(image.read_bytes()).decode()
    provenance=next(r for r in json.loads((out/'report.json').read_text()) if r['id']==sid)
    scene['title']=entry['title']
    # English presentation only: immutable model artifacts remain unchanged.
    for o in scene['objects']:
        if o['id'] in entry.get('labels',{}):o['label']=entry['labels'][o['id']]
    provenance={**provenance,'presentation_translation':bool(entry.get('labels'))}
    record={**record,'id':entry['id']}
    question=None
    if record.get('question_id'):
        figure=None
        if record.get('question_image_path'):
            qpath=Path(record['question_image_path'])
            if not qpath.is_absolute():qpath=out/qpath
            figure='data:'+(mimetypes.guess_type(qpath.name)[0] or 'image/png')+';base64,'+base64.b64encode(qpath.read_bytes()).decode()
        question=dict(id=record['question_id'],text=record['task'],image=figure)
    return dict(scene=scene,record=record,original=original,provenance=provenance,question=question)


def decode_upload(data):
    image=data.get('image','')
    if not isinstance(image,str) or not re.match(r'^data:image/(png|jpeg|webp);base64,',image):
        raise ValueError('Please submit a PNG, JPEG, or WebP image.')
    try:
        raw=base64.b64decode(image.split(',',1)[1],validate=True)
        if len(raw)>10*1024*1024:raise ValueError('Use an image smaller than 10 MB.')
        with Image.open(io.BytesIO(raw)) as im:
            size=im.size;fmt=im.format
            if fmt not in ('PNG','JPEG','WEBP'):raise ValueError('Unsupported image format.')
            if size[0]*size[1]>20_000_000:raise ValueError('Use an image smaller than 20 megapixels.')
            im.verify()
    except ValueError:raise
    except Exception:raise ValueError('This image could not be read. Please choose a valid image.')
    return raw,size,{'PNG':'.png','JPEG':'.jpg','WEBP':'.webp'}[fmt]


def decode_question_image(data):
    image=data.get('question_image')
    if image is None or image=='':return None
    try:raw,_,suffix=decode_upload({'image':image})
    except ValueError as exc:raise ValueError('Task figure: '+str(exc))
    mime='image/jpeg' if suffix=='.jpg' else 'image/'+suffix.lstrip('.')
    return 'data:'+mime+';base64,'+base64.b64encode(raw).decode()


def reconstruct(job_id,raw,size,suffix,task,question_image=None):
    out=ARTIFACTS/job_id
    started=time.perf_counter()
    try:
        out.mkdir(parents=True,exist_ok=False)
        source=out/('drawing'+suffix);source.write_bytes(raw)
        prompt=PROMPT.read_text();(out/'prompt.md').write_text(prompt)
        format_=RECONSTRUCTION['format']
        save(out/'schema.json',format_.model_json_schema())
        record=dict(id=job_id,filename=source.name,original_path=str(source),width=size[0],height=size[1],sha256=hashlib.sha256(raw).hexdigest(),task=task)
        question=None
        if question_image:
            qraw,_,qsuffix=decode_upload({'image':question_image})
            qsource=out/('question'+qsuffix);qsource.write_bytes(qraw)
            record.update(question_id=job_id+'_task',question_image_path=str(qsource))
            question=dict(id=record['question_id'],text=task,image=question_image)
        save(out/'drawing.input_manifest.json',record)
        save(out/'run_config.json',dict(agent='transformation',model=TRANSFORMATION_MODEL,profile=PROFILE,effort=RECONSTRUCTION['effort'],max_output_tokens=RECONSTRUCTION['max_output_tokens'],prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),store=False,image_detail='original',automatic_retries=0,task_context=task))
        image_url='data:'+(mimetypes.guess_type(source.name)[0] or 'image/png')+';base64,'+base64.b64encode(raw).decode()
        api_started=time.perf_counter()
        response,scene=TransformationAgent(client(),TRANSFORMATION_MODEL,PROFILE).transform(image_url,task,question_image,size)
        api_seconds=round(time.perf_counter()-api_started,3)
        save(out/'drawing.response.json',response.model_dump(mode='json',warnings=False))
        if response.status!='completed' or response.output_parsed is None:raise ValueError('The reconstruction did not finish. Try submitting the drawing again.')
        if PROFILE=='fast':save(out/'drawing.compact.json',response.output_parsed.model_dump())
        save(out/'drawing.scene.json',scene)
        timing=dict(api_seconds=api_seconds,total_seconds=round(time.perf_counter()-started,3))
        save(out/'drawing.timing.json',timing)
        provenance=dict(model=response.model,response_id=response.id,profile=PROFILE,effort=RECONSTRUCTION['effort'],timing=timing,usage=response.usage.model_dump() if response.usage else None)
        payload=dict(scene=scene,record=record,original=image_url,provenance=provenance,question=question)
        save(out/'payload.json',payload)
        result=dict(status='completed',payload=payload)
    except Exception as exc:
        result=dict(status='failed',error=safe_error(exc))
    with LOCK:JOBS[job_id]=result



class Handler(BaseHTTPRequestHandler):
    def log_message(self,format,*args):
        # Never log bodies, image data or API credentials.
        print(format%args,flush=True)
    def send_bytes(self,status,body,mime):
        self.send_response(status)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data: blob:; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers();self.wfile.write(body)
    def json(self,status,data):
        self.send_bytes(status,json.dumps(data,ensure_ascii=False).encode(),'application/json; charset=utf-8')
    def allowed(self):
        port=self.server.server_port
        if self.headers.get('Host') not in (f'127.0.0.1:{port}',f'localhost:{port}'):
            self.json(403,{'error':'Use the local workspace URL.'});return False
        origin=self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{port}',f'http://localhost:{port}'):
            self.json(403,{'error':'Cross-origin requests are not allowed.'});return False
        return True
    def do_GET(self):
        if not self.allowed():return
        path=urlsplit(self.path).path
        try:
            if path=='/api/resume-case':
                with LOCK:
                    resume=getattr(self.server,'resume_case',None)
                    if resume:
                        self.json(200,resume)
                        self.server.resume_case=None
                    else:self.send_bytes(204,b'','application/json')
                return
            if path=='/api/examples':self.json(200,[dict(id=e['id'],title=e['title']) for e in examples()]);return
            if path.startswith('/api/examples/'):
                item=next((e for e in examples() if e['id']==path.rsplit('/',1)[1]),None)
                if not item:self.json(404,{'error':'Example not found.'});return
                self.json(200,read_payload(item));return
            if path.startswith('/api/jobs/'):
                with LOCK:result=JOBS.get(path.rsplit('/',1)[1])
                self.json(200 if result else 404,result or {'error':'Drawing request not found.'});return
            files={'/':('index.html','text/html'),'/style.css':('style.css','text/css'),'/app.js':('app.js','text/javascript'),'/case_export.js':('case_export.js','text/javascript'),'/geometry.js':('geometry.js','text/javascript'),'/workflow.js':('workflow.js','text/javascript'),'/editor.js':('editor.js','text/javascript'),'/catalog.json':('catalog.json','application/json'),'/mechanism.js':('mechanism.js','text/javascript'),'/avatars/tutor.svg':('avatars/tutor.svg','image/svg+xml'),'/avatars/student.svg':('avatars/student.svg','image/svg+xml')}
            if path not in files:self.json(404,{'error':'Not found.'});return
            file,mime=files[path];self.send_bytes(200,(HERE/file).read_bytes(),mime+'; charset=utf-8')
        except Exception:self.json(500,{'error':'The local example could not be loaded.'})
    def do_POST(self):
        if not self.allowed():return
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':self.json(415,{'error':'JSON required.'});return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=MAX_BODY:self.json(413,{'error':'Request is too large or empty.'});return
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict):raise ValueError('JSON object required.')
            path=urlsplit(self.path).path
            if path=='/api/reconstruct':
                raw,size,suffix=decode_upload(data)
                question_image=decode_question_image(data)
                task=data.get('task','')
                if not isinstance(task,str) or len(task)>4000:raise ValueError('Task context must be at most 4,000 characters.')
                if not os.getenv('OPENAI_API_KEY'):raise ValueError('Configure OPENAI_API_KEY in .env and restart the service.')
                with LOCK:
                    if sum(j['status']=='running' for j in JOBS.values())>=2:self.json(429,{'error':'Two drawings are already being processed. Please wait.'});return
                    job_id='upload_'+uuid.uuid4().hex;JOBS[job_id]={'status':'running'}
                POOL.submit(reconstruct,job_id,raw,size,suffix,task,question_image);self.json(202,{'id':job_id});return
            if path=='/api/chat':self.json(400,{'error':'Start a feedback session and use Tutor dialogue.'});return
            if path=='/api/begin-revision':self.json(200,feedback.begin_revision(data));return
            if path=='/api/end-revision':self.json(200,feedback.end_revision(data));return
            if path=='/api/feedback':
                question_image=None
                student_image=None
                if data.get('trigger')=='submission':
                    if 'question_image' in data:question_image=decode_question_image(data)
                    item=next((e for e in examples() if e['id']==data.get('source_id')),None)
                    if item:
                        source=read_payload(item)
                        student_image=source.get('original')
                        if 'question_image' not in data:question_image=(source.get('question') or {}).get('image')
                self.json(200,feedback.handle(data,client(),ARTIFACTS,EVALUATION_MODEL,question_image=question_image,student_image=student_image,
                    dialogue_model=DIALOGUE_MODEL,dialogue_effort=DIALOGUE_EFFORT,
                    fast_dialogue_model=FAST_DIALOGUE_MODEL,fast_dialogue_effort=FAST_DIALOGUE_EFFORT,engaging_voice=True));return
            self.json(404,{'error':'Not found.'})
        except feedback.FeedbackError as exc:self.json(400,{'error':str(exc)})
        except (ValueError,TypeError,KeyError):self.json(400,{'error':'Please check the image, drawing data, and message and try again.'})
        except Exception as exc:self.json(502,{'error':safe_error(exc)})

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--resume-case',type=Path,action='append',help='Restore a saved case; repeat to retain multiple sessions. The last case opens in the next new page.')
    args=parser.parse_args()
    resume=None
    if args.resume_case:
        def resume_payload(source_id):
            item=next((e for e in examples() if e['id']==source_id),None)
            return read_payload(item) if item else None
        for case_path in args.resume_case:
            resume,state=prepare_resume(case_path,ARTIFACTS,resume_payload)
            state.setdefault('student_image',resume['payload'].get('original'))
            state.setdefault('question_image',(resume['payload'].get('question') or {}).get('image'))
            with feedback.GUARD:feedback.SESSIONS[state['id']]={'lock':threading.Lock(),'state':state}
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    server.resume_case=resume
    print(f'Local: http://127.0.0.1:{args.port}',flush=True)
    server.serve_forever()
