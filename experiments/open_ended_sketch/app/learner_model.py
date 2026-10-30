"""Sparse shared learning memory for the feedback application's three agents.

Evaluation owns the formal result. Tutor updates are grounded observations, not
new ability ratings. Short-term chat belongs to the runtime, outside this model.
All updates return copies so a failed turn cannot mutate committed memory.
"""
from copy import deepcopy
import re


SCHEMA_VERSION = 'learner-model-v1'
MAX_OBSERVATIONS = 12
PROJECTED_OBSERVATIONS = 6
OBSERVATION_KINDS = {'understanding', 'difficulty', 'subtask_completed'}
EVALUATION_FIELDS = (
    'learning_goal', 'task_summary', 'criteria', 'strengths', 'missing_parts', 'uncertainties',
    'revision_outcome', 'revision_evidence', 'addressed_issue_status', 'highlight_plan',
)
ACKNOWLEDGMENT = re.compile(
    r'(?:yes|yeah|yep|right|correct|okay|ok|thanks|thank you|i agree|i think so|'
    r'是|是的|好的|好|嗯|对|明白了|谢谢)[.!?。！？，,\s]*', re.I)
BARE_UNCERTAINTY = re.compile(
    r"(?:i (?:still )?(?:do not|don['’]\s*t) (?:know|understand|remember)|"
    r"(?:still )?don['’]\s*t know|i(?:['’]m| am) (?:not sure|unsure)|"
    r'not sure|maybe|no idea|我(?:还是|仍然)?(?:不知道|不会|不懂))[.!?。！？，,\s]*', re.I)


def _mapping(value):
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json')
    if not isinstance(value, dict):
        raise ValueError('Learning memory updates must be structured objects.')
    return deepcopy(value)


