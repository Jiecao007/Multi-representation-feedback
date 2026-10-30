"""Task-independent move selection and progress tracking."""
import re
import unicodedata
from .feedback_types import TALK_MOVES, canonical_talk_move

MOVES=TALK_MOVES
MEANING_MOVES={'revoice','ask_for_clarification'}
FORWARD={'propose_revision_plan','invite_dialogue'}
SUPPORT={'build_on_prior_knowledge','invite_elaboration_reasoning','prompt_reflection','provide_hints_guidance',*MEANING_MOVES}
THINKING_MOVES=('invite_elaboration_reasoning','build_on_prior_knowledge','prompt_reflection')
UNSUCCESSFUL_RESPONSE_LIMIT=3
EDIT_ACTION=r'(?:mov(?:e|ing)|plac(?:e|ing)|position(?:ing)?|adjust(?:ing)?|align(?:ing)?|rotat(?:e|ing)|resiz(?:e|ing)|scal(?:e|ing)|extend(?:ing)?|shorten(?:ing)?|drag(?:ging)?|draw(?:ing)?|add(?:ing)?|connect(?:ing)?|delet(?:e|ing)|remov(?:e|ing)|edit(?:ing)?|revis(?:e|ing)|chang(?:e|ing)|revers(?:e|ing)|flip(?:ping)?|invert(?:ing)?|(?:re)?label(?:ing|ling)?|annotat(?:e|ing)|mark(?:ing)?|eras(?:e|ing)|attach(?:ing)?|replac(?:e|ing))'
EDIT_IMPERATIVE=r'(?:move|place|position|adjust|align|rotate|resize|scale|extend|shorten|drag|draw|add|connect|delete|remove|edit|revise|change|reverse|flip|invert|(?:re)?label|annotate|mark|erase|attach|replace|create)'
EDIT_DECORATION=r'[\s\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]*'
COMMAND_PREFIX=r"(?:^|[.!?;,:]\s*|\bthen\s+|\band\s+)"+EDIT_DECORATION+r"(?:(?:please|now|next)\s+|let['’]s\s+|go ahead and\s+|try (?:to )?|you (?:can|should)\s+)*"
EDIT_COMMAND=re.compile(COMMAND_PREFIX+r'\b(?:'+EDIT_IMPERATIVE+r'|(?<=try )'+EDIT_ACTION+r')\b',re.I)
USE_EDIT_COMMAND=re.compile(COMMAND_PREFIX+r'\buse\b(?:(?!\bto\b)[^.!?;\n]){1,160}\bto\s+'+EDIT_IMPERATIVE+r'\b',re.I)
UI_EDIT_COMMAND=re.compile(COMMAND_PREFIX+r'''\b(?:use|select|choose|click|open)\s+(?:the\s+)?["'`“‘]?(?:↗\s*)?(?:Connect\b|\+\s*(?:Text|Object)\b|Edit connection\b|Save connection\b)''',re.I)
EDIT_COMMAND_PATTERNS=(EDIT_COMMAND,USE_EDIT_COMMAND,UI_EDIT_COMMAND)
MENTAL_TARGET=re.compile(r'\s*(?:(?:my|your|our|the|an?|this|that)\s+)?(?:explanation|reasoning|reason|answer|response|idea|understanding|paragraph|sentence)\b|\s+on\s+(?:your\s+)?prior knowledge\b',re.I)
THINKING_INVITATION=re.compile(
    r"(?:^|[.;,:]\s*|\bthen\s+|\band\s+)(?:(?:please|now|next)\s+|let['’]s\s+|try (?:to )?)*"
    r'\b(?:explain|consider|think|compare|reflect|describe|predict|inspect|check|look|watch|trace|identify|tell me)\b',re.I)
REQUEST_ACTION=r'(?:fix|correct|'+EDIT_ACTION+r')'
REQUEST_PREFIX=r'(?:^|[.!?]\s*|\n\s*)(?:(?:yes|no|ok(?:ay)?|oh|well|right|sure|all right|now)\b[\s,!，]+|not[,!，]\s*)*(?:please\s+)?'
REVISION_REQUEST=re.compile(REQUEST_PREFIX+r'(?:'
    r'(?:begin|start) (?:a |my |the )?revision\b|'
    r'(?:tell|show) me how to '+REQUEST_ACTION+r'\b|'
    r"(?:i (?:want|would like|need) to|i['’]d like to|help me) "+REQUEST_ACTION+r'\b|'
    r"(?:let me|i(?:['’]ll| will| am going to|['’]m going to)) "+REQUEST_ACTION+r'\b|'
    r'(?:can|could|may) (?:i|we) (?:please )?'+REQUEST_ACTION+r'\b|'
    r'(?:can|could|would) you (?:please )?(?:help me|(?:tell|show) me how to) '+REQUEST_ACTION+r'\b|'
    r'how (?:can|do) i '+REQUEST_ACTION+r'\b|'
    r'(?:开始|我要|我想|帮我|告诉我怎么)(?:修改|改图|修正))',re.I)
