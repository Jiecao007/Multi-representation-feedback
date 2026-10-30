"""Python-owned execution of the feedback process; no model calls or prose edits."""
from copy import deepcopy
import re

from move_selection import REVISION_REQUEST

VERSION = 'feedback-process-v1'
GUIDANCE_POLICY_VERSION = 'strict-guidance-v2'
MEANING = ['revoice', 'ask_for_clarification']
QUESTION_SUPPORT = [*MEANING, 'prompt_reflection', 'build_on_prior_knowledge',
                    'invite_elaboration_reasoning']
SUPPORT = [*QUESTION_SUPPORT, 'propose_revision_plan',
           'clarify_goals', 'invite_dialogue']
FINISH = re.compile(
    r"^\s*(?:please\s+)?(?:stop|quit|exit|finish|end(?: the session)?|"
    r"i(?:['’]m| am) (?:finished|done)|i(?: have)? finished|"
    r"i (?:want|need|would like) to (?:stop|quit|exit|finish|end)(?: now| here| the session)?|"
    r"let['’]s (?:stop|finish|end)(?: now| here)?|"
    r"(?:我想|我要|我需要|可以)?(?:结束|退出|停止)(?:了|学习|对话)?|我(?:已经)?完成了)"
    r"[.!?。！？，,\s]*$", re.I)
NO_QUESTIONS = re.compile(
    r"\s*(?:no(?:[,.]?\s*(?:thanks|thank you))?|no (?:more|further) questions|"
    r"i have no (?:more |further )?questions|i (?:don't have|do not have) (?:any )?(?:more |further )?questions|"
    r"that['’]s all|nothing else|没有(?:了|问题了)?|不用了|没有其他问题(?:了)?)"
    r"[.!?。！？，,\s]*", re.I)
HELP = re.compile(
    r"\bi (?:need|want|would like) (?:a |some |another )?(?:hint|help|guidance|an explanation)\b|"
    r"\bplease\s+(?:help(?: me)?|(?:directly )?tell me|explain|show me)\b|"
    r"\b(?:can|could|would) you (?:please )?(?:help|explain|show|tell|give me (?:a |an |another |some )?(?:hint|example|explanation|help))\b|"
    r"\b(?:can|could|may) i (?:please )?(?:have|get) (?:a |another )?hint\b|"
    r"^\s*(?:how|where) (?:do|can|should) i\b|"
    r"(?:^\s*|[.!?;,]\s*)(?:help(?: me)?|(?:directly )?tell me|explain|show me)\b|"
    r"\bdirectly tell me\b|"
    r"请(?:直接)?(?:告诉|解释|提示)|给我(?:一个)?提示|我需要(?:帮助|提示)", re.I)
FRUSTRATION = re.compile(
    r"\bi(?:['’]m| am| feel) (?:so |very |really )?frustrated\b|"
    r"\b(?:this|it)(?: is|['’]s) (?:so |very |really )?frustrating\b|"
    r"\bi (?:give up|am giving up)\b|\bi(?:['’]m| am) (?:so |really )?fed up\b|"
    r"\bi (?:can['’]t|cannot) take (?:this|it) anymore\b|"
    r"我(?:很|好|非常|感到)?(?:沮丧|挫败)|我(?:要|想)?放弃了|我受不了了|我快崩溃了", re.I)
QUOTED_TEXT = re.compile(r'"[^"\n]*"|“[^”\n]*”|「[^」\n]*」|『[^』\n]*』')
REPORTED_AFFECT = re.compile(
    r"\b(?:if|whether|suppose|imagine|says?|saying|said|tells?|told|thinks?|thought|"
    r"writes?|wrote|example|quote|not that)\b|(?:他说|她说|你说|据说|不是说|如果|假如|比如|例如)", re.I)
