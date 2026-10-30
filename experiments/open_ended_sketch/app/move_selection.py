"""Ground the Tutor's move candidates in the exact context it received.

The fast Tutor supplies the teaching judgment and response in one call. These
checks enforce source, completeness and candidate priority, without rewriting a
reply or treating task/tutor statements as demonstrated learner understanding.
"""
import re

from learner_model import ACKNOWLEDGMENT, BARE_UNCERTAINTY


MEANING_MOVES = {'revoice', 'ask_for_clarification'}
ORDERED_SUPPORT = MEANING_MOVES | {
    'prompt_reflection', 'build_on_prior_knowledge', 'invite_elaboration_reasoning'}
SUPPORT_ORDER = ['revoice', 'ask_for_clarification', 'prompt_reflection',
                 'build_on_prior_knowledge', 'invite_elaboration_reasoning']
EMPTY_IDEA = re.compile(
    r"(?:no|nope|yep|maybe|i (?:still )?(?:don[’';]?t|do not) know|"
    r"(?:still )?don[’';]?t know|(?:还是|仍然)?(?:不知道|不懂|不会))[.!?。！？，,\s]*", re.I)
NO_ANSWER = re.compile(
    r"(?:i(?:['’]m| am| feel) (?:still )?(?:not sure|unsure|stuck|confused)|"
    r"i (?:still )?(?:cannot|can['’]t|can not) (?:answer|work it out|figure it out)|"
    r"i (?:still )?(?:do not|don['’]t) know(?: (?:the answer|what to do))?|"
    r"我(?:还是|仍然)?(?:不确定|不知道|不会|不懂|答不出来|很困惑))[.!?。！？，,\s]*", re.I)
REQUEST_ONLY = re.compile(
    r"(?:i (?:need|want|would like) (?:a |some |another )?(?:hint|help|guidance|an explanation)|"
    r"(?:can|could|would) you (?:please )?(?:help|explain|show|tell|give)\b[^.!?;\n]*|"
    r"(?:can|could|may) i (?:please )?(?:have|get) (?:a |another )?hint|"
    r"please (?:help|explain|show|tell)\b[^.!?;\n]*|"
    r"(?:how|where) (?:do|can|should) i\b[^.!?;\n]*)[.!?。！？，,\s]*", re.I)
MIXED_ANSWER = re.compile(r"\b(?:i (?:think|believe|guess|know)|but|because|since)\b", re.I)
REVISION_REQUEST = re.compile(
    r"^\s*(?:please\s+)?(?:"
    r"(?:can|could|may)\s+i\s+(?:please\s+)?(?:revise|edit|change|redraw|draw)\b|"
    r"i\s+(?:want|need|would like)\s+to\s+(?:revise|edit|change|redraw|draw)\b|"
    r"i\s+need\s+(?:a\s+)?revision\b|"
    r"(?:begin|start)\s+(?:a\s+|my\s+|the\s+)?revision\b|"
    r"let\s+me\s+(?:revise|edit|change|redraw|draw)\b|"
    r"help\s+me\s+(?:revise|edit|change|redraw|draw)\b|"
    r"(?:我想|我要|我需要|让我|可以让我|我可以)(?:开始)?(?:修改|改图|修订|重画))", re.I)


def _brief(value, limit=35):
    return isinstance(value, str) and bool(value.strip()) and len(value.split()) <= limit


def substantive_quote(value):
    """A bare agreement or inability supplies no concept or explanation."""
    return bool(_brief(value, 25) and not any(pattern.fullmatch(value.strip())
                for pattern in (ACKNOWLEDGMENT, BARE_UNCERTAINTY, EMPTY_IDEA)))


