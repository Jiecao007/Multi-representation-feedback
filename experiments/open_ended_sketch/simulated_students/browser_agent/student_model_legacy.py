"""One auditable, knowledge-constrained learner decision.

Usage: python student_model.py --request request.json --response response.json
The observer proposes learning from past public events. A separate gate checks
those updates and the actor's candidate before the runner may execute it.
No answer key, browser access, SDK retry, or forced replacement action is used.
"""
from __future__ import annotations

import argparse
import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
from pathlib import Path
import sys
import time
from typing import Literal, Optional, Union

sys.dont_write_bytecode = True
from pydantic import BaseModel, ConfigDict, Field

from learner_knowledge import (
    KnowledgeUpdateProposal, apply_learning_proposal, memory_component_states,
    pending_learning_events, project_knowledge_model, validate_knowledge_model,
)

HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parents[1]
DEFAULT_MODEL = "gpt-6-sol"
DEFAULT_EFFORT = "low"
MAX_OUTPUT_TOKENS = 4000
IMAGE_DETAIL = "high"
INPUT_PROJECTION_VERSION = "deduplicated-v1"
KNOWLEDGE_PROJECTION_VERSION = "controller-knowledge-v1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Point(StrictModel):
    x: float
    y: float


class GlyphText(StrictModel):
    glyph_index: int
    text: str


class Action(StrictModel):
    # Required nullable fields produce a complete strict JSON Schema. A driver
    # must ignore null fields; only parameters relevant to `type` have values.
    type: Literal[
        "send_message", "show_feedback", "request_hint", "begin_revision", "exit_revision", "return_to_draft",
        "add_text", "edit_text", "add_object", "select", "move",
        "add_connection", "edit_connection", "reshape_connection", "resize",
        "delete", "undo", "submit_revisions", "cancel_dialog", "stop",
    ]
    id: Optional[str]
    text: Optional[str]
    messageIndex: Optional[int]
    topic: Optional[str]
    label: Optional[str]
    from_id: Optional[str] = Field(alias="from")
    to: Optional[Union[str, Point]]
    shape: Optional[Literal["straight", "curved", "bent"]]
    direction: Optional[Literal["forward", "backward", "both", "none", "larger", "smaller"]]
    endpoint: Optional[Literal["source", "target"]]
    control: Optional[int]
    space: Optional[Literal["canvas", "screen"]]
    dx: Optional[float]
    dy: Optional[float]
    glyphTexts: Optional[list[GlyphText]]
    steps: Optional[int]
    reason: Optional[str]


class LearnerMemory(StrictModel):
    # These are short state summaries, not a request for private reasoning.
    current_understanding: str
    unresolved_question: str
    next_intention: str
    component_states: list["ComponentState"]


class LearningEvidence(StrictModel):
    source: Literal["initial_case", "visible_message", "completed_action"]
    reference: str
    support: str


class ComponentState(StrictModel):
    component_id: str
    status: Literal["known", "tentative", "unlearned"]
    statement: str
    evidence: list[LearningEvidence]


LearnerMemory.model_rebuild()


class StudentDecision(StrictModel):
    action: Action
    utterance: Optional[str]
    memory: LearnerMemory


class LearnerActionProposal(StrictModel):
    action: Action
    utterance: Optional[str]


class KnowledgeGateCheck(StrictModel):
    target: Literal["knowledge_update", "candidate"]
    path: str
    component_ids: list[str]
    supported: bool
    explanation: str


class KnowledgeGateVerdict(StrictModel):
    updates_supported: bool
    candidate_supported: bool
    checks: list[KnowledgeGateCheck]
    summary: str


class ResponseFeature(StrictModel):
    feature_id: str
    observation: str
    evidence: str


class ResponseOmission(StrictModel):
    gap_id: str
    missing_part: str
    evidence: str
    affected_components: list[str]
    initial_awareness: Literal["unaware", "notices_incompleteness", "identifies_missing_part"]
    learner_belief: str


class ResponseGrounding(StrictModel):
    source_id: str
    present_features: list[ResponseFeature]
    missing_parts: list[ResponseOmission]
    inference_limits: str


class ResponseKnowledgeBinding(StrictModel):
    component_id: str
    response_feature_ids: list[str]
    response_gap_ids: list[str]
    initial_limitation: str
    learning_requirement: str


class ResponseConditioning(StrictModel):
    source_id: str
    constructed: Literal[True]
    assumption: str
    component_bindings: list[ResponseKnowledgeBinding]


