"""Restore an explicitly supplied local case when updating the workspace server."""
from copy import deepcopy
import json
from pathlib import Path
import re

from schema import validate_sketch


def prepare_resume(path, artifacts, payload_loader):
    """Return browser recovery data and the last committed backend session.

    The path is a server-startup argument, never an HTTP parameter. Recovery
    refuses stale backups so a deployment cannot silently roll back a case.
    """
    case = json.loads(Path(path).read_text(encoding='utf-8'))
    sid = case.get('feedback_session', '')
    if not re.fullmatch(r'feedback_[a-f0-9]{32}', sid):
        raise ValueError('The case backup has no valid feedback session.')
    turns = case.get('feedback_turns', [])
    if not turns:
        raise ValueError('The case backup has no completed feedback turn.')
    matching = []
    for file in Path(artifacts).glob('feedback_*/session.json'):
        candidate = json.loads(file.read_text(encoding='utf-8'))
        if candidate.get('id') == sid:
            matching.append((candidate['version'], file.stat().st_mtime, candidate))
    if not matching:
        raise ValueError('The saved backend session for this case was not found.')
    state = deepcopy(max(matching, key=lambda item: item[:2])[2])
    if state['version'] != turns[-1]['version'] or state['drawing_version'] != turns[-1]['drawing_version']:
        raise ValueError('The case backup is stale. Save the current case again.')
    if state['committed'] != case.get('committed_work'):
        raise ValueError('The case backup does not match the saved submission.')
    for snapshot in (state['original'], state['committed'], case.get('current_draft', {})):
        validate_sketch(snapshot.get('scene'))
    validate_sketch(case.get('original_model'))
    payload = payload_loader(case['source']['id'])
    if not payload or payload['record']['id'] != state['source_id']:
        raise ValueError('The original drawing for this case was not found.')
    workspace = case.get('workspace_state', {})
    # Safe recovery starts in viewing mode; the learner can begin another revision.
    state['edit_enabled'] = False
    browser_state = dict(
        session_id=sid,
        drawing_version=state['drawing_version'],
        edit_enabled=False,
        awaiting_revision_reason=bool(state.get('awaiting_revision_reason')),
        revision_reason=workspace.get('revision_reason', state.get('revision_reason', '')),
        initial_explanation=state['original']['explanation'],
        learning_requirements=[c['label'] for c in state['criteria']] if state['goals_configured'] else [],
    )
    return deepcopy(dict(payload=payload, case=case, state=browser_state)), state
