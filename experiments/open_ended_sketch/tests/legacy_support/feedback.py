"""Table 2 move routing with Table 1 text–visual coordination.

The evaluator assesses each contribution privately. Deterministic routing gates
the tutor's move, and only explicit reviews commit a changed drawing.
"""
from copy import deepcopy
import json
from pathlib import Path
import re
import threading
import time
import uuid
from .feedback_types import Assessment, TutorReply, Review, Evidence, MechanismPath, TraceStep, FastDialogueTurn, normalize_move_fields
from .dialogue_context import compact_context, teacher_style, EMOJI
from schema import validate_sketch
from .feedback_policy import select_move, select_moves, meaning_move_in_support, update_progress, revision_requested, hint_requested, diagnosis_policy, thinking_policy, disclosure_policy, record_response_progress, refresh_response_evidence, revision_review_policy, MOVES, FORWARD, SUPPORT, THINKING_MOVES, MEANING_MOVES, operational_revision_completed, revision_understanding_grounded, guidance_edit_requested, reply_requires_edit, visible_edit_command, learner_action_echo
from .visual_feedback import visual_policy, mechanism_problem, planned_visual, coordinate_reply
from .reply_format import canonical_reply

PROMPTS=Path(__file__).resolve().parent/'prompts'
TRIGGERS={'submission','message','revision','workspace-complete'}
INTENTS={'dialogue','hint','begin_revision'}
DEFAULT_GOALS=['Visible representation','Relationships or spatial structure','Explanation and evidence']
SESSIONS={}
GUARD=threading.Lock()

class FeedbackError(ValueError):pass


def short_turn_problem(content,previous='',question_required=None):
    # Ported validator, including one focused question and no repeated revoicing.
    if not isinstance(content,str) or not content.strip():return 'Return a usable student-facing question.'
    if len(content.split())>55:return 'Use at most 55 English words across acknowledgment and follow-up; prefer 20–40.'
    if question_required and (content.count('?')!=1 or not content.rstrip().endswith('?')):return 'End the follow-up with exactly one focused question.'
    if question_required is False and content.count('?'):return 'Use a direct statement without a new question for this turn.'
    if content.count('?')>1:return 'Use at most one focused question.'
    if len(re.split(r'(?<=[.!?])\s+',content.strip()))>3:return 'Use at most three short sentences.'
    emojis=re.findall(r'[\U0001F300-\U0001FAFF\u2600-\u27BF]',content)
    if len(emojis)>1:return 'Use at most one simple emoji, sparingly.'
    if emojis and re.search(r'[\U0001F300-\U0001FAFF\u2600-\u27BF]',previous):return 'Vary the warmth naturally; skip the emoji this turn because the previous turn used one.'
    if re.match(r'^you (said|say|mentioned|wrote|stated)\b',content,re.I) and re.match(r'^you (said|say|mentioned|wrote|stated)\b',previous,re.I):return 'Do not repeat a You said opening.'
    if '\n' in content or re.search(r'(STUDENT RESPONSE|Feedback|Guided action|Correct answer):',content,re.I):return 'Use a conversational paragraph without headings.'
    if re.search(r'\bConnection\s+\d+\b',content,re.I):return 'Do not show internal connection numbers. Describe the visible mark and supply its focus_ids.'
    return ''

def text(value,limit):
    if not isinstance(value,str) or len(value)>limit:raise FeedbackError('Please shorten the submitted text and try again.')
    return value.strip()

def begin_revision(data):
    """Authorize editing without inventing dialogue or assessing the drawing."""
    return set_revision_mode(data,True)

def end_revision(data):
    """Return to viewing without committing or discarding a private draft."""
    return set_revision_mode(data,False)

def set_revision_mode(data,enabled):
    sid=text(data.get('session_id',''),120)
    with GUARD:entry=SESSIONS.get(sid)
    if entry is None:raise FeedbackError('This feedback session is unavailable. Start a new submission to continue.')
    if not entry['lock'].acquire(blocking=False):raise FeedbackError('Feedback is already being prepared. Please wait.')
    try:
        state=entry['state']
        state['edit_enabled']=enabled
        return {'session_id':sid,'edit_enabled':enabled,'awaiting_revision_reason':bool(state.get('awaiting_revision_reason'))}
    finally:entry['lock'].release()

def edits(data):
    values=data.get('edits',[])
    if not isinstance(values,list) or len(values)>2000:raise FeedbackError('Too many drawing edits in this submission.')
    if len(json.dumps(values))>200000:raise FeedbackError('Drawing history is too large.')
    allowed={'move','resize','reset','rename','add-note','add-object','connect','delete'}
    if any(not isinstance(v,dict) or v.get('kind') not in allowed for v in values):raise FeedbackError('Invalid drawing history.')
    return deepcopy(values)

def relation_name(scene,r):
    if r['verbatim_text']:return r['verbatim_text']
    names={o['id']:o['label'] for o in scene['objects']}
    a,b=names.get(r['source']),names.get(r['target'])
    if a and b:return f'Line between {a} and {b}'
    if a or b:return f'Line near {a or b}'
    x=sum(p['x'] for p in r['points'])/len(r['points'])
    y=sum(p['y'] for p in r['points'])/len(r['points'])
    vertical='upper' if y<333 else 'lower' if y>667 else 'middle'
    horizontal='left' if x<333 else 'right' if x>667 else 'center'
    return f'Unlabeled line ({vertical} {horizontal})'

