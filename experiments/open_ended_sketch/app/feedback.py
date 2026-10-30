"""Three-agent orchestration: formal submission assessment and fast dialogue."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid

from agent_api import AgentCalls, AgentError
from agent_types import EvaluationResult, TutorTurn
from evaluation_agent import EvaluationAgent, PROMPT as EVALUATION_PROMPT
from revision_target import (revision_target_context, record_delivered_revision_target,
                             consume_reviewed_revision_target)
from tutor_agent import TutorAgent
from tutor_context import build_tutor_context, editor_context
from learner_model import create_learner_model, migrate_learner_model, record_evaluation, record_observations, record_representation
from interaction_contract import scene_ids, validate_evaluation, validate_tutor, canonical_tutor
from move_selection import validate_move_selection, canonical_move_evidence
from feedback_process import (ensure_process, active_issue, record_evaluation_process,
                              validate_process_turn, commit_process, GUIDANCE_POLICY_VERSION)
from schema import validate_sketch

TRIGGERS = {'submission','message','revision','workspace-complete'}
INTENTS = {'dialogue','hint','begin_revision'}
DEFAULT_GOALS = ['Visible representation','Relationships or spatial structure','Explanation and evidence']
SESSIONS = {}
GUARD = threading.Lock()
RUNTIME_VERSION = 'three-agent-v1'

class FeedbackError(ValueError):
    pass

def text(value, limit):
    if not isinstance(value,str) or len(value)>limit:
        raise FeedbackError('Please shorten the submitted text and try again.')
    return value.strip()

def edits(data):
    values=data.get('edits',[])
    allowed={'move','resize','reset','rename','add-note','add-object','connect','delete'}
    if not isinstance(values,list) or len(values)>2000 or len(json.dumps(values))>200000:
        raise FeedbackError('Drawing history is too large.')
    if any(not isinstance(item,dict) or item.get('kind') not in allowed for item in values):
        raise FeedbackError('Invalid drawing history.')
    return deepcopy(values)

def _new_state(data):
    scene=validate_sketch(data.get('scene')).model_dump()
    explanation=text(data.get('explanation',''),6000)
    task=text(data.get('task',''),4000)
    goals=data.get('goals',[])
    if not isinstance(goals,list) or len(goals)>5:
        raise FeedbackError('Use up to five feedback goals.')
    goals=[text(goal,200) for goal in goals if isinstance(goal,str) and goal.strip()]
    criteria=[{'id':f'c{index+1}','label':goal} for index,goal in enumerate(goals or DEFAULT_GOALS)]
    source=text(data.get('source_id',''),120)
    state=dict(id='feedback_'+uuid.uuid4().hex,runtime_version=RUNTIME_VERSION,
        original={'scene':validate_sketch(data.get('original_scene',scene)).model_dump(),'explanation':explanation},
        committed={'scene':scene,'explanation':explanation,'edits':edits(data)},
        task=task,criteria=criteria,goals_configured=bool(goals),source_id=source,
        version=0,drawing_version=1,turns=[],stage='recognition',current_issue_id='',
        edit_enabled=False,awaiting_revision_reason=False,revision_reason='',previous_submission=None,
        hint_turns_remaining=0,hint_request_pending=False,consecutive_difficulties=0,guidance_count=0,
        guidance_policy_version=GUIDANCE_POLICY_VERSION,
        review=[],learning_goal='',review_version=0)
    state['learner_model']=create_learner_model(task,criteria,source,1)
    ensure_process(state)
    return state

def _migrate(state):
    if state.get('runtime_version')==RUNTIME_VERSION:
        return deepcopy(state)
    stable=('id','original','committed','task','criteria','goals_configured','source_id','version',
        'drawing_version','turns','stage','edit_enabled','review','learning_goal','review_version',
        'question_image','student_image','previous_submission')
    migrated={key:deepcopy(state[key]) for key in stable if key in state}
    migrated.update(runtime_version=RUNTIME_VERSION,learner_model=migrate_learner_model(state),
        current_issue_id='',awaiting_revision_reason=False,revision_reason='',
        hint_turns_remaining=state.get('hint_turns_remaining',0),hint_request_pending=state.get('hint_request_pending',False),
        consecutive_difficulties=state.get('unsuccessful_response_count',0),guidance_count=state.get('hint_count',0))
    formal=(migrated['learner_model'].get('evaluation') or {}).get('result',{})
    parts=formal.get('missing_parts',[])
    migrated['current_issue_id']=parts[0]['id'] if parts else ''
    migrated['turns']=migrated.get('turns',[])[-12:]
    if migrated.get('stage')=='revision-explanation':
        migrated['stage']='thinking-dialogue'
    return migrated

def prepare(state,data):
    trigger,intent=data.get('trigger'),data.get('intent','dialogue')
    if trigger not in TRIGGERS or intent not in INTENTS:
        raise FeedbackError('Unknown feedback action.')
    if trigger=='submission':
        state=_new_state(data)
    elif state is None:
        raise FeedbackError('This feedback session is unavailable. Start a new submission to continue.')
    else:
        state=_migrate(state)
    ensure_process(state)
    message=text(data.get('message',''),4000)
    if trigger=='message' and not message:
        raise FeedbackError('Enter a message first.')
    changed=False
    if trigger in {'workspace-complete','revision'}:
        if not state.get('edit_enabled'):
            raise FeedbackError('Begin a revision before submitting changes.')
        previous=deepcopy(state['committed'])
        scene=validate_sketch(data.get('scene')).model_dump() if trigger=='workspace-complete' else deepcopy(previous['scene'])
        changed=scene!=previous['scene']
        state['previous_submission']=previous
        state['committed']=dict(scene=scene,explanation=text(data.get('explanation',''),6000),edits=edits(data))
        state['revision_reason']=text(data.get('revision_reason',''),4000)
        state['edit_enabled']=False
        if changed:
            state['drawing_version']+=1
            state['stage']='thinking-dialogue'
            state['consecutive_difficulties']=state['guidance_count']=0
    remaining=state.get('hint_turns_remaining',0)
    if trigger=='message' and intent=='hint':
        if remaining:
            raise FeedbackError(f'Please continue the dialogue for {remaining} more {"turn" if remaining==1 else "turns"}, then try again.')
        remaining=2
    elif trigger=='message' and intent=='dialogue':
        remaining=max(0,remaining-1)
    state.update(version=state['version']+1,hint_turns_remaining=remaining,hint_request_pending=remaining>0)
    context={'message':message,'trigger':trigger,'intent':intent,'diagram_changed':changed}
    return state,context,scene_ids(state['committed']['scene'])

def set_revision_mode(data,enabled):
    sid=text(data.get('session_id',''),120)
    with GUARD:
        entry=SESSIONS.get(sid)
    if not entry:
        raise FeedbackError('This feedback session is unavailable. Start a new submission to continue.')
    if not entry['lock'].acquire(blocking=False):
        raise FeedbackError('Feedback is already being prepared. Please wait.')
    try:
        entry['state']['edit_enabled']=enabled
        entry['state']['awaiting_revision_reason']=False
        return dict(session_id=sid,edit_enabled=enabled,awaiting_revision_reason=False)
    finally:
        entry['lock'].release()

def begin_revision(data):
    return set_revision_mode(data,True)

def end_revision(data):
    return set_revision_mode(data,False)

def _evaluation_context(state,reason):
    memory=state['learner_model']
    prior=(memory.get('evaluation') or {}).get('result',{})
    return dict(reason=reason,drawing_version=state['drawing_version'],
        task={'text':state['task'],'criteria':state['criteria'],'goals_configured':state['goals_configured']},
        submitted_work=deepcopy(state['committed']),previous_work=deepcopy(state.get('previous_submission')),
        prior_evaluation=deepcopy(prior),
        addressed_issue=active_issue(state),
        revision_target=revision_target_context(state,reason),
        significant_observations=deepcopy(memory.get('observations',[])),
        support_history=[{'instruction':turn.get('content',''),'move':turn.get('talk_move',''),'issue_id':turn.get('issue_id','')}
            for turn in state.get('turns',[])[-6:] if turn.get('talk_move') in {'provide_hints_guidance','propose_revision_plan'}])

def _evaluation_cache_key(base_state,context,state,model):
    """Reuse only an identical pending assessment against an unchanged session."""
    inputs=dict(base_state=base_state,context=context,model=model,
        student_image=state.get('student_image'),question_image=state.get('question_image'),
        prompt=EVALUATION_PROMPT.read_text(),schema=EvaluationResult.model_json_schema())
    packed=json.dumps(inputs,sort_keys=True,ensure_ascii=False,separators=(',',':'))
    return hashlib.sha256(packed.encode('utf-8')).hexdigest()

def _review_rows(formal):
    rows=[]
    for row in formal.get('criteria',[]):
        gaps=[item.get('description','') for item in formal.get('missing_parts',[]) if item.get('criterion')==row['criterion']]
        rows.append(dict(criterion=row['criterion'],status=row['status'],
            strength=' '.join(row.get('evidence','').split()[:12]) if row['status']=='established' else '',
            gap=' '.join(' '.join(gaps).split()[:12]) if row['status']!='not-requested' else ''))
    return rows

def _public(turn,state,trigger,evaluated,accepted_updates):
    formal=(state['learner_model'].get('evaluation') or {}).get('result',{})
    acknowledgment,follow=turn.acknowledgment.strip(),turn.content.strip()
    move=turn.talk_moves[0]
    ids,ack_ids=list(dict.fromkeys(turn.focus_ids)),list(dict.fromkeys(turn.acknowledgment_ids))
    action,delivery=turn.visual_action,turn.visual_delivery
    if action=='none' or not (ids or ack_ids or turn.mechanism_paths):
        action=delivery='none';ids=[];ack_ids=[]
    elif delivery=='none':
        delivery='automatic'
    instruction=turn.edit_instruction.strip()
    if instruction:
        state['edit_enabled']=True
    if turn.stage=='complete':
        state['edit_enabled']=False
    state['awaiting_revision_reason']=False
    current=active_issue(state)
    issue=current['id'] if current else ''
    if turn.progress=='progress':
        state['consecutive_difficulties']=0
    elif turn.progress=='difficulty':
        state['consecutive_difficulties']=state.get('consecutive_difficulties',0)+1
    if move=='provide_hints_guidance':
        state['guidance_count']=state.get('guidance_count',0)+1
    state['review']=_review_rows(formal)
    state['learning_goal']=formal.get('learning_goal') or state.get('learning_goal') or state['task']
    plan=instruction if move=='propose_revision_plan' else ''
    state['revision_plan'],state['revision_plan_ids']=plan,ids if plan else []
    if evaluated:
        state['review_version']=state['version']
    return dict(content=' '.join(value for value in (acknowledgment,follow) if value),follow_up=follow,
        acknowledgment=acknowledgment,acknowledgment_ids=ack_ids,review=state['review'],
        focus_id=ids[0] if ids else '',focus_ids=ids,highlight_ids=ack_ids or ids,
        talk_move=move,talk_moves=turn.talk_moves,stage=state['stage'],current_issue_id=issue,
        phase='feed-up' if move=='clarify_goals' else 'feed-forward' if move in {'propose_revision_plan','invite_dialogue'} else 'feedback',
        next_focus_kind='none' if not current else 'gap',
        criterion=current['criterion'] if current else state['criteria'][0]['id'],
        next_step='revise' if instruction else turn.next_step if turn.next_step!='revise' or state['edit_enabled'] else 'explain',
        revision_plan=plan,revision_plan_ids=state['revision_plan_ids'],
        guidance_instruction=instruction if move=='provide_hints_guidance' else '',
        guidance_requires_edit=bool(instruction and move=='provide_hints_guidance'),
        edit_enabled=state['edit_enabled'],awaiting_revision_reason=False,revision_reason_required=False,
        visual_action=action,visual_delivery=delivery,mechanism_paths=[path.model_dump() for path in turn.mechanism_paths],
        mechanism_condition=turn.mechanism_condition,learning_goal=state['learning_goal'],
        drawing_version=state['drawing_version'],response_mode='dialogue' if trigger=='message' else 'review',
        review_version=state.get('review_version',0),hint_turns_remaining=state['hint_turns_remaining'],
        hint_request_pending=state['hint_request_pending'],evaluation_updated=evaluated,
        learner_model_revision=state['learner_model']['revision'],memory_updates=accepted_updates,
        revision_review=(dict(revision_outcome=formal.get('revision_outcome','not_reviewed'),
            revision_evidence=formal.get('revision_evidence',''),
            addressed_issue_status=state['workflow'].get('addressed_issue_status','not_reviewed'),
            revision_target=deepcopy(state['workflow'].get('reviewed_revision_target')))
            if evaluated and trigger!='submission' else None))

def handle(data,client,artifact_root,model,question_image=None,dialogue_model='gpt-6-luna',dialogue_effort='low',
           fast_dialogue_model=None,fast_dialogue_effort='low',engaging_voice=False,student_image=None):
    trigger=data.get('trigger')
    if trigger not in TRIGGERS:
        raise FeedbackError('Unknown feedback action.')
    with GUARD:
        entry={'lock':threading.Lock(),'state':None} if trigger=='submission' else SESSIONS.get(data.get('session_id',''))
    if not entry:
        raise FeedbackError('This feedback session is unavailable. Start a new submission to continue.')
    if not entry['lock'].acquire(blocking=False):
        raise FeedbackError('Feedback is already being prepared. Please wait.')
    started=time.perf_counter()
    calls=AgentCalls(client,Path(artifact_root)/('feedback_turn_'+uuid.uuid4().hex))
    path='tutor-dialogue'
    try:
        state,context,_=prepare(entry['state'],data)
        if trigger=='submission':
            state['question_image'],state['student_image']=question_image,student_image
        before_revision=state['learner_model']['revision']
        evaluated=trigger=='submission' or context['diagram_changed']
        if evaluated:
            reason='initial' if trigger=='submission' else 'diagram_revision'
            path=reason
            state['learner_model']=record_representation(state['learner_model'],state['committed']['scene'],state['source_id'],state['drawing_version'])
            addressed=active_issue(state)
            evaluation_context=_evaluation_context(state,reason)
            cache_key=_evaluation_cache_key(entry['state'],evaluation_context,state,model) if trigger!='submission' else None
            pending=entry.get('pending_evaluation')
            reused=bool(cache_key and pending and pending.get('key')==cache_key)
            if reused:
                evaluation=EvaluationResult.model_validate(deepcopy(pending['result']))
            else:
                entry.pop('pending_evaluation',None)
                evaluation=EvaluationAgent(calls,model).evaluate(evaluation_context,state.get('student_image'),state.get('question_image'))
            problem=validate_evaluation(evaluation,state)
            if problem:
                entry.pop('pending_evaluation',None)
                calls.save('validation.json',dict(problem=problem,automatic_rewrite=False))
                raise FeedbackError('The evaluation could not be completed. Your previous feedback is unchanged; please retry.')
            if cache_key:
                if not reused:
                    entry['pending_evaluation']=dict(key=cache_key,result=evaluation.model_dump(),
                        source_artifact=calls.directory.name)
                calls.save('evaluation_cache.json',dict(status='reused' if reused else 'stored',key=cache_key,
                    source_artifact=entry['pending_evaluation']['source_artifact'],
                    base_version=entry['state']['version'],drawing_version=state['drawing_version'],
                    evaluation_api_calls=0 if reused else 1))
            state['learner_model']=record_evaluation(state['learner_model'],evaluation,state['drawing_version'])
            record_evaluation_process(state,evaluation,initial=trigger=='submission',addressed_issue=addressed,
                                      revision_target=evaluation_context['revision_target'])
        tutor_model=fast_dialogue_model or dialogue_model
        effort=fast_dialogue_effort if fast_dialogue_model else dialogue_effort
        context_for_tutor=build_tutor_context(state,context['message'],trigger,context['intent'],evaluated,context['diagram_changed'],data.get('selected_id',''))
        if trigger=='submission' and context_for_tutor.get('opening_highlight'):
            calls.save('highlight_plan.json',context_for_tutor['opening_highlight'])
        turn=TutorAgent(calls,tutor_model,effort).respond(context_for_tutor)
        evidenced=canonical_move_evidence(turn,context_for_tutor)
        canonical=canonical_tutor(evidenced,state,initial=trigger=='submission',process=context_for_tutor['interaction'],
            opening_highlight=context_for_tutor.get('opening_highlight'))
        before_fields,after_fields=turn.model_dump(),canonical.model_dump()
        changes=[dict(field=name,before=before_fields[name],after=after_fields[name])
            for name in ('focus_ids','acknowledgment_ids','visual_action','visual_delivery','mechanism_paths',
                         'mechanism_condition','edit_instruction','next_step','stage','move_evidence','acknowledgment','content')
            if before_fields[name]!=after_fields[name]]
        if changes:
            record=dict(changes=changes,reason='Align sourced metadata, existing praise and optional visuals; preserve the combined reply and process checks.')
            if len(changes)==1:
                record.update(changes[0])
            calls.save('canonicalization.json',record)
        turn=canonical
        problem=(validate_tutor(turn,state,initial=trigger=='submission')
                 or validate_move_selection(turn,context_for_tutor)
                 or validate_process_turn(turn,state,context_for_tutor))
        if problem:
            calls.save('validation.json',dict(problem=problem,automatic_rewrite=False))
            raise FeedbackError('The feedback could not be completed. Your previous feedback is unchanged; please retry.')
        sources=[context['message'],state['committed']['explanation']]
        sources += [item.get('student','') for item in state.get('turns',[])[-6:]]
        state['learner_model'],accepted=record_observations(state['learner_model'],turn.memory_updates,sources,state['drawing_version'])
        commit_process(state,turn,context_for_tutor)
        public=_public(turn,state,trigger,evaluated,accepted)
        if evaluated and context['diagram_changed']:
            consume_reviewed_revision_target(state)
        record_delivered_revision_target(state,turn,context_for_tutor)
        public.update(session_id=state['id'],version=state['version'],criteria=state['criteria'],goals_configured=state['goals_configured'],
            api_calls=len(calls.records),agents_called=[item['stage'] for item in calls.records],model=tutor_model,
            elapsed_seconds=round(time.perf_counter()-started,3))
        state['turns']=(state.get('turns',[])+[dict(student=context['message'],content=public['content'],talk_move=public['talk_move'],
            talk_moves=public['talk_moves'],issue_id=state['current_issue_id'],version=state['version'],trigger=trigger,stage=public['stage'],
            edit_instruction=turn.edit_instruction,drawing_version=state['drawing_version'])])[-12:]
        state['last_question_target']=turn.question_target
        calls.save('session.json',state)
        calls.save('public_reply.json',public)
        if state['learner_model']['revision']!=before_revision:
            calls.save('learner_model_update.json',state['learner_model'])
            destination=Path(artifact_root)/'learner_models';destination.mkdir(parents=True,exist_ok=True)
            (destination/(state['id']+'.json')).write_text(json.dumps(state['learner_model'],ensure_ascii=False,indent=2))
        entry['state']=state
        entry.pop('pending_evaluation',None)
        with GUARD:
            SESSIONS[state['id']]=entry
        return public
    except AgentError as exc:
        raise FeedbackError(str(exc)) from exc
    finally:
        calls.save('performance.json',dict(path=path,calls=calls.records,elapsed_seconds=round(time.perf_counter()-started,3)))
        entry['lock'].release()