UNCERTAINTY = re.compile(
    r"\b(?:i\s+)?(?:still\s+)?(?:don[’';]?t|do not) (?:know|understand|remember)\b|"
    r"\bi(?:['’]m| am| feel) (?:still )?(?:not sure|unsure|stuck|confused)\b|"
    r"\b(?:not sure|unsure|no idea|maybe)\b|"
    r"\b(?:i |we )?(?:still )?(?:cannot|can[’']t|can not)\b|"
    r"\b(?:this|it)(?: is|['’]s) confusing\b|"
    r"我(?:还是|仍然)?(?:不知道|不会|不懂|不确定)|(?:还是|仍然)?不知道|不太确定|"
    r"我(?:很|好|有点)?困惑", re.I)
GOALS = re.compile(
    r'\b(?:goals?|requirements?|criteria|instructions?)\b|'
    r'\b(?:understand|explain|clarify) (?:the |this )?task\b|'
    r'\bwhat (?:am i|are we) (?:supposed|expected) to\b|目标|要求|任务的意思|要做什么', re.I)


def frustration_evidence(message):
    """Recognize a clear current affective statement, never a quoted example."""
    unquoted = QUOTED_TEXT.sub(lambda match: ' ' * len(match.group()), message)
    for match in FRUSTRATION.finditer(unquoted):
        prefix = re.split(r'[.!?;。！？；]', unquoted[:match.start()])[-1]
        if not REPORTED_AFFECT.search(prefix):
            return message[match.start():match.end()]
    return ''


def _formal(state):
    return (state.get('learner_model', {}).get('evaluation') or {}).get('result', {})


def _pending(formal):
    parts = [deepcopy(item) for item in formal.get('missing_parts', []) if isinstance(item, dict)]
    if parts:
        return parts
    # An incomplete/uncertain criterion cannot silently become a completed task.
    for row in formal.get('criteria', []):
        if row.get('status') not in {'established', 'not-requested'} or row.get('level') == 'uncertain':
            criterion = row['criterion']
            return [dict(id='criterion:' + criterion, criterion=criterion,
                         description='Clarify the remaining requirement for this criterion.',
                         evidence=row.get('evidence', ''), focus_ids=[])]
    return []


def ensure_process(state):
    """Migrate saved runtime metadata without re-evaluating historical work."""
    if state.get('guidance_policy_version') != GUIDANCE_POLICY_VERSION:
        # Earlier streaks could include bare inability. Do not reinterpret them
        # as incorrect answers, or reconstruct workflow flags from old labels.
        state['guidance_counter_migration'] = dict(
            from_version=state.get('guidance_policy_version', 'legacy'),
            prior_count=state.get('consecutive_difficulties', 0),
            reason='Reset the legacy difficulty streak; only incorrect answers count under strict-guidance-v2.')
        state['consecutive_difficulties'] = 0
        state['guidance_policy_version'] = GUIDANCE_POLICY_VERSION
    workflow = state.get('workflow')
    if isinstance(workflow, dict) and workflow.get('version') == VERSION:
        return workflow
    pending = _pending(_formal(state))
    active = next((item for item in pending if item['id'] == state.get('current_issue_id')),
                  pending[0] if pending else None)
    stage = state.get('stage', 'recognition')
    workflow = dict(version=VERSION, active_issue=deepcopy(active),
                    check_issued=stage not in {'recognition'},
                    review_clarification_pending=False, closing_invited=stage == 'dialogue',
                    finished=stage == 'complete', review_outcome='not_reviewed', review_evidence='')
    state['workflow'] = workflow
    state['current_issue_id'] = active['id'] if active else ''
    return workflow


def active_issue(state):
    return deepcopy(ensure_process(state).get('active_issue'))


def review_issue_status(result, addressed_issue=None, initial=False):
    """Keep local revision success separate from broader issue completion.

    Saved legacy evaluations have no independent issue status. Infer their
    routing conservatively from the formal remaining gaps, without editing
    historical results or inferring that a locally correct edit finishes a task.
    """
    value = result.model_dump() if hasattr(result, 'model_dump') else result
    if initial or not addressed_issue or value.get('revision_outcome', 'not_reviewed') == 'not_reviewed':
        return 'not_reviewed'
    status = value.get('addressed_issue_status', 'not_reviewed')
    if status != 'not_reviewed':
        return status
    outcome = value.get('revision_outcome')
    if outcome == 'uncertain':
        return 'uncertain'
    if outcome == 'unsuccessful' or any(item.get('id') == addressed_issue['id']
                                      for item in value.get('missing_parts', [])):
        return 'unresolved'
    return 'resolved'