def editor_context(state):
    """Describe supported controls separately from current edit permission."""
    scene=state['committed']['scene']
    return {
        'canvas_mode':'objects_and_connections','current_edit_enabled':bool(state.get('edit_enabled')),
        'capabilities':{'freehand_drawing':False,'object_connections':True,'text_annotations':True,
                        'library_objects':True,'connection_endpoint_drag':True,'curved_connections':True},
        'authorization':'Editing controls become enabled when this reply gives an authorized current edit instruction.',
        'endpoint_behavior':'Connect selects existing scene objects by their labels and initially joins their centers; it does not infer tick snapping or calibrated scale.',
        'tools':[
            {'action':'connect','label':'↗ Connect','available':len(scene['objects'])>=2,'requires_edit_permission':True,
             'instructions':'Select From and To existing objects by label, set Shape and Direction, optionally Meaning, then Save connection.',
             'endpoint_source':'committed.scene.objects','fields':['From','To','Meaning','Shape','Direction'],
             'shapes':['Straight','Curved','Bent'],
             'directions':['From → To','From ← To','Both directions','Line without an arrow'],
             'save_label':'Save connection'},
            {'action':'add_text','label':'+ Text','available':True,'requires_edit_permission':True,
             'instructions':'Enter the text, select Save changes, then move the new label to its intended position.'},
            {'action':'add_object','label':'+ Object','available':True,'requires_edit_permission':True,
             'instructions':'Choose a topic and one existing library item. Arrows are connections created with Connect.'},
            {'action':'edit_connection','label':'Edit connection','available':bool(scene['relations']),'requires_edit_permission':True,
             'instructions':'Select an existing connection, then Edit connection. Change its fields and Save connection. Drag endpoints or a middle handle to reshape it.'},
            {'action':'submit_revision','label':'Review changes','available':True,'requires_edit_permission':True,
             'instructions':'Submit the current draft so its actual changes can be reviewed.'},
        ]}


