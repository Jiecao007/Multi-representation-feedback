"""Compact Tutor input: current evidence, sparse memory, and recent dialogue."""
from copy import deepcopy

from learner_model import project_learner_model
from move_selection import SUPPORT_ORDER, readiness_sources
from feedback_process import process_contract, active_issue
from highlight_plan import selected_highlight


OBJECT_FIELDS = ('id', 'label', 'verbatim_text', 'kind', 'bbox', 'members', 'ambiguity')
RELATION_FIELDS = ('id', 'source', 'target', 'direction', 'points', 'verbatim_text', 'ambiguity')


def _text(value, limit):
    return value[:limit] if isinstance(value, str) else ''


def _counter(value):
    return max(0, value) if isinstance(value, int) and not isinstance(value, bool) else 0


def editor_context(state):
    """Supported controls are separate from their current edit permission."""
    scene = state['committed']['scene']
    return {
        'canvas_mode': 'objects_and_connections',
        'current_edit_enabled': bool(state.get('edit_enabled')),
        'capabilities': {
            'freehand_drawing': False, 'object_connections': True,
            'text_annotations': True, 'library_objects': True,
            'connection_endpoint_drag': True, 'curved_connections': True,
        },
        'authorization': 'A visible manual-action instruction enables student canvas controls only. Chat never changes the diagram; the student must perform the action and select Review changes.',
        'endpoint_behavior': 'Connect selects existing objects by label and initially joins their centers; it does not infer tick snapping or calibrated scale.',
        'tools': [
            {'action': 'connect', 'label': '↗ Connect',
             'available': len(scene['objects']) >= 2, 'requires_edit_permission': True,
             'instructions': 'Select From and To existing objects by label, set Shape and Direction, optionally Meaning, then Save connection.',
             'endpoint_source': 'current_diagram.objects',
             'fields': ['From', 'To', 'Meaning', 'Shape', 'Direction'],
             'shapes': ['Straight', 'Curved', 'Bent'],
             'directions': ['From → To', 'From ← To', 'Both directions', 'Line without an arrow'],
             'save_label': 'Save connection'},
            {'action': 'add_text', 'label': '+ Text', 'available': True,
             'requires_edit_permission': True,
             'instructions': 'Enter the text, select Save changes, then move the new label to its intended position.'},
            {'action': 'add_object', 'label': '+ Object', 'available': True,
             'requires_edit_permission': True,
             'instructions': 'Choose a topic and one existing library item. Arrows are connections created with Connect.'},
            {'action': 'edit_connection', 'label': 'Edit connection',
             'available': bool(scene['relations']), 'requires_edit_permission': True,
             'instructions': 'Select an existing connection, then Edit connection. Change its fields and Save connection. Drag endpoints or a middle handle to reshape it.'},
            {'action': 'submit_revision', 'label': 'Review changes', 'available': True,
             'requires_edit_permission': True,
             'instructions': 'Submit the current draft so its actual changes can be reviewed.'},
        ],
    }


def build_tutor_context(state, message, trigger, intent, evaluation_updated=False, diagram_changed=False, selected_id=''):
    """Build one text-only request without full assessment or drawing strokes."""
    if not isinstance(message, str) or len(message) > 4000:
        raise ValueError('Use a current message of at most 4,000 characters.')
    scene = state['committed']['scene']
    memory = project_learner_model(state['learner_model'])
    evaluation = memory.get('evaluation') or {}
    # Legacy projection may derive workflow metadata; do not mutate its caller.
    process_state = dict(state)
    current_issue = active_issue(process_state)
    process = process_contract(process_state, message, trigger, intent, evaluation_updated and diagram_changed)
    opening_highlight = selected_highlight(evaluation.get('result', {}), scene) if process['expected_stage'] == 'recognition' else None
    history = state.get('recent_dialogue', state.get('turns', []))
    recent = []
    for turn in history[-6:]:
        if not isinstance(turn, dict):
            continue
        moves = turn.get('talk_moves') or ([turn['talk_move']] if turn.get('talk_move') else [])
        recent.append({
            'student': _text(turn.get('student'), 700),
            'tutor': _text(turn.get('tutor', turn.get('content')), 700),
            'talk_moves': [move for move in moves if isinstance(move, str)][:2] if isinstance(moves, list) else [],
        })
    context = {
        'learner_model': memory,
        'current_diagram': {
            'title': _text(scene.get('title'), 300),
            'objects': [{key: deepcopy(item[key]) for key in OBJECT_FIELDS if key in item}
                        for item in scene['objects']],
            'relations': [{key: deepcopy(item[key]) for key in RELATION_FIELDS if key in item}
                          for item in scene['relations']],
        },
        'latest_explanation': _text(state['committed'].get('explanation'), 2000),
        'recent_dialogue': recent,
        'student_message': message,
        'selected_id': selected_id if isinstance(selected_id,str) and any(item['id']==selected_id for item in scene['objects']+scene['relations']) else '',
        'current_issue': deepcopy(current_issue),
        **({'opening_highlight': opening_highlight} if opening_highlight is not None else {}),
        'interaction': {
            'trigger': trigger, 'intent': intent, 'stage': state.get('stage', 'recognition'),
            **process,
            'support_order': SUPPORT_ORDER[:], 'goals_configured': bool(state.get('goals_configured')),
            'evaluation_updated': bool(evaluation_updated), 'diagram_changed': bool(diagram_changed),
            'hint_turns_remaining': _counter(state.get('hint_turns_remaining', 0)),
            'consecutive_difficulties': _counter(process_state.get('consecutive_difficulties', 0)),
            'guidance_count': _counter(state.get('guidance_count', state.get('hint_count', 0))),
            'edit_enabled': bool(state.get('edit_enabled')),
        },
        'editor_context': editor_context(state),
    }
    if 'propose_revision_plan' in process['allowed_moves']:
        context['revision_readiness_sources'] = list(readiness_sources(context))
    return context