OBSERVATION_KEYS = frozenset({
    "screenshot_path", "screenshotPath", "visible_text", "task", "goal",
    "messages", "controls", "elements", "canvas", "handles", "dialogs",
    "status", "stopped",
})
CASE_KEYS = frozenset({
    "id", "case_id", "source_id", "source_title", "task", "task_text",
    "initial_explanation", "initial_conceptual_state",
})
PROFILE_KEYS = frozenset({"id", "constructed_profile", "dimensions"})
PRIVATE_KEYS = frozenset({
    "assessment", "assessments", "private_assessment", "private_review",
    "review", "criteria", "rubric", "rubrics", "diagnosis", "diagnostic",
    "routing", "routing_focus", "focus_ids", "repair_target", "repair_targets",
    "repairtarget", "repairtargets", "revision_plan_ids", "ready", "stage",
    "policy", "correct_answer", "correctanswer", "answer_key", "reference_answer",
    "reference_solution", "hidden_solution", "hidden_assessment", "helperdiagnosis",
    "visual_targets", "visual_delivery", "api_key", "openai_api_key",
    "session_state", "state_snapshot", "feedback_payload", "raw_response",
})


class InputBoundaryError(ValueError):
    pass


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def save_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def ensure_no_private_fields(value):
    """Fail closed on familiar private backend fields, including history/memory.

    This is a second boundary check, not proof that arbitrary text is public.
    The browser observer/controller remains responsible for DOM-only input.
    """
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in PRIVATE_KEYS or normalized.startswith("private_"):
                raise InputBoundaryError("A private or backend field was present in learner input.")
            ensure_no_private_fields(item)
    elif isinstance(value, list):
        for item in value:
            ensure_no_private_fields(item)


def resolve_profile(profile: dict, case: dict):
    """Expand selected operational definitions; unused levels stay out of input.

    Motivation and feedback uptake are selected alongside the three components
    of one representation construct. Legacy field names remain stable; grouping
    metadata makes that structure explicit without repeating behavior text.
    Misconception and content knowledge remain shared categorical case state.
    """
    catalogue = json.loads((HERE / "profile_dimensions.json").read_text(encoding="utf-8"))
    definitions = catalogue["dimensions"]
    configured = profile.get("dimensions")
    if not isinstance(configured, dict):
        raise InputBoundaryError("Profile must configure the supported operational components.")
    compatibility = None
    legacy_keys = set(definitions) - {"coordination_translation"}
    if set(configured) == legacy_keys:
        # Historical four-key configs remain usable, but their new default is
        # explicit in the actual model input rather than silently inferred.
        configured = {**configured, "coordination_translation": {"level": "average"}}
        compatibility = {
            "legacy_four_component_profile": True,
            "coordination_translation_default": "average",
            "interpretation": "Added operational default for an older configuration, not an observed or validated learner ability.",
        }
    elif set(configured) != set(definitions):
        raise InputBoundaryError("Profile must select motivation, feedback uptake, and all three representation components.")
    resolved = {key: value for key, value in profile.items() if key in PROFILE_KEYS}
    resolved["dimensions"] = {}
    for name, configuration in configured.items():
        if isinstance(configuration, dict) and set(configuration) != {"level"}:
            raise InputBoundaryError("Profile dimensions select standardized levels; behavior overrides are not supported.")
        level = configuration.get("level") if isinstance(configuration, dict) else configuration
        if not isinstance(level, str) or level not in definitions[name]["levels"]:
            raise InputBoundaryError("Profile level has no operational definition.")
        resolved["dimensions"][name] = {
            "level": level,
            "definition": definitions[name]["definition"],
            "operational_behavior": definitions[name]["levels"][level],
        }
    resolved["constructs"] = catalogue["constructs"]
    if compatibility is not None:
        resolved["compatibility"] = compatibility
    initial = case.get("initial_conceptual_state", {})
    category = initial.get("misconception_type")
    categories = catalogue["misconception_type"]["values"]
    if category not in categories:
        raise InputBoundaryError("Case must select a supported constructed misconception category.")
    resolved["case_dimensions"] = {
        "misconception_type": {"value": category, **categories[category]},
    }
    resolved["shared_communication_style"] = catalogue["shared_communication_style"]
    prior = resolve_prior_knowledge(case)
    if prior is not None:
        resolved["prior_knowledge"] = prior
    return resolved


def resolve_response_grounding(case: dict):
    """Inject observed omissions as initial conditioning, not an answer key.

    Awareness/belief is an explicitly configured simulation assumption. Absence
    in a drawing never changes knowledge status or supplies a corrected model.
    """
    if "response_grounding" not in case:
        return None
    try:
        grounding = ResponseGrounding.model_validate(case["response_grounding"])
    except Exception as exc:
        raise InputBoundaryError("Response grounding does not match the annotation contract.") from exc
    source_id = case.get("source_id") or case.get("example_id") or case.get("case_id")
    if not source_id or grounding.source_id != source_id:
        raise InputBoundaryError("Response grounding must refer to this case's source response.")
    if not grounding.inference_limits.strip():
        raise InputBoundaryError("Response grounding must distinguish observed omissions from inferred knowledge.")
    components = {item["component_id"] for item in case.get("initial_conceptual_state", {}).get("knowledge_components", [])}
    seen = set()
    for feature in grounding.present_features:
        if not feature.feature_id.strip() or feature.feature_id in seen or not feature.observation.strip() or not feature.evidence.strip():
            raise InputBoundaryError("Present features require distinct IDs and concrete source evidence.")
        seen.add(feature.feature_id)
    seen = set()
    omissions, positions = [], []
    for gap in grounding.missing_parts:
        if not gap.gap_id.strip() or gap.gap_id in seen or not all(value.strip() for value in (gap.missing_part, gap.evidence, gap.learner_belief)):
            raise InputBoundaryError("Response omissions require distinct IDs, evidence and a configured learner belief.")
        if not gap.affected_components or len(gap.affected_components) != len(set(gap.affected_components)) or not set(gap.affected_components).issubset(components):
            raise InputBoundaryError("Each omission must map to existing case knowledge components.")
        seen.add(gap.gap_id)
        omissions.append({key: value for key, value in gap.model_dump().items()
                          if key not in {"initial_awareness", "learner_belief"}})
        positions.append({"gap_id": gap.gap_id, "initial_awareness": gap.initial_awareness,
                          "learner_belief": gap.learner_belief})
    return {"source_id": grounding.source_id,
            "already_present": [feature.model_dump() for feature in grounding.present_features],
            "response_omissions": omissions, "learner_starting_position": positions,
            "inference_limits": grounding.inference_limits}