QUOTED_TEXT=re.compile(r'```[\s\S]*?```|`[^`\n]*`|"[^"\n]*"|“[^”]*”|‘[^’]*’|(?<!\w)\x27[^\x27\n]*\x27')
HINT_NOUN=r'(?:(?:a|one|some|another|more|clearer|direct)\s+)*(?:hints?|guidance)\b'
HINT_REQUEST=re.compile(REQUEST_PREFIX+r'(?:'
    r"(?:i (?:need|want|would like|could use)|i['’]d like) "+HINT_NOUN+r'|'
    r'(?:give|provide|offer) me '+HINT_NOUN+r'|'
    r'(?:can|could|may) i (?:please )?(?:have|get) '+HINT_NOUN+r'|'
    r'(?:can|could|would) you (?:please )?(?:give|provide|offer) (?:me )?'+HINT_NOUN+r'|'
    r'(?:hints?|guidance)\s*,?\s*please\b|'
    r'(?:请|我需要|给我)(?:一个|一些)?(?:提示|指导))',re.I)
HELP_PREFIX=r'(?:^|[.!?;,，]\s*|\n\s*)(?:(?:okay|ok|yes|well)\b[\s,!，]+)*(?:please\s+)?'
EXPLICIT_HELP_REQUEST=re.compile(HELP_PREFIX+r'(?:'
    r"(?:i (?:need|want|would like|could use)|i['’]d like) (?:some |more )?help\b|"
    r'(?:can|could|would) you (?:please )?help me\b|help me\b|'
    r'(?:请)?(?:帮帮我|帮我理解|给我帮助))',re.I)
DIRECT_HELP_REQUEST=re.compile(HELP_PREFIX+r'(?:(?:can|could|would) you (?:please )?)?(?:'
    r'(?:(?:just|directly|simply)\s+)+(?:tell|show|explain)(?:\s+me)?\b|'
    r'(?:tell|show) me (?:(?:just|directly|simply)\s+|what to do\b|how to (?:start|begin|do|solve|work)\b|(?:the )?(?:first|next) step\b|the answer\b)|'
    r'(?:explain|show) (?:(?:to )?me )?(?:the |this |that )?(?:first|next) step\b|'
    r'explain (?:this|that|it)(?: to me)?\b|'
    r'(?:请)?(?:直接告诉我|告诉我(?:该|要)?怎么做|告诉我(?:第一|下一)步|解释(?:一下)?(?:第一|下一)步))',re.I)
LEARNING_UNCERTAINTY=re.compile(HELP_PREFIX+r'(?:'
    r"i (?:still |really )?(?:do not|don['’]\s*t|cannot|can['’]t) (?:know|understand|remember|figure (?:it|this) out)\b|"
    r"(?:still )?(?:do not|don['’]\s*t) (?:know|understand)\b|"
    r"(?:i(?:['’]m| am) )?(?:still )?(?:not sure|unsure|confused)\b|"
    r'(?:i have )?no idea\b|(?:我)?(?:还是|仍然)?(?:不懂|不会|不知道|没明白|不明白))',re.I)
UI_STATUS=re.compile(r'\b(?:loading|upload(?:ing)?|download(?:ing)?|sav(?:e|ing)|export(?:ing)?|browser|toolbar|button|network)\b|按钮|上传|保存|导出|加载',re.I)


def current_mismatch(assessment):
    """A sparse evidence list must not erase a cached, selected diagram gap."""
    return bool(assessment.areas_for_improvement or (
        assessment.next_focus_kind=='gap' and any(
            row.criterion==assessment.criterion and row.status in {'developing','not-yet-visible'} and row.gap.strip()
            for row in assessment.criteria)))


def revision_requested(assessment,state,message):
    if state.get('intent')=='begin_revision':
        return True
    unquoted=QUOTED_TEXT.sub('',message)
    return any(not MENTAL_TARGET.match(unquoted[match.end():]) for match in REVISION_REQUEST.finditer(unquoted))


def hint_requested(state,message):
    """A typed explicit hint request has the same meaning as the hint button."""
    return bool(state.get('intent')=='hint' or HINT_REQUEST.search(QUOTED_TEXT.sub('',message)) or
                EXPLICIT_HELP_REQUEST.search(QUOTED_TEXT.sub('',message)) or direct_help_requested(message))