def record_evaluation_process(state, result, initial=False, addressed_issue=None, revision_target=None):
    """Route using Evaluation's result; preserve its formal assessment unchanged."""
    workflow = ensure_process(state)
    value = result.model_dump() if hasattr(result, 'model_dump') else result
    pending = _pending(value)
    outcome = value.get('revision_outcome', 'not_reviewed')
    issue_status = review_issue_status(value, addressed_issue, initial)
    if initial or (outcome == 'successful' and issue_status in {'resolved', 'not_reviewed'}):
        current = pending[0] if pending else None
    else:
        current = next((item for item in pending if addressed_issue and item['id'] == addressed_issue['id']),
                       deepcopy(addressed_issue))
        if current is None:
            current = pending[0] if pending else dict(
                id='review:' + str(state['drawing_version']), criterion=state['criteria'][0]['id'],
                description='Clarify the effect of this submitted revision.',
                evidence=value.get('revision_evidence', ''), focus_ids=[])
    if current:
        ids = {item['id'] for group in ('objects', 'relations') for item in state['committed']['scene'][group]}
        current['focus_ids'] = [item for item in current.get('focus_ids', []) if item in ids]
    old_id = (workflow.get('active_issue') or {}).get('id', '')
    new_id = (current or {}).get('id', '')
    if old_id != new_id or (not initial and outcome == 'successful'):
        state['consecutive_difficulties'] = state['guidance_count'] = 0
    workflow.update(active_issue=deepcopy(current), check_issued=not initial,
                    review_clarification_pending=not initial and (outcome == 'uncertain' or issue_status == 'uncertain'),
                    closing_invited=False, finished=False, review_outcome=outcome,
                    addressed_issue_status=issue_status,
                    review_status_source='evaluation' if value.get('addressed_issue_status') not in {None, 'not_reviewed'} else 'legacy_inferred',
                    reviewed_revision_target=deepcopy(revision_target),
                    review_evidence=value.get('revision_evidence', ''))
    state['current_issue_id'] = new_id


