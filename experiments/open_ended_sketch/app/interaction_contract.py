"""Mechanical output checks; the Tutor owns instructional move selection."""
import re

EDIT_VERB = r'(?:move|place|position|adjust|align|rotate|resize|scale|extend|shorten|drag|draw|add|connect|delete|remove|edit|revise|change|reverse|flip|label|relabel|annotate|mark|erase|attach|replace|create)'
DECORATION = r'[\s\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]*'
PREFIX = r'(?:^|[.!?;,:]\s*|\bthen\s+|\band\s+)' + DECORATION + r"(?:(?:please|now|next)\s+|let['’]s\s+|go ahead and\s+|you (?:can|should)\s+)*"
COMMAND = re.compile(PREFIX + r'(?:' + EDIT_VERB + r'\b|try (?:to )?' + EDIT_VERB + r'\w*\b)', re.I)
USE_COMMAND = re.compile(PREFIX + r'use\b[^.!?;\n]{1,140}\bto\s+' + EDIT_VERB + r'\b', re.I)
TOOL_COMMAND = re.compile(PREFIX + r'''(?:use|select|choose|click|open)\s+(?:the\s+)?["'`“‘]?(?:↗\s*)?(?:Connect\b|\+\s*(?:Text|Object)\b|Edit connection\b|Save connection\b)''', re.I)
MENTAL = re.compile(r'\s*(?:(?:my|your|our|the|an?|this|that)\s+)?(?:explanation|reasoning|answer|response|idea|understanding|paragraph|sentence)\b', re.I)
NUMBER_WORD = r'(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand)'
NUMBER = (r'(?:[+\-−]?(?:\d+/\d+|(?:\d+(?:\.\d+)?|\.\d+)(?:e[+\-]?\d+)?)|'
          r'(?:(?:minus|negative|plus|positive)\s+)?' + NUMBER_WORD
          + r'(?:[-\s]+' + NUMBER_WORD + r')*|a few)')
NUMERIC_MOTION = re.compile(
    r'\s*(?:(?:from|to|by|towards?|along|through|left|right|forward|backward)\b|'
    + NUMBER + r'\s+(?:steps?|spaces?|units?|left|right|from|to|along|on)\b|'
    + NUMBER + r'(?=\s*(?:[.!?]|$)))', re.I)
NUMERIC_OPERATION = re.compile(
    r'\s*(?:' + NUMBER + r'\b|(?:these|those|both|the(?: two| three)?)\s+'
    r'(?:numbers?|integers?|values?|terms?|quantities)\b)', re.I)
HYPOTHETICAL = re.compile(r'^\s*(?:imagine|suppose|picture|think about|if\b|'
    r'(?:you|i|we|the student|the learner)\s+(?:said|proposed|wrote|suggested)\b)', re.I)


def _sentences(text):
    # A decimal point is not a sentence boundary (e.g. an endpoint at −2.5).
    return (match.group().strip() for match in re.finditer(
        r'\S[\s\S]*?(?:[.!?](?=\s|$)|\n|$)', text))


def _conceptual_operation(sentence, match):
    tail = sentence[match.end():]
    verb = re.search(r'\b(move|moving|add|adding|change|changing)\b$', match.group(), re.I)
    if not verb:
        return False
    name = verb.group().lower()
    if name in {'move', 'moving'}:
        return bool(NUMERIC_MOTION.match(tail))
    return bool(NUMERIC_OPERATION.match(tail))


def _edit_sentences(text):
    """Find actual graphical imperatives, using the same rule for all callers."""
    for sentence in _sentences(text):
        if sentence.endswith('?') or HYPOTHETICAL.match(sentence):
            continue
        for pattern in (COMMAND, USE_COMMAND, TOOL_COMMAND):
            if any(not MENTAL.match(sentence[match.end():])
                   and not _conceptual_operation(sentence, match)
                   for match in pattern.finditer(sentence)):
                yield sentence
                break


def visible_edit_command(text):
    return next(_edit_sentences(text), None) is not None


def visible_edit_instruction(text):
    """Copy one exact visible edit sentence, including its introductory phrase."""
    return next(_edit_sentences(text), '')


def scene_ids(scene):
    return {item['id'] for group in ('objects','relations') for item in scene[group]}