def direct_help_requested(message):
    """Recognize an actual request to explain the local step directly."""
    return bool(DIRECT_HELP_REQUEST.search(QUOTED_TEXT.sub('',message)))


def learner_uncertainty(assessment,state,message=''):
    """Current same-issue inability calls for a scaffold, independently of cached labels."""
    current=QUOTED_TEXT.sub('',message or state.get('_current_message',''))
    return bool(state.get('_current_trigger')=='message' and state.get('intent','dialogue')=='dialogue' and
                assessment.progress_status!='new' and
                state.get('progress_focus')==[assessment.criterion,assessment.focus_id] and
                LEARNING_UNCERTAINTY.search(current) and not UI_STATUS.search(current))


def refresh_response_evidence(assessment,state,message=''):
    """Keep transient response evidence about this contribution, never the cached turn."""
    if state.get('_current_trigger')!='message' or state.get('intent','dialogue')!='dialogue' or hint_requested(state,message):
        assessment.current_response_outcome='not_applicable'
        assessment.outcome_evidence=''
    elif learner_uncertainty(assessment,state,message):
        words=list(re.finditer(r'\S+',message))
        assessment.current_response_outcome='unsuccessful'
        assessment.outcome_evidence=message[:words[min(len(words),25)-1].end()].strip() if words else ''
        assessment.student_stuck=True
    elif assessment.outcome_evidence and (len(assessment.outcome_evidence.split())>25 or assessment.outcome_evidence not in message):
        assessment.current_response_outcome='uncertain'
        assessment.outcome_evidence=''
    frustration=assessment.frustration_evidence.strip()
    if frustration and (len(frustration.split())>25 or frustration not in message):assessment.frustration_evidence=''
    return assessment


def revision_understanding_grounded(assessment,state):
    """Reuse the learner's established reasoning, never a tutor's explanation."""
    quote=assessment.revision_understanding_evidence.strip()
    if not quote or len(quote.split())>25 or re.fullmatch(
            r'(?:yes|yeah|yep|no|nope|right|correct|both|one|maybe|i agree|i think so)[.!? ]*',quote,re.I):
        return False
    contributions=[t['student'] for t in state.get('turns',[])]
    contributions.append(state.get('revision_reason',''))
    contributions += [state.get(k,{}).get('explanation','') for k in ('original','committed')]
    if state.get('previous_submission'):contributions.append(state['previous_submission'].get('explanation',''))
    return any(quote in value for value in contributions)


def operational_revision_completed(assessment,state):
    """Waive a new WHY only for a verified tool correction with known meaning.

    The evaluator checks the delta's meaning; this gate also requires an actual
    submitted change and grounded learner understanding. A remaining fault in
    the same issue cannot be certified as a completed operational correction.
    """
    previous=state.get('previous_submission')
    if (assessment.revision_change_kind!='operational' or not previous or
            not any(previous.get(k)!=state['committed'].get(k) for k in ('scene','explanation')) or
            not revision_understanding_grounded(assessment,state)):
        return False
    prior=state.get('assessment',{})
    same_issue=(not prior.get('focus_id') or
                (prior.get('criterion')==assessment.criterion and prior.get('focus_id')==assessment.focus_id))
    return not (same_issue and (current_mismatch(assessment) or assessment.ambiguities))


def visible_edit_command(content):
    """An imperative about the diagram must be visible, not hidden metadata."""
    return any(not MENTAL_TARGET.match(content[match.end():])
               for pattern in EDIT_COMMAND_PATTERNS for match in pattern.finditer(content))


