"""Billable routing/latency check; all learner dialogue below is synthetic."""
from datetime import datetime,timezone
import json
from pathlib import Path
import time
from urllib.request import Request,urlopen
BASE='http://127.0.0.1:8765'
OUT=Path(__file__).resolve().parents[1]/'results'/('fast_dialogue_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
records=[]
def post(data):
    req=Request(BASE+'/api/feedback',data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Origin':BASE})
    start=time.perf_counter()
    with urlopen(req,timeout=240) as r:reply=json.load(r)
    record=dict(trigger=data['trigger'],synthetic_student_message=data.get('message',''),wall_seconds=round(time.perf_counter()-start,3),response=reply)
    records.append(record);OUT.write_text(json.dumps(records,indent=2)+'\n')
    print(json.dumps(record),flush=True)
    return reply
if __name__=='__main__':
    with urlopen(BASE+'/api/examples/sketchjudge-ph020') as r:p=json.load(r)
    a=post(dict(trigger='submission',source_id='sketchjudge-ph020',scene=p['scene'],original_scene=p['scene'],task=p['question']['text'],explanation='',goals=[],edits=[],message=''))
    assert a['response_mode']=='review' and a['model']=='gpt-6-astra'
    for message in ['I think G would stay vertically downward if the incline got steeper.',
                    'What do you mean by vertically downward? Please explain it directly.',
                    'Thanks, I want to stop here for now.']:
        b=post(dict(trigger='message',session_id=a['session_id'],message=message))
        assert b['response_mode']=='dialogue' and b['model']=='gpt-6-sol' and b['api_calls']==1
        assert not b['acknowledgment'] and not b['acknowledgment_ids']
        assert b['content'].count('?')<=1 and b['review']==a['review'] and b['review_version']==a['review_version']
    assert '?' not in b['content']
    print('Saved:',OUT)