def validate_evaluation(result, state):
    wanted = [row['id'] for row in state['criteria']]
    actual = [row.criterion for row in result.criteria]
    if sorted(wanted) != sorted(actual):
        return 'Evaluation must cover each configured criterion exactly once.'
    previous = state.get('previous_submission')
    changed = bool(previous and previous.get('scene') != state['committed']['scene'])
    if changed:
        if result.revision_outcome not in {'successful', 'unsuccessful', 'uncertain'} or not result.revision_evidence.strip():
            return 'Review the actual submitted change with an outcome and supporting revision evidence.'
        addressed = (state.get('workflow') or {}).get('active_issue')
        from feedback_process import review_issue_status
        status = review_issue_status(result, addressed)
        retained = bool(addressed and any(item.id == addressed['id'] for item in result.missing_parts))
        if addressed and status == 'resolved' and (retained or result.revision_outcome != 'successful'):
            return 'A resolved broader issue requires a successful local revision and retirement of that issue; local success alone may leave it unresolved.'
        if (addressed and result.addressed_issue_status in {'unresolved', 'uncertain'} and not retained):
            return 'Keep the broader addressed issue in missing_parts while it remains unresolved or uncertain.'
    elif previous is None and result.revision_outcome != 'not_reviewed':
        return 'An initial submission has no revision outcome.'
    if previous is None and result.addressed_issue_status != 'not_reviewed':
        return 'An initial submission has no addressed-issue revision status.'
    ids = scene_ids(state['committed']['scene'])
    issues = [item.id for item in result.missing_parts]
    if len(set(issues)) != len(issues) or any(not value.strip() for value in issues):
        return 'Evaluation issue IDs must be nonempty and unique.'
    if any(item.criterion not in wanted for item in result.missing_parts):
        return 'Evaluation must use an existing criterion.'
    if len(result.strengths) > 2 or len(result.missing_parts) > 3:
        return 'Keep at most two strengths and three priority missing parts.'
    for item in [*result.strengths, *result.missing_parts]:
        if len(item.focus_ids) > 4 or not set(item.focus_ids).issubset(ids):
            return 'Evaluation visual targets must reference at most four submitted parts.'
    return ''


def _visual_problem(turn, state):
    ids = scene_ids(state['committed']['scene'])
    for selected in (turn.focus_ids, turn.acknowledgment_ids):
        if len(selected) > 4 or not set(selected).issubset(ids):
            return 'Visual feedback must reference at most four existing submitted parts.'
    if len(turn.mechanism_paths) > 2:
        return 'Use at most two connected mechanism paths.'
    relations = {item['id']:item for item in state['committed']['scene']['relations']}
    for path in turn.mechanism_paths:
        if not path.label.strip() or len(path.label.split()) > 8 or not 1 <= len(path.steps) <= 12:
            return 'Use a short path label and 1–12 actual connections.'
        end, seen = None, set()
        for step in path.steps:
            relation = relations.get(step.relation_id)
            if not relation or step.relation_id in seen:
                return 'Trace only existing connections once per path.'
            seen.add(step.relation_id)
            start, finish = (relation['source'],relation['target']) if step.direction == 'forward' else (relation['target'],relation['source'])
            if not start or not finish or (end is not None and start != end):
                return 'Mechanism steps must have resolved, connected endpoints.'
            end = finish
    if turn.mechanism_paths and turn.visual_action != 'trace':
        return 'Use trace for a mechanism path.'
    if turn.visual_action == 'trace' and not turn.mechanism_paths:
        return 'Supply a connected mechanism path for a trace.'
    return ''


def _clear_visuals(turn):
    turn.focus_ids = []
    turn.acknowledgment_ids = []
    turn.visual_action = turn.visual_delivery = 'none'
    turn.mechanism_paths = []
    turn.mechanism_condition = ''


