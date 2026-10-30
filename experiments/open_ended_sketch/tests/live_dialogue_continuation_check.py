"""Billable PH_036 dialogue check; follow-up learner message is synthetic."""
from datetime import datetime,timezone
import json
from pathlib import Path
import time
from urllib.request import Request,urlopen
BASE='http://127.0.0.1:8765'
HERE=Path(__file__).resolve().parents[1]

def post(data):
    req=Request(BASE+'/api/feedback',data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Origin':BASE})
    start=time.perf_counter()
    with urlopen(req,timeout=240) as r:reply=json.load(r)
    result={'seconds':round(time.perf_counter()-start,3),'response':reply}
    print(json.dumps(result),flush=True)
    assert reply['follow_up'].count('?')<=1 and len(reply['content'].split())<=80
    assert reply['next_focus_kind']!='none'
    assert reply['focus_ids']
    return result

if __name__=='__main__':
    with urlopen(BASE+'/api/examples/sketchjudge-ph036') as r:p=json.load(r)
    a=post(dict(trigger='submission',source_id='sketchjudge-ph036',scene=p['scene'],original_scene=p['scene'],task=p['question']['text'],explanation='',goals=[],edits=[],message=''))
    assert a['response']['acknowledgment'] and a['response']['acknowledgment_ids']
    learner='I am not sure. Can you help me take a smaller step?'
    b=post(dict(trigger='message',session_id=a['response']['session_id'],message=learner))
    assert b['response']['follow_up']!=a['response']['follow_up']
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out=HERE/'results'/('dialogue_continuation_'+stamp+'.json')
    out.write_text(json.dumps({'source':'sketchjudge-ph036','initial_explanation':'','turns':[a,{'synthetic_student_message':learner,**b}]},indent=2)+'\n')
    print('Saved:',out)
