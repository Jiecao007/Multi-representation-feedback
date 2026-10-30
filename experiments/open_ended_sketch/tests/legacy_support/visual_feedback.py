"""Coordinate visual evidence with the purpose of the current text turn."""
from copy import deepcopy
import re
from .feedback_types import MechanismPath
from .feedback_policy import thinking_policy


def visual_policy(assessment,state,trigger,message,ids,move):
    protected=set(assessment.solution_target_ids)&ids
    scene=state['committed']['scene']
    # Existing incorrect marks are evidence, not hidden correction locations.
    if assessment.focus_id in ids:
        protected.discard(assessment.focus_id)
    if assessment.focus_id in {o['id'] for o in scene['objects']}:
        protected.difference_update(r['id'] for r in scene['relations']
                                    if assessment.focus_id in (r['source'],r['target']))
    identified={e.claim for e in assessment.learner_identifications
                if e.claim in ids and e.evidence.strip() and len(e.evidence.split())<=25 and e.evidence in message}
    explicit_visual=bool(re.search(r'\b(show(?: me)?|highlight|point (?:to|out)|visual (?:hint|help)|mark)\b|高亮|标出|图上|显示',message,re.I))
    later_visual=(explicit_visual or (assessment.student_stuck and assessment.visual_hint_needed)) and state.get('text_hint_focus')==[assessment.criterion,assessment.focus_id]
    thinking=thinking_policy(assessment,state,message,move)
    direct_guidance=move=='provide_hints_guidance' and thinking['repair_instruction_allowed']
    revision_guidance=move=='propose_revision_plan' and thinking['repair_instruction_allowed']
    later_visual=later_visual and thinking['hint_allowed']
    unlocked=protected if later_visual or direct_guidance or revision_guidance else identified
    if state.get('revision_plan'):unlocked |= protected.intersection(state.get('revision_plan_ids',[]))
    allowed=ids-(protected-unlocked)
    if trigger=='submission':allowed=set(assessment.response_highlight_ids)&ids
    return dict(allowed_ids=sorted(allowed),automatic_allowed=bool(allowed) and not assessment.closing_requested,
                solution_cue_allowed=bool(later_visual or direct_guidance or identified or revision_guidance))


def mechanism_problem(paths,condition,scene,requires_condition=False):
    """Validate overlays on existing connected geometry without task rules."""
    if len(paths)>2:return 'Show at most two relevant mechanism paths.'
    if len(condition.split())>20:return 'Keep the mechanism condition to at most 20 words.'
    if paths and requires_condition and not condition.strip():return 'State the assumed condition for this mechanism.'
    relations={r['id']:r for r in scene['relations']}
    for path in paths:
        if not path.label.strip() or len(path.label.split())>8:return 'Use a short, meaningful path label.'
        if not 1<=len(path.steps)<=12:return 'Use 1–12 existing relations in each path.'
        seen=set();end=None
        for step in path.steps:
            r=relations.get(step.relation_id)
            if not r or step.relation_id in seen:return 'Trace existing relations once per path; never invent a connection.'
            seen.add(step.relation_id)
            start,finish=(r['source'],r['target']) if step.direction=='forward' else (r['target'],r['source'])
            if start is None or finish is None:return 'Clarify unresolved endpoints before demonstrating a mechanism.'
            if end is not None and start!=end:return 'Consecutive trace steps must share the same actual endpoint.'
            end=finish
    return ''


def planned_visual(assessment,state,trigger,message,ids,move):
    policy=visual_policy(assessment,state,trigger,message,ids,move)
    intent='inspect-diagram' if trigger=='submission' else assessment.visual_intent
    policy['automatic_allowed']=policy['automatic_allowed'] and intent in {'inspect-diagram','explain-mechanism'}
    allowed=set(policy['allowed_ids'])
    targets=[i for i in assessment.visual_focus_ids if i in allowed][:4]
    if trigger=='submission':targets=[i for i in assessment.response_highlight_ids if i in allowed][:4]
    if not targets and assessment.focus_id in allowed:targets=[assessment.focus_id]
    paths=deepcopy(assessment.mechanism_paths) if intent=='explain-mechanism' else []
    condition=assessment.mechanism_condition.strip() if paths else ''
    if mechanism_problem(paths,condition,state['committed']['scene'],assessment.mechanism_requires_condition):
        paths=[];condition=''
    paths=[p for p in paths if all(s.relation_id in allowed for s in p.steps)]
    if paths and not targets:targets=[paths[0].steps[0].relation_id]
    automatic=bool(intent in {'inspect-diagram','explain-mechanism'} and (targets or paths) and not assessment.closing_requested)
    return {**policy,'prefer_automatic':automatic,'intent':intent,'focus_ids':targets,
            'mechanism_paths':[p.model_dump() for p in paths] if automatic else [],
            'mechanism_condition':condition if paths and automatic else '',
            'guidance':'Use static highlights for locating or comparing marks. Animate only when this turn asks about or explains a mechanism. Match text to the displayed evidence; omit visuals for purely conceptual replies or closure.'}


def coordinate_reply(reply,plan):
    """Keep automatic evidence, but never turn a static question into animation."""
    if not plan['prefer_automatic']:return reply
    if reply.visual_action=='none':
        reply.focus_ids=plan['focus_ids'];reply.focus_id=next(iter(reply.focus_ids),'')
        reply.visual_action='highlight'
    reply.visual_delivery='automatic'
    if plan['intent']!='explain-mechanism':
        if reply.visual_action=='trace':reply.visual_action='highlight'
        reply.mechanism_paths=[];reply.mechanism_condition=''
    elif reply.visual_action=='trace' and plan['mechanism_paths'] and not reply.mechanism_paths:
        reply.mechanism_paths=[MechanismPath(**p) for p in plan['mechanism_paths']]
        reply.mechanism_condition=plan['mechanism_condition']
    return reply
