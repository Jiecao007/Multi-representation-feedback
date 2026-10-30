"""Bind revision review to delivered local instructions, not an entire issue.

This module stores provenance and compares submitted data only. Evaluation
still judges whether the actual local change succeeds.
"""
from copy import deepcopy

VERSION = 'bounded-revision-target-v1'
EDIT_MOVES = {'provide_hints_guidance', 'propose_revision_plan'}


def _number(value, default=0):
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _issue_id(state):
    issue = (state.get('workflow') or {}).get('active_issue') or {}
    return issue.get('id') or state.get('current_issue_id', '')


def _new_target(state):
    return dict(version=VERSION, issue_id=_issue_id(state),
                base_drawing_version=_number(state.get('drawing_version'), 1),
                instructions=[], learner_requests=[])


def _append_instruction(target, instruction, delivery_version, move, source):
    if instruction and not any(row['instruction'] == instruction for row in target['instructions']):
        target['instructions'].append(dict(instruction=instruction,
            delivery_version=delivery_version, talk_move=move, source=source))


def _recover_legacy_target(state, for_review=False):
    """Recover visible imperatives only from actual delivered historical turns."""
    from interaction_contract import visible_edit_instruction

    target = _new_target(state)
    reviewed_version = _number(state.get('review_version'))
    history = state.get('turns', [])
    for turn in history:
        # A review reply can also deliver the NEXT local edit. Its version is
        # exactly review_version, so retain that instruction for the next review.
        if not isinstance(turn, dict) or _number(turn.get('version')) < reviewed_version:
            continue
        if turn.get('issue_id', '') != target['issue_id']:
            continue
        moves = turn.get('talk_moves') or [turn.get('talk_move')]
        move = moves[0] if moves else ''
        if move not in EDIT_MOVES:
            continue
        content = turn.get('content', '')
        if not isinstance(content, str):
            continue
        instruction = turn.get('edit_instruction', '')
        if not isinstance(instruction, str) or not instruction.strip() or instruction.strip() not in content:
            instruction = visible_edit_instruction(content)
        _append_instruction(target, instruction.strip(), _number(turn.get('version')),
                            move, 'delivered_legacy_turn')
    if target['instructions']:
        # On a changed submission drawing_version has already advanced once.
        if for_review and state.get('previous_submission') is not None:
            target['base_drawing_version'] = max(1, target['base_drawing_version'] - 1)
        available_versions = [_number(row.get('version')) for row in history if isinstance(row, dict)]
        target['legacy_history_may_be_truncated'] = bool(
            available_versions and min(available_versions) > reviewed_version)
    return target


def _pending_target(state, for_review=False):
    workflow = state.get('workflow') or {}
    target = workflow.get('pending_revision_target')
    if isinstance(target, dict) and target.get('version') == VERSION and target.get('issue_id') == _issue_id(state):
        value = deepcopy(target)
        value.setdefault('instructions', [])
        value.setdefault('learner_requests', [])
        return value
    if workflow.get('revision_target_protocol') != VERSION:
        return _recover_legacy_target(state, for_review)
    value = _new_target(state)
    if for_review and state.get('previous_submission') is not None:
        value['base_drawing_version'] = max(1, value['base_drawing_version'] - 1)
    return value


def record_delivered_revision_target(state, turn, context=None):
    """Call only for a validated Tutor turn that will be committed/delivered.

    Multiple exact edit instructions accumulate until an actual changed-diagram
    review is delivered. A planning invitation contributes no instruction.
    """
    target = _pending_target(state)
    instruction = turn.edit_instruction.strip()
    move = turn.talk_moves[0]
    if instruction and move in EDIT_MOVES:
        _append_instruction(target, instruction, _number(state.get('version')), move,
                            'delivered_tutor_edit_instruction')
    context = context or {}
    interaction = context.get('interaction') or context
    intent = interaction.get('intent')
    message = context.get('student_message', context.get('message', ''))
    if intent == 'begin_revision' and isinstance(message, str) and message.strip():
        request = message.strip()
        if not any(row['text'] == request for row in target['learner_requests']):
            target['learner_requests'].append(dict(text=request,
                delivery_version=_number(state.get('version')), source='learner_revision_request'))
    workflow = state.setdefault('workflow', {})
    workflow['revision_target_protocol'] = VERSION
    if target['instructions'] or target['learner_requests']:
        workflow['pending_revision_target'] = target
    else:
        workflow.pop('pending_revision_target', None)


def consume_reviewed_revision_target(state):
    """Call after a changed-diagram Evaluation AND Tutor delivery succeeds.

    Call before recording any new instruction in that same review reply.
    Unchanged submissions and failed deliveries must not consume the target.
    """
    workflow = state.setdefault('workflow', {})
    workflow['revision_target_protocol'] = VERSION
    workflow.pop('pending_revision_target', None)


def _delta(previous, current):
    previous = previous if isinstance(previous, dict) else {}
    current = current if isinstance(current, dict) else {}
    result = {}
    absent = object()
    for group in ('objects', 'relations'):
        old = {item['id']: item for item in previous.get(group, []) if isinstance(item, dict) and 'id' in item}
        new = {item['id']: item for item in current.get(group, []) if isinstance(item, dict) and 'id' in item}
        result[group] = dict(
            added_ids=sorted(new.keys() - old.keys()),
            removed_ids=sorted(old.keys() - new.keys()),
            changed=[dict(id=key, fields=sorted(
                field for field in old[key].keys() | new[key].keys()
                if old[key].get(field, absent) != new[key].get(field, absent)))
                for key in sorted(old.keys() & new.keys()) if old[key] != new[key]])
    return result


def revision_target_context(state, reason):
    """Read-only Evaluation input separating the local target from its issue.

    Without a recoverable instruction, assess learner intention and the actual
    delta. Never silently substitute all missing parts as the local target.
    """
    if reason == 'initial':
        return None
    target = _pending_target(state, for_review=reason == 'diagram_revision')
    reason_text = state.get('revision_reason', '')
    reason_text = reason_text.strip() if isinstance(reason_text, str) else ''
    scope = ('delivered_tutor_instructions' if target['instructions'] else
             'learner_revision_intent' if reason_text or target['learner_requests'] else 'submitted_delta')
    previous = state.get('previous_submission') or {}
    committed = state.get('committed') or {}
    result = dict(version=VERSION, issue_id=target['issue_id'], scope_source=scope,
        base_drawing_version=target['base_drawing_version'],
        submitted_drawing_version=_number(state.get('drawing_version'), 1),
        instructions=deepcopy(target['instructions']),
        learner_requests=deepcopy(target['learner_requests']),
        learner_revision_reason=reason_text,
        submitted_delta=_delta(previous.get('scene'), committed.get('scene')))
    if 'legacy_history_may_be_truncated' in target:
        result['legacy_history_may_be_truncated'] = target['legacy_history_may_be_truncated']
    return result
