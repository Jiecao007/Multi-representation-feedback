"""Billable first-feedback checks for three real SketchJudge responses.

No invented student explanation, answer key, correctness flag or error annotation
is supplied. The server obtains the unsolved question image from the saved example.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from datetime import datetime, timezone
from pathlib import Path
import time
from urllib.request import Request,urlopen

HERE=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8765'
STAMP=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
CASES=[('sketchjudge-ph007','20260923T060121944116Z'),
       ('sketchjudge-ph020','20260923T060120537786Z'),
       ('sketchjudge-ph036','20260923T060122390014Z')]

def check(case):
    source,run=case
    with urlopen(BASE+'/api/examples/'+source,timeout=30) as response:payload=json.load(response)
    question=payload['question'];scene=payload['scene']
    assert question['text'] and question['id'] in ('PH_007','PH_020','PH_036')
    if question['id']!='PH_007':assert question['image'].startswith('data:image/')
    data=dict(trigger='submission',source_id=source,scene=scene,original_scene=scene,
              explanation='',task=question['text'],goals=[],edits=[],message='')
    request=Request(BASE+'/api/feedback',data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Origin':BASE})
    started=time.perf_counter()
    with urlopen(request,timeout=600) as response:reply=json.load(response)
    elapsed=round(time.perf_counter()-started,3)
    ids={o['id'] for o in scene['objects']}|{r['id'] for r in scene['relations']}
    assert reply['highlight_ids'] and all(i in ids for i in reply['highlight_ids'])
    assert reply['acknowledgment'] and reply['highlight_ids']==reply['acknowledgment_ids']
    assert len(reply['content'].split())<=60
    assert reply['content'].count('?')==(0 if reply['next_focus_kind']=='none' else 1)
    record=dict(source=source,question_id=question['id'],question_text=question['text'],
                question_image_supplied=bool(question['image']),student_explanation_supplied=False,
                reference_answer_supplied=False,grading_annotations_supplied=False,
                feedback_seconds=elapsed,response=reply)
    (HERE/'results'/run/('live_feedback_check_'+STAMP+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(question=question['id'],seconds=elapsed,feedback=reply['content'],targets=reply['highlight_ids']),ensure_ascii=False),flush=True)
    return record

if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(check,CASES))
    (HERE/'results'/('physics_feedback_'+STAMP+'.json')).write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
