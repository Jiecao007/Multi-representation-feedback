"""Controller-owned learner knowledge, grounded in public interaction events.

An assessor may classify events and propose narrow updates. It cannot directly
set knowledge status. The deterministic controller owns transitions and replays
the complete update ledger when accepting a persisted model. Classification and
semantic entailment still require model-assisted assessment; hashes are integrity
checks, not a claim that a simulated state measures real human mastery.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

FORMAT = "learner-knowledge-v1"
CONTENT_ACTIONS = frozenset({"send_message", "add_text", "edit_text", "add_object",
                             "move", "add_connection", "edit_connection",
                             "reshape_connection", "resize", "delete", "undo",
                             "submit_revisions"})
SUPPORT_KINDS = frozenset({"concrete_explanation", "concrete_hint", "attempt_feedback"})
NO_UPDATE_KINDS = frozenset({"plain_question", "praise_or_acknowledgment", "other"})


class KnowledgeBoundaryError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgePatch(StrictModel):
    component_id: str
    kind: Literal["support_received", "attempt_observed", "independent_application"]
    statement: str
    evidence_quote: str
    support_event_ids: list[str]
    confirmation_event_id: Optional[str]


class KnowledgeEventDecision(StrictModel):
    event_id: str
    kind: Literal["plain_question", "praise_or_acknowledgment", "concrete_explanation",
                  "concrete_hint", "completed_attempt", "attempt_feedback", "other"]
    updates: list[KnowledgePatch]


class KnowledgeUpdateProposal(StrictModel):
    events: list[KnowledgeEventDecision]


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _finish(state):
    state["content_sha256"] = _hash({"case_binding": state["case_binding"],
                                     "owner_id": state["owner_id"],
                                     "components": state["components"]})
    state["state_sha256"] = _hash({key: value for key, value in state.items()
                                   if key != "state_sha256"})
    return state


def initialize_knowledge_model(case_config, prior_knowledge=None, *, owner_id=None):
    initial = case_config.get("initial_conceptual_state", {}).get("knowledge_components")
    if not isinstance(initial, list) or not initial:
        raise KnowledgeBoundaryError("A learner knowledge model needs initial case components.")
    prior = prior_knowledge or {}
    bound = {item["component_id"]: item for item in prior.get("components", [])}
    components = []
    seen = set()
    for item in initial:
        component_id = item.get("component_id")
        status = item.get("status")
        if (not isinstance(component_id, str) or not component_id.strip() or component_id in seen
                or status not in {"known", "tentative", "unlearned"}
                or not isinstance(item.get("statement"), str) or not item["statement"].strip()):
            raise KnowledgeBoundaryError("Initial knowledge components need unique IDs and valid states.")
        seen.add(component_id)
        binding = bound.get(component_id, {})
        if binding and (binding.get("status") != status or binding.get("statement") != item["statement"]):
            raise KnowledgeBoundaryError("Resolved prior disagrees with the case starting state.")
        initial_scope = []
        if status != "unlearned":
            initial_scope.append({"statement": item["statement"],
                                  "basis": "initial_known" if status == "known" else "initial_tentative",
                                  "event_ids": ["initial:" + component_id]})
        components.append({"component_id": component_id,
                           "label": item.get("label", component_id),
                           "initial_status": status, "status": status,
                           "initial_statement": item["statement"],
                           "statement": item["statement"],
                           "initial_limitation": binding.get("initial_limitation", ""),
                           "learning_requirement": binding.get("learning_requirement", ""),
                           "unresolved_scope": "The initial limitation continues to apply outside the explicit local statements in available_knowledge; a status label does not release the whole named component.",
                           "available_knowledge": initial_scope,
                           "attempted_beliefs": [], "independent_evidence": []})
    if bound and set(bound) != seen:
        raise KnowledgeBoundaryError("Resolved prior must cover exactly the case components.")
    # Bind all response evidence, including Figure provenance and grounding,
    # rather than assuming that a reused source ID identifies identical content.
    binding_data = {"case": case_config, "resolved_prior": prior}
    return _finish({"format": FORMAT, "case_binding": _hash(binding_data),
                    "owner_id": owner_id, "revision": 0, "event_revision": 0,
                    "components": components, "processed_event_ids": [],
                    "event_ledger": [],
                    "scope_policy": "Only explicitly available local statements may support responses or diagram actions. A component status never unlocks its entire named topic; initial limits remain for the unsupported remainder. Attempted beliefs are provisional, not established procedures. Controller states are constructed simulation records, not measured human mastery."})


def _meaningful_action(entry):
    action = entry.get("action") or {}
    result = entry.get("result", entry.get("execution")) or {}
    kind = action.get("type")
    if kind not in CONTENT_ACTIONS or result.get("ok") is not True or result.get("error"):
        return False
    proof = entry.get("learning_observation") or result.get("learning_observation") or {}
    if proof.get("noop") is True or proof.get("changed") is False and kind != "send_message":
        return False
    if kind == "send_message":
        return bool(isinstance(action.get("text"), str) and action["text"].strip()
                    and proof.get("content_attempt") is not False)
    if "content_attempt" in proof:
        return proof["content_attempt"] is True
    if "diagram_changed" in proof:
        return proof["diagram_changed"] is True
    if proof.get("diagram_changed") is True or proof.get("content_attempt") is True:
        return True
    # Legacy driver creation methods return the actual created object ID.
    # Opening the library or cancelling it returns no ID and cannot qualify.
    return (kind in {"add_text", "add_object", "add_connection"}
            and bool((result.get("result") or {}).get("id")))


def public_learning_events(observation, history):
    """Extract delivered tutor support and completed, meaningful attempts."""
    events = []
    seen = set()
    for message in observation.get("messages", []):
        if message.get("role") not in {"assistant", "tutor"} or message.get("error"):
            continue
        index = message.get("index")
        text = message.get("text")
        if not isinstance(index, int) or isinstance(index, bool) or not isinstance(text, str):
            raise KnowledgeBoundaryError("Public tutor messages require stable integer indices and text.")
        event_id = "message:" + str(index)
        if event_id in seen:
            raise KnowledgeBoundaryError("Public event IDs must be unique.")
        seen.add(event_id)
        payload = {"text": text, "message_index": index}
        events.append({"event_id": event_id, "source": "tutor_message", "text": text,
                       "payload": payload, "sha256": _hash(payload)})
    public_tutor_indices = {event["payload"]["message_index"] for event in events}
    for entry in history:
        if not isinstance(entry, dict):
            continue
        result = entry.get("result", entry.get("execution")) or {}
        proof = entry.get("learning_observation") or result.get("learning_observation") or {}
        visual_support = (entry.get("action", {}).get("type") == "show_feedback"
                          and result.get("ok") is True and not result.get("error")
                          and proof.get("noop") is not True
                          and proof.get("visible_support_revealed") is True)
        if visual_support and (proof.get("message_index") not in public_tutor_indices
                               or not isinstance(proof.get("visible_text"), str)
                               or not isinstance(proof.get("visible_elements"), list)
                               or not proof["visible_elements"]):
            raise KnowledgeBoundaryError("Revealed tutor Figures require an actual public message and visible elements.")
        if not visual_support and not _meaningful_action(entry):
            continue
        step = entry.get("step")
        if not isinstance(step, int) or isinstance(step, bool) or step < 1:
            raise KnowledgeBoundaryError("Completed attempts require stable positive step IDs.")
        event_id = "action:" + str(step)
        if event_id in seen:
            raise KnowledgeBoundaryError("Public event IDs must be unique.")
        seen.add(event_id)
        action = {key: value for key, value in entry["action"].items() if value is not None}
        payload = {"step": step, "action": action, "result": result,
                   "learning_observation": proof}
        source = "tutor_visual" if visual_support else "completed_attempt"
        evidence_text = (_canonical({"visible_elements": proof["visible_elements"],
                                     "visible_text": proof["visible_text"]}) if visual_support else _canonical(action))
        events.append({"event_id": event_id, "source": source, "text": evidence_text,
                       "payload": payload, "sha256": _hash(payload)})
    return events


def pending_learning_events(state, observation, history):
    processed = set(state.get("processed_event_ids", []))
    return [event for event in public_learning_events(observation, history)
            if event["event_id"] not in processed]


def _all_decisions(state):
    return {item["event_id"]: item for round_ in state["event_ledger"]
            for item in round_["proposal"]["events"]}


def _all_sources(state):
    return {event["event_id"]: event for round_ in state["event_ledger"]
            for event in round_["events"]}


def _add_unique(items, item):
    if any(old["statement"] == item["statement"] and old.get("basis") == item.get("basis")
           for old in items):
        return False
    items.append(item)
    return True


def _confirmed_attempt(current, event, decision, patch, sources, kinds):
    """Bind explicit feedback either in the attempt batch or on later receipt.

    The later path never mutates an already recorded action/receipt. Its public
    feedback must be new, chronologically later, and refer to one latest actual
    attempt; semantic correctness and local entailment remain assessor duties.
    """
    confirmation = patch.confirmation_event_id
    if (confirmation not in sources
            or sources[confirmation]["source"] != "tutor_message"
            or kinds.get(confirmation) != "attempt_feedback"
            or confirmation not in patch.support_event_ids):
        raise KnowledgeBoundaryError("Independent application requires completed action and explicit attempt feedback.")
    if decision.kind == "completed_attempt":
        attempt = event
        permitted_feedback = (attempt["payload"].get("learning_observation") or {}).get("feedback_message_indices")
        if (permitted_feedback is not None
                and sources[confirmation]["payload"]["message_index"] not in permitted_feedback):
            raise KnowledgeBoundaryError("Confirmation is not feedback on this completed attempt.")
        return attempt, sources[confirmation]
    if decision.kind != "attempt_feedback" or confirmation != event["event_id"]:
        raise KnowledgeBoundaryError("Independent application requires completed action and explicit attempt feedback.")
    attempt_refs = [ref for ref in patch.support_event_ids
                    if sources[ref]["source"] == "completed_attempt"
                    and kinds.get(ref) == "completed_attempt"]
    if len(attempt_refs) != 1:
        raise KnowledgeBoundaryError("Later feedback must identify exactly one completed attempt.")
    prior_sources = _all_sources(current)
    if attempt_refs[0] not in prior_sources:
        raise KnowledgeBoundaryError("Later feedback must bind an earlier recorded attempt.")
    attempt = sources[attempt_refs[0]]
    if any(source["source"] == "completed_attempt"
           and kinds.get(source["event_id"]) == "completed_attempt"
           and source["payload"]["step"] > attempt["payload"]["step"]
           for source in sources.values()):
        raise KnowledgeBoundaryError("Later feedback must bind the latest completed content attempt.")
    feedback_index = event["payload"]["message_index"]
    proof = attempt["payload"].get("learning_observation") or {}
    previous_indices = [source["payload"]["message_index"] for source in prior_sources.values()
                        if source["source"] == "tutor_message"]
    previous_indices.extend(proof.get("user_message_indices") or [])
    previous_indices.extend(proof.get("feedback_message_indices") or [])
    if previous_indices and feedback_index <= max(previous_indices):
        raise KnowledgeBoundaryError("Later feedback must be newly delivered after the recorded attempt.")
    return attempt, event


def apply_learning_proposal(state, proposal, events):
    """Apply assessor proposals; no actor memory or proposed action is read."""
    if isinstance(proposal, dict):
        proposal = KnowledgeUpdateProposal.model_validate(proposal)
    if not isinstance(proposal, KnowledgeUpdateProposal):
        raise KnowledgeBoundaryError("A structured knowledge event proposal is required.")
    current = deepcopy(state)
    event_map = {event["event_id"]: event for event in events}
    if len(event_map) != len(events):
        raise KnowledgeBoundaryError("Assessment input contains duplicate events.")
    decisions = {item.event_id: item for item in proposal.events}
    if len(decisions) != len(proposal.events) or set(decisions) != set(event_map):
        raise KnowledgeBoundaryError("Classify each new public event exactly once.")
    if set(event_map) & set(current["processed_event_ids"]):
        raise KnowledgeBoundaryError("A public event cannot be applied twice.")
    if not events:
        return current
    sources = {**_all_sources(current), **event_map}
    kinds = {key: value["kind"] for key, value in _all_decisions(current).items()}
    kinds.update({key: value.kind for key, value in decisions.items()})
    components = {item["component_id"]: item for item in current["components"]}
    changed = False
    for decision in proposal.events:
        event = event_map[decision.event_id]
        if event["sha256"] != _hash(event["payload"]):
            raise KnowledgeBoundaryError("An event payload does not match its digest.")
        if decision.kind == "completed_attempt" and event["source"] != "completed_attempt":
            raise KnowledgeBoundaryError("An attempt classification needs a completed action.")
        if decision.kind in SUPPORT_KINDS and event["source"] not in {"tutor_message", "tutor_visual"}:
            raise KnowledgeBoundaryError("Concrete support must come from delivered tutor text or a revealed Figure.")
        if decision.kind in NO_UPDATE_KINDS and decision.updates:
            raise KnowledgeBoundaryError("Plain questions, praise and other events cannot update knowledge.")
        for patch in decision.updates:
            if patch.component_id not in components:
                raise KnowledgeBoundaryError("An update refers to an unknown knowledge component.")
            if not patch.statement.strip() or not patch.evidence_quote.strip() or patch.evidence_quote not in event["text"]:
                raise KnowledgeBoundaryError("Knowledge updates require an exact, nonempty public evidence quote.")
            if len(patch.support_event_ids) != len(set(patch.support_event_ids)):
                raise KnowledgeBoundaryError("Support event IDs must be unique.")
            if any(ref not in sources for ref in patch.support_event_ids):
                raise KnowledgeBoundaryError("Knowledge support references an unavailable event.")
            component = components[patch.component_id]
            if patch.kind == "support_received":
                if decision.kind not in SUPPORT_KINDS:
                    raise KnowledgeBoundaryError("Local support requires an explanation, hint, or attempt feedback.")
                if decision.kind == "attempt_feedback" and not any(
                        sources[ref]["source"] == "completed_attempt" and kinds.get(ref) == "completed_attempt"
                        for ref in patch.support_event_ids):
                    raise KnowledgeBoundaryError("Attempt feedback must bind a completed attempt.")
                if patch.confirmation_event_id is not None:
                    raise KnowledgeBoundaryError("Support exposure is not an independent mastery confirmation.")
                scope = {"statement": patch.statement, "basis": "received_local_support",
                         "source_quote": patch.evidence_quote,
                         "event_ids": [decision.event_id] + patch.support_event_ids}
                # Equal phrasing can refer to different diagram parts in later
                # context. Deduplicate identical scope, not the quote alone;
                # the assessor must reject mere paraphrases as new learning.
                repeated_scope = any(old["statement"] == patch.statement
                                     for old in component["available_knowledge"])
                local_changed = False if repeated_scope else _add_unique(component["available_knowledge"], scope)
                if local_changed:
                    if component["status"] == "unlearned":
                        component["status"] = "tentative"
                    component["statement"] = patch.statement
                changed |= local_changed
            elif patch.kind == "attempt_observed":
                if decision.kind != "completed_attempt":
                    raise KnowledgeBoundaryError("Attempt evidence requires an actual completed attempt.")
                if patch.confirmation_event_id is not None:
                    raise KnowledgeBoundaryError("A provisional attempt cannot self-confirm.")
                claim = {"statement": patch.statement, "basis": "provisional_attempt",
                         "event_ids": [decision.event_id] + patch.support_event_ids}
                changed |= _add_unique(component["attempted_beliefs"], claim)
                # An attempt is recorded without making its possibly incorrect
                # belief an available procedure or upgrading unlearned status.
            else:
                attempt, confirmation = _confirmed_attempt(current, event, decision, patch, sources, kinds)
                scope = {"statement": patch.statement, "basis": "independently_applied_with_feedback",
                         "event_ids": list(dict.fromkeys([attempt["event_id"], confirmation["event_id"]]
                                                        + patch.support_event_ids))}
                local_changed = _add_unique(component["independent_evidence"], scope)
                if local_changed:
                    _add_unique(component["available_knowledge"], scope)
                    component["status"] = "known"
                    component["statement"] = patch.statement
                changed |= local_changed
    current["processed_event_ids"].extend(event["event_id"] for event in events)
    current["event_ledger"].append({"events": deepcopy(events), "proposal": proposal.model_dump()})
    current["event_revision"] += 1
    if changed:
        current["revision"] += 1
    return _finish(current)


def validate_knowledge_model(case_config, prior_knowledge, persisted, observation, history, *, owner_id=None):
    """Recompute persisted knowledge from its ledger and actual public sources."""
    initial = initialize_knowledge_model(case_config, prior_knowledge, owner_id=owner_id)
    if persisted is None:
        return initial
    if not isinstance(persisted, dict) or persisted.get("format") != FORMAT:
        raise KnowledgeBoundaryError("Unsupported persisted learner knowledge format.")
    if persisted.get("case_binding") != initial["case_binding"] or persisted.get("owner_id") != owner_id:
        raise KnowledgeBoundaryError("Learner knowledge belongs to a different case or owner.")
    supplied_hash = persisted.get("state_sha256")
    if supplied_hash != _hash({key: value for key, value in persisted.items() if key != "state_sha256"}):
        raise KnowledgeBoundaryError("Persisted learner knowledge was altered.")
    available = {event["event_id"]: event for event in public_learning_events(observation, history)}
    replayed = initial
    for round_ in persisted.get("event_ledger", []):
        if not isinstance(round_, dict) or set(round_) != {"events", "proposal"}:
            raise KnowledgeBoundaryError("Knowledge ledger entries must contain source events and their proposal.")
        for event in round_["events"]:
            original = available.get(event.get("event_id"))
            if original != event:
                raise KnowledgeBoundaryError("Persisted learning evidence differs from the actual visible history.")
        replayed = apply_learning_proposal(replayed, round_["proposal"], round_["events"])
    if replayed != persisted:
        raise KnowledgeBoundaryError("Persisted knowledge does not match controller-ledger replay.")
    return deepcopy(persisted)


def project_knowledge_model(state):
    """Expose current knowledge content, not the assessor's full ledger."""
    return {"format": state["format"], "revision": state["revision"],
            "content_sha256": state["content_sha256"], "scope_policy": state["scope_policy"],
            "components": deepcopy(state["components"])}


def memory_component_states(state):
    result = []
    for item in state["components"]:
        evidence = []
        if item["status"] != "unlearned":
            for scope in item["available_knowledge"]:
                for ref in scope["event_ids"]:
                    source = "initial_case" if ref.startswith("initial:") else "visible_message" if ref.startswith("message:") else "completed_action"
                    value = {"source": source, "reference": ref, "support": scope["statement"]}
                    if value not in evidence:
                        evidence.append(value)
        result.append({"component_id": item["component_id"], "status": item["status"],
                       "statement": item["statement"], "evidence": evidence})
    return result
