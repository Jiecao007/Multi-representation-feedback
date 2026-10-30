"""Two-agent knowledge memory: optional knowledge lists and once-per-move updates.

The model owns semantic knowledge decisions. Python supplies typed replies,
chronological public context, save-before-action storage and checkpoint integrity.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict

FORMAT = "knowledge-model-agent-v4"


class KnowledgeAgentBoundaryError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeState(StrictModel):
    known: Optional[list[str]] = None
    unknown: Optional[list[str]] = None
    possibly_known: Optional[list[str]] = None


class KnowledgeInitialization(StrictModel):
    knowledge_state: KnowledgeState


class KnowledgeMoveCheck(StrictModel):
    move_id: str
    knowledge_state: KnowledgeState


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def normalize_knowledge(value):
    value = KnowledgeState.model_validate(value) if isinstance(value, dict) else value
    result = {}
    for key in KnowledgeState.model_fields:
        entries = getattr(value, key) or []
        if any(not item.strip() for item in entries):
            raise KnowledgeAgentBoundaryError("Knowledge entries must be nonempty statements; use an empty list when unassessed.")
        result[key] = list(dict.fromkeys(item.strip() for item in entries))
    return result


def _finish(state):
    state["content_sha256"] = digest({key: state[key] for key in (
        "owner_id", "case_binding", "knowledge_profile_binding", "knowledge_state")})
    state["state_sha256"] = digest({key: value for key, value in state.items() if key != "state_sha256"})
    return state


def public_moves(observation):
    moves, seen = [], set()
    for message in observation.get("messages", []):
        if message.get("role") not in {"assistant", "tutor"} or message.get("error"):
            continue
        index, text = message.get("index"), message.get("text")
        if not isinstance(index, int) or isinstance(index, bool) or not isinstance(text, str):
            raise KnowledgeAgentBoundaryError("Delivered Teacher moves need stable integer indices and text.")
        mid = "message:" + str(index)
        if mid in seen:
            raise KnowledgeAgentBoundaryError("Delivered Teacher move indices must be unique.")
        seen.add(mid)
        payload = {"message_index": index, "text": text}
        moves.append({"move_id": mid, "message_index": index, "text": text,
                      "sha256": digest(payload), "payload": payload})
    return sorted(moves, key=lambda value: value["message_index"])


def _bounded_history(history, current_index):
    """Do not give an earlier backlog check actions that happened after it."""
    result = []
    for event in history or []:
        if not isinstance(event, dict):
            continue
        proof = event.get("learning_observation") or {}
        context = proof.get("action_context_move_id", "")
        if isinstance(context, str) and context.startswith("message:"):
            try:
                if int(context.split(":", 1)[1]) >= current_index:
                    continue
            except ValueError:
                continue
        user = proof.get("user_message_indices") or []
        feedback = proof.get("feedback_message_indices") or []
        if user and min(user) >= current_index or not user and feedback and min(feedback) > current_index:
            continue
        result.append({key: deepcopy(value) for key, value in event.items()
                       if key in {"step", "action", "result", "utterance", "learning_observation"}})
    return result


class KnowledgeModelAgent:
    """Knowledge state and runtime bookkeeping; no learner answer generation."""
    def __init__(self, case_config, prior_knowledge=None, owner_id=None, persisted=None,
                 knowledge_profile=None):
        self.case_config = deepcopy(case_config)
        initial = _finish({"format": FORMAT, "agent": "KnowledgeModelAgent", "owner_id": owner_id,
            "case_binding": digest(case_config), "knowledge_profile_binding": digest(knowledge_profile),
            "initialized": False, "revision": 0, "event_revision": 0,
            "knowledge_state": normalize_knowledge({}), "processed_move_ids": [],
            "move_checks": [], "initialization": None})
        # prior_knowledge is a compatibility argument only. The model initializes
        # its own state from original Response evidence, without forced statuses.
        if persisted is None:
            self.state = initial
            return
        if not isinstance(persisted, dict) or persisted.get("format") != FORMAT:
            raise KnowledgeAgentBoundaryError("Unsupported Knowledge Model Agent state format; start a new learner instance.")
        if any(persisted.get(key) != initial[key] for key in (
                "owner_id", "case_binding", "knowledge_profile_binding")):
            raise KnowledgeAgentBoundaryError("Knowledge memory belongs to another learner, case or uptake profile.")
        if persisted.get("state_sha256") != digest({k: v for k, v in persisted.items() if k != "state_sha256"}):
            raise KnowledgeAgentBoundaryError("Knowledge state digest mismatch.")
        cursor = persisted.get("processed_move_ids")
        if not isinstance(cursor, list) or len(cursor) != len(set(cursor)) or cursor != [
                item.get("move", {}).get("move_id") for item in persisted.get("move_checks", [])]:
            raise KnowledgeAgentBoundaryError("Processed Teacher moves differ from the stored check log.")
        if normalize_knowledge(persisted.get("knowledge_state", {})) != persisted.get("knowledge_state"):
            raise KnowledgeAgentBoundaryError("Persisted knowledge state is not normalized.")
        self.state = deepcopy(persisted)

    def initialization_payload(self, public_initial_context=None):
        if self.state["initialized"]:
            raise KnowledgeAgentBoundaryError("Knowledge initialization is exactly once.")
        context = public_initial_context or {}
        return {"mode": "initialize",
            "task": {key: deepcopy(value) for key, value in self.case_config.items()
                     if key in {"source_id", "source_title", "task", "task_text"}},
            "initial_response": {
                "student_response_text": context.get("student_response_text", self.case_config.get("initial_explanation", "")),
                "figures": deepcopy(context.get("figures", [])),
                "initialization_excludes_feedback": True}}

    def initialize(self, parsed, *, public_initial_context=None, require_current=False):
        if self.state["initialized"]:
            raise KnowledgeAgentBoundaryError("Knowledge initialization is exactly once.")
        parsed = KnowledgeInitialization.model_validate(parsed) if isinstance(parsed, dict) else parsed
        knowledge = normalize_knowledge(parsed.knowledge_state)
        self.state["knowledge_state"] = knowledge
        self.state["initialized"] = True
        self.state["initialization"] = {"reply": parsed.model_dump()}
        _finish(self.state)
        return {"mode": "initialize", "check_complete": True, "warnings": [],
                "after": deepcopy(self.state), "semantic_authority": "KnowledgeModelAgent"}

    def pending_moves(self, observation, history=None):
        actual = public_moves(observation)
        by_id = {move["move_id"]: move for move in actual}
        for record in self.state["move_checks"]:
            if by_id.get(record["move"]["move_id"]) != record["move"]:
                raise KnowledgeAgentBoundaryError("A previously checked Teacher move differs from delivered history.")
        return [move for move in actual if move["move_id"] not in self.state["processed_move_ids"]]

    def move_payload(self, move, observation, history):
        if not self.state["initialized"]:
            raise KnowledgeAgentBoundaryError("Initialize knowledge before checking Teacher moves.")
        pending = self.pending_moves(observation, history)
        if not pending or pending[0] != move:
            raise KnowledgeAgentBoundaryError("Check each delivered Teacher move once in chronological order.")
        visible = deepcopy(observation)
        visible["messages"] = [item for item in visible.get("messages", [])
                               if item.get("index", -1) <= move["message_index"]]
        # Only the latest pending turn may see its current visual observation.
        if len(pending) > 1:
            visible = {"messages": visible["messages"]}
        return {"mode": "check_move", "previous_knowledge_state": self.project(),
                "move": deepcopy(move), "observation": visible,
                "history": _bounded_history(history, move["message_index"])}

    def check_move(self, move, parsed, *, observation=None, history=None, evidence=None,
                   require_current=False):
        if not self.state["initialized"]:
            raise KnowledgeAgentBoundaryError("Initialize knowledge before checking Teacher moves.")
        parsed = KnowledgeMoveCheck.model_validate(parsed) if isinstance(parsed, dict) else parsed
        if parsed.move_id != move.get("move_id"):
            raise KnowledgeAgentBoundaryError("Knowledge reply must identify its exact Teacher move.")
        if move["move_id"] in self.state["processed_move_ids"]:
            raise KnowledgeAgentBoundaryError("A Teacher move may be checked only once.")
        if observation is not None:
            pending = self.pending_moves(observation, history)
            if not pending or pending[0] != move:
                raise KnowledgeAgentBoundaryError("Teacher checks must follow delivered chronological order.")
        previous_index = self.state["move_checks"][-1]["move"]["message_index"] if self.state["move_checks"] else -1
        if move.get("message_index", -1) <= previous_index:
            raise KnowledgeAgentBoundaryError("Teacher checks must follow chronological order.")
        knowledge = normalize_knowledge(parsed.knowledge_state)
        before = deepcopy(self.state)
        changed = knowledge != self.state["knowledge_state"]
        self.state["knowledge_state"] = knowledge
        self.state["revision"] += int(changed)
        self.state["event_revision"] += 1
        self.state["processed_move_ids"].append(move["move_id"])
        self.state["move_checks"].append({"move": deepcopy(move), "reply": parsed.model_dump(),
                                          "changed": changed})
        _finish(self.state)
        return {"mode": "check_move", "move_id": move["move_id"], "check_complete": True,
                "decision": "update" if changed else "no_change", "warnings": [],
                "before": before, "after": deepcopy(self.state),
                "semantic_authority": "KnowledgeModelAgent"}

    def project(self):
        return deepcopy(self.state["knowledge_state"])

    def learner_projection(self):
        return self.project()

    def memory_component_states(self):
        return []  # Historical driver memory is not a second knowledge state.

    def save(self, path):
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(destination)

    def save_memory(self, path):
        self.save(path)

    def run_initialize(self, call_adapter, public_initial_context=None, *, memory_path=None):
        parsed = call_adapter(self.initialization_payload(public_initial_context), KnowledgeInitialization)
        receipt = self.initialize(parsed)
        if memory_path is not None:
            self.save_memory(memory_path)
        return receipt

    def run_move(self, call_adapter, move, observation, history, *, memory_path=None):
        parsed = call_adapter(self.move_payload(move, observation, history), KnowledgeMoveCheck)
        receipt = self.check_move(move, parsed, observation=observation, history=history)
        if memory_path is not None:
            self.save_memory(memory_path)
        return receipt