def _drawing_version(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError('Use a positive submitted drawing version.')
    return value


def _formal_result(value):
    """Keep the evaluation contract, never cached tutor/routing fields."""
    value = _mapping(value)
    result = {key: deepcopy(value[key]) for key in EVALUATION_FIELDS if key in value}
    if not isinstance(result.get('criteria', []), list):
        raise ValueError('Evaluation criteria must be a list.')
    if 'criteria' in result:
        result['criteria'] = [
            {key: deepcopy(row[key]) for key in ('criterion', 'status', 'level', 'evidence') if key in row}
            for row in result['criteria'] if isinstance(row, dict)
        ]
    return result


def create_learner_model(task, criteria, source_id='', drawing_version=1):
    """Start a session/task memory without inferring any student ability."""
    if not isinstance(task, str) or not isinstance(criteria, list) or not isinstance(source_id, str):
        raise ValueError('Provide task text, configured criteria, and a source ID.')
    return {
        'schema_version': SCHEMA_VERSION,
        'revision': 0,
        'task': {'text': task, 'criteria': deepcopy(criteria), 'source_id': source_id},
        'drawing_version': _drawing_version(drawing_version),
        'representation': None,
        'evaluation': None,
        'observations': [],
    }


def record_representation(memory, scene, source_id, drawing_version):
    """Keep a compact transformation/submission summary, never duplicate geometry.

    The authoritative objects and strokes stay in the runtime's committed scene.
    Empty or older representations cannot overwrite an existing summary.
    """
    result = _mapping(memory)
    version = _drawing_version(drawing_version)
    if version < result['drawing_version'] or not scene:
        return result
    scene = _mapping(scene)
    objects, relations = scene.get('objects', []), scene.get('relations', [])
    if not isinstance(objects, list) or not isinstance(relations, list):
        raise ValueError('Representation objects and relations must be lists.')
    if not objects and not relations:
        return result
    if not isinstance(source_id, str):
        raise ValueError('Representation source ID must be text.')
    uncertainties = []
    for item in objects + relations:
        if not isinstance(item, dict) or not isinstance(item.get('ambiguity'), str):
            continue
        uncertainty = item['ambiguity'].strip()
        if not uncertainty or uncertainty in uncertainties:
            continue
        uncertainties.append(uncertainty)
        if len(uncertainties) == 4:
            break
    representation = {
        'source_id': source_id,
        'drawing_version': version,
        'object_count': len(objects),
        'relation_count': len(relations),
        'uncertainties': uncertainties,
    }
    if result.get('representation') == representation and result['drawing_version'] == version:
        return result
    result.update(drawing_version=version, representation=representation,
                  revision=result.get('revision', 0) + 1)
    return result


def record_evaluation(memory, evaluation, drawing_version):
    """Replace the formal result only at an Evaluation-agent submission event."""
    result = _mapping(memory)
    version = _drawing_version(drawing_version)
    if version < result['drawing_version']:
        raise ValueError('A stale evaluation cannot replace the current drawing assessment.')
    updated = {'source': 'evaluation', 'drawing_version': version, 'result': _formal_result(evaluation)}
    if result.get('evaluation') == updated and result['drawing_version'] == version:
        return result
    result.update(drawing_version=version, evaluation=updated, revision=result.get('revision', 0) + 1)
    return result


def record_observations(memory, updates, learner_sources, drawing_version):
    """Accept only significant, current-version, evidenced Tutor observations.

    learner_sources must contain actual learner text, never Tutor replies or task
    givens. Unsupported optional updates are ignored without blocking a reply.
    Formal results, levels, task data and version are never patched by this API.
    """
    result = _mapping(memory)
    version = _drawing_version(drawing_version)
    if version != result['drawing_version']:
        return result, []
    if updates is None:
        return result, []
    if not isinstance(updates, list) or not isinstance(learner_sources, (list, tuple)):
        return result, []
    sources = [text for text in learner_sources if isinstance(text, str)]
    accepted = []
    existing = result.get('observations', [])
    keys = {(item.get('kind'), item.get('summary'), item.get('evidence'), item.get('drawing_version'))
            for item in existing if isinstance(item, dict)}
    for candidate in updates[:3]:
        try:
            item = _mapping(candidate)
        except ValueError:
            continue
        # Tutor can propose an observation, not overwrite another agent's data.
        if set(item) - {'kind', 'summary', 'evidence'}:
            continue
        kind, summary, evidence = (item.get(key, '') for key in ('kind', 'summary', 'evidence'))
        if not isinstance(kind, str) or kind not in OBSERVATION_KINDS or not isinstance(summary, str) or not isinstance(evidence, str):
            continue
        summary, evidence = summary.strip(), evidence.strip()
        if not summary or len(summary.split()) > 35 or not evidence or len(evidence.split()) > 25:
            continue
        if ACKNOWLEDGMENT.fullmatch(evidence):
            continue
        if kind != 'difficulty' and BARE_UNCERTAINTY.fullmatch(evidence):
            continue
        if not any(evidence in text for text in sources):
            continue
        key = (kind, summary, evidence, version)
        if key in keys:
            continue
        keys.add(key)
        accepted.append({'kind': kind, 'summary': summary, 'evidence': evidence,
                         'drawing_version': version, 'source': 'tutor_observation'})
    if accepted:
        result['observations'] = (deepcopy(existing) + accepted)[-MAX_OBSERVATIONS:]
        result['revision'] = result.get('revision', 0) + 1
    return result, accepted


def migrate_learner_model(state):
    """Import a saved session once, preserving the provenance of old assessment.

    Old statuses are retained as historical evidence. An ability level absent
    from that assessment is left absent rather than inferred from its status.
    """
    present = state.get('learner_model')
    if isinstance(present, dict) and present.get('schema_version') == SCHEMA_VERSION:
        return deepcopy(present)
    result = create_learner_model(state.get('task', ''), state.get('criteria', []),
                                  state.get('source_id', ''), state.get('drawing_version', 1))
    assessment = state.get('assessment')
    if not isinstance(assessment, dict):
        return result
    rows = []
    for row in assessment.get('criteria', []):
        if not isinstance(row, dict):
            continue
        rows.append({key: deepcopy(row[key]) for key in ('criterion', 'status', 'level', 'evidence') if key in row})
        if 'evidence' not in rows[-1]:
            rows[-1]['evidence'] = ' '.join(str(row.get(key, '')).strip() for key in ('strength', 'gap')).strip()
    formal = {
        'learning_goal': assessment.get('learning_goal', state.get('learning_goal', '')),
        'task_summary': state.get('task_figure_context', ''),
        'criteria': rows,
        'strengths': [
            {'description': item.get('claim', ''), 'evidence': item.get('evidence', ''), 'focus_ids': []}
            for item in assessment.get('strengths', []) if isinstance(item, dict)
        ],
        'missing_parts': [
            {'id': 'legacy_gap_' + str(index + 1), 'criterion': assessment.get('criterion', ''),
             'description': item.get('claim', ''), 'evidence': item.get('evidence', ''), 'focus_ids': []}
            for index, item in enumerate(assessment.get('areas_for_improvement', [])) if isinstance(item, dict)
        ],
        'uncertainties': [
            ': '.join(str(item.get(key, '')).strip() for key in ('claim', 'evidence')).strip(': ')
            for item in assessment.get('ambiguities', []) if isinstance(item, dict)
        ],
        'revision_outcome': assessment.get('revision_outcome', 'not_reviewed'),
        'revision_evidence': assessment.get('revision_outcome_evidence', ''),
    }
    result['evaluation'] = {'source': 'legacy_assessment', 'drawing_version': result['drawing_version'], 'result': formal}
    result['revision'] = 1
    return result


def project_learner_model(memory):
    """Return the compact shared state read by Tutor, with no raw chat history."""
    value = _mapping(memory)
    evaluation = value.get('evaluation')
    if evaluation:
        evaluation = {'source': evaluation['source'], 'drawing_version': evaluation['drawing_version'],
                      'result': _formal_result(evaluation['result'])}
    return {
        'revision': value.get('revision', 0),
        'task': deepcopy(value['task']),
        'drawing_version': value['drawing_version'],
        'representation': deepcopy(value.get('representation')),
        'evaluation': evaluation,
        'observations': deepcopy(value.get('observations', [])[-PROJECTED_OBSERVATIONS:]),
    }