def resolve_prior_knowledge(case: dict):
    """Join configured starting knowledge to validated submission evidence.

    The researcher supplies the inability assumption explicitly; this resolver
    does not diagnose inability from an omitted mark or an ability level.
    """
    if "response_conditioning" not in case:
        return None
    try:
        conditioning = ResponseConditioning.model_validate(case["response_conditioning"])
    except Exception as exc:
        raise InputBoundaryError("Response-conditioned prior knowledge does not match its contract.") from exc
    context = resolve_response_grounding(case)
    if context is None or conditioning.source_id != context["source_id"]:
        raise InputBoundaryError("Prior knowledge must bind to this case's validated submitted response.")
    initial = case.get("initial_conceptual_state", {})
    if initial.get("constructed") is not True or not conditioning.assumption.strip():
        raise InputBoundaryError("Response-conditioned prior knowledge requires an explicit constructed assumption.")
    components = initial.get("knowledge_components", [])
    if not components or any(not isinstance(c, dict) or not c.get("component_id") for c in components):
        raise InputBoundaryError("Prior knowledge requires identified case knowledge components.")
    by_id = {c["component_id"]: c for c in components}
    if len(by_id) != len(components):
        raise InputBoundaryError("Prior knowledge component IDs must be unique.")
    features = {f["feature_id"] for f in context["already_present"]}
    gaps = {g["gap_id"]: set(g["affected_components"]) for g in context["response_omissions"]}
    bindings = conditioning.component_bindings
    if len(bindings) != len(by_id) or {b.component_id for b in bindings} != set(by_id):
        raise InputBoundaryError("Bind each case knowledge component exactly once to the submitted response.")
    result = []
    for binding in bindings:
        component = by_id[binding.component_id]
        if component.get("status") not in {"known", "tentative", "unlearned"} or not isinstance(component.get("statement"), str) or not component["statement"].strip():
            raise InputBoundaryError("Bound components need a valid starting state and statement.")
        refs = binding.response_feature_ids + binding.response_gap_ids
        required_gaps = {g for g, affected in gaps.items() if binding.component_id in affected}
        if (not refs or len(binding.response_feature_ids) != len(set(binding.response_feature_ids))
                or len(binding.response_gap_ids) != len(set(binding.response_gap_ids))
                or not set(binding.response_feature_ids).issubset(features)
                or set(binding.response_gap_ids) != required_gaps
                or any(g not in gaps or binding.component_id not in gaps[g] for g in binding.response_gap_ids)
                or not binding.initial_limitation.strip() or not binding.learning_requirement.strip()):
            raise InputBoundaryError("Prior knowledge needs valid response references and explicit learning limits.")
        result.append({
            "component_id": binding.component_id, "status": component["status"],
            "statement": component["statement"],
            "response_evidence_ids": ["feature:" + f for f in binding.response_feature_ids]
                                     + ["gap:" + g for g in binding.response_gap_ids],
            "initial_limitation": binding.initial_limitation,
            "learning_requirement": binding.learning_requirement,
        })
    return {"source_id": conditioning.source_id, "constructed": True,
            "assumption": conditioning.assumption, "components": result,
            "use": "Starting knowledge and action limits shared across profiles. Read response evidence in case_config.initial_response_context; update only the supported local scope during interaction."}


def _normalized_text(value):
    return " ".join(value.split())


def _compact_geometry(value, precision=None):
    """Shorten layout numbers, never round mathematical field values."""
    if isinstance(value, dict):
        geometry = {"bounds", "canvas_bounds", "screen_bounds", "screen_center",
                    "canvas_center", "points"}
        return {key: _compact_geometry(item, 6 if key == "screen_transform" else
                                      2 if key in geometry else precision)
                for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_compact_geometry(item, precision) for item in value]
    if isinstance(value, float) and precision is not None:
        return round(value, precision)
    return value


