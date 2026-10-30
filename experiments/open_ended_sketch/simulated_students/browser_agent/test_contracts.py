"""Offline contracts; no browser, feedback request, or model API call.

Optionally set SIMULATED_STUDENT_AUDIT_DIR to audit a completed live run.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parents[1]
ROOT = HERE.parents[3]
spec = importlib.util.spec_from_file_location("browser_student_model_contracts", HERE / "student_model.py")
model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = model
spec.loader.exec_module(model)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical_sha(value):
    return sha(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())


def image_bytes(data_url):
    return base64.b64decode(data_url.split(",", 1)[1], validate=True)


class ConfigurationContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p1 = load(HERE / "profiles/p1_average.json")
        cls.p2 = load(HERE / "profiles/p2_low_motivation.json")
        cls.case = load(HERE / "cases/math_2_numberline.json")
        cls.catalogue = load(HERE / "profile_dimensions.json")

    def test_profiles_change_only_motivation_and_id(self):
        left, right = deepcopy(self.p1), deepcopy(self.p2)
        self.assertEqual((left.pop("id"), right.pop("id")), ("P1", "P2"))
        m1 = left["dimensions"].pop("task_motivation")
        m2 = right["dimensions"].pop("task_motivation")
        self.assertEqual((m1["level"], m2["level"]), ("average", "low"))
        self.assertNotEqual(m1, m2)
        self.assertEqual(left, right, "A non-motivation trait or shared instruction changed.")
        self.assertEqual(set(left["dimensions"]), {
            "feedback_processing", "textual_representation", "diagrammatic_representation",
            "coordination_translation"})
        self.assertTrue(left["constructed_profile"])
        self.assertTrue(all(d["level"] == "average" for d in left["dimensions"].values()))

    def test_p3_and_p4_change_only_their_selected_component(self):
        for filename, profile_id, component in (
            ("p3_low_feedback_uptake.json", "P3", "feedback_processing"),
            ("p4_low_textual_expression.json", "P4", "textual_representation"),
        ):
            with self.subTest(profile=profile_id):
                baseline = deepcopy(self.p1)
                selected = load(HERE / "profiles" / filename)
                self.assertEqual(selected.pop("id"), profile_id)
                baseline.pop("id")
                self.assertEqual(selected["dimensions"][component]["level"], "low")
                selected["dimensions"][component]["level"] = "average"
                self.assertEqual(selected, baseline,
                                 "A second trait or shared learner instruction changed.")

    def test_representation_is_one_construct_with_exactly_three_selected_components(self):
        resolved = model.resolve_profile(self.p1, self.case)
        self.assertEqual(set(resolved["constructs"]), {"representation_ability"})
        components = resolved["constructs"]["representation_ability"]["components"]
        self.assertEqual(components, {
            "textual_expression": "textual_representation",
            "diagrammatic_expression": "diagrammatic_representation",
            "coordination_and_translation": "coordination_translation",
        })
        for selected_key in components.values():
            self.assertIn(selected_key, resolved["dimensions"])
        self.assertNotIn("compatibility", resolved)

    def test_legacy_four_key_profile_adds_an_explicit_coordination_default(self):
        legacy = deepcopy(self.p1)
        legacy["dimensions"].pop("coordination_translation")
        original = deepcopy(legacy)
        resolved = model.resolve_profile(legacy, self.case)
        self.assertEqual(legacy, original, "Resolution must not modify the saved configuration.")
        self.assertEqual(resolved["dimensions"]["coordination_translation"]["level"], "average")
        self.assertTrue(resolved["compatibility"]["legacy_four_component_profile"])
        self.assertIn("not an observed", resolved["compatibility"]["interpretation"])
        legacy["dimensions"].pop("feedback_processing")
        with self.assertRaises(model.InputBoundaryError):
            model.resolve_profile(legacy, self.case)

    def test_math_2_case_has_provenance_without_oracle(self):
        self.assertEqual(self.case["source_id"], "math-2")
        self.assertTrue(self.case["initial_explanation"].strip())
        self.assertTrue(self.case["initial_conceptual_state"]["constructed"])
        self.assertTrue(self.case["provenance"]["constructed_initial_explanation"])
        model.ensure_no_private_fields(self.case)
        entries = load(EXPERIMENT / "app/examples.json")
        example = next(item for item in entries if item["id"] == "math-2")
        manifest = load(EXPERIMENT / example["run"] / (example["sample"] + ".input_manifest.json"))
        scene = load(EXPERIMENT / example["run"] / (example["sample"] + ".scene.json"))
        source_image = Path(manifest["original_path"])
        if not source_image.is_absolute():
            source_image = EXPERIMENT / example["run"] / source_image
        self.assertEqual(sha(source_image.read_bytes()), self.case["provenance"]["student_crop_sha256"])
        self.assertEqual(scene["relations"], [], "The seed is the unworked number-line setup.")
        self.assertEqual(self.case["task_text"], manifest["task"])

    def test_seed_has_specific_unlearned_components_without_a_worked_answer(self):
        initial = self.case["initial_conceptual_state"]
        components = {item["component_id"]: item for item in initial["knowledge_components"]}
        self.assertEqual(len(components), len(initial["knowledge_components"]), "Component IDs must be unique.")
        self.assertEqual(components["K1"]["status"], "known")
        self.assertEqual(components["K2"]["status"], "tentative")
        for component_id in ("K3", "K4", "K5"):
            self.assertEqual(components[component_id]["status"], "unlearned")
        # This deliberately unworked seed describes uncertainty, not calculated
        # endpoints. The task itself retains its necessary card values.
        seed_statements = [self.case["initial_explanation"], initial["initial_belief"]]
        seed_statements.extend(item["statement"] for item in components.values())
        self.assertFalse(any(re.search(r"\d", text) for text in seed_statements),
                         "Do not bootstrap a numerical solution in the constructed seed prose.")
        self.assertNotIn("correct_answer", self.case)
        self.assertNotIn("solution", initial)
        self.assertNotIn("actions", initial)

    def test_selected_levels_expand_independently_and_share_brevity(self):
        baseline = model.resolve_profile(self.p1, self.case)
        self.assertEqual(set(baseline["dimensions"]), set(self.catalogue["dimensions"]))
        for dimension, definition in self.catalogue["dimensions"].items():
            self.assertEqual(set(definition["levels"]), {"average", "low"})
            for level in ("average", "low"):
                with self.subTest(dimension=dimension, level=level):
                    selected = deepcopy(self.p1)
                    selected["dimensions"][dimension]["level"] = level
                    expanded = model.resolve_profile(selected, self.case)
                    self.assertEqual(expanded["dimensions"][dimension]["level"], level)
                    self.assertEqual(expanded["dimensions"][dimension]["operational_behavior"],
                                     definition["levels"][level])
                    for other in set(baseline["dimensions"]) - {dimension}:
                        self.assertEqual(expanded["dimensions"][other], baseline["dimensions"][other])
                    self.assertEqual(expanded["shared_communication_style"], baseline["shared_communication_style"])
                    self.assertEqual(expanded["case_dimensions"], baseline["case_dimensions"])

    def test_unsupported_levels_and_silent_behavior_overrides_are_rejected(self):
        for bad in ({"level": "expert"}, {"level": None}, {"level": []},
                    {"level": "low", "behavioral_tendency": "Pretend to be an expert."}):
            with self.subTest(configuration=bad):
                profile = deepcopy(self.p1)
                profile["dimensions"]["task_motivation"] = bad
                with self.assertRaises(model.InputBoundaryError):
                    model.resolve_profile(profile, self.case)
        profile = deepcopy(self.p1)
        profile["dimensions"]["prior_knowledge"] = {"level": "average"}
        with self.assertRaises(model.InputBoundaryError):
            model.resolve_profile(profile, self.case)

    def test_case_category_requires_a_catalogue_definition(self):
        case = deepcopy(self.case)
        case["initial_conceptual_state"]["misconception_type"] = "UNCONFIGURED"
        with self.assertRaises(model.InputBoundaryError):
            model.resolve_profile(self.p1, case)


class StudentInputContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.request_path = self.dir / "request.json"
        # Valid 1x1 PNG; this fixture is never submitted to a model.
        self.png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j2ioAAAAASUVORK5CYII=")
        (self.dir / "visible.png").write_bytes(self.png)
        self.request = {
            "profile": load(HERE / "profiles/p1_average.json"),
            "case_config": load(HERE / "cases/math_2_numberline.json"),
            "observation": {"screenshot_path": "visible.png", "visible_text": "Visible learner UI",
                            "messages": [{"index": 0, "role": "assistant", "text": "What does your line show?"}],
                            "elements": [], "controls": [], "canvas": None},
            "history": [], "memory": None,
        }

    def test_prepare_input_excludes_research_metadata_and_checks_image(self):
        self.request["profile"]["reference_solution"] = "PROFILE_ORACLE_SENTINEL"
        self.request["case_config"]["correct_answer"] = "CASE_ORACLE_SENTINEL"
        visible, provenance, url = model.prepare_input(self.request, self.request_path)
        serialized = json.dumps(visible)
        self.assertNotIn("ORACLE_SENTINEL", serialized)
        self.assertNotIn("provenance", visible["case_config"])
        self.assertNotIn("screenshot_path", visible["observation"])
        self.assertEqual(visible["observation"]["messages"], self.request["observation"]["messages"])
        self.assertEqual(provenance["sha256"], sha(self.png))
        self.assertEqual(image_bytes(url), self.png)

    def test_unapproved_observation_field_fails_closed(self):
        self.request["observation"]["backend_payload"] = {"answer": "hidden"}
        with self.assertRaises(model.InputBoundaryError):
            model.prepare_input(self.request, self.request_path)

    def test_nested_private_fields_cannot_enter_observation_history_or_memory(self):
        for location in ("observation", "history", "memory"):
            with self.subTest(location=location):
                request = deepcopy(self.request)
                secret = {"private_assessment": "PRIVATE_SENTINEL"}
                if location == "observation":
                    request["observation"]["elements"] = [secret]
                elif location == "history":
                    request["history"] = [{"result": secret}]
                else:
                    request["memory"] = secret
                with self.assertRaises(model.InputBoundaryError):
                    model.prepare_input(request, self.request_path)

    def test_dry_run_cannot_call_client_or_invent_decision(self):
        self.request_path.write_text(json.dumps(self.request), encoding="utf-8")
        response_path = self.dir / "response.json"
        with patch.object(model, "existing_client", side_effect=AssertionError("No API in offline contract")) as client:
            code = model.main(["--request", str(self.request_path), "--response", str(response_path), "--dry-run"])
        self.assertEqual(code, 0)
        client.assert_not_called()
        result = load(response_path)
        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(result["api"]["called"])
        self.assertIsNone(result["decision"])

    def test_hint_button_is_an_available_decision_action(self):
        action = {(field.alias or name): None for name, field in model.Action.model_fields.items()}
        action["type"] = "request_hint"
        parsed = model.Action.model_validate(action)
        self.assertEqual(parsed.type, "request_hint")
        self.assertIn("request_hint", model.Action.model_json_schema()["properties"]["type"]["enum"])


class MemoryProvenanceContracts(unittest.TestCase):
    def setUp(self):
        self.case = load(HERE / "cases/math_2_numberline.json")
        action = {(field.alias or name): None for name, field in model.Action.model_fields.items()}
        action["type"] = "begin_revision"
        states = []
        for item in self.case["initial_conceptual_state"]["knowledge_components"]:
            evidence = [] if item["status"] == "unlearned" else [{
                "source": "initial_case", "reference": "initial:" + item["component_id"],
                "support": "Constructed starting state.",
            }]
            states.append({"component_id": item["component_id"], "status": item["status"],
                           "statement": item["statement"], "evidence": evidence})
        self.decision = model.StudentDecision.model_validate({
            "action": action, "utterance": None,
            "memory": {"current_understanding": "The drawing has labels.",
                       "unresolved_question": "How does that represent this task?",
                       "next_intention": "Inspect the editor.", "component_states": states},
        })
        self.visible = {"case_config": self.case, "observation": {"messages": [
            {"index": 0, "role": "assistant", "text": "What does this feature tell you?"}]},
            "history": [], "memory": None}

    def component(self, component_id):
        return next(item for item in self.decision.memory.component_states if item.component_id == component_id)

    def test_initial_state_is_preserved_and_valid_past_evidence_can_be_cited(self):
        self.assertFalse(model.audit_memory(self.decision, self.visible)["issues"])
        component = self.component("K2")
        component.evidence = [model.LearningEvidence(source="visible_message", reference="message:0",
                                                    support="A local question made me reconsider this feature.")]
        self.assertFalse(model.audit_memory(self.decision, self.visible)["issues"])
        self.visible["history"] = [{"step": 1, "action": {"type": "select", "id": "visible-part"},
                                    "result": {"ok": True}}]
        component.evidence = [model.LearningEvidence(source="completed_action", reference="action:1",
                                                    support="I inspected the selected visible part.")]
        self.assertFalse(model.audit_memory(self.decision, self.visible)["issues"])

    def test_future_action_and_missing_message_do_not_supply_provenance(self):
        for source, reference in (("completed_action", "action:1"), ("visible_message", "message:8")):
            with self.subTest(source=source):
                component = self.component("K3")
                component.status = "known"
                component.evidence = [model.LearningEvidence(source=source, reference=reference,
                                                            support="This has not actually happened.")]
                original = self.decision.model_dump()
                audit = model.audit_memory(self.decision, self.visible)
                self.assertTrue(audit["issues"])
                self.assertIn({"component_id": "K3", "before": "unlearned", "after": "known"},
                              audit["component_state_changes"])
                self.assertEqual(self.decision.model_dump(), original,
                                 "An audit must not silently manufacture a repair or rewrite learner state.")

    def test_seed_only_or_absent_evidence_cannot_justify_a_new_known_claim(self):
        component = self.component("K3")
        component.status = "known"
        for evidence in ([], [model.LearningEvidence(source="initial_case", reference="initial:K3",
                                                    support="The seed explicitly left this unlearned.")]):
            with self.subTest(evidence=evidence):
                component.evidence = evidence
                self.assertTrue(model.audit_memory(self.decision, self.visible)["issues"])

    def test_state_change_is_compared_to_previous_memory_not_repeated_as_new_learning(self):
        component = self.component("K2")
        component.status = "known"
        component.evidence = [model.LearningEvidence(source="visible_message", reference="message:0",
                                                    support="A remembered past interaction.")]
        self.visible["memory"] = self.decision.memory.model_dump()
        audit = model.audit_memory(self.decision, self.visible)
        self.assertEqual(audit["component_state_changes"], [])

    def test_missing_duplicate_and_unknown_components_are_audited(self):
        self.decision.memory.component_states.pop()
        self.decision.memory.component_states.append(self.component("K1").model_copy(deep=True))
        unknown = self.component("K1").model_copy(update={"component_id": "NOT_IN_CASE"}, deep=True)
        self.decision.memory.component_states.append(unknown)
        self.assertGreaterEqual(len(model.audit_memory(self.decision, self.visible)["issues"]), 3)


@unittest.skipUnless(os.getenv("SIMULATED_STUDENT_AUDIT_DIR"), "Set SIMULATED_STUDENT_AUDIT_DIR for completed-run audit.")
class CompletedRunContracts(unittest.TestCase):
    def test_same_start_and_unmodified_source_in_both_ui_downloads(self):
        output = Path(os.environ["SIMULATED_STUDENT_AUDIT_DIR"]).resolve()
        manifest = load(output / "experiment_manifest.json")
        self.assertFalse(manifest["dry_run"])
        self.assertEqual(manifest["seed"]["source_id"], "math-2")
        expected_profiles = {profile["id"] for profile in manifest["profiles"]}
        self.assertTrue(expected_profiles)
        self.assertEqual(len(expected_profiles), len(manifest["profiles"]))
        self.assertEqual({run["profile_id"] for run in manifest["runs"]}, expected_profiles)
        self.assertEqual(len(manifest["runs"]), len(expected_profiles))
        seed = manifest["seed"]
        payload = load(output / "seed_payload.json")
        self.assertEqual(canonical_sha(payload["scene"]), seed["scene_sha256"])
        self.assertEqual(sha(image_bytes(payload["original"])), seed["image_sha256"])
        self.assertEqual(sha((output / "original_student_response.png").read_bytes()), seed["image_sha256"])
        for run in manifest["runs"]:
            with self.subTest(profile=run["profile_id"]):
                self.assertIn(run["status"], {"student_stopped", "step_budget_reached"})
                self.assertEqual(run["source_id"], seed["source_id"])
                self.assertEqual(run["initial_scene_sha256"], seed["scene_sha256"])
                self.assertEqual(run["original_image_sha256"], seed["image_sha256"])
                self.assertEqual(run["student_model"], manifest["student_model"])
                self.assertEqual(run["effort"], manifest["effort"])
                self.assertEqual(run["max_student_decisions"], manifest["max_student_decisions"])
                explanation = manifest["case_config"]["initial_explanation"]
                self.assertEqual(run["initial_explanation_sha256"], sha(explanation.encode()))
                run_dir = output / run["run_id"]
                exported = run["exports"]
                self.assertIsNotNone(exported)
                saved = load(run_dir / exported["exploration_path"])
                self.assertEqual(saved["source"]["id"], seed["source_id"])
                self.assertEqual(canonical_sha(saved["original_model"]), seed["scene_sha256"])
                self.assertEqual(sha(image_bytes(saved["original_image"])), seed["image_sha256"])
                self.assertEqual(saved["workspace_state"]["initial_explanation"], explanation)
                html = (run_dir / exported["html_path"]).read_text(encoding="utf-8")
                self.assertIn("Feedback dialogue", html)
                events = [json.loads(line) for line in (run_dir / "action_trace.jsonl").read_text().splitlines() if line.strip()]
                self.assertEqual(len(events), len(run["steps"]))
                self.assertLessEqual(len(events), manifest["max_student_decisions"])
                for number, event in enumerate(events, 1):
                    self.assertEqual(event["step"], number)
                    self.assertIn("ok", event["execution"])
                    self.assertIn("action", event["decision"])
                if run["status"] == "student_stopped":
                    self.assertEqual(events[-1]["decision"]["action"]["type"], "stop")
                else:
                    self.assertEqual(len(events), manifest["max_student_decisions"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
