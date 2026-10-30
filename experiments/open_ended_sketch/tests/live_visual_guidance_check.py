"""Billable GPT-6 check: saved electric-field drawing, synthetic explanation."""
import json
import re
import argparse
import time
from pathlib import Path
from urllib.request import Request, urlopen

BASE='http://127.0.0.1:8765'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-id',default='upload_ec79d3497ee1452db01c20da95c6c8d4')
parser.add_argument('--output',type=Path)
args=parser.parse_args()
SOURCE=args.source_id
with urlopen(BASE+'/api/examples/'+SOURCE) as response:
    scene=json.load(response)['scene']
explanation='I drew a positive charge on the left and a negative charge on the right. My arrows show the electric field. I want feedback on how my arrows relate to these two charges.'
data=dict(trigger='submission',source_id=SOURCE,scene=scene,original_scene=scene,
          explanation=explanation,task='Explain the electric field represented in your drawing.',goals=[],edits=[],message='')
request=Request(BASE+'/api/feedback',data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Origin':BASE})
started=time.perf_counter()
with urlopen(request,timeout=600) as response:
    result=json.load(response)
seconds=round(time.perf_counter()-started,3)
ids={o['id']:o['label'] for o in scene['objects']}
ids.update({r['id']:r['verbatim_text'] or 'Drawn line' for r in scene['relations']})
assert 1<=len(result['highlight_ids'])<=4
assert all(id_ in ids for id_ in result['highlight_ids'])
assert not re.search(r'\bConnection\s+\d+\b',result['content'],re.I)
assert len(result['content'].split())<=60
record={'synthetic_dialogue':True,'source':SOURCE,'seconds':seconds,'synthetic_explanation':explanation,'response':result,
        'resolved_targets':{id_:ids[id_] for id_ in result['highlight_ids']}}
out=args.output or Path(__file__).resolve().parents[1]/'app/live_visual_guidance_check.json'
out.write_text(json.dumps(record,indent=2))
print(json.dumps({'content':result['content'],'targets':record['resolved_targets'],'seconds':seconds},indent=2))