def _memory_delta(previous, current, path=""):
    """Lossless JSON Patch changes; keep novel beliefs and evidence as well as status."""
    if isinstance(previous, dict) and isinstance(current, dict):
        changes = []
        for key in previous:
            if key not in current:
                token = str(key).replace("~", "~0").replace("/", "~1")
                changes.append({"op": "remove", "path": path + "/" + token})
        for key, value in current.items():
            token = str(key).replace("~", "~0").replace("/", "~1")
            child_path = path + "/" + token
            if key not in previous:
                changes.append({"op": "add", "path": child_path, "value": deepcopy(value)})
            else:
                changes.extend(_memory_delta(previous[key], value, child_path))
        return changes
    if isinstance(previous, list) and isinstance(current, list):
        changes = []
        for index in range(min(len(previous), len(current))):
            changes.extend(_memory_delta(previous[index], current[index], path + "/" + str(index)))
        for index in range(len(previous) - 1, len(current) - 1, -1):
            changes.append({"op": "remove", "path": path + "/" + str(index)})
        for index in range(len(previous), len(current)):
            changes.append({"op": "add", "path": path + "/" + str(index), "value": deepcopy(current[index])})
        return changes
    if type(previous) is type(current) and previous == current:
        return []
    return [{"op": "replace", "path": path, "value": deepcopy(current)}]


def compact_input(visible: dict):
    """Project validated input without truncating dialogue or action evidence.

    Full controller requests/traces stay on disk. Historical memory is delta
    encoded without losing novel content; the latest memory stays full.
    """
    payload = deepcopy(visible)
    case = payload["case_config"]
    previous_memory = {}
    for event in payload.get("history", []):
        if not isinstance(event, dict):
            continue
        action = event.get("action")
        if isinstance(action, dict):
            event["action"] = {key: value for key, value in action.items() if value is not None}
        if "utterance" in event and (event["utterance"] in (None, "") or
                isinstance(action, dict) and event["utterance"] == action.get("text")):
            event.pop("utterance")
        if "memory_update" in event:
            old_memory = event.pop("memory_update")
            changes = _memory_delta(previous_memory, old_memory)
            if changes:
                # Changing many fields can make a patch larger than one state.
                # Keep whichever lossless representation sends less text.
                replacement = [{"op": "replace", "path": "", "value": old_memory}]
                if len(serialize_input(replacement)) < len(serialize_input(changes)):
                    changes = replacement
                event["memory_delta"] = changes
            previous_memory = old_memory

    observation = payload["observation"]
    # Remove only whole page lines already represented by named text fields.
    # Distinct notices and quoted wording remain, even when partly repetitive.
    represented = set()

    def cover(text):
        if isinstance(text, str):
            represented.add(_normalized_text(text))
            represented.update(_normalized_text(line) for line in text.splitlines())

    for key in ("task", "task_text"):
        cover(case.get(key))
    for key in ("task", "goal"):
        cover(observation.get(key))
    for message in observation.get("messages", []):
        cover(message.get("text"))
        if message.get("show_available") and isinstance(message.get("text"), str):
            cover(message["text"] + "Show")
    for control in observation.get("controls", []):
        cover(control.get("label"))
    for element in observation.get("elements", []):
        cover(element.get("label"))
        for text in element.get("texts", []):
            cover(text)
    for dialog in observation.get("dialogs", []):
        cover(dialog.get("title"))
        cover(dialog.get("text"))
    for text in observation.get("status", {}).values():
        cover(text)
    if isinstance(observation.get("visible_text"), str):
        observation["visible_text"] = "\n".join(
            line for line in observation["visible_text"].splitlines()
            if _normalized_text(line) and _normalized_text(line) not in represented)
    if isinstance(observation.get("task"), str) and any(
            isinstance(case.get(key), str) and _normalized_text(observation["task"]) == _normalized_text(case[key])
            for key in ("task", "task_text")):
        observation.pop("task")
    observation = _compact_geometry(observation)
    # Stable profile/case and append-only actions precede changing memory/UI.
    return {"profile": payload["profile"], "case_config": case,
            "history": payload.get("history", []), "memory": payload.get("memory"),
            "observation": observation}


def serialize_input(visible: dict):
    return json.dumps(visible, ensure_ascii=False, separators=(",", ":"))