def learner_action_echo(reply,state):
    """Distinguish a grounded paraphrase from a newly supplied repair step.

    This exception never grants edit permission. It is limited to descriptive
    uptake of the current learner's quoted proposal, with no new action arguments.
    """
    quote=reply.evidence_quote.strip()
    if (reply.evidence_source!='dialogue' or not quote or len(quote.split())>12 or
            quote not in state.get('_current_message','') or
            reply.question_purpose not in {'develop_reasoning','clarify_meaning'} or
            reply.next_step in {'revise','annotate'} or reply.guidance_requires_edit or reply.revision_plan):
        return False
    prefix=re.compile(r"^"+EDIT_DECORATION+r"(?:(?:yes|right|exactly|got it|ah|okay)[,\s—–-]*)?(?:"
                      r"you(?:['’]ve| have) (?:got|described|identified|proposed)|"
                      r"you(?:['’]d| would| are proposing|['’]re proposing| mean)|"
                      r"that (?:describes|matches|reflects))\b",re.I)
    omit={'a','an','the','at','from','to','then','and','of','in','on','by','it','this','that',
          'units','unit','steps','step'}
    def tokens(value):
        value=unicodedata.normalize('NFKC',value).lower().replace('−','-')
        values=re.findall(r'[+-]?\d+(?:\.\d+)?|[a-z]+\d*',value)
        return [('start' if v=='begin' else v.lstrip('+')) for v in values if v not in omit]
    known=tokens(quote)
    commands=[]
    for sentence in re.split(r'(?<=[.!?])\s+',reply.content.strip()):
        matches=[m for pattern in EDIT_COMMAND_PATTERNS for m in pattern.finditer(sentence)]
        if not matches:continue
        uptake=prefix.match(sentence)
        if not uptake or '?' in sentence:return False
        proposal=sentence.split(':',1)[1] if ':' in sentence else sentence[uptake.end():]
        # Purpose/explanation adjuncts do not add movement arguments.
        parts=re.split(r'\b(?:for|so|because)\b',proposal,maxsplit=1,flags=re.I)
        if len(parts)>1 and visible_edit_command(parts[1].strip()):return False
        proposal=parts[0]
        # Keep the learner's action order and multiplicity: the same words in
        # reverse order, or a repeated operation, would introduce a new step.
        remaining=iter(known)
        if not all(any(candidate==token for candidate in remaining)
                   for token in tokens(proposal)):return False
        # Also check values outside the abbreviated proposal (e.g. its stated purpose).
        values=lambda v:{t for t in tokens(v) if re.search(r'\d',t)}
        if not values(sentence).issubset(values(quote)):return False
        commands.extend(matches)
    return bool(commands)


def revision_edit_requested(reply,move):
    """A feedforward label or reasoning question alone cannot unlock editing."""
    return bool(move=='propose_revision_plan' and reply.next_step=='revise' and
                visible_edit_command(reply.content.strip()))


def guidance_edit_requested(reply,move):
    """An observation or explanation hint is not permission to edit."""
    instruction=reply.guidance_instruction.strip()
    return bool(move=='provide_hints_guidance' and reply.guidance_requires_edit and
                reply.next_step=='revise' and instruction and '?' not in instruction and
                instruction in reply.content and visible_edit_command(instruction))


def reply_requires_edit(reply,move):
    return revision_edit_requested(reply,move) or guidance_edit_requested(reply,move)


def grounded_support_evidence(quote,state,message=''):
    """Support choices use learner evidence, never the tutor's own explanation."""
    quote=quote.strip()
    if not quote or len(quote.split())>25 or re.fullmatch(
            r'(?:yes|yeah|no|right|correct|maybe|okay|ok)[.!? ]*',quote,re.I):return False
    sources=[message,state.get('_current_message','')]
    sources += [t.get('student','') for t in state.get('turns',[])]
    sources += [state.get(k,{}).get('explanation','') for k in ('original','committed')]
    return any(quote in value for value in sources)


def substantive_support_quote(quote):
    """An acknowledgment or bare uncertainty is not a concept or explanation."""
    quote=quote.strip()
    return bool(quote and len(quote.split())<=25 and not re.fullmatch(
        r"(?:yes|yeah|yep|no|nope|right|correct|maybe|okay|ok|thanks|thank you|"
        r"i (?:do not|don['’]t) (?:know|remember|understand)|"
        r"i(?:['’]m| am) (?:not sure|unsure)|not sure|i agree|i (?:think|guess) so)[.!? ]*",
        quote,re.I))


def reflection_eligible(assessment,state,message=''):
    """Require an expressed idea and an evaluative task, not a conflict label.

    These are source/completeness checks. Relevance to this issue, accessible
    comparison evidence and an unfinished evaluation remain evaluator judgments.
    """
    details=(assessment.reflection_target,assessment.reflection_reference,assessment.reflection_need)
    return bool(all(value.strip() and len(value.split())<=35 for value in details) and
                assessment.reflection_reference_source!='none' and
                substantive_support_quote(assessment.reflection_evidence) and
                grounded_support_evidence(assessment.reflection_evidence,state,message))


