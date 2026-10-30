"""Offline checks for matched comparisons, provenance, budgets and portability.

Scripted transport checks never measure actual profile behavior.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compare_profiles as compare
import matched_contexts as contexts
import student_model as model


class ScriptedClient:
    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()
        self.responses = SimpleNamespace(parse=self.parse)

    def parse(self, **kwargs):
        schema = kwargs["text_format"]
        payload = json.loads(kwargs["input"][0]["content"][0]["text"])
        with self.lock:
            self.calls.append({"schema": schema.__name__, "payload": payload})
            number = len(self.calls)
        if schema.__name__ == "KnowledgeMoveCheck":
            value = {"move_id": payload["move"]["move_id"],
                     "knowledge_state": payload["previous_knowledge_state"]}
        elif schema.__name__ == "LearnerAgentReply":
            action = {field.alias or name: None for name, field in model.Action.model_fields.items()}
            action.update(type="select", id="marker_a")
            value = {"action": action, "utterance": None,
                "episodic_memory": {"last_action": "Selected A.", "pending_question": ""}}
        else:
            raise AssertionError("Unexpected third role or initialization API call.")
        return SimpleNamespace(status="completed", output_parsed=schema.model_validate(value),
            output_text=json.dumps(value), id="scripted-" + str(number), model=kwargs["model"],
            _request_id="scripted-request-" + str(number),
            usage=SimpleNamespace(model_dump=lambda: {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}))


class MatchedContextsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.synthetic = [item for item in contexts.SPECS if "archive_step" not in item]

    def test_registered_demands_cover_all_traits_two_boundaries_and_control(self):
        self.assertEqual(len(contexts.SPECS), 8)
        self.assertEqual(sum("archive_step" in spec for spec in contexts.SPECS), 2)
        singles = {spec["dimension"] for spec in self.synthetic if spec["target"] != "P7"}
        self.assertEqual(singles, set(contexts.profile("P1")["dimensions"]))
        for spec in self.synthetic:
            if spec["target"] == "P7":
                continue
            base = contexts.profile("P1")["dimensions"]
            target = contexts.profile(spec["target"])["dimensions"]
            changed = {key for key in base if base[key] != target[key]}
            self.assertEqual(changed, {spec["dimension"]})

    def test_full_dry_run_has_identical_held_context_and_zero_api(self):
        with patch.object(model, "existing_client", side_effect=AssertionError("Dry-run loaded API credentials.")):
            manifest = compare.freeze(self.root / "prepared")
        self.assertEqual(len(manifest["episodes"]), 32)
        self.assertEqual(manifest["role_call_upper_bound"], 64)
        self.assertFalse(manifest["api_called"])
        hashes = {}
        for episode in manifest["episodes"]:
            hashes.setdefault(episode["fixture_id"], set()).add(episode["held_context_sha256"])
            dry = contexts.read_json(self.root / "prepared" / Path(episode["request"]).parent / "dry_run_response.json")
            self.assertEqual(dry["status"], "dry_run")
            self.assertFalse(dry["api_calls"])
        self.assertTrue(all(len(values) == 1 for values in hashes.values()))
        self.assertEqual(compare.verify_prepared(self.root / "prepared")["manifest_content_sha256"],
                         manifest["manifest_content_sha256"])

    def test_synthetic_seed_has_simple_known_state_and_one_pending_move(self):
        spec = self.synthetic[0]
        frozen = contexts.materialize(spec, self.root / "fixture")
        first, _ = contexts.seed_request(frozen, "P1", 1)
        second, _ = contexts.seed_request(frozen, "P2", 2)
        self.assertEqual(contexts.held_context(first), contexts.held_context(second))
        state = first["learner_knowledge_model"]["knowledge_state"]
        self.assertEqual(len(state["known"]), 3)
        self.assertTrue(all(isinstance(value, str) for value in state["known"]))
        self.assertEqual(state["unknown"], [])
        self.assertEqual(state["possibly_known"], [])
        self.assertNotIn("components", contexts.held_context(first))

    def test_archive_import_does_not_promote_negative_uncertainty_or_change_archive(self):
        spec = contexts.SPECS[0]
        source = contexts.ARCHIVE / "P7/step_03_request.json"
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        frozen = contexts.materialize(spec, self.root / "archive")
        request, receipts = contexts.seed_request(frozen, "P1", 1)
        state = request["learner_knowledge_model"]["knowledge_state"]
        self.assertEqual(len(state["known"]), 1)
        self.assertEqual(state["unknown"], [])
        self.assertEqual(state["possibly_known"], [])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        self.assertEqual(len(receipts), 3)  # Fixture seed + two prior message identities.
        self.assertIn("constant imported pre-turn state", frozen["provenance"]["reinterpretation"])

    def test_legacy_conversion_uses_structural_provenance_not_an_english_classifier(self):
        legacy = {"components": [{"initial_status": "tentative", "available_knowledge": [
            {"statement": "Initial absence note.", "basis": "initial_tentative"},
            {"statement": "The direction does not reverse in this local case.", "basis": "received_local_support"},
            {"statement": "This confirmed local move ends at B.", "basis": "received_local_support",
             "evidence_basis": "attempt_confirmation"}],
            "attempted_beliefs": [{"statement": "I think the route reverses at C."}]}]}
        state = contexts.imported_knowledge_state(legacy)
        self.assertEqual(state["known"], ["This confirmed local move ends at B."])
        self.assertEqual(state["unknown"], [])
        self.assertEqual(state["possibly_known"], [
            "The direction does not reverse in this local case.", "I think the route reverses at C."])

    def test_synthetic_cross_form_fixture_contains_a_real_direction_discrepancy(self):
        spec = next(spec for spec in contexts.SPECS if spec["id"] == "cross_form_discrepancy")
        value = contexts.synthetic_fixture(spec)
        link = next(item for item in value["observation"]["elements"] if item["id"] == "link_bc")
        self.assertEqual((link["from"], link["to"]), ("marker_c", "marker_b"))
        self.assertIn("A, B, C", value["case_config"]["initial_explanation"])

    def test_prepared_input_tampering_is_rejected_before_live_client(self):
        prepared = self.root / "prepared"
        manifest = compare.freeze(prepared, specs=[self.synthetic[0]])
        request = prepared / manifest["episodes"][0]["request"]
        request.write_text(request.read_text() + " ")
        with patch.object(model, "existing_client", side_effect=AssertionError("Client constructed before verification.")):
            with self.assertRaisesRegex(ValueError, "request was modified"):
                compare.run_live(prepared, self.root / "live")

    def test_fresh_output_only_preserves_existing_evidence(self):
        target = self.root / "existing"
        target.mkdir()
        marker = target / "keep.json"
        marker.write_text("{}")
        with self.assertRaises(FileExistsError):
            compare.freeze(target, specs=[self.synthetic[0]])
        self.assertEqual(marker.read_text(), "{}")

    def test_bounded_transport_rejects_wrong_role_and_third_call(self):
        client = ScriptedClient()
        bounded = compare.BoundedClient(client)
        wrong = type("KnowledgeInitialization", (), {})
        with self.assertRaisesRegex(ValueError, "budget or order"):
            bounded.parse(text_format=wrong)
        self.assertEqual(bounded.calls, 0)
        bounded.calls = 2
        with self.assertRaisesRegex(ValueError, "budget or order"):
            bounded.parse(text_format=model.LearnerAgentReply)
        self.assertEqual(client.calls, [])

    def test_copied_live_bundle_uses_exact_frozen_requests_and_only_two_roles(self):
        prepared, live = self.root / "prepared", self.root / "live"
        manifest = compare.freeze(prepared, specs=[self.synthetic[-1]])
        client = ScriptedClient()
        result = compare.run_live(prepared, live, client=client)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["actual_role_calls"], 8)
        self.assertEqual(len(client.calls), 8)
        self.assertEqual({item["schema"] for item in client.calls}, {"KnowledgeMoveCheck", "LearnerAgentReply"})
        self.assertTrue(all(episode["metrics"]["status"] == "ok" for episode in result["episodes"]))
        self.assertTrue(all(not episode["metrics"]["semantic_entailment_checked"] for episode in result["episodes"]))
        for episode in manifest["episodes"]:
            self.assertEqual((prepared / episode["request"]).read_bytes(), (live / episode["request"]).read_bytes())
            self.assertFalse((prepared / Path(episode["request"]).parent / "step_01_response.json").exists())
            actual = contexts.read_json(live / Path(episode["request"]).parent / "step_01_response.json")
            actor_input = actual["model_visible_input"]
            self.assertIn(self.synthetic[-1]["teacher"], json.dumps(actor_input))
            self.assertIn("knowledge_state", actor_input)
            for removed in ("current_turn", "content_grounding", "response_permissions"):
                self.assertNotIn(removed, json.dumps(actor_input))
            images = contexts.read_json(live / Path(episode["request"]).parent / "step_01_learner_agent.images.json")
            self.assertIn("synthetic_full.png", images[0]["path"])


if __name__ == "__main__":
    unittest.main()