def prepare_input(request: dict, request_path: Path):
    if not isinstance(request, dict):
        raise InputBoundaryError("Request must be an object.")
    profile = request.get("profile")
    case = request.get("case_config")
    observation = request.get("observation")
    if not all(isinstance(value, dict) for value in (profile, case, observation)):
        raise InputBoundaryError("profile, case_config, and observation must be objects.")
    unexpected = set(observation) - OBSERVATION_KEYS
    if unexpected:
        raise InputBoundaryError("Observation contains fields outside the DOM allowlist.")
    screenshot = observation.get("screenshot_path") or observation.get("screenshotPath")
    if not isinstance(screenshot, str) or not screenshot:
        raise InputBoundaryError("A current learner-visible screenshot is required.")
    screenshot_path = Path(screenshot).expanduser()
    if not screenshot_path.is_absolute():
        screenshot_path = request_path.parent / screenshot_path
    screenshot_path = screenshot_path.resolve()
    mime = mimetypes.guess_type(screenshot_path.name)[0]
    if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
        raise InputBoundaryError("Screenshot must be PNG, JPEG, WEBP, or GIF.")
    image_bytes = screenshot_path.read_bytes()
    if not image_bytes or len(image_bytes) > 12 * 1024 * 1024:
        raise InputBoundaryError("Screenshot is empty or larger than 12 MB.")
    history = request.get("history", [])
    memory = request.get("memory")
    if not isinstance(history, list):
        raise InputBoundaryError("history must contain only learner-visible events in a list.")
    visible = {
        "profile": resolve_profile(profile, case),
        "case_config": {key: value for key, value in case.items() if key in CASE_KEYS},
        "observation": {key: value for key, value in observation.items()
                        if key not in {"screenshot_path", "screenshotPath"}},
        "history": history,
        "memory": memory,
    }
    grounding = resolve_response_grounding(case)
    if grounding is not None:
        visible["case_config"]["initial_response_context"] = grounding
    # Validate before projection, including old snapshots that will be omitted.
    ensure_no_private_fields(visible)
    visible = compact_input(visible)
    ensure_no_private_fields(visible)
    provenance = {
        "path": str(screenshot_path), "mime_type": mime, "bytes": len(image_bytes),
        "sha256": hashlib.sha256(image_bytes).hexdigest(),
    }
    return visible, provenance, "data:" + mime + ";base64," + base64.b64encode(image_bytes).decode("ascii")


def audit_memory(decision: StudentDecision, visible: dict):
    """Expose unsupported state claims without changing an action or retrying.

    Matching an event reference checks provenance only. It cannot establish
    actual understanding, so no automatic mastery scoring is performed.
    """
    initial = visible["case_config"].get("initial_conceptual_state", {})
    components = {item["component_id"]: item for item in initial.get("knowledge_components", [])}
    messages = {f"message:{item['index']}" for item in visible["observation"].get("messages", [])
                if isinstance(item, dict) and "index" in item}
    completed = {f"action:{item['step']}" for item in visible.get("history", [])
                 if isinstance(item, dict) and "step" in item and ("result" in item or "execution" in item)}
    previous = visible.get("memory") or {}
    previous_states = {item["component_id"]: item for item in previous.get("component_states", [])}
    issues, changes, seen = [], [], set()
    for item in decision.memory.component_states:
        if item.component_id in seen:
            issues.append("Duplicate component state: " + item.component_id)
        seen.add(item.component_id)
        if item.component_id not in components:
            issues.append("Unknown component id: " + item.component_id)
            continue
        before = previous_states.get(item.component_id, components[item.component_id]).get("status")
        if before != item.status:
            changes.append({"component_id": item.component_id, "before": before, "after": item.status})
        if item.status != "unlearned" and not item.evidence:
            issues.append("Non-unlearned component lacks an evidence reference: " + item.component_id)
        for evidence in item.evidence:
            valid = ((evidence.source == "initial_case" and evidence.reference == "initial:" + item.component_id)
                     or (evidence.source == "visible_message" and evidence.reference in messages)
                     or (evidence.source == "completed_action" and evidence.reference in completed))
            if not valid:
                issues.append("Evidence reference is not an available past event: " + evidence.reference)
        if before != "known" and item.status == "known" and not any(
                evidence.source != "initial_case" for evidence in item.evidence):
            issues.append("Promotion to known cites only the constructed starting state: " + item.component_id)
    for missing in set(components) - seen:
        issues.append("Missing component state: " + missing)
    return {"issues": issues, "component_state_changes": changes,
            "interpretation": "Provenance check only; neither mastery scoring nor a forced action/outcome."}


def decision_issues(decision: StudentDecision):
    """Report malformed commands; never turn a bad request into a useful edit."""
    a = decision.action
    issues = []
    if a.type == "send_message":
        if not a.text or not a.text.strip():
            issues.append("send_message requires nonempty text")
        if decision.utterance != a.text:
            issues.append("utterance must equal send_message.text")
    elif decision.utterance is not None:
        issues.append("utterance must be null unless sending a message")
    if a.type in {"edit_text", "select", "move", "edit_connection", "reshape_connection", "resize", "delete"} and not a.id:
        issues.append("this action requires a visible element id")
    if a.type == "add_text" and not a.text:
        issues.append("add_text requires text")
    if a.type == "edit_text" and a.text is None and a.glyphTexts is None:
        issues.append("edit_text requires text or glyphTexts")
    if a.type == "move" and not (isinstance(a.to, Point) or (a.dx is not None and a.dy is not None)):
        issues.append("move requires a coordinate point or dx and dy")
    if a.type == "add_connection" and (not a.from_id or not isinstance(a.to, str) or not a.to):
        issues.append("add_connection requires visible from/to element ids")
    if a.type in {"add_connection", "edit_connection"} and a.direction in {"larger", "smaller"}:
        issues.append("connection direction cannot be a resize direction")
    if a.type == "reshape_connection":
        if not isinstance(a.to, Point):
            issues.append("reshape_connection requires a coordinate point")
        if (a.endpoint is None) == (a.control is None):
            issues.append("reshape_connection requires either endpoint or control")
    if a.type == "resize" and a.direction not in {"larger", "smaller"}:
        issues.append("resize requires larger or smaller direction")
    if a.glyphTexts is not None:
        indices = [item.glyph_index for item in a.glyphTexts]
        if len(indices) != len(set(indices)) or any(index < 0 for index in indices):
            issues.append("glyphTexts indices must be distinct and nonnegative")
    return issues