def grounded_activation_evidence(quote,state,message=''):
    """Ground a recall cue in actual context without claiming learner mastery."""
    if not substantive_support_quote(quote):return False
    quote=quote.strip()
    sources=[state.get('task',''),state.get('task_figure_context',''),
             message,state.get('_current_message','')]
    sources += [t.get('student','') for t in state.get('turns',[])]
    if state.get('goals_configured'):
        sources += [c.get('label','') for c in state.get('criteria',[])]
    for key in ('original','committed'):
        submitted=state.get(key,{})
        sources.append(submitted.get('explanation',''))
        scene=submitted.get('scene',{})
        sources += [mark.get('verbatim_text','') for kind in ('objects','relations')
                    for mark in scene.get(kind,[])]
    return any(quote in value for value in sources if isinstance(value,str))


def prior_knowledge_eligible(assessment,state,message=''):
    """Apply demonstrated knowledge or explicitly activate a contextual concept."""
    if not assessment.prior_knowledge_connection.strip():return False
    if assessment.prior_knowledge_mode=='activate':
        return grounded_activation_evidence(assessment.prior_knowledge_activation_evidence,state,message)
    return bool(substantive_support_quote(assessment.prior_knowledge_evidence) and
                grounded_support_evidence(assessment.prior_knowledge_evidence,state,message))


def revoice_eligible(assessment,state,message=''):
    """A grounded expressed idea and an actual need to check its interpretation."""
    return bool(assessment.revoice_need.strip() and len(assessment.revoice_need.split())<=35 and
                substantive_support_quote(assessment.revoice_evidence) and
                grounded_support_evidence(assessment.revoice_evidence,state,message))


def clarification_eligible(assessment):
    """An explicit unresolved meaning need, not a stale ambiguity flag."""
    return bool(assessment.clarification_need.strip() and len(assessment.clarification_need.split())<=35)


def meaning_moves(assessment,state,message='',initial=False):
    moves=[]
    if revoice_eligible(assessment,state,message):moves.append('revoice')
    if clarification_eligible(assessment):moves.append('ask_for_clarification')
    return moves or (['ask_for_clarification'] if initial else [])


def thinking_move(assessment,state,repeated=False,message=''):
    """Keep the original support order and the system-led reasoning default."""
    meaning=meaning_moves(assessment,state,message)
    if meaning:return meaning[0]
    if reflection_eligible(assessment,state,message):return 'prompt_reflection'
    if prior_knowledge_eligible(assessment,state,message):return 'build_on_prior_knowledge'
    return 'invite_elaboration_reasoning'


def revision_review_policy(assessment,state,trigger=None):
    """Evaluate the attempted issue separately from whether all issues are resolved."""
    trigger=trigger or state.get('_current_trigger')
    previous=state.get('previous_submission')
    changed=bool(state.get('_review_changed',True) and previous and
                 any(previous.get(k)!=state.get('committed',{}).get(k) for k in ('scene','explanation')))
    active=bool(trigger in {'revision','workspace-complete'} and changed and
                assessment.revision_outcome!='not_reviewed' and assessment.revision_outcome_evidence.strip())
    prior=state.get('assessment') or state.get('previous_focus') or {}
    prior_key=[prior.get('criterion'),prior.get('focus_id')]
    wrong_issue=bool(active and assessment.revision_outcome=='unsuccessful' and all(prior_key) and
                     prior_key!=[assessment.criterion,assessment.focus_id])
    if wrong_issue:active=False
    outcome=assessment.revision_outcome if active else 'not_reviewed'
    return {'active':active,'outcome':outcome,'praise_required':outcome=='successful',
            'diagnosis_required':outcome=='unsuccessful' and current_mismatch(assessment),
            'evidence':assessment.revision_outcome_evidence.strip() if active else '',
            'bypass_initial_check':active,
            'invalid_reason':'Keep an unsuccessful review on the issue under revision.' if wrong_issue else ''}


def failed_revision_diagnosis(assessment,state):
    key=[assessment.criterion,assessment.focus_id]
    current=revision_review_policy(assessment,state)
    return bool(current['diagnosis_required'] or (state.get('review_outcome')=='unsuccessful' and
                state.get('review_support_focus')==key and assessment.progress_status!='new' and current_mismatch(assessment)))


