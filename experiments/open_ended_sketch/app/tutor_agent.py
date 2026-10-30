"""Fast teaching dialogue: no formal Assessment and no evaluator fallback."""
from functools import lru_cache
from pathlib import Path
from typing import Literal, get_args

from pydantic import Field, create_model
from agent_types import TalkMove, TutorTurn, MoveEvidence
from move_selection import readiness_sources

PROMPT = Path(__file__).resolve().parents[1] / 'prompts/feedback_tutor.md'
EXAMPLES = PROMPT.with_name('feedback_move_examples.md')


@lru_cache(maxsize=128)
def _process_tutor_type(moves, stages, issue_id, opening_praise='', opening_question='',
                        source_ids=('',), require_review_praise=False):
    """Constrain the same Tutor response to the controller's current boundary."""
    if not moves or not stages:
        raise ValueError('The feedback process needs an allowed move and stage.')
    if not set(moves).issubset(get_args(TalkMove)):
        raise ValueError('The feedback process supplied an unknown move.')
    if not set(stages).issubset(get_args(TutorTurn.model_fields['stage'].annotation)):
        raise ValueError('The feedback process supplied an unknown stage.')
    overrides = {}
    evidence_type = create_model('MoveEvidenceSources', __base__=MoveEvidence,
        readiness_source_id=(Literal[source_ids], Field(default='',
            description=MoveEvidence.model_fields['readiness_source_id'].description)))
    overrides['move_evidence'] = (evidence_type, Field(default_factory=evidence_type,
        description=TutorTurn.model_fields['move_evidence'].description))
    if require_review_praise:
        overrides['acknowledgment'] = (str, Field(min_length=1,
            description='Required: warmly recognize the successful submitted correction using interaction.review_evidence. Put the praise here before the follow-up in content.'))
    if opening_praise and opening_question:
        overrides.update(
            acknowledgment=(Literal[opening_praise], Field(default=opening_praise,
                description='Use the Evaluation-selected praise exactly.')),
            content=(Literal[opening_question], Field(default=opening_question,
                description='Use the Evaluation-selected confirmation question exactly.')))
    return create_model(
        'TutorTurnProcess', __base__=TutorTurn,
        talk_moves=(list[Literal[moves]], Field(min_length=1, max_length=2,
            description='Select only from the current process boundary; use one move or the ordered Revoice/Clarification pair.')),
        stage=(Literal[stages], Field(default=stages[0],
            description='Use the current process stage or an explicitly allowed help/revision exception.')),
        issue_id=(Literal[issue_id], Field(default=issue_id,
            description='The controller-selected issue. Keep this ID throughout dialogue until its actual revision is reviewed.')),
        **overrides,
    )


def process_tutor_type(context):
    interaction = context.get('interaction', {})
    if not {'allowed_moves', 'allowed_stages', 'active_issue_id'}.issubset(interaction):
        return TutorTurn
    plan = context.get('opening_highlight') or {}
    bind = interaction.get('expected_stage') == 'recognition' and plan.get('bind_opening')
    return _process_tutor_type(tuple(interaction['allowed_moves']),
                               tuple(interaction['allowed_stages']), interaction['active_issue_id'],
                               plan.get('praise', '') if bind else '',
                               plan.get('question', '') if bind else '',
                               ('', *readiness_sources(context)) if 'propose_revision_plan' in interaction['allowed_moves'] else ('',),
                               bool(interaction.get('new_review') and interaction.get('review_outcome') == 'successful'))


def select_examples(context):
    """Include examples for this teaching phase in the same Tutor request."""
    interaction = context.get('interaction', {})
    stage = interaction.get('expected_stage', interaction.get('stage'))
    allowed = interaction.get('allowed_moves')
    guidance_allowed = allowed is None or 'provide_hints_guidance' in allowed
    planning_allowed = allowed is None or 'propose_revision_plan' in allowed
    if interaction.get('exit_requested') or stage == 'complete':
        selected = ('closing',)
    elif stage == 'recognition':
        selected = ('recognition',)
    elif interaction.get('intent') == 'hint' or interaction.get('help_requested'):
        selected = ('help',)
    elif interaction.get('review_clarification_required'):
        selected = ('review_uncertain', 'meaning', 'help', 'goals')
    elif interaction.get('evaluation_updated') and interaction.get('diagram_changed'):
        selected = ('review', 'meaning', 'support', 'help', 'closing', 'goals')
    elif stage == 'inquiry':
        selected = ('inquiry', 'meaning', 'help', 'goals')
    elif stage in {'dialogue', 'complete'}:
        selected = ('closing', 'help', 'goals')
    elif stage == 'revision-planning':
        selected = ('support', 'help', 'goals')
    else:
        selected = ('meaning', 'support', 'help', 'goals')
    selected = [key for key in selected if key != 'help' or guidance_allowed]
    if stage not in {'recognition', 'complete'} and not interaction.get('exit_requested'):
        if interaction.get('support_question_scaffold') == 'high':
            selected.insert(0, 'scaffolding')
        if planning_allowed and stage not in {'inquiry', 'dialogue'}:
            selected.append('planning')
    parts = EXAMPLES.read_text().split('\n## ')
    sections = {part.split('\n', 1)[0]: part.split('\n', 1)[1]
                for part in parts[1:]}
    return parts[0].strip() + '\n\n' + '\n\n'.join(
        '## ' + key + '\n' + sections[key].strip() for key in selected)


class TutorAgent:
    def __init__(self, calls, model, effort='low'):
        self.calls, self.model, self.effort = calls, model, effort

    def respond(self, context):
        instructions = PROMPT.read_text() + '\n\n' + select_examples(context)
        return self.calls.call('tutor', instructions, context, process_tutor_type(context),
                               self.model, self.effort, max_output_tokens=1600)