def prepare(state,data):
    trigger=data.get('trigger')
    if trigger not in TRIGGERS:raise FeedbackError('Use Start feedback, Send, or Review changes to request feedback.')
    intent=data.get('intent','dialogue')
    if intent not in INTENTS:raise FeedbackError('Unknown feedback action.')
    if trigger=='submission':
        scene=validate_sketch(data.get('scene')).model_dump()
        explanation=text(data.get('explanation',''),6000)
        task=text(data.get('task',''),4000)
        goals=data.get('goals',[])
        if not isinstance(goals,list) or len(goals)>5:raise FeedbackError('Use up to five feedback goals.')
        goals=[text(g,200) for g in goals if isinstance(g,str) and g.strip()]
        configured=bool(goals)
        criteria=[{'id':f'c{i+1}','label':g} for i,g in enumerate(goals or DEFAULT_GOALS)]
        original={'scene':validate_sketch(data.get('original_scene',scene)).model_dump(),'explanation':explanation}
        current={'scene':deepcopy(scene),'explanation':explanation,'edits':edits(data)}
        state={'id':'feedback_'+uuid.uuid4().hex,'original':original,'committed':current,'task':task,'criteria':criteria,
               'goals_configured':configured,'source_id':text(data.get('source_id',''),120),'version':0,'turns':[],'review':[],'previous_focus':None,
               'learning_goal':'','task_figure_context':'','revision_plan':'','revision_plan_ids':[],'stage':'recognition','drawing_version':1,
               'accuracy_focus':[],'accuracy_started_at':0,'thinking_focus':[],'thinking_started_at':0,'text_hint_focus':[],
               'issue_check_focus':[],'issue_check_started_at':0,'review_support_focus':[],'review_outcome':'not_reviewed',
               'edit_enabled':False,'awaiting_revision_reason':False,'revision_reason':'','previous_submission':None,
               'progress_focus':[],'issue_turn_count':0,'thinking_opportunity_count':0,'hint_count':0,'last_question_target':'',
               'response_progress_focus':[],'unsuccessful_response_count':0,'response_progress_version':-1,
               'last_response_frustration':False,'last_response_outcome_grounded':False,'hint_request_pending':False,'hint_turns_remaining':0}
    else:
        if state is None:raise FeedbackError('Submit your drawing for feedback first.')
        state=deepcopy(state)
        # Normalize copied runtime records; immutable imported artifacts stay intact.
        if state.get('assessment'):state['assessment']=normalize_move_fields(state['assessment'])
        state['turns']=[normalize_move_fields(turn) for turn in state['turns']]
        state.setdefault('task_figure_context','')
        state.setdefault('thinking_opportunity_count',0)
        for key,value in dict(response_progress_focus=[],unsuccessful_response_count=0,response_progress_version=-1,
                              last_response_frustration=False,last_response_outcome_grounded=False,
                              issue_check_focus=[],issue_check_started_at=0,review_support_focus=[],review_outcome='not_reviewed').items():
            state.setdefault(key,value)
        state['_review_changed']=False
        if trigger=='workspace-complete':
            if not state.get('edit_enabled'):raise FeedbackError('Begin a revision before editing and reviewing your diagram.')
            current={'scene':validate_sketch(data.get('scene')).model_dump(),'explanation':text(data.get('explanation',''),6000),'edits':edits(data)}
            changed=any(current[k]!=state['committed'][k] for k in ('scene','explanation'))
            state['_review_changed']=changed
            if changed or not state.get('awaiting_revision_reason'):
                state['previous_submission']=deepcopy(state['committed'])
            state['committed']=current
            state['revision_reason']=text(data.get('revision_reason',''),4000)
            state['awaiting_revision_reason']=bool(changed or state.get('awaiting_revision_reason'))
            state['drawing_version']=state.get('drawing_version',1)+1
        elif trigger=='revision':
            if not state.get('edit_enabled'):raise FeedbackError('Begin a revision before submitting changes.')
            explanation=text(data.get('explanation',''),6000)
            changed=explanation!=state['committed']['explanation']
            state['_review_changed']=changed
            state['previous_submission']=deepcopy(state['committed'])
            state['committed']['explanation']=explanation
            state['revision_reason']=text(data.get('revision_reason',''),4000)
            state['awaiting_revision_reason']=bool(changed or state.get('awaiting_revision_reason'))
        if trigger in {'revision','workspace-complete'}:
            # Remaining issues in a newly submitted model start a new inquiry.
            state.update(accuracy_focus=[],accuracy_started_at=0,thinking_focus=[],thinking_started_at=0,text_hint_focus=[],
                         issue_check_focus=[],issue_check_started_at=0,review_support_focus=[],review_outcome='not_reviewed',
                         progress_focus=[],issue_turn_count=0,thinking_opportunity_count=0,hint_count=0,last_question_target='',edit_enabled=False,
                         response_progress_focus=[],unsuccessful_response_count=0,response_progress_version=-1,
                         last_response_frustration=False,last_response_outcome_grounded=False)
        # Ordinary chat deliberately ignores client scene/task/goals/explanation.
    message=text(data.get('message',''),4000)
    if trigger=='message' and not message:raise FeedbackError('Enter a message first.')
    remaining=state.get('hint_turns_remaining',2 if state.get('hint_request_pending') else 0)
    if trigger=='message' and intent=='hint':
        if remaining:
            raise FeedbackError(f'Please answer the Dialogue question for {remaining} more {"turn" if remaining==1 else "turns"}, then try again.')
        remaining=2
    elif trigger=='message' and intent=='dialogue':
        remaining=max(0,remaining-1)
    state['hint_turns_remaining']=remaining
    state['hint_request_pending']=remaining>0
    state['intent']=intent
    if state.get('awaiting_revision_reason'):
        # Explaining a submitted change is a viewing task, not another edit.
        # An explicit new revision request can authorize editing after routing.
        state['edit_enabled']=False
    if trigger=='message' and intent=='dialogue' and state.get('awaiting_revision_reason'):
        state['revision_reason']=message
    state.pop('_reason_completed',None)
    state['version']+=1
    state['_current_trigger']=trigger
    state['_current_message']=message
    scene=state['committed']['scene']
    ids={o['id'] for o in scene['objects']}|{r['id'] for r in scene['relations']}
    references=[{'id':o['id'],'name':o['label'],'visible_text':o['verbatim_text'],'origin':o['origin']} for o in scene['objects']]
    references += [{'id':r['id'],'name':relation_name(scene,r),'visible_text':r['verbatim_text'],'origin':r['origin']} for r in scene['relations']]
    context={k:deepcopy(state[k]) for k in ('original','committed','task','task_figure_context','criteria','goals_configured','source_id','review','previous_focus','learning_goal','revision_plan','stage','accuracy_focus','accuracy_started_at','thinking_focus','thinking_started_at','text_hint_focus',
               'intent','edit_enabled','awaiting_revision_reason','revision_reason','previous_submission','progress_focus','issue_turn_count','thinking_opportunity_count','hint_count','last_question_target',
               'response_progress_focus','unsuccessful_response_count','response_progress_version','last_response_frustration',
               'issue_check_focus','issue_check_started_at','review_support_focus','review_outcome')}
    context.update(trigger=trigger,message=message,selected_id=data.get('selected_id') if data.get('selected_id') in ids else '',references=references,
                   editor_context=editor_context(state),
                   dialogue=[{'student':t['student'],'tutor':t['content'],'trigger':t['trigger'],'talk_move':t.get('talk_move',''),
                              'talk_moves':deepcopy(t.get('talk_moves',[])),'version':t['version']} for t in state['turns'][-16:]],
                   previous_assessment=deepcopy(state.get('assessment',{})))
    return state,context,ids

def valid_review(rows,criteria):
    ids=[c['id'] for c in criteria]
    if len(rows)!=len(ids) or sorted(r.criterion for r in rows)!=sorted(ids):return 'Provide exactly one review row for each configured criterion ID.'
    for row in rows:
        if len(row.strength.split())>12 or len(row.gap.split())>12:return 'Use at most 12 words in each review strength and gap.'
        if row.status=='not-requested' and row.gap:return 'An unrequested criterion must have an empty gap.'
    return ''