def guidance_progress(assessment,state,message=''):
    """Project grounded learner-response evidence, never tutor-question counts.

    Pure projection permits routing and validation to inspect a contribution
    repeatedly without counting it repeatedly. Only a successful transaction
    commits the projection, via record_response_progress.
    """
    key=[assessment.criterion,assessment.focus_id]
    current=message or state.get('_current_message','')
    version=state.get('version',0)
    recorded=(state.get('response_progress_version')==version and
              state.get('response_progress_focus')==key)
    same=state.get('response_progress_focus')==key and assessment.progress_status!='new'
    count=state.get('unsuccessful_response_count',0) if same or recorded else 0
    eligible=(state.get('_current_trigger')=='message' and state.get('intent','dialogue')=='dialogue' and bool(current))
    quote=assessment.outcome_evidence.strip()
    grounded=bool(eligible and quote and len(quote.split())<=25 and quote in current)
    outcome=assessment.current_response_outcome
    if eligible and learner_uncertainty(assessment,state,current) and not hint_requested(state,current):
        grounded=True;outcome='unsuccessful'
    frustration=assessment.frustration_evidence.strip()
    # Ordinary uncertainty alone is not evidence of affective frustration.
    bare_uncertainty=bool(re.fullmatch(r"(?:i (?:do not|don['’]t) know|i(?:['’]m| am) (?:not sure|unsure)|not sure|maybe)[.!? ]*",frustration,re.I))
    frustrated=bool(eligible and frustration and len(frustration.split())<=25 and
                    frustration in current and not bare_uncertainty)
    if recorded:
        grounded=bool(state.get('last_response_outcome_grounded'))
        frustrated=bool(state.get('last_response_frustration'))
    elif same and grounded and outcome=='unsuccessful':
        count+=1
    elif same and grounded and outcome=='successful':
        count=0
    due=frustrated or count>=UNSUCCESSFUL_RESPONSE_LIMIT
    return {'unsuccessful_responses':count,'frustration_present':frustrated,
            'outcome_grounded':grounded,'automatic_guidance_due':due,
            'automatic_reason':'frustration' if frustrated else 'three_unsuccessful_responses' if due else 'none'}


def record_response_progress(assessment,state,message=''):
    progress=guidance_progress(assessment,state,message)
    state.update(response_progress_focus=[assessment.criterion,assessment.focus_id],
                 unsuccessful_response_count=progress['unsuccessful_responses'],
                 response_progress_version=state.get('version',0),
                 last_response_frustration=progress['frustration_present'],
                 last_response_outcome_grounded=progress['outcome_grounded'])
    return progress


def hint_due(assessment,state,same_issue=None,repeated=False,message=''):
    # Compatibility parameters are deliberately irrelevant to this gate.
    return guidance_progress(assessment,state,message)['automatic_guidance_due']


def thinking_policy(assessment,state,message,move):
    """One shared gate for clear hints, diagnosis and revealing repair locations."""
    key=[assessment.criterion,assessment.focus_id]
    same_issue=state.get('progress_focus')==key and assessment.progress_status!='new'
    opportunities=state.get('thinking_opportunity_count',0) if same_issue else 0
    repeated=bool(same_issue and assessment.current_question_target.strip() and
                  assessment.current_question_target.strip()==state.get('last_question_target'))
    requested=revision_requested(assessment,state,message)
    progress=guidance_progress(assessment,state,message)
    uncertainty=learner_uncertainty(assessment,state,message)
    explicit_hint=hint_requested(state,message)
    direct=direct_help_requested(message)
    hint_allowed=bool(explicit_hint or requested or uncertainty or progress['automatic_guidance_due'])
    ready=bool(move=='propose_revision_plan' and assessment.progress_status!='new' and assessment.ready_for_revision and
               ready_evidence(assessment,state,message))
    prior=max(0,state.get('hint_count',0)) if same_issue else 0
    reason=('explicit_hint' if explicit_hint else 'explicit_revision' if requested else
            'learner_uncertainty' if uncertainty else progress['automatic_reason'] if progress['automatic_guidance_due'] else
            'grounded_readiness' if ready else 'none')
    return {'opportunities_offered':opportunities,**progress,'hint_allowed':hint_allowed,
            'assistance_reason':reason,'prior_guidance_count':prior,
            'guidance_level':'concrete_step' if direct or prior else 'focused_cue',
            'guidance_question_mode':'direct_statement' if direct else 'focused_application' if uncertainty and not prior else 'optional_application',
            'repair_instruction_allowed':bool(requested or ready or (move=='provide_hints_guidance' and hint_allowed))}


def disclosure_policy(assessment,state,message,move):
    """Permission is a ceiling: focused assistance never means a full solution."""
    thinking=thinking_policy(assessment,state,message,move)
    ready=bool(move=='propose_revision_plan' and ready_evidence(assessment,state,message))
    reason=thinking['assistance_reason']
    bounded=bool(reason!='none' and move in {'provide_hints_guidance','propose_revision_plan'})
    ideas=[]
    for quote in (diagnosis_policy(assessment,state,message,move)['learner_evidence'],
                  assessment.readiness_evidence if ready else '',
                  assessment.revision_understanding_evidence if revision_understanding_grounded(assessment,state) else ''):
        if quote and quote not in ideas:ideas.append(quote)
    review_diagnosis=failed_revision_diagnosis(assessment,state)
    return {'max_new_conceptual_steps':1 if bounded or review_diagnosis else 0,'full_solution_allowed':False,
            'preserve_learner_decisions':True,'grounded_learner_ideas':ideas,
            'assistance_reason':'unsuccessful_revision_diagnosis' if reason=='none' and review_diagnosis else reason,
            'diagnosis_only':review_diagnosis and not bounded,'editor_access_is_not_conceptual_mastery':True}