def canonical_tutor(turn, state, initial=False, process=None, opening_highlight=None):
    """Align grounded metadata without changing the Tutor's visible advice."""
    result = turn.model_copy(deep=True)
    if ((process or {}).get('new_review') and (process or {}).get('review_outcome') == 'successful'
            and not result.acknowledgment.strip()):
        content = result.content.strip()
        first = next(iter(_sentences(content)), '')
        # Recognize praise already written in the reply; never invent missing
        # feedback or turn a neutral observation into a success claim.
        if ('?' not in first and re.match(
                r'^(?:nice (?:work|job|revision)|great (?:work|job|revision)|well done|good (?:work|job|revision))\b',
                first, re.I)):
            result.acknowledgment = first
            result.content = content[len(first):].lstrip()
    move = result.talk_moves[0]
    invite_plan = move == 'propose_revision_plan' and result.move_evidence.plan_mode == 'invite'
    if invite_plan:
        result.stage = 'revision-planning'
        result.next_step = 'explain'
    elif move in {'provide_hints_guidance', 'propose_revision_plan'}:
        combined = ' '.join(value for value in (result.acknowledgment.strip(), result.content.strip()) if value)
        instruction = result.edit_instruction.strip()
        if not instruction or instruction not in combined or '?' in instruction or not visible_edit_command(instruction):
            visible = visible_edit_instruction(result.content)
            if visible:
                result.edit_instruction = visible
        if result.edit_instruction and result.edit_instruction in combined and visible_edit_command(result.edit_instruction):
            result.next_step = 'revise'
            result.stage = 'revision-planning'
    expected = (process or {}).get('expected_stage')
    if initial and move == 'recognize_strengths':
        result.stage = 'recognition'
    elif not result.edit_instruction and result.stage != 'complete':
        if move == 'provide_hints_guidance':
            result.stage = 'dialogue' if expected == 'dialogue' else 'thinking-dialogue'
        elif expected == 'inquiry' and move in {'press_for_accuracy', 'revoice', 'ask_for_clarification'}:
            result.stage = 'inquiry'
        elif expected == 'thinking-dialogue' and move not in {'clarify_goals', 'invite_dialogue', 'propose_revision_plan'}:
            result.stage = 'thinking-dialogue'
    if initial and result.talk_moves == ['recognize_strengths']:
        ids = scene_ids(state['committed']['scene'])
        focus = set(result.focus_ids)
        formal = (state.get('learner_model',{}).get('evaluation') or {}).get('result',{})
        supported = any(focus.issubset(set(item.get('focus_ids',[]))) for item in formal.get('strengths',[]))
        if focus and len(result.focus_ids) <= 4 and focus.issubset(ids) and supported:
            acknowledged = set(result.acknowledgment_ids)
            criteria = {row['id'] for row in state['criteria']}
            aliases = acknowledged - ids
            criterion_alias = bool(aliases) and aliases.issubset(criteria) and (acknowledged & ids).issubset(focus)
            if not acknowledged or criterion_alias:
                result.acknowledgment_ids = list(dict.fromkeys(result.focus_ids))
    plan = opening_highlight or {}
    if (initial and plan.get('bind_opening') and result.talk_moves == ['recognize_strengths']
            and result.acknowledgment.strip() == plan.get('praise', '').strip()
            and result.content.strip() == plan.get('question', '').strip()):
        result.focus_ids = list(plan.get('focus_ids', []))
        result.acknowledgment_ids = list(result.focus_ids)
        result.visual_action = 'highlight' if result.focus_ids else 'none'
        result.visual_delivery = 'automatic' if result.focus_ids else 'none'
        result.mechanism_paths = []
        result.mechanism_condition = ''
    # Visuals are optional delivery metadata. Clear dormant values before any
    # bounds check; a bad overlay must not discard an otherwise usable reply.
    result.focus_ids = list(dict.fromkeys(result.focus_ids))
    result.acknowledgment_ids = list(dict.fromkeys(result.acknowledgment_ids))
    if not result.acknowledgment.strip():
        result.acknowledgment_ids = []
    if (result.visual_action == 'none' or _visual_problem(result, state)
            or (initial and not set(result.focus_ids).issubset(result.acknowledgment_ids))):
        _clear_visuals(result)
    elif result.visual_delivery == 'none':
        result.visual_delivery = 'automatic'
    return result


def validate_tutor(turn, state, initial=False):
    combined = ' '.join(value for value in (turn.acknowledgment.strip(), turn.content.strip()) if value)
    if not combined or len(combined.split()) > 45 or combined.count('?') > 1:
        return 'Use a concise usable reply, at most 45 words and one question.'
    if initial and (turn.talk_moves != ['recognize_strengths'] or not turn.acknowledgment.strip() or combined.count('?') != 1):
        return 'Open with one evidenced strength and one question about that same strength.'
    if turn.stage == 'complete' and '?' in combined:
        return 'Finish without a new question.'
    visual_problem = _visual_problem(turn, state)
    if visual_problem:
        return visual_problem
    if initial and not set(turn.focus_ids).issubset(set(turn.acknowledgment_ids)):
        return 'The opening visual must match the recognized strength.'
    instruction = turn.edit_instruction.strip()
    if instruction and (instruction not in combined or '?' in instruction or not visible_edit_command(instruction)):
        return 'The edit instruction must be an exact visible actionable statement.'
    if instruction and turn.talk_moves[0] not in {'provide_hints_guidance','propose_revision_plan'}:
        return 'Use guidance or a revision plan for a current diagram edit instruction.'
    if turn.talk_moves[0] in {'provide_hints_guidance','propose_revision_plan'} and visible_edit_command(turn.content) and not instruction:
        return 'Include the visible drawing instruction in edit_instruction so editing can open.'
    if turn.talk_moves[0] == 'propose_revision_plan':
        if turn.move_evidence.plan_mode == 'invite':
            if instruction or combined.count('?') != 1 or turn.next_step != 'explain':
                return 'Invite one learner revision plan with a question and no current edit instruction.'
        elif not instruction:
            return 'A provided revision plan needs one visible current edit instruction.'
    return ''
