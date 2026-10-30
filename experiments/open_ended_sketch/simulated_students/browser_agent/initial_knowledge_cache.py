"""Cache one Response-based K0; each learner copies it into separate memory.

This is runtime storage, not an Agent or a semantic knowledge assessor. An
exclusive file lock prevents concurrent profile processes from creating the
same initialization twice. No profile or Teacher history enters the cache key.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path

from knowledge_model_agent import KnowledgeInitialization, digest, normalize_knowledge

FORMAT = "initial-knowledge-cache-v1"


class InitialKnowledgeCacheError(ValueError):
    pass


class InitialKnowledgeCache:
    def __init__(self, directory):
        self.directory = Path(directory).expanduser().resolve()

    def get_or_create(self, binding, create):
        """Return a validated snapshot and whether its model call was reused.

        create() returns the parsed initialization reply and its factual call
        provenance. It runs only on a miss, while holding the per-key lock.
        """
        key = digest({"format": FORMAT, "binding": binding})
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / (key + ".json")
        with (self.directory / (key + ".lock")).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if path.exists():
                try:
                    entry = json.loads(path.read_text(encoding="utf-8"))
                    self._validate(entry, key, binding)
                except Exception as exc:
                    raise InitialKnowledgeCacheError("Cached initial knowledge failed its integrity check; use a fresh cache directory.") from exc
                return deepcopy(entry), True, path
            created = create()
            reply = KnowledgeInitialization.model_validate(created["reply"]).model_dump()
            state = normalize_knowledge(reply["knowledge_state"])
            entry = {"format": FORMAT, "key": key, "binding": deepcopy(binding),
                     "knowledge_state": state, "knowledge_sha256": digest(state),
                     "initialization_reply": reply, "origin": deepcopy(created["origin"]),
                     "created_at": datetime.now(timezone.utc).isoformat()}
            entry["entry_sha256"] = digest(entry)
            # Validate before publishing; incomplete/failed calls never seed K0.
            self._validate(entry, key, binding)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
            return deepcopy(entry), False, path

    @staticmethod
    def _validate(entry, key, binding):
        if (not isinstance(entry, dict) or entry.get("format") != FORMAT
                or entry.get("key") != key or entry.get("binding") != binding
                or entry.get("entry_sha256") != digest({k: v for k, v in entry.items() if k != "entry_sha256"})):
            raise InitialKnowledgeCacheError("Cached initialization binding or digest mismatch.")
        reply = KnowledgeInitialization.model_validate(entry["initialization_reply"])
        state = normalize_knowledge(reply.knowledge_state)
        if state != entry.get("knowledge_state") or digest(state) != entry.get("knowledge_sha256"):
            raise InitialKnowledgeCacheError("Cached knowledge does not match its original initialization.")
        if not isinstance(entry.get("origin"), dict):
            raise InitialKnowledgeCacheError("Cached initialization lacks call provenance.")