def ready_evidence(assessment,state,message):
    """Accept reasoning already established in this issue; do not re-test it."""
    since=state.get('thinking_started_at',0)
    key=[assessment.criterion,assessment.focus_id]
    if not since or state.get('thinking_focus')!=key or state['version']<=since:
        return False
    quote=assessment.readiness_evidence.strip()
    contributions=[message]+[t['student'] for t in state['turns'] if t['version']>since]
    return bool(quote and len(quote.split())<=25 and any(quote in s for s in contributions))


def diagnosis_policy(assessment,state,message,move):
    """A prior answer about another feature cannot unlock a new diagnosis."""
    key=[assessment.criterion,assessment.focus_id]
    since=state.get('issue_check_started_at',0) if state.get('issue_check_focus')==key else state.get('accuracy_started_at',0)
    checked=(state.get('issue_check_focus')==key or state.get('accuracy_focus')==key) and bool(since) and state['version']>since and assessment.progress_status!='new'
    quote=assessment.learner_diagnosis_evidence.strip()
    contributions=[message]+[t['student'] for t in state['turns'] if t['version']>since]
    vague=bool(re.fullmatch(r'(?:yes|yeah|yep|no|nope|right|correct|both|one|maybe|i agree|i think so)[.!? ]*',quote,re.I))
    grounded=bool(checked and quote and not vague and len(quote.split())<=25 and any(quote in s for s in contributions))
    thinking=thinking_policy(assessment,state,message,move)
    requested=hint_requested(state,message) or (thinking['repair_instruction_allowed'] and (
        move=='propose_revision_plan' or revision_requested(assessment,state,message)))
    guidance=move=='provide_hints_guidance' and thinking['hint_allowed'] and (checked or thinking['automatic_guidance_due'])
    review_failure=failed_revision_diagnosis(assessment,state)
    return {'allowed':bool(move!='press_for_accuracy' and (grounded or requested or guidance or review_failure)),
            'learner_evidence':quote if grounded else '', 'current_issue_checked':checked,
            'failed_revision_diagnosis_allowed':review_failure}


def select_move(assessment,state,trigger,message=''):
    """Support thinking without trapping learners in a question loop."""
    if assessment.closing_requested:return 'invite_dialogue'
    if trigger=='submission':return 'recognize_strengths'
    if revision_requested(assessment,state,message):
        return 'provide_hints_guidance' if state.get('edit_enabled') else 'propose_revision_plan'
    review=revision_review_policy(assessment,state,trigger)
    if review['active']:
        if not current_mismatch(assessment) and not assessment.ambiguities and assessment.next_focus_kind=='none':
            return 'invite_dialogue'
        return thinking_move(assessment,state,message=message)
    if state.get('awaiting_revision_reason'):
        same_issue=state.get('progress_focus')==[assessment.criterion,assessment.focus_id] and assessment.progress_status!='new'
        return 'provide_hints_guidance' if hint_requested(state,message) or learner_uncertainty(assessment,state,message) or hint_due(assessment,state,same_issue,message=message) else 'invite_elaboration_reasoning'
    if hint_requested(state,message):return 'provide_hints_guidance'
    if learner_uncertainty(assessment,state,message):return 'provide_hints_guidance'
    if guidance_progress(assessment,state,message)['frustration_present']:return 'provide_hints_guidance'
    reviewed=trigger in {'revision','workspace-complete'} or state.get('_reason_completed',False)
    gap=current_mismatch(assessment)
    if reviewed and assessment.revision_resolved and not gap and not assessment.ambiguities:
        return 'invite_dialogue'
    key=[assessment.criterion,assessment.focus_id]
    same_issue=state.get('progress_focus')==key and assessment.progress_status!='new'
    grounded_ready=bool(not state.get('edit_enabled') and assessment.ready_for_revision and
                        gap and not assessment.ambiguities and assessment.progress_status!='new' and
                        ready_evidence(assessment,state,message))
    if hint_due(assessment,state,same_issue,message=message):
        return 'provide_hints_guidance'
    if assessment.goal_unclear:return 'clarify_goals'
    checked=(state.get('issue_check_focus')==key or state.get('accuracy_focus')==key or state.get('review_support_focus')==key) and assessment.progress_status!='new'
    if assessment.next_focus_kind=='clarification' or (assessment.ambiguities and not gap):
        if not checked:return meaning_moves(assessment,state,message,initial=True)[0]
    elif gap and (reviewed or not checked):
        # Evidence inspection for a fresh mismatch comes before general support.
        return 'press_for_accuracy'
    repeated=bool(same_issue and assessment.current_question_target.strip() and
                  assessment.current_question_target.strip()==state.get('last_question_target'))
    if grounded_ready:
        return 'propose_revision_plan'
    if (assessment.next_focus_kind=='none' and not gap and not assessment.ambiguities and (
            (state.get('thinking_started_at') and state['version']>state['thinking_started_at']) or
            (state.get('turns') and state['turns'][-1].get('talk_move')=='invite_dialogue'))):
        return 'invite_dialogue'
    if hint_due(assessment,state,same_issue,repeated,message=message):return 'provide_hints_guidance'
    return thinking_move(assessment,state,repeated,message)


