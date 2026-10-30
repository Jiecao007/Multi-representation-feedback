"""Historical scoped-v3 implementation, retained only for offline regressions.

Current runtime uses knowledge_model_agent.py with simple optional lists.
This module is not imported by the current learner entry point.

Stateful Knowledge Model Agent for the former two-agent architecture.

The language-model agent decides what a delivered Feedback move establishes.
This module supplies typed messages, public evidence, persistence and mechanical
reference checks. It is not another semantic assessor, learner-output gate or
task solver. Each delivered Feedback message is checked once before the next
Learner Agent action; editor-only actions do not trigger extra model checks.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

FORMAT = "knowledge-model-agent-v3"
STATUS = Literal["known", "tentative", "unlearned"]
CONTENT_ACTIONS = frozenset({"send_message", "add_text", "edit_text", "add_object",
                            "move", "add_connection", "edit_connection", "reshape_connection",
                            "resize", "delete", "undo", "submit_revisions"})
CLASSIFICATIONS = Literal["plain_question", "praise_or_acknowledgment", "concrete_explanation",
                          "concrete_hint", "attempt_feedback", "other"]


class KnowledgeAgentBoundaryError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InitialResponseEvidence(StrictModel):
    source: Literal["student_text", "student_figure"]
    quote: Optional[str]
    figure_index: Optional[int]
    observation: str


class InitialPositiveScope(StrictModel):
    statement: str
    evidence: list[InitialResponseEvidence]


class InitialComponentKnowledge(StrictModel):
    component_id: str
    status: STATUS
    evidence_summary: str
    remaining_uncertainty: str
    # None is only for explicitly reading old raw replies. Current calls must
    # distinguish [] (no positively supported local scope) from missing data.
    positive_scopes: Optional[list[InitialPositiveScope]] = None
    provisional_beliefs: list[InitialPositiveScope] = Field(default_factory=list)


class KnowledgeInitialization(StrictModel):
    initial_state_summary: str
    components: list[InitialComponentKnowledge]


class KnowledgeEvidence(StrictModel):
    reference: str
    quote: str


class KnowledgeComponentUpdate(StrictModel):
    component_id: str
    kind: Literal["local_support", "attempt_record", "independent_application", "refined_belief"]
    status: STATUS
    statement: str
    evidence: list[KnowledgeEvidence]
    remaining_uncertainty: str
    # New replies identify what each patch learns from. A missing value keeps
    # saved pre-split replies conservative rather than reinterpreting them.
    evidence_basis: Optional[Literal["instructional_content", "attempt_confirmation", "learner_attempt"]] = None


class TurnGivenFact(StrictModel):
    statement: str
    evidence: list[KnowledgeEvidence]


class UnderstoodProposition(StrictModel):
    statement: str
    scope_refs: list[str]
    given_fact_indices: list[int]


class ResponsePermissions(StrictModel):
    answer_mode: Literal["supported", "partial", "clarification"]
    can_attempt: bool
    clarification_target: Optional[str]


class CurrentTurnInterpretation(StrictModel):
    understood_request: str
    understood_propositions: list[UnderstoodProposition]
    unresolved_relations: list[str]
    relevant_scope_ids: list[str]
    new_scope_update_indices: list[int]
    given_facts: list[TurnGivenFact]
    response_permissions: ResponsePermissions


class KnowledgeMoveCheck(StrictModel):
    move_id: str
    classification: CLASSIFICATIONS
    decision: Literal["no_change", "update"]
    updates: list[KnowledgeComponentUpdate]
    memory_summary: str
    current_turn: Optional[CurrentTurnInterpretation] = None


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def scope_id(component_id, statement):
    """Stable identity for exact local content, independent of profile/owner."""
    return "scope:" + digest({"component_id": component_id, "statement": statement})[:20]


def fact_id(move_id, statement):
    return "fact:" + digest({"move_id": move_id, "statement": statement})[:20]


def belief_id(component_id, statement):
    return "belief:" + digest({"component_id": component_id, "statement": statement})[:20]


def _positive_scope(component_id, statement, basis, event_ids, **extra):
    return {"scope_id": scope_id(component_id, statement), "statement": statement,
            "basis": basis, "event_ids": event_ids, **extra}


def _finish(state):
    state["content_sha256"] = digest({"case_binding": state["case_binding"],
                                      "owner_id": state["owner_id"],
                                      "knowledge_profile_binding": state.get("knowledge_profile_binding"),
                                      "components": state["components"]})
    state["state_sha256"] = digest({key: value for key, value in state.items() if key != "state_sha256"})
    return state


def _new_state(case_config, prior_knowledge, owner_id, knowledge_profile=None):
    if knowledge_profile is not None and (
            not isinstance(knowledge_profile, dict)
            or not isinstance(knowledge_profile.get("level"), str)
            or not knowledge_profile["level"].strip()
            or not isinstance(knowledge_profile.get("definition"), str)
            or not isinstance(knowledge_profile.get("operational_behavior"), dict)):
        raise KnowledgeAgentBoundaryError("Knowledge profile must be the expanded selected uptake definition.")
    initial = case_config.get("initial_conceptual_state", {}).get("knowledge_components")
    if not isinstance(initial, list) or not initial:
        raise KnowledgeAgentBoundaryError("Knowledge Model Agent needs response-conditioned initial components.")
    prior = prior_knowledge or {}
    bound = {item["component_id"]: item for item in prior.get("components", [])}
    components = []
    seen = set()
    for item in initial:
        cid, status = item.get("component_id"), item.get("status")
        if not isinstance(cid, str) or not cid or cid in seen or status not in {"known", "tentative", "unlearned"}:
            raise KnowledgeAgentBoundaryError("Initial component identifiers and states must be valid and unique.")
        if not isinstance(item.get("statement"), str) or not item["statement"].strip():
            raise KnowledgeAgentBoundaryError("Each initial component needs a scoped statement.")
        seen.add(cid)
        binding = bound.get(cid, {})
        if binding and (binding.get("status") != status or binding.get("statement") != item["statement"]):
            raise KnowledgeAgentBoundaryError("Resolved prior differs from the initial response-conditioned seed.")
        # A seed status is an evidence hypothesis, not a positive procedure.
        # Initialization explicitly extracts usable content from the Response.
        scopes = []
        components.append({"component_id": cid, "label": item.get("label", cid),
                           "initial_status": status, "status": status,
                           "initial_statement": item["statement"], "statement": item["statement"],
                           "initial_limitation": binding.get("initial_limitation", ""),
                           "learning_requirement": binding.get("learning_requirement", ""),
                           "remaining_uncertainty": binding.get("initial_limitation", ""),
                           "available_knowledge": scopes, "attempted_beliefs": [],
                           "independent_evidence": []})
    if bound and set(bound) != seen:
        raise KnowledgeAgentBoundaryError("Resolved prior must cover the same initial components.")
    return _finish({"format": FORMAT, "agent": "KnowledgeModelAgent", "owner_id": owner_id,
                    "case_binding": digest({"case": case_config, "prior_knowledge": prior}),
                    "knowledge_profile_binding": digest(knowledge_profile) if knowledge_profile is not None else None,
                    "initialized": False, "revision": 0, "event_revision": 0,
                    "components": components, "processed_move_ids": [], "move_checks": [],
                    "initialization": None, "checked_action_steps": [], "current_turn": None,
                    "agent_memory": {"initial_state_summary": "", "latest_move_summary": ""},
                    "scope_policy": "Only positive available_knowledge scopes are usable content. Evidence uncertainty and remaining_uncertainty describe what the Response does not establish, not proven inability. Status does not unlock the named topic. Attempted beliefs are provisional, never self-confirming. Preserve the existing limited local-transfer boundary. Current-turn givens apply to the request, not general mastery. Knowledge Model Agent owns the record; Learner Agent cannot write or reinterpret it."})


def _public_attempt(entry):
    action = entry.get("action") or {}
    result = entry.get("result", entry.get("execution")) or {}
    proof = entry.get("learning_observation") or result.get("learning_observation") or {}
    kind = action.get("type")
    if kind not in CONTENT_ACTIONS or proof.get("noop") is True:
        return False
    if kind == "send_message":
        # A learner message may be delivered even when the subsequent Tutor
        # operation fails; public receipt, rather than operation.ok, is decisive.
        return (isinstance(action.get("text"), str) and bool(action["text"].strip())
                and (proof.get("learner_message_delivered") is True
                     or bool(proof.get("user_message_indices"))
                     or result.get("ok") is True and proof.get("content_attempt") is not False))
    return (result.get("ok") is True and not result.get("error")
            and (proof.get("content_attempt") is True or proof.get("diagram_changed") is True
                 or kind in {"add_text", "add_object", "add_connection"}
                 and bool((result.get("result") or {}).get("id"))))


def public_moves(observation):
    moves, seen = [], set()
    for message in observation.get("messages", []):
        if message.get("role") not in {"assistant", "tutor"} or message.get("error"):
            continue
        index, text = message.get("index"), message.get("text")
        if not isinstance(index, int) or isinstance(index, bool) or not isinstance(text, str):
            raise KnowledgeAgentBoundaryError("Delivered Feedback moves need stable integer indices and visible text.")
        mid = "message:" + str(index)
        if mid in seen:
            raise KnowledgeAgentBoundaryError("Delivered Feedback move identifiers must be unique.")
        seen.add(mid)
        payload = {"message_index": index, "text": text}
        moves.append({"move_id": mid, "message_index": index, "text": text,
                      "sha256": digest(payload), "payload": payload})
    return moves


def _public_evidence(move, observation, history, state):
    evidence = {move["move_id"]: {"reference": move["move_id"], "kind": "feedback_move",
                                   "text": move["text"], "message_index": move["message_index"]}}
    current_index = move["message_index"]
    for entry in history:
        if not isinstance(entry, dict):
            continue
        step = entry.get("step")
        if not isinstance(step, int) or isinstance(step, bool) or step < 1:
            continue
        proof = entry.get("learning_observation") or {}
        result = entry.get("result", entry.get("execution")) or {}
        action = entry.get("action") or {}
        user_indices = proof.get("user_message_indices") or []
        feedback_indices = proof.get("feedback_message_indices") or []
        context_move = proof.get("action_context_move_id")
        if isinstance(context_move, str) and context_move.startswith("message:"):
            try:
                context_index = int(context_move.split(":", 1)[1])
            except ValueError:
                context_index = None
            if context_index is not None and context_index >= current_index:
                # The action happened after receiving this or a later move;
                # it was not evidence available for the pre-action check.
                continue
        # Do not make a future action available while replaying an earlier move.
        if user_indices and min(user_indices) >= current_index:
            continue
        if not user_indices and feedback_indices and min(feedback_indices) > current_index:
            continue
        legacy_ui_without_timing = (action.get("type") != "send_message"
                                    and not context_move and not user_indices and not feedback_indices)
        if _public_attempt(entry) and not legacy_ui_without_timing:
            ref = "action:" + str(step)
            evidence[ref] = {"reference": ref, "kind": "completed_attempt",
                             "text": canonical({key: value for key, value in action.items() if value is not None}),
                             "step": step, "action": deepcopy(action),
                             "feedback_message_indices": feedback_indices,
                             "user_message_indices": user_indices}
        if (action.get("type") == "show_feedback" and result.get("ok") is True
                and proof.get("visible_support_revealed") is True
                and isinstance(proof.get("visible_elements"), list)
                and proof.get("message_index", current_index + 1) <= current_index):
            ref = "figure:" + str(step)
            evidence[ref] = {"reference": ref, "kind": "revealed_figure",
                             "text": canonical({"visible_text": proof.get("visible_text", ""),
                                                "visible_elements": proof["visible_elements"]}),
                             "originating_move_id": "message:" + str(proof["message_index"]),
                             "deferred_to_next_move": "message:" + str(proof["message_index"]) in state["processed_move_ids"]}
    # Previous actually delivered moves remain evidence, without being checked
    # again or counted as a new exposure.
    for item in state["move_checks"]:
        past = item["move"]
        evidence[past["move_id"]] = {"reference": past["move_id"], "kind": "feedback_move",
                                     "text": past["text"], "message_index": past["message_index"]}
    return evidence


class KnowledgeModelAgent:
    """Persistent semantic-agent memory, with no external model/API coupling.

    The caller invokes its chosen model with initialization_payload or
    move_payload and the corresponding strict schema. Only this agent's replies
    are passed to initialize/check_move. Learner output is never accepted here.
    """

    def __init__(self, case_config, prior_knowledge=None, owner_id=None, persisted=None,
                 knowledge_profile=None):
        self.case_config = deepcopy(case_config)
        self.prior_knowledge = deepcopy(prior_knowledge or {})
        initial = _new_state(case_config, prior_knowledge, owner_id, knowledge_profile)
        if persisted is None:
            self.state = initial
            return
        if not isinstance(persisted, dict) or persisted.get("format") != FORMAT:
            raise KnowledgeAgentBoundaryError("Unsupported Knowledge Model Agent state format.")
        if persisted.get("owner_id") != owner_id or persisted.get("case_binding") != initial["case_binding"]:
            raise KnowledgeAgentBoundaryError("Knowledge Model Agent memory belongs to another case or learner.")
        if persisted.get("knowledge_profile_binding") != initial["knowledge_profile_binding"]:
            raise KnowledgeAgentBoundaryError("Knowledge Model Agent memory uses another uptake profile; start a new learner instance.")
        if persisted.get("state_sha256") != digest({key: value for key, value in persisted.items() if key != "state_sha256"}):
            raise KnowledgeAgentBoundaryError("Knowledge Model Agent state digest mismatch.")
        if not isinstance(persisted.get("processed_move_ids"), list) or len(persisted["processed_move_ids"]) != len(set(persisted["processed_move_ids"])):
            raise KnowledgeAgentBoundaryError("Knowledge Model Agent contains duplicate processed moves.")
        if [entry.get("move", {}).get("move_id") for entry in persisted.get("move_checks", [])] != persisted["processed_move_ids"]:
            raise KnowledgeAgentBoundaryError("Knowledge check log differs from its processed-move cursor.")
        if {item["component_id"] for item in persisted.get("components", [])} != {item["component_id"] for item in initial["components"]}:
            raise KnowledgeAgentBoundaryError("Knowledge Model Agent component identifiers changed.")
        for component in persisted["components"]:
            ids = []
            for value in component.get("available_knowledge", []):
                expected = scope_id(component["component_id"], value.get("statement"))
                if value.get("scope_id") != expected:
                    raise KnowledgeAgentBoundaryError("Positive scope identity differs from its exact content.")
                ids.append(expected)
            if len(ids) != len(set(ids)):
                raise KnowledgeAgentBoundaryError("Positive scope identifiers must be unique within a component.")
        self.state = deepcopy(persisted)

    def initialization_payload(self, public_initial_context=None):
        if self.state["initialized"]:
            raise KnowledgeAgentBoundaryError("Knowledge Model Agent was already initialized.")
        return {"mode": "initialize", "case_config": deepcopy(self.case_config),
                "response_conditioned_prior": deepcopy(self.prior_knowledge),
                "initial_components": deepcopy(self.state["components"]),
                "initial_response": deepcopy(public_initial_context or {}),
                "instruction": "Read the actual task and initial student text/Figure. Separate positively supported usable scopes from evidence uncertainty and provisional beliefs. Return positive_scopes for every component, including [] where no positive scope is evidenced. Missing evidence is not itself inability; do not add a blanket support requirement or infer a solution from general model knowledge."}

    def initialize(self, parsed, *, public_initial_context=None, require_current=False):
        if self.state["initialized"]:
            raise KnowledgeAgentBoundaryError("Knowledge Model Agent initialization is exactly once.")
        if isinstance(parsed, dict):
            parsed = KnowledgeInitialization.model_validate(parsed)
        if require_current and any(item.positive_scopes is None for item in parsed.components):
            raise KnowledgeAgentBoundaryError("Current initialization requires explicit positive_scopes for every component.")
        notes, warnings, seen = [], [], set()
        components = {item["component_id"]: item for item in self.state["components"]}
        if require_current and (len(parsed.components) != len(components)
                                or {item.component_id for item in parsed.components} != set(components)):
            raise KnowledgeAgentBoundaryError("Current initialization requires one note for every component.")
        for item in parsed.components:
            if item.component_id not in components or item.component_id in seen:
                warnings.append({"component_id": item.component_id, "reason": "Unknown or repeated initialization component ignored."})
                continue
            seen.add(item.component_id)
            baseline = components[item.component_id]
            # A response-conditioned starting prior is shared research input.
            # The agent records its reading, without silently replacing those
            # assumptions with a more capable model's own task knowledge.
            if item.status != baseline["initial_status"]:
                warnings.append({"component_id": item.component_id, "reason": "Initialization status differs from the shared response-conditioned prior; configured prior retained."})
            baseline["remaining_uncertainty"] = item.remaining_uncertainty
            if item.positive_scopes is None:
                # Historical raw replies did not separate positive scopes.
                # Retain only the explicit known seed for those offline readers;
                # tentative evidence-absence prose never becomes usable content.
                if baseline["initial_status"] == "known":
                    baseline["available_knowledge"] = [_positive_scope(
                        item.component_id, baseline["initial_statement"], "initial_known",
                        ["initial:" + item.component_id])]
            else:
                context = public_initial_context or {}
                text = context.get("student_response_text", context.get("text", self.case_config.get("initial_explanation", "")))
                figures = [value for value in context.get("figures", [])
                           if value.get("role") == "student_response_figure"]
                claims = [("positive_scopes", number, value) for number, value in enumerate(item.positive_scopes)]
                claims += [("provisional_beliefs", number, value) for number, value in enumerate(item.provisional_beliefs)]
                for category, number, value in claims:
                    reason = None
                    if not value.statement.strip() or not value.evidence:
                        reason = "An initial scope or belief needs content and actual student-response evidence."
                    for source in value.evidence:
                        if not source.observation.strip():
                            reason = "Initial response evidence needs a concrete observation."
                        elif source.source == "student_text" and (
                                not source.quote or source.quote not in text or source.figure_index is not None):
                            reason = "Initial text evidence must quote the student's original Response exactly."
                        elif source.source == "student_figure" and (
                                source.quote is not None or source.figure_index is None
                                or isinstance(source.figure_index, bool)
                                or not 0 <= source.figure_index < len(figures)):
                            reason = "Initial Figure evidence must identify an actually supplied student Figure."
                    if reason:
                        warnings.append({"component_id": item.component_id, "field": category, "scope_index": number,
                                         "reason": reason, "rejected_scope": value.model_dump()})
                        continue
                    if category == "provisional_beliefs":
                        belief = {"belief_id": belief_id(item.component_id, value.statement),
                                  "statement": value.statement, "basis": "response_provisional_belief",
                                  "event_ids": ["initial:" + item.component_id],
                                  "response_evidence": [source.model_dump() for source in value.evidence]}
                        if not any(old.get("belief_id") == belief["belief_id"] for old in baseline["attempted_beliefs"]):
                            baseline["attempted_beliefs"].append(belief)
                        continue
                    positive = _positive_scope(item.component_id, value.statement, "response_demonstrated",
                                               ["initial:" + item.component_id],
                                               response_evidence=[source.model_dump() for source in value.evidence])
                    if not any(old["scope_id"] == positive["scope_id"] for old in baseline["available_knowledge"]):
                        baseline["available_knowledge"].append(positive)
            notes.append(item.model_dump())
        if seen != set(components):
            if require_current:
                raise KnowledgeAgentBoundaryError("Current initialization requires one note for every component.")
            warnings.append({"reason": "Missing initialization notes retained the existing response-conditioned prior."})
        self.state["initialized"] = True
        self.state["initialization"] = {"reply": parsed.model_dump(), "component_notes": notes, "warnings": warnings}
        self.state["agent_memory"]["initial_state_summary"] = parsed.initial_state_summary
        _finish(self.state)
        return {"mode": "initialize", "check_complete": True, "warnings": warnings,
                "after": deepcopy(self.state), "semantic_authority": "KnowledgeModelAgent"}

    def pending_moves(self, observation, history=None):
        actual = public_moves(observation)
        by_id = {item["move_id"]: item for item in actual}
        for entry in self.state["move_checks"]:
            if by_id.get(entry["move"]["move_id"]) != entry["move"]:
                raise KnowledgeAgentBoundaryError("Previously checked Feedback move differs from delivered public history.")
        return [item for item in actual if item["move_id"] not in self.state["processed_move_ids"]]

    def move_payload(self, move, observation, history):
        if not self.state["initialized"]:
            raise KnowledgeAgentBoundaryError("Initialize the Knowledge Model Agent before checking moves.")
        if move["move_id"] in self.state["processed_move_ids"]:
            raise KnowledgeAgentBoundaryError("A delivered Feedback move cannot be checked twice.")
        actual = {item["move_id"]: item for item in public_moves(observation)}
        if actual.get(move["move_id"]) != move:
            raise KnowledgeAgentBoundaryError("Move is not a delivered public Feedback message.")
        evidence = _public_evidence(move, observation, history, self.state)
        return {"mode": "check_move", "move": deepcopy(move),
                "knowledge_model": self.project(), "agent_memory": deepcopy(self.state["agent_memory"]),
                "available_evidence": list(evidence.values()),
                "new_attempt_references": [ref for ref, value in evidence.items()
                                           if value["kind"] == "completed_attempt" and value["step"] not in self.state["checked_action_steps"]],
                "public_observation": deepcopy(observation)}

    def check_move(self, move, parsed, *, observation=None, history=None, evidence=None,
                   require_current=False):
        if not self.state["initialized"]:
            raise KnowledgeAgentBoundaryError("Initialize the Knowledge Model Agent before checking moves.")
        if move["move_id"] in self.state["processed_move_ids"]:
            raise KnowledgeAgentBoundaryError("A delivered Feedback move cannot be checked twice.")
        if isinstance(parsed, dict):
            parsed = KnowledgeMoveCheck.model_validate(parsed)
        if require_current and (parsed.current_turn is None or parsed.move_id != move["move_id"]):
            raise KnowledgeAgentBoundaryError("Current move checks require a complete current_turn for the exact delivered move.")
        if parsed.current_turn is not None and not parsed.current_turn.understood_request.strip():
            raise KnowledgeAgentBoundaryError("Current-turn interpretation needs a request description, without its answer.")
        evidence_map = evidence or _public_evidence(move, observation or {}, history or [], self.state)
        if isinstance(evidence_map, list):
            evidence_map = {item["reference"]: item for item in evidence_map}
        if move["move_id"] not in evidence_map:
            raise KnowledgeAgentBoundaryError("Knowledge check lacks its delivered Feedback evidence.")
        before = deepcopy(self.state)
        warnings, accepted, accepted_scope_refs = [], [], {}
        components = {item["component_id"]: item for item in self.state["components"]}
        no_learning = parsed.classification in {"plain_question", "praise_or_acknowledgment", "other"}
        for number, update in enumerate(parsed.updates):
            reason = None
            refs = [item.reference for item in update.evidence]
            sources = [evidence_map[ref] for ref in refs if ref in evidence_map]
            basis = update.evidence_basis
            if basis is None:
                # Preserve the old contract for historical replies: local
                # support under attempt_feedback still requires an attempt.
                basis = ("attempt_confirmation" if update.kind == "independent_application"
                         or update.kind == "local_support" and parsed.classification == "attempt_feedback"
                         else "instructional_content" if update.kind == "local_support"
                         else "learner_attempt")
            if parsed.move_id != move["move_id"]:
                reason = "Agent replied for another move; update ignored."
            elif parsed.decision == "no_change":
                reason = "Agent declared no change; contradictory update ignored."
            elif update.component_id not in components:
                reason = "Unknown component identifier."
            elif not update.statement.strip() or not update.evidence:
                reason = "An update requires a scoped statement and actual evidence."
            elif any(item.reference not in evidence_map or not item.quote.strip()
                     or item.quote not in evidence_map[item.reference]["text"] for item in update.evidence):
                reason = "Evidence reference or exact public quote is invalid."
            elif (update.kind == "local_support" and basis not in {"instructional_content", "attempt_confirmation"}
                    or update.kind == "independent_application" and basis != "attempt_confirmation"
                    or update.kind in {"attempt_record", "refined_belief"} and basis != "learner_attempt"):
                reason = "Evidence basis does not match the kind of knowledge update."
            elif update.kind == "local_support" and no_learning:
                reason = "A plain question, praise or other event does not supply new knowledge."
            elif update.kind == "local_support" and not any(source["kind"] in {"feedback_move", "revealed_figure"} for source in sources):
                reason = "Local support needs delivered Feedback content or a revealed Figure."
            elif (update.kind == "local_support" and update.evidence_basis == "instructional_content"
                    and move["move_id"] not in refs
                    and not any(source["kind"] == "revealed_figure" for source in sources)):
                reason = "New instructional content needs the current delivered move or a revealed Figure."
            elif update.kind == "local_support" and basis == "attempt_confirmation" and not any(
                    source["kind"] == "completed_attempt" for source in sources):
                reason = "Attempt-feedback support must cite the actual completed attempt as well as support."
            elif update.kind == "local_support" and basis == "attempt_confirmation" and (
                    move["move_id"] not in refs or not any(
                        move["message_index"] in source.get("feedback_message_indices", [])
                        for source in sources if source["kind"] == "completed_attempt")):
                reason = "Confirming Feedback is not linked to the cited actual attempt."
            elif update.kind == "attempt_record" and not any(source["kind"] == "completed_attempt" for source in sources):
                reason = "A provisional attempted belief needs an actual completed attempt."
            elif update.kind == "refined_belief" and not any(source["kind"] == "completed_attempt" for source in sources):
                reason = "A refined provisional belief needs an actual completed attempt."
            elif update.kind == "independent_application" and (parsed.classification != "attempt_feedback"
                    or not any(source["kind"] == "completed_attempt" for source in sources)
                    or move["move_id"] not in refs):
                reason = "Independent local application needs the current feedback move and an actual completed attempt."
            elif update.kind == "independent_application" and not any(
                    move["message_index"] in source.get("feedback_message_indices", [])
                    for source in sources if source["kind"] == "completed_attempt"):
                reason = "Confirming Feedback is not linked to the cited actual attempt."
            elif update.kind in {"attempt_record", "refined_belief"} and update.status != components[update.component_id]["status"]:
                reason = "Provisional belief recording cannot promote knowledge status."
            elif update.kind == "local_support" and update.status == "known" and components[update.component_id]["status"] != "known":
                reason = "Received support alone is not independent mastery; tentative status required."
            if reason:
                warnings.append({"update_index": number, "component_id": update.component_id, "reason": reason,
                                 "rejected_update": update.model_dump()})
                continue
            component = components[update.component_id]
            value = {"statement": update.statement,
                     "basis": {"local_support": "received_local_support", "attempt_record": "provisional_attempt",
                               "refined_belief": "refined_provisional_belief", "independent_application": "independently_applied_with_feedback"}[update.kind],
                     "event_ids": list(dict.fromkeys(refs)),
                     "evidence_basis": basis,
                     "source_quotes": [item.model_dump() for item in update.evidence]}
            target = component["attempted_beliefs"] if update.kind in {"attempt_record", "refined_belief"} else component["available_knowledge"]
            if update.kind not in {"attempt_record", "refined_belief"}:
                value["scope_id"] = scope_id(update.component_id, update.statement)
                accepted_scope_refs["update:" + str(number)] = value["scope_id"]
            else:
                value["belief_id"] = belief_id(update.component_id, update.statement)
            duplicate = any(item.get("scope_id") == value["scope_id"] for item in target) if "scope_id" in value else any(
                item["statement"] == value["statement"] and item["basis"] == value["basis"] for item in target)
            if duplicate and update.kind == "independent_application":
                # The same content can acquire new independent evidence without
                # acquiring a second identity or requiring a paraphrase.
                existing = next(item for item in target if item["scope_id"] == value["scope_id"])
                existing["basis"] = value["basis"]
                existing["evidence_basis"] = value["evidence_basis"]
                existing["event_ids"] = list(dict.fromkeys(existing["event_ids"] + value["event_ids"]))
                quotes = existing.setdefault("source_quotes", [])
                quotes.extend(quote for quote in value["source_quotes"] if quote not in quotes)
                if value not in component["independent_evidence"]:
                    component["independent_evidence"].append(deepcopy(value))
                component["status"] = update.status
                component["statement"] = update.statement
                component["remaining_uncertainty"] = update.remaining_uncertainty
                accepted.append(update.model_dump())
                continue
            if not duplicate:
                target.append(value)
                if update.kind == "independent_application":
                    component["independent_evidence"].append(deepcopy(value))
                if update.kind not in {"attempt_record", "refined_belief"}:
                    component["status"] = update.status
                    component["statement"] = update.statement
                component["remaining_uncertainty"] = update.remaining_uncertainty
                accepted.append(update.model_dump())
        if parsed.move_id != move["move_id"] and not parsed.updates:
            warnings.append({"reason": "Agent replied for another move; recorded a conservative no-change check."})
        turn, turn_warnings = self._interpret_turn(move, parsed.current_turn, evidence_map, accepted_scope_refs)
        self.state["current_turn"] = turn
        record = {"move": deepcopy(move), "reply": parsed.model_dump(), "accepted_updates": accepted,
                  "rejected_updates": warnings, "check_complete": True,
                  "decision": "updated" if accepted else "no_change", "evidence": deepcopy(list(evidence_map.values())),
                  "current_turn": deepcopy(turn), "interpretation_warnings": turn_warnings}
        self.state["processed_move_ids"].append(move["move_id"])
        self.state["move_checks"].append(record)
        steps = [value["step"] for value in evidence_map.values() if value["kind"] == "completed_attempt"]
        self.state["checked_action_steps"] = sorted(set(self.state["checked_action_steps"]) | set(steps))
        self.state["event_revision"] += 1
        self.state["agent_memory"]["latest_move_summary"] = parsed.memory_summary
        if self.state["components"] != before["components"]:
            self.state["revision"] += 1
        _finish(self.state)
        return {"mode": "check_move", "move_id": move["move_id"], "check_complete": True,
                "decision": record["decision"], "accepted_updates": accepted, "rejected_updates": warnings,
                "interpretation_warnings": turn_warnings,
                "before": before, "after": deepcopy(self.state),
                "semantic_authority": "KnowledgeModelAgent"}

    def _interpret_turn(self, move, interpretation, evidence_map, accepted_scope_refs):
        """Resolve semantic-agent claims to actual positive scope/fact identities.

        This checks provenance only. Whether a paraphrase expresses what the
        learner understands remains the existing Knowledge Model Agent's job.
        """
        if interpretation is None:
            return None, []  # Historical raw replies are never current run_* calls.
        if not interpretation.understood_request.strip():
            raise KnowledgeAgentBoundaryError("Current-turn interpretation needs a request description, without its answer.")
        existing = {value["scope_id"] for component in self.state["components"]
                    for value in component["available_knowledge"]}
        warnings, facts, fact_indices = [], [], {}
        for number, value in enumerate(interpretation.given_facts):
            if (not value.statement.strip() or not value.evidence or any(
                    item.reference not in evidence_map or not item.quote.strip()
                    or item.quote not in evidence_map[item.reference]["text"]
                    or evidence_map[item.reference]["kind"] not in {"feedback_move", "revealed_figure"}
                    for item in value.evidence)):
                warnings.append({"field": "given_facts", "index": number,
                                 "reason": "A current-question given needs exact delivered instructional evidence; an attempt cannot confirm itself."})
                continue
            fid = fact_id(move["move_id"], value.statement)
            fact_indices[number] = fid
            if not any(old["fact_id"] == fid for old in facts):
                facts.append({"fact_id": fid, "statement": value.statement,
                              "source_quotes": [item.model_dump() for item in value.evidence]})

        def resolve(ref):
            resolved = accepted_scope_refs.get(ref, ref)
            return resolved if resolved in existing else None

        relevant = []
        for ref in interpretation.relevant_scope_ids + ["update:" + str(index) for index in interpretation.new_scope_update_indices]:
            resolved = resolve(ref)
            if resolved is None:
                warnings.append({"field": "relevant_scope_ids", "reference": ref,
                                 "reason": "Reference is not an existing or accepted positive scope."})
            elif resolved not in relevant:
                relevant.append(resolved)
        propositions = []
        for number, value in enumerate(interpretation.understood_propositions):
            refs = [resolve(ref) for ref in value.scope_refs]
            givens = [fact_indices.get(index) for index in value.given_fact_indices]
            if (not value.statement.strip() or not refs and not givens
                    or any(ref is None for ref in refs + givens)):
                warnings.append({"field": "understood_propositions", "index": number,
                                 "reason": "An understood proposition must cite positive scopes or valid question givens; summaries and provisional beliefs cannot establish it."})
                continue
            refs = list(dict.fromkeys(refs))
            propositions.append({"statement": value.statement, "scope_ids": refs,
                                 "given_fact_ids": list(dict.fromkeys(givens))})
            relevant.extend(ref for ref in refs if ref not in relevant)
        permissions = interpretation.response_permissions.model_dump()
        if warnings and permissions["answer_mode"] == "supported":
            permissions["answer_mode"] = "partial" if relevant or facts else "clarification"
        return {"move_id": move["move_id"], "understood_request": interpretation.understood_request,
                "understood_propositions": propositions,
                "unresolved_relations": list(interpretation.unresolved_relations),
                "relevant_scope_ids": relevant, "given_facts": facts,
                "response_permissions": permissions}, warnings

    def project(self):
        return {"format": FORMAT, "agent": "KnowledgeModelAgent", "initialized": self.state["initialized"],
                "revision": self.state["revision"], "content_sha256": self.state["content_sha256"],
                "scope_policy": self.state["scope_policy"], "components": deepcopy(self.state["components"]),
                "current_turn": deepcopy(self.state["current_turn"]),
                "last_checked_move_id": self.state["processed_move_ids"][-1] if self.state["processed_move_ids"] else None}

    def learner_projection(self):
        """Positive semantic content and interpreted feedback, without raw quotes."""
        projected = self.project()
        projected["components"] = [{
            "component_id": component["component_id"], "label": component["label"],
            "status": component["status"],
            "available_knowledge": [{key: deepcopy(value[key]) for key in ("scope_id", "statement", "basis")}
                                    for value in component["available_knowledge"]],
            "evidence_uncertainty": component["remaining_uncertainty"],
            "provisional_beliefs": [{"belief_id": value.get("belief_id"), "statement": value["statement"],
                                     "basis": value["basis"]} for value in component["attempted_beliefs"]],
        } for component in self.state["components"]]
        if projected["current_turn"] is not None:
            projected["current_turn"]["given_facts"] = [
                {"fact_id": value["fact_id"], "statement": value["statement"]}
                for value in projected["current_turn"]["given_facts"]]
        return projected

    def memory_component_states(self):
        result = []
        for component in self.state["components"]:
            evidence = []
            for scope in component["available_knowledge"]:
                for ref in scope["event_ids"]:
                    source = "initial_case" if ref.startswith("initial:") else "visible_message" if ref.startswith("message:") else "completed_action"
                    value = {"source": source, "reference": ref.replace("figure:", "action:"), "support": scope["statement"]}
                    if value not in evidence:
                        evidence.append(value)
            result.append({"component_id": component["component_id"], "status": component["status"],
                           "statement": component["statement"], "evidence": evidence})
        return result

    def save(self, path):
        """Persist the agent's own memory atomically; never accept actor memory."""
        from pathlib import Path
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(destination)

    def save_memory(self, path):
        self.save(path)

    def run_initialize(self, call_adapter, public_initial_context=None, *, memory_path=None):
        """Agent thinks through the injected LLM endpoint, then stores its memory.

        Adapter signature is (payload: dict, response_schema: type) -> parsed
        Pydantic reply. The adapter owns SDK transport and exact call logging.
        """
        payload = self.initialization_payload(public_initial_context)
        parsed = call_adapter(payload, KnowledgeInitialization)
        receipt = self.initialize(parsed, public_initial_context=public_initial_context, require_current=True)
        if memory_path is not None:
            self.save_memory(memory_path)
        return receipt

    def run_move(self, call_adapter, move, observation, history, *, memory_path=None):
        """Check one delivered move through the Agent, then persist before reply."""
        payload = self.move_payload(move, observation, history)
        parsed = call_adapter(payload, KnowledgeMoveCheck)
        receipt = self.check_move(move, parsed, evidence=payload["available_evidence"], require_current=True)
        if memory_path is not None:
            self.save_memory(memory_path)
        return receipt