def visual_problem(reply,ids,assessment):
    requested=list(dict.fromkeys(([reply.focus_id] if reply.focus_id else [])+reply.focus_ids))
    if any(id_ not in ids for id_ in requested):return 'Use only existing object/relation IDs for the visual cue.'
    if len(requested)>4:return 'Focus on at most four relevant parts.'
    if any(id_ not in ids for id_ in reply.acknowledgment_ids):return 'Use existing IDs for the student-response highlight.'
    if len(reply.acknowledgment_ids)>4:return 'Highlight at most four parts of the student response.'
    return ''

def reply_problem(reply,state,assessment,ids,trigger,previous,move=None):
    """Require response recognition before an optional, separately grounded next step."""
    ack=reply.acknowledgment.strip();follow=reply.content.strip()
    combined=' '.join(s for s in (ack,follow) if s)
    review_policy=revision_review_policy(assessment,state,trigger)
    if not assessment.closing_requested:
        if review_policy['praise_required'] and not re.search(r'\b(correct(?:ly)?|right|well|good|great|nice|successful(?:ly)?|works|meets|accurate(?:ly)?)\b',ack,re.I):
            return 'First praise the successful submitted correction specifically, using the actual changed evidence and acknowledgment_ids, then support the next priority issue.'
        if review_policy['diagnosis_required'] and not reply.reveals_diagnosis:
            return 'State the actual unsuccessful revision\'s remaining problem directly and specifically, set reveals_diagnosis=true, then use the selected support move. Do not restart an accuracy quiz or supply the whole repair.'
    thinking=thinking_policy(assessment,state,state.get('_current_message',''),move)
    if move=='provide_hints_guidance' and not thinking['hint_allowed']:
        return 'Provide guidance for current same-issue uncertainty, an explicit help/revision request, frustration, or three grounded unsuccessful responses; otherwise develop reasoning.'
    disclosure=disclosure_policy(assessment,state,state.get('_current_message',''),move)
    if len(reply.new_conceptual_information)>disclosure['max_new_conceptual_steps']:
        return ('Preserve the learner’s thinking space. Remove tutor-supplied answers, alternatives or repair choices embedded in the prose/question; '
                'confirm only what the learner has supplied. Authorized guidance may introduce one focused point, not the full solution.')
    if not thinking['repair_instruction_allowed'] and (
            reply_requires_edit(reply,move) or reply.next_step in {'revise','annotate'} or
            (move in {*THINKING_MOVES,*MEANING_MOVES} and visible_edit_command(follow) and not learner_action_echo(reply,state))):
        return 'Do not supply a diagram repair instruction or destination yet. Invite an inference from the existing evidence, without giving the next operation away.'
    if move=='press_for_accuracy':
        observation=reply.check_observation.strip();question=reply.check_question.strip()
        verdict=r'\b(?:so|therefore|thus|hence|consequently|incorrect|wrong|fails? to|should|must|needs? to)\b|\b(?:which|this|that) means\b|\bas a result\b|\bdoes(?:n[’\']t| not) meet\b|[—–]\s*not\b'
        if reply.reveals_diagnosis or reply.question_purpose!='judge_current_diagram':
            return 'Press for accuracy must let the learner judge the CURRENT diagram, without announcing its diagnosis or asking how to repair it.'
        if (trigger=='message' and ack) or (ack and re.search(verdict,ack,re.I)):
            return 'Do not put a diagnosis in acknowledgment. Leave it empty on message checks; on actual reviews acknowledge only the visible change neutrally.'
        if not question or follow!=' '.join(s for s in (observation,question) if s):
            return 'Compose content ONLY from neutral check_observation and check_question; do not add a diagnostic preface or conclusion.'
        if len(observation.split())>20 or '?' in observation or re.search(verdict,observation,re.I):
            return 'check_observation must be short, neutral visible evidence or a warm invitation to inspect; leave the mismatch and its consequence for the learner to discover.'
        if len(re.split(r'(?<=[.!?])\s+',question))!=1 or re.search(
                r'\b(?:since|because|therefore|thus|hence|consequently|incorrect|wrong)\b|\b(?:which|this|that) means\b|\b(?:now|given) that\b',question,re.I):
            return 'check_question must be one question without a diagnostic premise or an inserted conclusion; a supported hypothetical mechanism condition is allowed.'
        if re.search(r'\b(?:where|how)\b.*\b(?:should|could|would|need)\b.*\b(?:move|place|put|change|fix|revise|edit|go|sit)\b|'
                     r'\bwhat\b.*\b(?:position|placement|connection)\b.*\b(?:need|should|must)\b',question,re.I):
            return 'Ask whether the current evidence meets the task goal, not where/how the corrected diagram should be arranged.'
    elif reply.reveals_diagnosis and not diagnosis_policy(assessment,state,state.get('_current_message',''),move)['allowed']:
        return 'Keep the private diagnosis unstated until the learner identifies THIS issue after its accuracy check, or explicitly requests hint/revision guidance. An answer about another feature does not count.'
    if trigger in {'submission','revision','workspace-complete'} and not ack:
        return 'First acknowledge the actual student response with a specific evidence-based observation.'
    if ack and '?' in ack:return 'The acknowledgment must recognize work, not question or challenge it.'
    quote=reply.evidence_quote.strip()
    text_uptake=bool(trigger=='message' and reply.evidence_source=='dialogue' and quote and
                     len(quote.split())<=12 and quote in state.get('_current_message',''))
    if ack and not reply.acknowledgment_ids and not text_uptake and not (trigger=='message' and assessment.closing_requested and assessment.next_focus_kind=='none'):
        return 'Supply acknowledgment_ids for the visible student work you recognize.'
    if not ack and reply.acknowledgment_ids:return 'Do not provide acknowledgment targets without an acknowledgment.'
    if trigger=='submission' and any(i not in reply.acknowledgment_ids for i in reply.focus_ids+([reply.focus_id] if reply.focus_id else [])):
        return 'The opening strength-confirmation question must refer to the recognized feature; keep its targets within acknowledgment_ids.'
    if trigger=='submission' and assessment.recognized_strength_supported and not re.search(r'\b(correct(?:ly)?|right|well|good|great|nice|successful(?:ly)?|works|meets|accurate(?:ly)?)\b',ack,re.I):
        return 'Explicitly affirm the supported feature as correct or successful, warmly and specifically; a neutral description alone is insufficient.'
    operational_praise=bool(state.get('_operational_revision_completed') and move=='invite_dialogue' and
                           not assessment.areas_for_improvement and not assessment.ambiguities and assessment.next_focus_kind=='none')
    if not follow and not assessment.closing_requested and not (operational_praise and ack):return 'Provide a usable response for the selected move.'
    required=False if assessment.closing_requested else True if move in {'recognize_strengths','press_for_accuracy',*MEANING_MOVES,'clarify_goals'} else None
    if move in THINKING_MOVES and not thinking['hint_allowed']:required=True
    if state.get('awaiting_revision_reason') and not assessment.closing_requested:required=True
    if operational_praise:required=False
    if move=='provide_hints_guidance':
        required=None
        instruction=reply.guidance_instruction.strip()
        if not instruction or instruction not in follow or '?' in instruction:
            return 'Supply guidance_instruction as a direct actionable statement appearing in content, not another quiz.'
        if visible_edit_command(follow) and not guidance_edit_requested(reply,move):
            return 'A visible drawing or editing instruction must set guidance_requires_edit=true, next_step=revise, and include that exact current edit command in guidance_instruction so the learner can carry it out.'
        if thinking['guidance_question_mode']=='direct_statement':required=False
        elif thinking['guidance_question_mode']=='focused_application':required=True
    if reply.guidance_requires_edit and not guidance_edit_requested(reply,move):
        return 'Set guidance_requires_edit only for provide_hints_guidance with next_step=revise and a direct instruction to modify the current diagram; observation or explanation guidance does not open editing.'
    if move=='propose_revision_plan' and (not reply.revision_plan.strip() or len(reply.revision_plan.split())>45):
        return 'Provide a concise revision_plan of at most 45 words; present the actionable next step in the conversation.'
    if move!='propose_revision_plan' and (reply.revision_plan or reply.revision_plan_ids):return 'Only propose_revision_plan can issue a new revision plan.'
    if reply.next_step in {'revise','annotate'} and not state.get('edit_enabled') and not (
            reply_requires_edit(reply,move) or revision_requested(assessment,state,state.get('_current_message',''))):
        return 'Use explain, clarify, or explore unless the learner requests revision or your visible plan/guidance explicitly instructs an operation on the current diagram.'
    if any(i not in ids for i in reply.revision_plan_ids) or len(reply.revision_plan_ids)>4:return 'Use up to four current IDs for the revision plan.'
    if (reply.visual_action=='none')!=(reply.visual_delivery=='none'):return 'Set both visual_action and visual_delivery to none for a text-only turn.'
    policy=visual_policy(assessment,state,trigger,state.get('_current_message',''),ids,move)
    if reply.visual_delivery=='automatic' and (not policy['automatic_allowed'] or (trigger!='submission' and assessment.visual_intent in {'conceptual','none'})):
        return 'This turn has no useful automatic diagram cue; use none or a relevant reference-only link.'
    shown=set(reply.focus_ids+reply.acknowledgment_ids+([reply.focus_id] if reply.focus_id else []))
    if reply.visual_action!='none' and (not shown or not shown.issubset(policy['allowed_ids'])):return 'Do not reveal a protected repair location. Use text only or allowed reference IDs from visual_policy.'
    if trigger=='submission' and reply.visual_delivery=='automatic' and not shown.issubset(reply.acknowledgment_ids):return 'Automatic opening cues may show only the recognized strength.'
    if reply.mechanism_paths:
        if reply.visual_action!='trace':return 'Use trace for a mechanism demonstration.'
        problem=mechanism_problem(reply.mechanism_paths,reply.mechanism_condition,state['committed']['scene'],assessment.mechanism_requires_condition)
        if problem:return problem
        if any(s.relation_id not in policy['allowed_ids'] for p in reply.mechanism_paths for s in p.steps):return 'Do not animate a protected repair position before the learner is ready.'
    elif reply.mechanism_condition:return 'Provide a condition only with actual mechanism paths.'
    if reply.visual_action=='trace' and assessment.visual_intent!='explain-mechanism':
        return 'Use a static highlight for this turn. Trace is only for a current mechanism question or explanation.'
    plan=planned_visual(assessment,state,trigger,state.get('_current_message',''),ids,move)
    if trigger!='submission' and plan['mechanism_paths'] and reply.visual_action!='trace':
        return 'Use the approved mechanism animation and write a matching mechanism explanation or question; static highlights alone do not show this process.'
    if reply.visual_action=='trace' and not reply.mechanism_paths:
        relations={r['id'] for r in state['committed']['scene']['relations'] if r['direction'] in {'forward','backward','both'}}
        if not relations.intersection(reply.focus_ids+[reply.focus_id]):return 'Trace only existing directed relations included in the focus targets; otherwise use highlight.'
    if reply.visual_action!='trace' and re.search(r"\b(?:animated|moving) (?:arrows|paths)|\bwatch (?:the |these )?(?:arrows|animation)|\blet['’]s trace\b",combined,re.I):
        return 'Do not promise an animation without an actual trace. Use a supported mechanism or ask about the visible highlight.'
    if state.get('_teacher_style',{}).get('emoji_expected') and not assessment.closing_requested and not EMOJI.search(combined):
        return 'Keep your specific teaching point and add one natural, supportive emoji with warm teacher wording.'
    return short_turn_problem(combined,previous,required) or valid_review(reply.review,state['criteria']) or visual_problem(reply,ids,assessment)