def driver_decision(decision: StudentDecision):
    value = decision.model_dump(by_alias=True)
    glyphs = value["action"]["glyphTexts"]
    if glyphs is not None:
        value["action"]["glyphTexts"] = {str(item["glyph_index"]): item["text"] for item in glyphs}
    return value


def existing_client():
    # Import the existing server only when a real call has been requested. Its
    # dotenv order and client settings are reused; environment values are never logged.
    sys.path[:0] = [str(EXPERIMENT / "app"), str(EXPERIMENT)]
    import server
    return server.client()


def api_metadata(response, model, effort, elapsed):
    usage = getattr(response, "usage", None)
    return {
        "called": True,
        "model_requested": model,
        "model_returned": getattr(response, "model", None),
        "effort": effort,
        "response_id": getattr(response, "id", None),
        "request_id": getattr(response, "_request_id", None),
        "status": getattr(response, "status", None),
        "usage": usage.model_dump() if usage else None,
        "elapsed_seconds": round(elapsed, 3),
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "store": False,
        "automatic_retries": 0,
        "image_detail": IMAGE_DETAIL,
    }


def controlled_projection(visible, state):
    """Old actor-authored memory cannot re-enter the knowledge channel."""
    payload = deepcopy(visible)
    payload.pop("memory", None)
    payload["history"] = [{key: deepcopy(value) for key, value in event.items()
                           if key in {"step", "action", "result", "utterance", "learning_observation"}}
                          for event in payload.get("history", []) if isinstance(event, dict)]
    payload["learner_knowledge_model"] = project_knowledge_model(state)
    return payload


def controller_memory(state, action):
    scopes = [scope["statement"] for component in state["components"]
              for scope in component["available_knowledge"]]
    limits = [component["initial_limitation"] or component["initial_statement"]
              for component in state["components"] if component["status"] != "known"]
    return LearnerMemory(current_understanding=" | ".join(scopes),
                         unresolved_question=" | ".join(limits),
                         next_intention=action.type,
                         component_states=memory_component_states(state))


def required_gate_checks(proposal, candidate):
    update_paths = ["learning_proposal.events"]
    update_paths.extend(f"learning_proposal.events[{i}].updates[{j}]"
                        for i, event in enumerate(proposal.events) for j, _ in enumerate(event.updates))
    action = candidate.action.model_dump(by_alias=True)
    candidate_paths = ["candidate.action." + key for key, value in action.items()
                       if value is not None]
    if candidate.utterance is not None:
        candidate_paths.append("candidate.utterance")
    return {"knowledge_update": update_paths, "candidate": candidate_paths}


def gate_receipt(verdict, syntax_issues, required, component_ids):
    checks = verdict.checks
    structural = []
    for target, paths in required.items():
        assessed = {check.path for check in checks if check.target == target}
        for path in paths:
            if path not in assessed:
                structural.append({"target": target, "missing_path": path})
    for check in checks:
        if set(check.component_ids) - set(component_ids):
            structural.append({"target": check.target, "unknown_component_ids": check.component_ids})
    # A contradictory verdict is rejected, even if its summary says approved.
    updates = verdict.updates_supported and not any(
        not check.supported for check in checks if check.target == "knowledge_update") and not any(
        item["target"] == "knowledge_update" for item in structural)
    candidate = verdict.candidate_supported and not any(
        not check.supported for check in checks if check.target == "candidate") and not any(
        item["target"] == "candidate" for item in structural)
    return {**verdict.model_dump(), "updates_supported": updates,
            "candidate_supported": candidate, "syntax_issues": syntax_issues,
            "structural_issues": structural,
            "approved": updates and candidate and not syntax_issues}