def process_contract(state, message, trigger, intent, reviewed=False):
    """Define the allowed response boundary before the single Tutor call."""
    workflow = ensure_process(state)
    current = workflow.get('active_issue')
    resolved = bool(_formal(state)) and not current and not _pending(_formal(state))
    exit_requested = bool(FINISH.fullmatch(message) or
                          (resolved and workflow.get('closing_invited') and NO_QUESTIONS.fullmatch(message)))
    explicit_revision = bool(intent == 'begin_revision' or REVISION_REQUEST.match(message))
    revision = bool(explicit_revision or state.get('edit_enabled'))
    hint_button = trigger == 'message' and intent == 'hint'
    frustration = frustration_evidence(message)
    # Asking for an example/explanation in chat asks for more scaffolding, not
    # permission to disclose a method. Only the actual button event is a hint.
    support_requested = bool(HELP.search(message))
    help_requested = bool(hint_button or frustration)
    uncertainty = bool(UNCERTAINTY.search(message))
    goal_requested = bool(intent != 'hint' and GOALS.search(message) and (
        support_requested or uncertainty or re.match(r'^\s*(?:what|which|how|why)\b', message, re.I)
        or re.search(r'\b(?:unclear|confusing)\b|不清楚|不理解|不懂|什么', message, re.I)))
    check_required = bool(current and not workflow.get('check_issued'))
    clarify_review = bool(current and workflow.get('review_clarification_pending'))
    if trigger == 'submission':
        phase, stage, stages, moves = 'highlight', 'recognition', ['recognition'], ['recognize_strengths']
    elif exit_requested:
        phase, stage, stages, moves = 'complete', 'complete', ['complete'], ['invite_dialogue']
    elif help_requested:
        phase, stage, stages, moves = 'help', 'thinking-dialogue', ['thinking-dialogue', 'revision-planning'], ['provide_hints_guidance']
    elif explicit_revision:
        phase, stage, stages, moves = 'revision', 'revision-planning', ['revision-planning', 'thinking-dialogue'], ['propose_revision_plan']
    elif workflow.get('finished') and not state.get('edit_enabled'):
        phase, stage, stages, moves = 'complete', 'complete', ['complete'], ['invite_dialogue']
    elif goal_requested:
        stage = 'inquiry' if check_required else 'thinking-dialogue' if current else 'dialogue'
        phase, stages, moves = 'goals', [stage], ['clarify_goals']
    elif revision:
        phase, stage, stages, moves = 'editing', 'thinking-dialogue', ['thinking-dialogue', 'revision-planning'], SUPPORT
    elif resolved:
        phase, stage, stages = 'dialogue', 'dialogue', ['dialogue']
        moves = ['invite_dialogue'] if not workflow.get('closing_invited') else [
            'invite_dialogue', 'clarify_goals', *MEANING,
            'invite_elaboration_reasoning', 'build_on_prior_knowledge', 'prompt_reflection']
    elif clarify_review:
        phase, stage, stages, moves = 'review-clarification', 'thinking-dialogue', ['thinking-dialogue'], MEANING
    elif (uncertainty or support_requested) and current:
        phase, stage, stages, moves = 'support', 'thinking-dialogue', ['thinking-dialogue'], QUESTION_SUPPORT
    elif check_required:
        phase, stage, stages = 'check', 'inquiry', ['inquiry']
        moves = ['press_for_accuracy', *MEANING, 'clarify_goals', 'invite_dialogue']
    else:
        phase, stage, stages, moves = 'support', 'thinking-dialogue', ['thinking-dialogue', 'revision-planning'], SUPPORT
    # Uncertainty calls for a smaller question before a supplied explanation or
    # repair, including when a revision request also asks for missing knowledge.
    # A formally uncertain review keeps its meaning-check priority.
    question_support = bool((uncertainty or support_requested) and not help_requested
                            and phase in {'support', 'editing', 'revision', 'review-clarification'})
    if question_support and phase != 'review-clarification':
        stage, stages, moves = 'thinking-dialogue', ['thinking-dialogue'], QUESTION_SUPPORT
    # Classify the current contribution in the same Tutor call. Guidance is
    # expressible at two prior difficulties, then validated against current difficulty.
    guidance_requested = bool(help_requested and phase in {'help', 'revision'})
    third_difficulty_available = bool(state.get('consecutive_difficulties', 0) >= 2
                                      and phase in {'check', 'support', 'editing', 'revision', 'review-clarification'})
    if guidance_requested or third_difficulty_available:
        moves = list(dict.fromkeys([*moves, 'provide_hints_guidance']))
        stages = list(dict.fromkeys([*stages, 'thinking-dialogue', 'revision-planning']))
    return dict(process_phase=phase, expected_stage=stage, allowed_stages=stages, allowed_moves=list(moves),
                guidance_policy_version=GUIDANCE_POLICY_VERSION,
                active_issue_id=(current or {}).get('id', ''), all_issues_resolved=resolved,
                exit_requested=exit_requested, help_requested=guidance_requested, revision_requested=revision,
                hint_button_requested=hint_button, support_requested=support_requested,
                frustration_expressed=bool(frustration), frustration_evidence=frustration,
                uncertainty_expressed=uncertainty, uncertainty_question_support=question_support,
                support_question_scaffold='high' if uncertainty or support_requested or state.get('consecutive_difficulties', 0) else 'focused',
                goal_clarification_requested=phase == 'goals',
                check_required=phase == 'check', review_clarification_required=phase == 'review-clarification',
                closing_invited=bool(workflow.get('closing_invited')), review_outcome=workflow.get('review_outcome'),
                addressed_issue_status=workflow.get('addressed_issue_status', 'not_reviewed'),
                reviewed_revision_target=deepcopy(workflow.get('reviewed_revision_target')) if reviewed else None,
                review_evidence=workflow.get('review_evidence', ''), new_review=bool(reviewed))