def normalize_reply(reply,state,assessment,ids):
    result=reply.model_dump()
    result['acknowledgment_ids']=list(dict.fromkeys(i for i in result['acknowledgment_ids'] if i in ids))[:4]
    result['follow_up']=result['content'].strip()
    result['acknowledgment']=result['acknowledgment'].strip()
    result['content']=' '.join(s for s in (result['acknowledgment'],result['follow_up']) if s)
    result['next_focus_kind']=assessment.next_focus_kind
    if result['focus_id'] not in ids:result['focus_id']=''
    result['focus_ids']=list(dict.fromkeys(([result['focus_id']] if result['focus_id'] else [])+[id_ for id_ in result['focus_ids'] if id_ in ids]))[:4]
    if not result['focus_id'] and result['focus_ids']:result['focus_id']=result['focus_ids'][0]
    if result['visual_delivery']=='none':
        # Grounding IDs stay in the private artifact; no Show link or cue leaks out.
        result['focus_id']='';result['focus_ids']=[];result['acknowledgment_ids']=[]
    source={'original':state['original']['explanation'],'revision':state['committed']['explanation'],
            'dialogue':'\n'.join([t['student'] for t in state['turns']]+[state.get('_current_message','')])}
    quote=result['evidence_quote'].strip()
    if quote and (len(quote.split())>12 or quote not in source[result['evidence_source']]):result['evidence_quote']=''
    prior={r['criterion']:r for r in state['review']}
    changed=set(assessment.changed_criteria)
    # Preserve unchanged overview rows verbatim, as in the original workflow.
    result['review']=[prior[r['criterion']] if r['criterion'] in prior and r['criterion'] not in changed else r for r in result['review']]
    return result