def _learner_source_items(context):
    """Stable references to learner text already present in the Tutor request."""
    values = [('student_message', context.get('student_message', '')),
              ('latest_explanation', context.get('latest_explanation', ''))]
    values += [(f'recent_dialogue[{index}].student', item.get('student', ''))
               for index, item in enumerate(context.get('recent_dialogue', [])) if isinstance(item, dict)]
    memory = context.get('learner_model', {})
    values += [(f'learner_model.observations[{index}].evidence', item.get('evidence', ''))
               for index, item in enumerate(memory.get('observations', []))
               if isinstance(item, dict) and item.get('source') == 'tutor_observation']
    return [(key, value) for key, value in values if isinstance(value, str)]


def learner_sources(context):
    """Only actual learner text exposed in this particular Tutor request."""
    return [value for _, value in _learner_source_items(context)]


def readiness_sources(context):
    """Source IDs select evidence; they do not certify revision readiness."""
    return {key: value for key, value in _learner_source_items(context)
            if value.strip() and not any(pattern.fullmatch(value.strip())
                for pattern in (ACKNOWLEDGMENT, BARE_UNCERTAINTY, EMPTY_IDEA))}


def revision_readiness_grounded(evidence, context):
    if evidence.readiness_source_id:
        return evidence.readiness_source_id in readiness_sources(context) and not evidence.readiness_evidence.strip()
    return grounded_learner_quote(evidence.readiness_evidence, context)


def canonical_move_evidence(turn, context):
    """Recover only learner quotations literally present in claimed evidence."""
    result = turn.model_copy(deep=True)
    evidence = result.move_evidence
    value = evidence.readiness_evidence.strip()
    if (result.talk_moves != ['propose_revision_plan'] or evidence.readiness_source_id
            or grounded_learner_quote(value, context) or not value):
        return result
    candidates = [value.strip('"“”')]
    candidates += re.findall(r'[“"]([^”"]+)[”"]', value)
    # A model may join several genuine learner turns. Retain one existing
    # contiguous source, rather than invent a quote from its summary.
    candidates += [source.strip() for source in learner_sources(context)
                   if source.strip() and source.strip() in value]
    for candidate in candidates:
        for quote in (candidate.strip(), candidate.strip().rstrip('.,;:!?')):
            if grounded_learner_quote(quote, context):
                evidence.readiness_evidence = quote
                return result
    return result


def grounded_learner_quote(value, context):
    return substantive_quote(value) and any(value.strip() in source for source in learner_sources(context))


def activation_sources(context):
    """Context establishes recall relevance, never learner mastery."""
    memory = context.get('learner_model', {})
    task = memory.get('task', {})
    formal = (memory.get('evaluation') or {}).get('result', {})
    values = learner_sources(context) + [task.get('text', ''), formal.get('task_summary', '')]
    if context.get('interaction', {}).get('goals_configured'):
        values += [item.get('label', '') for item in task.get('criteria', []) if isinstance(item, dict)]
    scene = context.get('current_diagram', {})
    values += [item.get('verbatim_text', '') for group in ('objects', 'relations')
               for item in scene.get(group, []) if isinstance(item, dict)]
    return [value for value in values if isinstance(value, str)]


def revoice_eligible(evidence, context):
    return _brief(evidence.revoice_need) and grounded_learner_quote(evidence.revoice_evidence, context)


def clarification_eligible(evidence, context=None):
    return _brief(evidence.clarification_need)


def reflection_eligible(evidence, context):
    return bool(all(_brief(value) for value in (
        evidence.reflection_target, evidence.reflection_reference, evidence.reflection_need))
        and evidence.reflection_reference_source != 'none'
        and grounded_learner_quote(evidence.reflection_evidence, context))


def prior_knowledge_eligible(evidence, context):
    if not _brief(evidence.prior_knowledge_connection):
        return False
    if evidence.prior_knowledge_mode == 'activate':
        quote = evidence.prior_knowledge_activation_evidence
        # Recall context cannot be recorded as a student's demonstrated idea.
        return bool(not evidence.prior_knowledge_evidence.strip() and substantive_quote(quote)
                    and any(quote.strip() in source for source in activation_sources(context)))
    return grounded_learner_quote(evidence.prior_knowledge_evidence, context)


