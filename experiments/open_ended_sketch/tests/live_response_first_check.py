"""Billable regression: real PH_020 and explicitly synthetic reversed-friction variant.
No grading labels, reference answer, or invented student explanation is supplied.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen

HERE=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8765'

def check(reverse=False):
    with urlopen(BASE+'/api/examples/sketchjudge-ph020',timeout=30) as response:payload=json.load(response)
    scene=deepcopy(payload['scene'])
    if reverse:
        arrow=next(r for r in scene['relations'] if r['id']=='r1')
        arrow['direction']='backward'
        # Remove original interpretation/evidence that would contradict the new geometry.
        arrow['interpretation']='Arrow labeled f.'
        arrow['evidence']='Arrow labeled f, with the arrowhead at the first point.'
    request=Request(BASE+'/api/feedback',data=json.dumps(dict(trigger='submission',source_id='sketchjudge-ph020',
        scene=scene,original_scene=scene,task=payload['question']['text'],explanation='',goals=[],edits=[],message='')).encode(),
        headers={'Content-Type':'application/json','Origin':BASE})
    start=time.perf_counter()
    with urlopen(request,timeout=240) as response:reply=json.load(response)
    result=dict(case='synthetic_reversed_friction' if reverse else 'real_PH_020_ans_04',
        seconds=round(time.perf_counter()-start,3),synthetic=reverse,response=reply)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    assert reply['acknowledgment'] and reply['highlight_ids']==reply['acknowledgment_ids']
    assert len(reply['content'].split())<=60
    assert set(reply['acknowledgment_ids']) <= {'r1','r2'}, 'Highlight student arrows, not the supplied apparatus.'
    if reverse:
        assert reply['next_focus_kind']=='gap'
        assert 'r1' in reply['focus_ids'] and reply['follow_up'].count('?')==1
    else:
        assert set(reply['acknowledgment_ids'])=={'r1','r2'}
        assert reply['next_focus_kind']=='extension' and reply['follow_up'].count('?')==1
        assert not any(r['gap'] for r in reply['review'])
        assert reply['review'][-1]['status']=='not-requested'
    return result

if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(check,[False,True]))
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out=HERE/'results'/('response_first_feedback_'+stamp+'.json')
    out.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    print('Saved:',out)