def handle(data,client,artifact_root,model,question_image=None,dialogue_model='gpt-6-sol',dialogue_effort='low',
           fast_dialogue_model=None,fast_dialogue_effort='low',engaging_voice=False):
    trigger=data.get('trigger')
    if trigger not in TRIGGERS:raise FeedbackError('Use Start feedback, Send, or Review changes to request feedback.')
    sid=data.get('session_id','')
    with GUARD:
        entry=SESSIONS.get(sid) if trigger!='submission' else {'lock':threading.Lock(),'state':None}
    if entry is None:raise FeedbackError('This feedback session is unavailable. Start a new submission to continue.')
    if not entry['lock'].acquire(blocking=False):raise FeedbackError('Feedback is already being prepared. Please wait.')
    started=time.perf_counter();calls=[]
    out=Path(artifact_root)/('feedback_turn_'+uuid.uuid4().hex);out.mkdir(parents=True)
    def save(name,value): (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    def call(name,prompt,context,format_,effort,call_model=None,token_limit=6000):
        (out/(name+'.prompt.md')).write_text(prompt,encoding='utf-8')
        save(name+'.input.json',context)
        content=[{'type':'input_text','text':json.dumps(context,ensure_ascii=False)}]
        if name=='evaluator' and state.get('question_image'):
            content.extend([{'type':'input_text','text':'QUESTION IMAGE: unsolved task figure, not the student response or a reference answer. Assess student marks only from the committed reconstruction.'},
                {'type':'input_image','image_url':state['question_image'],'detail':'original'}])
            save('evaluator.media.json',{'role':'unsolved_question_figure','image_url':state['question_image']})
        record={'stage':name,'model':call_model or model,'effort':effort,'input_chars':len(json.dumps(context,ensure_ascii=False))}
        calls.append(record);call_started=time.perf_counter()
        response=client.responses.parse(model=call_model or model,instructions=prompt,input=[{'role':'user','content':content}],reasoning={'effort':effort},max_output_tokens=token_limit,store=False,text_format=format_)
        record['elapsed_seconds']=round(time.perf_counter()-call_started,3)
        usage=getattr(response,'usage',None)
        if usage:
            record.update({k:getattr(usage,k,None) for k in ('input_tokens','output_tokens')})
        save(name+'.response.json',response.model_dump(mode='json',warnings=False))
        if response.status!='completed' or response.output_parsed is None:raise FeedbackError('Feedback did not finish. Your previous review is unchanged; please retry.')
        return response.output_parsed
    try:
        state,context,ids=prepare(entry['state'],data)
        if trigger=='submission':state['question_image']=question_image
        context['task_figure_present']=bool(state.get('question_image'))
        context['teacher_style']=teacher_style(state,trigger)
        if engaging_voice:state['_teacher_style']=context['teacher_style']
        prompt=(PROMPTS/'feedback_tutor.md').read_text()
        examples=PROMPTS/'feedback_examples.md'
        if examples.exists():prompt+='\n\n'+examples.read_text()
        fast=bool(trigger=='message' and fast_dialogue_model and state.get('assessment') and
                  (not state.get('question_image') or state['task_figure_context']))
        combined=None
        if fast:
            context=compact_context(context,state)
            fast_prompt=(PROMPTS/'feedback_fast_dialogue.md').read_text()+'\n\n'+prompt
            combined=call('dialogue',fast_prompt,context,FastDialogueTurn,fast_dialogue_effort,fast_dialogue_model,5000)
            assessment=combined.assessment
        else:
            # Changed drawings receive a fresh complete assessment.
            assessment=call('evaluator',(PROMPTS/'feedback_evaluator.md').read_text(),context,Assessment,'low')
        problem=valid_review(assessment.criteria,state['criteria'])
        if problem or assessment.criterion not in {c['id'] for c in state['criteria']}:
            raise FeedbackError('The review was incomplete. Your previous feedback is unchanged; please retry.')
        if len(assessment.learning_goal.split())>45:
            raise FeedbackError('The goal summary was too long. Please retry.')
        if not fast and state.get('question_image') and assessment.task_figure_context.strip():
            state['task_figure_context']=assessment.task_figure_context.strip()
        assessment.task_figure_context=state['task_figure_context']
        context['task_figure_context']=state['task_figure_context']
        refresh_response_evidence(assessment,state,context['message'])
        review_policy=revision_review_policy(assessment,state,trigger)
        if review_policy['invalid_reason']:
            raise FeedbackError('The review did not stay with the issue under revision. Your previous feedback is unchanged; please retry.')
        if review_policy['active']:
            # The reviewed result determines the next support need, not a compulsory WHY loop.
            state['awaiting_revision_reason']=False
        reason_eligible=trigger!='message' or context['intent']=='dialogue'
        operational_complete=bool(reason_eligible and state.get('awaiting_revision_reason') and operational_revision_completed(assessment,state))
        reason_established=bool(assessment.revision_reason_sufficient and (
            state.get('revision_reason','').strip() or revision_understanding_grounded(assessment,state)))
        if reason_eligible and state.get('awaiting_revision_reason') and (operational_complete or reason_established):
            state.update(awaiting_revision_reason=False,edit_enabled=False,_reason_completed=True)
        state['_operational_revision_completed']=operational_complete
        if assessment.closing_requested:
            state.update(awaiting_revision_reason=False,edit_enabled=False)
        context['awaiting_revision_reason']=state['awaiting_revision_reason']
        context['edit_enabled']=state['edit_enabled']
        record_response_progress(assessment,state,context['message'])
        for key in ('response_progress_focus','unsuccessful_response_count','response_progress_version','last_response_frustration'):
            context[key]=deepcopy(state[key])
        moves=select_moves(assessment,state,trigger,context['message'])
        move=moves[0]
        meaning_support=move in MEANING_MOVES and meaning_move_in_support(assessment,state,trigger)
        assessment.talk_move=move
        assessment.talk_moves=deepcopy(moves)
        if trigger=='submission':
            # The opening inquiry always concerns the recognized feature. Errors
            # and ambiguities stay private until the learner has an opening turn.
            assessment.next_focus_kind='extension'
            assessment.focus_id=next((i for i in assessment.response_highlight_ids if i in ids),'')
            assessment.inquiry_target='Ask one question inviting the learner to identify, confirm, or briefly explain the supported strength just recognized. Keep the question on that same feature and use their response to enter the next selected move. For uncertain work, ask about the meaning of the visible attempt.'
        state['_current_message']=context['message']
        policy=planned_visual(assessment,state,trigger,context['message'],ids,move)
        writer_context={**context,'private_assessment':assessment.model_dump(),'selected_talk_move':move,
                        'selected_talk_moves':deepcopy(moves),'visual_policy':policy,
                        'review_feedback_policy':review_policy,
                        'diagnosis_policy':diagnosis_policy(assessment,state,context['message'],move),
                        'thinking_policy':thinking_policy(assessment,state,context['message'],move),
                        'disclosure_policy':disclosure_policy(assessment,state,context['message'],move),
                        'revision_response_policy':{'operational_fix_verified':operational_complete,
                                                    'ask_revision_reason':state['awaiting_revision_reason']}}
        if trigger=='message':prompt+='\n\n'+(PROMPTS/'feedback_dialogue.md').read_text()
        writer_model=fast_dialogue_model if fast else dialogue_model if trigger=='message' else model
        effort=fast_dialogue_effort if fast else dialogue_effort if trigger=='message' else 'low'
        reply=canonical_reply(coordinate_reply(combined.reply if combined else call('tutor',prompt,writer_context,TutorReply,effort,writer_model,3000),policy),assessment)
        previous=state['turns'][-1]['content'] if state['turns'] else ''
        problem=reply_problem(reply,state,assessment,ids,trigger,previous,move)
        if combined and (combined.selected_talk_move!=move or combined.selected_talk_moves!=moves):
            problem=' '.join(s for s in (f'Use the authoritative selected_talk_move={move} and selected_talk_moves={moves}; the cached routing state does not permit {combined.selected_talk_move}/{combined.selected_talk_moves} this turn.',problem) if s)
        if problem:
            first_problem=problem
            reply=canonical_reply(coordinate_reply(call('tutor_rewrite',prompt,{**writer_context,'rewrite_requirement':problem,'previous_draft':reply.model_dump()},TutorReply,effort,writer_model,3000),policy),assessment)
            problem=reply_problem(reply,state,assessment,ids,trigger,previous,move)
            save('validation.json',{'initial_problem':first_problem,'rewrite_problem':problem})
        if problem:raise FeedbackError('The feedback could not be completed. Your previous feedback is unchanged; please retry.')
        public=normalize_reply(reply,state,assessment,ids)
        update_progress(state,assessment,move,reply)
        if not state['learning_goal'] or move=='clarify_goals':
            state['learning_goal']=assessment.learning_goal.strip() or 'Explain how your diagram represents the task and improve it using your reasoning.'
        if move=='propose_revision_plan':
            state['revision_plan']=reply.revision_plan.strip()
            state['revision_plan_ids']=deepcopy(reply.revision_plan_ids)
        elif trigger in {'revision','workspace-complete'} or state.get('_reason_completed'):
            # The old plan was tied to the prior model version and is now retired.
            state['revision_plan']='';state['revision_plan_ids']=[]
            state['edit_enabled']=False
        if state.get('awaiting_revision_reason'):state['edit_enabled']=False
        if revision_requested(assessment,state,context['message']) or reply_requires_edit(reply,move):
            state['edit_enabled']=True
        if assessment.closing_requested:state['edit_enabled']=False
        if assessment.closing_requested:state['stage']='complete'
        elif state['awaiting_revision_reason']:state['stage']='revision-explanation'
        elif move=='recognize_strengths':state['stage']='recognition'
        elif move=='propose_revision_plan':state['stage']='revision-planning'
        elif move=='invite_dialogue':state['stage']='dialogue'
        elif move in MEANING_MOVES:state['stage']='thinking-dialogue' if meaning_support else 'inquiry'
        elif move in SUPPORT:state['stage']='revision-planning' if state['revision_plan'] else 'thinking-dialogue'
        else:state['stage']='inquiry'
        public.update(phase='feed-up' if move=='clarify_goals' else 'feed-forward' if move in FORWARD else 'feedback',
                      talk_move=move,talk_moves=deepcopy(moves),criterion=assessment.criterion,stage=state['stage'],
                      learning_goal=state['learning_goal'],revision_plan=state['revision_plan'],
                      revision_plan_ids=deepcopy(state['revision_plan_ids']),drawing_version=state['drawing_version'],
                      edit_enabled=state['edit_enabled'],awaiting_revision_reason=state['awaiting_revision_reason'],
                      hint_request_pending=bool(state.get('hint_request_pending')),
                      hint_turns_remaining=state['hint_turns_remaining'])
        state['assessment']=assessment.model_dump()
        state.pop('_current_message',None)
        state.pop('_reason_completed',None)
        state.pop('_operational_revision_completed',None)
        state.pop('_teacher_style',None)
        state.pop('_review_changed',None)
        if trigger!='message':state['review_version']=state['version']
        public.update(response_mode='dialogue' if trigger=='message' else 'review',
                      review_version=state.get('review_version',state['version']),
                      model=calls[-1]['model'],api_calls=len(calls),elapsed_seconds=round(time.perf_counter()-started,3))
        state['turns'].append({'trigger':trigger,'student':context['message'],'submitted_explanation':state['committed']['explanation'],'version':state['version']})
        state['turns'][-1].update(public)
        state['review']=public['review']
        state['previous_focus']={'criterion':public['criterion'],'focus_id':public['focus_id']}
        save('session.json',state)
        save('public_reply.json',public)
        save('performance.json',{'path':'fast-dialogue' if fast else 'full-review','calls':calls,
                                 'elapsed_seconds':public['elapsed_seconds']})
        # Commit only after both stages and validation succeed.
        entry['state']=state
        with GUARD:SESSIONS[state['id']]=entry
        return {**public,'session_id':state['id'],'version':state['version'],'criteria':state['criteria'],
                'goals_configured':state['goals_configured'],'highlight_ids':public['acknowledgment_ids'] or public['focus_ids']}
    finally:entry['lock'].release()