def validate_process_turn(turn, state, context):
    interaction = context['interaction']
    if turn.issue_id != interaction['active_issue_id']:
        return 'Keep the active issue until its submitted revision is reviewed.'
    if any(move not in interaction['allowed_moves'] for move in turn.talk_moves):
        return 'Use an allowed move for the current feedback-process phase.'
    if turn.stage not in interaction['allowed_stages']:
        return 'Use an allowed stage for the current feedback-process phase.'
    if interaction['process_phase'] == 'check' and turn.talk_moves[0] in {'press_for_accuracy', *MEANING}:
        if (turn.acknowledgment + turn.content).count('?') != 1:
            return 'Ask one focused current-diagram question before entering Supporting learning.'
    if interaction.get('new_review') and interaction['review_outcome'] == 'successful' and not turn.acknowledgment.strip():
        return 'Recognize the evidenced successful correction before continuing.'
    if turn.stage == 'complete' and not (interaction['exit_requested'] or ensure_process(state).get('finished')):
        return 'Finish only when the learner requests finishing or declines further dialogue.'
    if interaction['process_phase'] == 'dialogue' and not interaction['closing_invited']:
        if turn.talk_moves != ['invite_dialogue'] or (turn.acknowledgment + turn.content).count('?') != 1:
            return 'Invite one further question when all issues have been resolved.'
    if turn.stage == 'revision-planning' and turn.talk_moves[0] not in {'propose_revision_plan', 'provide_hints_guidance'}:
        return 'Enter revision planning with a bounded plan or actionable guidance.'
    if interaction.get('uncertainty_question_support') and turn.talk_moves[0] != 'provide_hints_guidance':
        if (turn.acknowledgment + turn.content).count('?') != 1 or turn.edit_instruction or turn.next_step == 'revise':
            return 'Continue uncertainty with one focused Supporting-learning question and no supplied edit.'
    if interaction['review_clarification_required'] and interaction['process_phase'] == 'review-clarification':
        third_help = turn.talk_moves[0] == 'provide_hints_guidance' and turn.progress == 'difficulty' and interaction.get('consecutive_difficulties', 0) >= 2
        if turn.talk_moves[0] not in MEANING and not third_help:
            return 'Clarify the uncertain revision within Supporting learning.'
    if interaction['process_phase'] == 'check' and turn.talk_moves[0] == 'provide_hints_guidance':
        if turn.progress != 'difficulty' or interaction.get('consecutive_difficulties', 0) < 2:
            return 'Use the initial check unless current difficulty warrants the help exception.'
    return ''


def commit_process(state, turn, context):
    """Advance only after a validated, delivered response."""
    workflow = ensure_process(state)
    phase = context['interaction']['process_phase']
    if phase == 'check' and turn.talk_moves[0] in {'press_for_accuracy', *MEANING}:
        workflow['check_issued'] = True
    if phase == 'check' and turn.talk_moves[0] == 'provide_hints_guidance':
        workflow['check_issued'] = True
    if phase in {'help', 'revision', 'editing'}:
        workflow['check_issued'] = True
    if phase == 'support' and context['interaction'].get('uncertainty_question_support'):
        workflow['check_issued'] = True
    if phase in {'revision', 'editing'}:
        workflow['finished'] = False
    if phase == 'review-clarification' and turn.talk_moves[0] in MEANING:
        workflow['review_clarification_pending'] = False
    if phase == 'dialogue' and turn.talk_moves == ['invite_dialogue']:
        workflow['closing_invited'] = True
    if turn.stage == 'complete':
        workflow['finished'] = True
    state['stage'] = turn.stage
    state['current_issue_id'] = (workflow.get('active_issue') or {}).get('id', '')