def eligible_support_moves(evidence, context):
    """All grounded candidates in priority order, with reasoning as default."""
    result = []
    for move, check in (('revoice', revoice_eligible), ('ask_for_clarification', clarification_eligible),
                        ('prompt_reflection', reflection_eligible), ('build_on_prior_knowledge', prior_knowledge_eligible)):
        if check(evidence, context):
            result.append(move)
    return result + ['invite_elaboration_reasoning']


def preferred_support_moves(evidence, context):
    eligible = eligible_support_moves(evidence, context)
    meaning = [move for move in eligible if move in MEANING_MOVES]
    return meaning or eligible[:1]


def revision_requested(context):
    interaction = context.get('interaction', {})
    return bool(interaction.get('intent') == 'begin_revision' or interaction.get('edit_enabled')
                or REVISION_REQUEST.match(context.get('student_message', '')))


def validate_move_selection(turn, context):
    """Return a contract error; never substitute a different move or response."""
    evidence = turn.move_evidence
    selected = turn.talk_moves
    move = selected[0]
    interaction = context.get('interaction', {})
    message = context.get('student_message', '').strip()
    request_only = REQUEST_ONLY.fullmatch(message) and not MIXED_ANSWER.search(message)
    affect_only = bool(interaction.get('frustration_evidence') and
                       message.strip('.!?。！？，, ') == interaction['frustration_evidence'].strip('.!?。！？，, '))
    if turn.progress == 'difficulty' and (request_only or affect_only or any(pattern.fullmatch(message)
            for pattern in (ACKNOWLEDGMENT, BARE_UNCERTAINTY, EMPTY_IDEA, NO_ANSWER))):
        return 'Count an actual incorrect current-issue answer as difficulty; uncertainty or no answer alone is not an incorrect attempt.'
    if interaction.get('hint_button_requested') and move != 'provide_hints_guidance':
        return 'An accepted hint request requires provide_hints_guidance.'
    third_difficulty = interaction.get('consecutive_difficulties', 0) >= 2 and turn.progress == 'difficulty'
    if move == 'provide_hints_guidance' and not (
            interaction.get('hint_button_requested') or interaction.get('frustration_expressed') or third_difficulty):
        return 'Use Guidance only for the actual hint-button event, clear current frustration, or the third incorrect same-issue answer. Chat requests and uncertainty need other scaffolded moves.'
    requested_revision = move == 'propose_revision_plan' and revision_requested(context)
    finishing = move == 'invite_dialogue' and turn.stage == 'complete'
    goal_clarification = move == 'clarify_goals' and interaction.get('process_phase') == 'goals'
    if third_difficulty and move != 'provide_hints_guidance' and not (requested_revision or finishing or goal_clarification):
        return 'The third consecutive same-issue difficulty requires provide_hints_guidance.'
    checks = {'revoice': revoice_eligible, 'ask_for_clarification': clarification_eligible,
              'prompt_reflection': reflection_eligible, 'build_on_prior_knowledge': prior_knowledge_eligible}
    for item in selected:
        if item in checks and not checks[item](evidence, context):
            return 'Provide the current need and grounded move evidence for ' + item + '.'
    if move == 'invite_elaboration_reasoning' and not _brief(evidence.reasoning_gap or turn.question_target):
        return 'Identify one unanswered reasoning gap.'
    if move == 'propose_revision_plan' and not (revision_requested(context)
            or revision_readiness_grounded(evidence, context)):
        return 'Ground revision readiness in learner reasoning or a current revision request.'
    if interaction.get('expected_stage') == 'thinking-dialogue' and move in ORDERED_SUPPORT:
        if selected != preferred_support_moves(evidence, context):
            return 'Select the first eligible support need: meaning, reflection, prior knowledge, then reasoning.'
    return ''
