"""Billable GPT-6 integration check using explicitly synthetic learner text."""
import json
from pathlib import Path
from urllib.request import Request,urlopen
BASE='http://127.0.0.1:8765'
OUT=Path(__file__).resolve().parents[1]/'app/live_feedback_check.json'
def post(data):
 req=Request(BASE+'/api/feedback',data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Origin':BASE})
 with urlopen(req,timeout=600) as r:return json.load(r)
with urlopen(BASE+'/api/examples/energy-food') as r:payload=json.load(r)
scene=payload['scene']
records=[]
def record(trigger,student,result):
 assert len(result['content'].split())<=(80 if result.get('response_mode')=='dialogue' else 60)
 assert result['content'].count('?')<=1
 assert len(result['review'])==3
 assert all(k not in result for k in ['private_assessment','avoid_telling','strengths','areas_for_improvement'])
 records.append({'trigger':trigger,'synthetic_student_text':student,'response':result})
 OUT.write_text(json.dumps({'synthetic_dialogue':True,'image_source':'existing energy pic1','turns':records},indent=2))
 print(trigger+': '+result['content'],flush=True)
initial='Food production uses water and energy. After people eat the food, some energy is gained and the rest is lost in waste.'
a=post(dict(trigger='submission',scene=scene,original_scene=scene,source_id='energy-food',explanation=initial,task='Explain connections among food, water, and energy in your drawing.',goals=[],edits=[],message=''))
record('submission',initial,a)
assert a['phase']=='feedback'
reply='By lost, I mean the energy disappears completely. I have not changed the picture yet.'
b=post(dict(trigger='message',session_id=a['session_id'],message=reply))
record('message',reply,b)
scene=json.loads(json.dumps(scene));o=next(o for o in scene['objects'] if o['id']=='o11');o['label']='Waste and energy transferred to surroundings';o['verbatim_text']='WASTE / ENERGY TO SURROUNDINGS';o['glyph']=[{'kind':'text','points':[{'x':0,'y':500}],'text':o['verbatim_text'],'filled':False,'color':None}]
revision='I changed lost energy to energy transferred to the surroundings. I mean it spreads out rather than disappearing; waste can still contain energy.'
c=post(dict(trigger='workspace-complete',session_id=a['session_id'],scene=scene,explanation=revision,edits=[{'kind':'rename','id':'o11','value':{'text':o['label']}}],message=''))
record('workspace-complete',revision,c)
print('Three-turn live feedback check passed; all text is synthetic.',flush=True)
