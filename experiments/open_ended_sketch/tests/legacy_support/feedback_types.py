"""Typed contracts for private assessment and public tutoring turns."""
from typing import Literal, get_args
from pydantic import BaseModel, ConfigDict, Field, model_validator


TalkMove = Literal['recognize_strengths','press_for_accuracy','revoice','ask_for_clarification',
                   'build_on_prior_knowledge','invite_elaboration_reasoning','prompt_reflection',
                   'provide_hints_guidance','propose_revision_plan','invite_dialogue','clarify_goals']
TALK_MOVES = get_args(TalkMove)


def canonical_talk_move(value):
    """Read the former combined ID without retaining it in the current contract."""
    return 'ask_for_clarification' if value=='revoice_or_clarify' else value


def normalize_move_fields(value,primary='talk_move',plural='talk_moves'):
    """Normalize a copied legacy record and validate the only supported pairing."""
    if not isinstance(value,dict) or primary not in value:return value
    result=dict(value)
    move=canonical_talk_move(result[primary])
    moves=result.get(plural,[])
    if not isinstance(moves,list):raise ValueError('Talk moves must be an ordered list.')
    moves=[canonical_talk_move(item) for item in moves] if moves else [move]
    if moves!=[move] and not (move=='revoice' and moves==['revoice','ask_for_clarification']):
        raise ValueError('Use the primary move alone or revoice followed by ask_for_clarification.')
    result[primary]=move
    result[plural]=moves
    return result

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Review(Strict):
    criterion: str
    status: Literal['established','developing','not-yet-visible','not-requested']
    strength: str
    gap: str
class Evidence(Strict):
    claim: str
    evidence: str
class TraceStep(Strict):
    relation_id: str
    direction: Literal['forward','backward']
class MechanismPath(Strict):
    label: str
    steps: list[TraceStep]
class Assessment(Strict):
    @model_validator(mode='before')
    @classmethod
    def read_move_contract(cls,value):
        return normalize_move_fields(value)

    criteria: list[Review]
    changed_criteria: list[str]
    strengths: list[Evidence]
    ambiguities: list[Evidence]
    areas_for_improvement: list[Evidence]
    criterion: str
    student_idea: str
    focus_id: str
    talk_move: TalkMove
    talk_moves: list[TalkMove] = Field(default_factory=list)
    ready_for_revision: bool
    inquiry_target: str
    avoid_telling: list[str]
    response_highlight_ids: list[str] = Field(default_factory=list)
    closing_requested: bool = False
    next_focus_kind: Literal['gap','clarification','extension','none'] = 'clarification'
    learning_goal: str = ''
    goal_unclear: bool = False
    student_stuck: bool = False
    current_response_outcome: Literal['not_applicable','successful','unsuccessful','uncertain'] = 'not_applicable'
    outcome_evidence: str = ''
    frustration_evidence: str = ''
    readiness_evidence: str = ''
    revision_resolved: bool = False
    recognized_strength_supported: bool = True
    solution_target_ids: list[str] = Field(default_factory=list)
    learner_identifications: list[Evidence] = Field(default_factory=list)
    visual_hint_needed: bool = False
    comparison_needed: bool = False
    comparison_evidence: str = ''
    visual_intent: Literal['inspect-diagram','explain-mechanism','conceptual','none'] = 'inspect-diagram'
    visual_focus_ids: list[str] = Field(default_factory=list)
    mechanism_paths: list[MechanismPath] = Field(default_factory=list)
    mechanism_condition: str = ''
    mechanism_requires_condition: bool = False
    learner_requested_revision: bool = False
    revision_reason_sufficient: bool = False
    revision_change_kind: Literal['none','conceptual','operational'] = 'conceptual'
    revision_understanding_evidence: str = ''
    progress_status: Literal['new','developing','ready','stalled'] = 'developing'
    current_question_target: str = ''
    learner_diagnosis_evidence: str = ''
    issue_priority_reason: str = ''
    prior_knowledge_connection: str = ''
    prior_knowledge_evidence: str = ''
    prior_knowledge_mode: Literal['established','activate'] = 'established'
    prior_knowledge_activation_evidence: str = ''
    reasoning_gap: str = ''
    cognitive_conflict: str = ''
    cognitive_conflict_evidence: str = ''
    revoice_need: str = ''
    revoice_evidence: str = ''
    clarification_need: str = ''
    reflection_target: str = ''
    reflection_evidence: str = ''
    reflection_reference: str = ''
    reflection_reference_source: Literal['none','task_or_observable','learner_demonstrated','tutor_provided'] = 'none'
    reflection_need: str = ''
    revision_outcome: Literal['not_reviewed','successful','unsuccessful','uncertain'] = 'not_reviewed'
    revision_outcome_evidence: str = ''
    task_figure_context: str = Field(default='',max_length=2000)
class TutorReply(Strict):
    new_conceptual_information: list[str] = Field(default_factory=list)
    check_observation: str = ''
    check_question: str = ''
    question_purpose: Literal['none','judge_current_diagram','clarify_meaning','develop_reasoning','plan_revision'] = 'none'
    reveals_diagnosis: bool = False
    guidance_instruction: str = ''
    guidance_requires_edit: bool = False
    acknowledgment: str = ''
    acknowledgment_ids: list[str] = Field(default_factory=list)
    content: str
    review: list[Review]
    focus_id: str
    focus_ids: list[str] = Field(default_factory=list)
    evidence_quote: str
    evidence_source: Literal['original','revision','dialogue']
    next_step: Literal['explain','clarify','annotate','revise','explore']
    revision_plan: str = ''
    revision_plan_ids: list[str] = Field(default_factory=list)
    visual_action: Literal['highlight','trace','none'] = 'none'
    visual_delivery: Literal['none','on-request','automatic'] = 'none'
    mechanism_paths: list[MechanismPath] = Field(default_factory=list)
    mechanism_condition: str = ''

class FastDialogueTurn(Strict):
    @model_validator(mode='before')
    @classmethod
    def read_move_contract(cls,value):
        return normalize_move_fields(value,'selected_talk_move','selected_talk_moves')

    assessment: Assessment
    selected_talk_move: TalkMove
    selected_talk_moves: list[TalkMove] = Field(default_factory=list)
    reply: TutorReply
