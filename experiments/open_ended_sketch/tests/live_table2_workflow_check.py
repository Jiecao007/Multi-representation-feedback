"""Real-provider check using authored circuit versions and synthetic messages."""
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE/'app'))
import server
from legacy_support import feedback

ROOT=HERE.parents[1]
out=ROOT/'outputs/system_workflow_1010/live'
out.mkdir(parents=True,exist_ok=True)
versions=json.loads((ROOT/'outputs/system_feedback_guided_example/demonstration_submissions.json').read_text())
client=server.client();turns=[]
def run(data):
    result=feedback.handle(data,client,out,server.MODEL,dialogue_model=server.DIALOGUE_MODEL,dialogue_effort=server.DIALOGUE_EFFORT)
    turns.append(dict(trigger=data['trigger'],synthetic_student_message=data.get('message',''),reply=result))
    (out/'check.json').write_text(json.dumps(dict(evidence='Real API replies to synthetic learner dialogue and authored diagram versions.',turns=turns),indent=2))
    print(json.dumps(dict(turn=len(turns),move=result['talk_move'],stage=result['stage'],seconds=result['elapsed_seconds'],calls=result['api_calls'],content=result['content'],plan=result['revision_plan'])),flush=True)
    return result

first=run({**versions[0],'session_id':'','trigger':'submission','explanation':'','goals':[],'message':''})
assert first['talk_move']=='recognize_strengths' and first['content'].count('?')==1
sid=first['session_id']
second=run(dict(trigger='message',session_id=sid,message='The bulbs each connect across the same two junctions, so they are in parallel. Each branch gives current its own route.'))
assert second['talk_move']=='press_for_accuracy',second['talk_move']
third=run(dict(trigger='message',session_id=sid,message='A2 is currently in the L2 branch, so only that branch current passes through it. To measure the total, both branch currents need to pass through A2. I should revise it into a shared path.'))
assert third['talk_move'] in feedback.SUPPORT and not third['revision_plan'],third['talk_move']
# This contribution follows a thinking invitation. A readiness judgment is
# semantic: a further support question is valid when the model needs more evidence.
fourth=run(dict(trigger='message',session_id=sid,message='The branch currents combine at a junction. A2 must be on a common wire before they split or after they recombine, so both currents pass through it. This explains why the present branch position cannot measure their sum.'))
assert fourth['talk_move'] in feedback.SUPPORT | {'propose_revision_plan'},fourth['talk_move']
if fourth['talk_move']=='propose_revision_plan':assert fourth['revision_plan']
fifth=run({**versions[1],'session_id':sid,'trigger':'workspace-complete','message':''})
assert fifth['talk_move']=='invite_dialogue' and not fifth['revision_plan'],fifth['talk_move']
sixth=run(dict(trigger='message',session_id=sid,message='I have no further questions. I am done.'))
assert sixth['stage']=='complete' and '?' not in sixth['content']
print('Real-provider highlight, accuracy, thinking dialogue, reviewed revision, and closure checks passed.',flush=True)