def run_controlled_decision(request, visible, screenshot, image_url, response_path,
                            model, effort, output, *, client=None, dry_run=False):
    """Separate update -> actor -> gate. Only an approved candidate is executable.

    The single optional regeneration receives rejected field/component IDs, not
    a worked correction. Every candidate and gate verdict remains in sidecars.
    """
    instance = request.get("learner_instance_id")
    if instance is not None and (not isinstance(instance, str) or not instance.strip()):
        raise InputBoundaryError("learner_instance_id must be a nonempty string.")
    owner = visible["profile"]["id"] + ":" + (instance or str(
        visible["case_config"].get("id") or visible["case_config"].get("source_id") or "saved-context"))
    prior = visible["profile"].get("prior_knowledge")
    before = validate_knowledge_model(request["case_config"], prior,
                                     request.get("learner_knowledge_model"),
                                     visible["observation"], visible["history"], owner_id=owner)
    events = pending_learning_events(before, visible["observation"], visible["history"])
    state = before
    audit = {"before": before, "events": events, "after": before,
             "update_validated": False, "gate": {"approved": False}}
    output.update({"learner_knowledge_model": before, "knowledge_audit": audit,
                   "api_calls": [], "candidate_attempts": [],
                   "input_projection": {"version": KNOWLEDGE_PROJECTION_VERSION,
                     "base_projection": INPUT_PROJECTION_VERSION,
                     "history": "Actual public actions/results; actor-authored memory excluded",
                     "knowledge_authority": "Separate controller state with replayable public evidence ledger"}})
    role_prefix = response_path.name.removesuffix("_response.json") if response_path.name.endswith("_response.json") else response_path.stem
    response_path.parent.mkdir(parents=True, exist_ok=True)
    if not dry_run and any(
            (response_path.parent / (role_prefix + "_" + role)).with_suffix(suffix).exists()
            for role in ("learning_observer", "learner_candidate_1", "learner_candidate_2", "knowledge_gate_1", "knowledge_gate_2")
            for suffix in (".prompt.md", ".input.json", ".schema.json", ".response.json")):
        raise InputBoundaryError("Role evidence already exists; use a new output prefix.")

    def role_call(role, filename, payload, schema):
        prompt = (HERE / filename).read_text(encoding="utf-8")
        input_text = serialize_input(payload)
        stem = response_path.parent / (role_prefix + "_" + role)
        if any(stem.with_suffix(suffix).exists() for suffix in
               (".prompt.md", ".input.json", ".schema.json", ".response.json")):
            raise InputBoundaryError("Role evidence already exists; use a new output prefix.")
        stem.with_suffix(".prompt.md").write_text(prompt, encoding="utf-8")
        save_json(stem.with_suffix(".input.json"), payload)
        save_json(stem.with_suffix(".schema.json"), schema.model_json_schema(by_alias=True))
        record = {"role": role, "called": False,
                  "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                  "input_text_sha256": hashlib.sha256(input_text.encode()).hexdigest(),
                  "sidecar_prefix": stem.name, "screenshot": screenshot}
        output["api_calls"].append(record)
        started = time.perf_counter()
        try:
            record["called"] = True
            response = client.responses.parse(
                model=model, instructions=prompt, reasoning={"effort": effort},
                max_output_tokens=MAX_OUTPUT_TOKENS, store=False, text_format=schema,
                input=[{"role": "user", "content": [
                    {"type": "input_text", "text": input_text},
                    {"type": "input_image", "image_url": image_url, "detail": IMAGE_DETAIL}]}])
            record.update(api_metadata(response, model, effort, time.perf_counter() - started))
            parsed = response.output_parsed
            raw = getattr(response, "output_text", None)
            if response.status != "completed" or parsed is None:
                save_json(stem.with_suffix(".response.json"), {"api": record, "raw_output_text": raw, "parsed": None})
                raise ValueError("NoCompletedStructuredResponse")
            if not isinstance(parsed, schema):
                parsed = schema.model_validate(parsed)
            save_json(stem.with_suffix(".response.json"), {"api": record, "raw_output_text": raw,
                                                         "parsed": parsed.model_dump(by_alias=True)})
            if role.startswith("learner_candidate"):
                output["api"] = deepcopy(record)
                output["raw_output_text"] = raw
            return parsed
        except Exception as exc:
            record.update({"error_type": type(exc).__name__, "http_status": getattr(exc, "status_code", None),
                           "request_id": getattr(exc, "request_id", record.get("request_id"))})
            if not stem.with_suffix(".response.json").exists():
                save_json(stem.with_suffix(".response.json"), {"api": record, "parsed": None})
            raise

    initial_payload = controlled_projection(visible, before)
    output["model_visible_input"] = initial_payload
    output["schema"] = LearnerActionProposal.model_json_schema(by_alias=True)
    output["prompt_sha256"] = hashlib.sha256((HERE / "student_prompt.md").read_bytes()).hexdigest()
    output["input_text_sha256"] = hashlib.sha256(serialize_input(initial_payload).encode()).hexdigest()
    if dry_run:
        output["status"] = "dry_run"
        return
    proposal = KnowledgeUpdateProposal(events=[])
    if events:
        observer_payload = {"case_config": visible["case_config"],
                            "prior_knowledge": prior, "profile": visible["profile"],
                            "learner_knowledge_model": project_knowledge_model(before),
                            "new_public_events": events,
                            "past_public_events": [event for round_ in before["event_ledger"] for event in round_["events"]],
                            "observation": visible["observation"]}
        proposal = role_call("learning_observer", "learning_observer_prompt.md", observer_payload, KnowledgeUpdateProposal)
        state = apply_learning_proposal(before, proposal, events)
    audit["proposed_after"] = state
    output["learning_proposal"] = proposal.model_dump()
    payload = controlled_projection(visible, state)
    output["model_visible_input"] = payload
    output["input_text_sha256"] = hashlib.sha256(serialize_input(payload).encode()).hexdigest()
    for attempt in (1, 2):
        candidate = role_call("learner_candidate_" + str(attempt), "student_prompt.md", payload, LearnerActionProposal)
        decision = StudentDecision(action=candidate.action, utterance=candidate.utterance,
                                   memory=controller_memory(state, candidate.action))
        issues = decision_issues(decision)
        required = required_gate_checks(proposal, candidate)
        gate_payload = {"case_config": visible["case_config"], "profile": visible["profile"],
                        "knowledge_before": project_knowledge_model(before),
                        "new_public_events": events,
                        "past_public_events": [event for round_ in before["event_ledger"] for event in round_["events"]],
                        "learning_proposal": proposal.model_dump(),
                        "knowledge_after": project_knowledge_model(state),
                        "candidate": candidate.model_dump(by_alias=True),
                        "observation": visible["observation"], "history": payload["history"],
                        "required_checks": required}
        verdict = role_call("knowledge_gate_" + str(attempt), "knowledge_gate_prompt.md", gate_payload, KnowledgeGateVerdict)
        gate = gate_receipt(verdict, issues, required, [component["component_id"] for component in state["components"]])
        audit["gate"] = gate
        output["candidate_attempts"].append({"attempt": attempt, "candidate": candidate.model_dump(by_alias=True), "gate": gate})
        if not gate["updates_supported"]:
            output["status"] = "knowledge_update_rejected"
            output["error"] = {"type": "UnsupportedKnowledgeUpdate", "retry_performed": False}
            return
        # Received support remains even when a later candidate is rejected.
        audit.update({"after": state, "update_validated": True})
        output["learner_knowledge_model"] = state
        if gate["approved"]:
            output.update({"status": "ok", "decision": driver_decision(decision),
                           "raw_decision": candidate.model_dump(by_alias=True),
                           "memory_audit": {"issues": [], "authority": "Controller-derived compatibility projection; no actor memory accepted"}})
            return
        if attempt == 1 and not issues:
            # Field IDs only: do not teach the actor a solution via rejection.
            payload = controlled_projection(visible, state)
            payload["previous_candidate_rejection"] = {
                "instruction": "The previous proposal exceeded available knowledge. Re-read the current knowledge scopes and choose your own supported response or action. No new learning occurred through this rejection.",
                "fields": [{"path": check.path, "component_ids": check.component_ids}
                           for check in verdict.checks if check.target == "candidate" and not check.supported]}
            continue
        output["status"] = "knowledge_gate_rejected" if not issues else "invalid_decision"
        output["error"] = {"type": "UnsupportedLearnerCandidate" if not issues else "InvalidActionArguments",
                           "issues": issues, "retry_performed": attempt > 1}
        return


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--model")
    parser.add_argument("--effort")
    parser.add_argument("--dry-run", action="store_true", help="Validate/build visible input; make no model request.")
    args = parser.parse_args(argv)
    if args.response.expanduser().resolve().exists():
        print(json.dumps({"status": "output_exists", "response": str(args.response),
                          "api_called": False}))
        return 1
    started = time.perf_counter()
    output = {"status": "invalid_input", "created_at": utcnow(), "decision": None,
              "api": {"called": False}, "error": None}
    phase = "input"
    try:
        request_path = args.request.expanduser().resolve()
        request = json.loads(request_path.read_text(encoding="utf-8"))
        visible, screenshot, image_url = prepare_input(request, request_path)
        model = args.model or request.get("model") or DEFAULT_MODEL
        effort = args.effort or request.get("effort") or DEFAULT_EFFORT
        output.update({
            "screenshot": screenshot,
            "dimension_catalogue_sha256": hashlib.sha256((HERE / "profile_dimensions.json").read_bytes()).hexdigest(),
        })
        phase = "controller" if args.dry_run else "api"
        run_controlled_decision(request, visible, screenshot, image_url,
                                args.response.expanduser().resolve(), model, effort, output,
                                client=None if args.dry_run else existing_client(), dry_run=args.dry_run)
    except Exception as exc:
        output["status"] = {"input": "invalid_input", "api": "api_or_controller_error",
                            "controller": "invalid_input"}[phase]
        # Error bodies, headers, environment and tracebacks can expose secrets.
        output["error"] = {"type": type(exc).__name__, "retry_performed": False}
        if phase == "api":
            output["api"]["http_status"] = getattr(exc, "status_code", None)
            output["api"]["request_id"] = getattr(exc, "request_id", None)
    output["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    save_json(args.response.expanduser().resolve(), output)
    print(json.dumps({"status": output["status"], "response": str(args.response),
                      "response_id": output["api"].get("response_id")}))
    return 0 if output["status"] in {"ok", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