def select_moves(assessment,state,trigger,message=''):
    """Keep the primary API while recording an evidenced two-intent sequence."""
    move=select_move(assessment,state,trigger,message)
    return meaning_moves(assessment,state,message,initial=True) if move in MEANING_MOVES else [move]


def meaning_move_in_support(assessment,state,trigger=None):
    """Distinguish the first check from local meaning work after that check."""
    if revision_review_policy(assessment,state,trigger)['active']:return True
    if assessment.progress_status=='new':return False
    key=[assessment.criterion,assessment.focus_id]
    if state.get('review_support_focus')==key:return True
    if state.get('thinking_focus')==key and state.get('thinking_started_at'):return True
    for focus,started in (('issue_check_focus','issue_check_started_at'),('accuracy_focus','accuracy_started_at')):
        if state.get(focus)==key and state.get(started) and state.get('version',0)>state[started]:return True
    return False


def update_progress(state,assessment,move,reply=None):
    move=canonical_talk_move(move)
    meaning_support=move in MEANING_MOVES and meaning_move_in_support(assessment,state)
    record_response_progress(assessment,state)
    review=revision_review_policy(assessment,state)
    key=[assessment.criterion,assessment.focus_id]
    if (assessment.progress_status=='new' or key!=state.get('progress_focus') or
            (move=='press_for_accuracy' and key!=state.get('accuracy_focus'))):
        # Recognition/clarification turns are not failed attempts at this check.
        state.update(progress_focus=key,issue_turn_count=0,thinking_opportunity_count=0,hint_count=0,last_question_target='',text_hint_focus=[],
                     accuracy_focus=[],accuracy_started_at=0,thinking_focus=[],thinking_started_at=0,
                     issue_check_focus=[],issue_check_started_at=0,review_support_focus=[],review_outcome='not_reviewed')
    state['issue_turn_count']+=1
    target=assessment.current_question_target.strip()
    repeated=bool(target and target==state.get('last_question_target'))
    invitation=bool(reply and (reply.content.count('?') or THINKING_INVITATION.search(reply.content)))
    if move in {'press_for_accuracy',*THINKING_MOVES} and invitation and not repeated:
        state['thinking_opportunity_count']=state.get('thinking_opportunity_count',0)+1
    state['last_question_target']=target
    if move=='provide_hints_guidance':
        state['hint_count']+=1
        state['text_hint_focus']=key
    if move=='press_for_accuracy':state.update(accuracy_focus=key,accuracy_started_at=state['version'])
    if move=='press_for_accuracy' or (move in MEANING_MOVES and not meaning_support and
            (state.get('issue_check_focus')!=key or not state.get('issue_check_started_at'))):
        state.update(issue_check_focus=key,issue_check_started_at=state['version'])
    if review['active']:
        state.update(issue_check_focus=key,issue_check_started_at=state['version'],
                     review_support_focus=key,review_outcome=review['outcome'])
    if move in {'press_for_accuracy','invite_dialogue'} or (move in MEANING_MOVES and not meaning_support):
        state.update(thinking_focus=[],thinking_started_at=0)
        if move=='invite_dialogue':state.update(accuracy_focus=[],accuracy_started_at=0)
    elif move in SUPPORT and not state.get('awaiting_revision_reason') and (
            not state['thinking_started_at'] or state['thinking_focus']!=key):
        state.update(thinking_focus=key,thinking_started_at=state['version'])
