"""Small, separate contracts for formal evaluation and fast tutoring."""
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

TalkMove = Literal['recognize_strengths','press_for_accuracy','revoice','ask_for_clarification',
                   'build_on_prior_knowledge','invite_elaboration_reasoning','prompt_reflection',
                   'provide_hints_guidance','propose_revision_plan','invite_dialogue','clarify_goals']
Status = Literal['established','developing','not-yet-visible','not-requested']


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class CriterionAssessment(Strict):
    criterion: str
    status: Status
    level: Literal['not-yet-demonstrated','developing','demonstrated','uncertain','not-requested']
    evidence: str


class Strength(Strict):
    description: str
    evidence: str
    focus_ids: list[str] = Field(default_factory=list)


class MissingPart(Strict):
    id: str
    criterion: str
    description: str
    evidence: str
    focus_ids: list[str] = Field(default_factory=list)


class HighlightPlan(Strict):
    feature: str
    evidence: str
    focus_ids: list[str] = Field(default_factory=list)
    related_issue_id: str = ''
    selection_reason: str
    praise: str
    question: str


class EvaluationResult(Strict):
    learning_goal: str
    task_summary: str = ''
    criteria: list[CriterionAssessment]
    strengths: list[Strength] = Field(default_factory=list)
    missing_parts: list[MissingPart] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    revision_outcome: Literal['not_reviewed','successful','unsuccessful','uncertain'] = Field(default='not_reviewed', description='Outcome of the bounded submitted revision_target, not completion of the broader addressed_issue or whole task. A correct requested local change is successful even when other parts remain.')
    revision_evidence: str = Field(default='', description='Identify the actual submitted local change and why it meets, fails or cannot yet establish the bounded revision target; distinguish remaining broader work.')
    addressed_issue_status: Literal['not_reviewed','resolved','unresolved','uncertain'] = Field(default='not_reviewed', description='Independent status of the broader addressed_issue after this change. A successful local revision may leave it unresolved. Use not_reviewed for initial work or no addressed issue; unresolved/uncertain issues retain their stable ID in missing_parts.')
    highlight_plan: Optional[HighlightPlan] = Field(default=None, description='One Evaluation-selected strength for the initial Highlight: exact feature/evidence from strengths, related priority issue, current diagram IDs, warm praise and one brief confirmation question. Use null only when no supported strength is available.')


class MemoryUpdate(Strict):
    kind: Literal['understanding','difficulty','subtask_completed']
    summary: str
    evidence: str


class TraceStep(Strict):
    relation_id: str
    direction: Literal['forward','backward']


class MechanismPath(Strict):
    label: str
    steps: list[TraceStep]


class MoveEvidence(Strict):
    """Transient grounds for the Tutor's candidate moves, not learner memory."""
    revoice_need: str = ''
    revoice_evidence: str = ''
    clarification_need: str = ''
    reflection_target: str = ''
    reflection_evidence: str = ''
    reflection_reference: str = ''
    reflection_reference_source: Literal['none','task_or_observable','learner_demonstrated','tutor_provided'] = 'none'
    reflection_need: str = ''
    prior_knowledge_mode: Literal['established','activate'] = 'established'
    prior_knowledge_connection: str = ''
    prior_knowledge_evidence: str = ''
    prior_knowledge_activation_evidence: str = ''
    reasoning_gap: str = ''
    readiness_source_id: str = Field(default='', description='For a revision plan, choose one revision_readiness_sources ID whose learner text supports this correction. Leave readiness_evidence empty when using an ID. Other moves leave this empty.')
    readiness_evidence: str = Field(default='', description='Legacy alternative to readiness_source_id: one exact contiguous learner quote, at most 25 words. No summary, added quotation marks, or concatenated turns.')
    plan_mode: Literal['invite','provide'] = 'provide'


class TutorTurn(Strict):
    content: str = Field(description='One teaching point, ordinarily 15–30 words. Combined with acknowledgment: at most 45 words and one question.')
    acknowledgment: str = Field(default='', description='Explicit, warm praise of one evidenced strength or actual progress. May be empty on other turns.')
    talk_moves: list[TalkMove]
    issue_id: str = ''
    stage: Literal['recognition','inquiry','thinking-dialogue','revision-planning','dialogue','complete'] = 'thinking-dialogue'
    focus_ids: list[str] = Field(default_factory=list, description='Existing object or relation IDs from current_diagram for this visual cue.')
    acknowledgment_ids: list[str] = Field(default_factory=list, description='Existing diagram part IDs for the work recognized in acknowledgment. On opening use the same IDs as focus_ids. Criterion IDs and issue IDs belong in other fields.')
    visual_action: Literal['none','highlight','trace'] = 'none'
    visual_delivery: Literal['none','automatic','on-request'] = 'none'
    mechanism_paths: list[MechanismPath] = Field(default_factory=list)
    mechanism_condition: str = ''
    edit_instruction: str = Field(default='', description='Exact visible instruction for one manual canvas action, copied verbatim from the reply. Enables student tools only; never executes an edit. Set next_step=revise when present; otherwise empty.')
    next_step: Literal['explain','clarify','revise','explore'] = 'explain'
    question_target: str = ''
    progress: Literal['progress','difficulty','uncertain','other'] = Field(default='other', description='Classify the current learner contribution: difficulty only for an actual incorrect answer/attempt on the active issue. Bare uncertainty or I do not know is uncertain; a request, question, or UI action alone is other. Neither adds an incorrect answer. Grounded correct reasoning or genuine advance is progress and resets the incorrect-answer streak. Judge a mixed substantive answer and request by its actual answer content.')
    memory_updates: list[MemoryUpdate] = Field(default_factory=list)
    move_evidence: MoveEvidence = Field(default_factory=MoveEvidence, description='Current move candidates only. Learner/context quotes are at most 25 exact words; needs and descriptions at most 35. Supporting-learning priority: meaning, reflection, prior knowledge, reasoning. This is not a Learner model update.')

    @model_validator(mode='after')
    def valid_moves(self):
        if len(self.talk_moves) != 1 and self.talk_moves != ['revoice','ask_for_clarification']:
            raise ValueError('Select one move or Revoice followed by Ask for clarification.')
        return self
