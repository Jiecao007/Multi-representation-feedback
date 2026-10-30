"""Read the Evaluation-selected opening without another teaching decision."""
from copy import deepcopy


def _text(value, limit=35):
    return isinstance(value, str) and bool(value.strip()) and len(value.split()) <= limit


def _strengths(formal, ids):
    return [item for item in formal.get('strengths', []) if isinstance(item, dict)
            and _text(item.get('description')) and _text(item.get('evidence'))
            and isinstance(item.get('focus_ids', []), list)
            and len(item.get('focus_ids', [])) <= 4
            and set(item.get('focus_ids', [])).issubset(ids)]


def selected_highlight(formal, scene):
    """Return a grounded opening plan, or a clearly marked legacy fallback.

    A plan's feature/evidence is copied from one assessed strength. Relevance and
    the quality of its confirmation question remain Evaluation's judgment.
    Historical assessments without a plan retain their response wording.
    """
    if hasattr(formal, 'model_dump'):
        formal = formal.model_dump()
    if not isinstance(formal, dict):
        return None
    ids = {item['id'] for group in ('objects', 'relations') for item in scene.get(group, [])}
    strengths = _strengths(formal, ids)
    raw = formal.get('highlight_plan')
    if hasattr(raw, 'model_dump'):
        raw = raw.model_dump()
    reason = ''
    if isinstance(raw, dict):
        plan = deepcopy(raw)
        focus = plan.get('focus_ids', [])
        top_issue = next((item.get('id', '') for item in formal.get('missing_parts', [])
                          if isinstance(item, dict)), '')
        supported = any(plan.get('feature', '').strip() == item['description'].strip()
                        and plan.get('evidence', '').strip() == item['evidence'].strip()
                        and set(focus).issubset(set(item.get('focus_ids', [])))
                        for item in strengths) if isinstance(focus, list) else False
        praise, question = plan.get('praise', ''), plan.get('question', '')
        valid = (supported and len(focus) <= 4 and set(focus).issubset(ids)
                 and _text(plan.get('selection_reason'))
                 and plan.get('related_issue_id', '') == top_issue
                 and _text(praise) and _text(question)
                 and '?' not in praise and question.count('?') == 1 and question.rstrip().endswith('?')
                 and len((praise + ' ' + question).split()) <= 35)
        if valid:
            plan['focus_ids'] = list(dict.fromkeys(focus))
            plan.update(source='evaluation_plan', bind_opening=True)
            return plan
        reason = 'The selected plan did not match one supported strength, the priority issue, or the opening bounds.'
    if not strengths:
        return None
    first = strengths[0]
    praise = 'Nice work! ' + first['description'].strip().rstrip('.!?') + '.'
    question = 'Is that what you intended to show?'
    return dict(feature=first['description'], evidence=first['evidence'],
                focus_ids=list(dict.fromkeys(first.get('focus_ids', []))),
                related_issue_id=next((item.get('id', '') for item in formal.get('missing_parts', [])
                                       if isinstance(item, dict)), ''),
                selection_reason='Use the first supported strength when no usable selected plan is available.',
                praise=praise, question=question,
                source='first_strength_fallback', bind_opening=isinstance(raw, dict),
                fallback_reason=reason or 'This saved assessment has no selected Highlight plan.')
