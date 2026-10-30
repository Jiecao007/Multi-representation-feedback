"""Offline response-grounding contracts; no browser or model requests.

These test annotation projection, provenance links, and input isolation. They
cannot establish annotation truth or whether an LLM will behave like a learner.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("student_grounding_contracts", HERE / "student_model.py")
model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = model
spec.loader.exec_module(model)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class ResponseGroundingContracts(unittest.TestCase):
    def setUp(self):
        self.case = load(HERE / "cases/math_2_numberline.json")
        # This fixture supplies different feature/gap IDs and exercises the
        # original annotation contract without response-conditioned assumptions.
        self.case.pop("response_conditioning", None)
        self.case["response_grounding"] = {
            "source_id": "math-2",
            "present_features": [
                {"feature_id": "axis", "observation": "A drawn axis is present.",
                 "evidence": "Source drawing and scene object number_line_axis."},
                {"feature_id": "labels", "observation": "Signed number labels are present.",
                 "evidence": "Visible handwritten labels in the source response."},
            ],
            "missing_parts": [
                {"gap_id": "operation-model", "missing_part": "The requested operation is not represented.",
                 "evidence": "No operation marks are visible in the source response.",
                 "affected_components": ["K3", "K4"], "initial_awareness": "unaware",
                 "learner_belief": "The labels seem sufficient to me."},
                {"gap_id": "result-support", "missing_part": "A supported result is absent.",
                 "evidence": "The drawing and seeded explanation do not state a result.",
                 "affected_components": ["K5"], "initial_awareness": "unaware",
                 "learner_belief": "I have not formed a numerical result."},
            ],
            "inference_limits": "Observed omissions do not diagnose knowledge, motivation, or awareness.",
        }
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        # This image exists solely to exercise input preparation offline.
        self.png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j2ioAAAAASUVORK5CYII=")
        (self.folder / "visible.png").write_bytes(self.png)
        self.request = {
            "profile": load(HERE / "profiles/p1_average.json"), "case_config": self.case,
            "observation": {"screenshot_path": "visible.png", "visible_text": "Learner-visible drawing",
                            "messages": [], "controls": [], "elements": [], "canvas": None},
            "history": [], "memory": None,
        }
        self.request_path = self.folder / "request.json"

    def prepare(self, case=None):
        request = deepcopy(self.request)
        if case is not None:
            request["case_config"] = case
        visible, _image_provenance, _image_url = model.prepare_input(request, self.request_path)
        return visible

    def test_present_features_and_missing_component_links_are_preserved_separately(self):
        annotation = self.case["response_grounding"]
        projected = model.resolve_response_grounding(self.case)
        self.assertEqual(projected["already_present"], annotation["present_features"])
        omissions = {item["gap_id"]: item for item in projected["response_omissions"]}
        positions = {item["gap_id"]: item for item in projected["learner_starting_position"]}
        for gap in annotation["missing_parts"]:
            omission = omissions[gap["gap_id"]]
            self.assertEqual(omission["missing_part"], gap["missing_part"])
            self.assertEqual(omission["evidence"], gap["evidence"])
            self.assertEqual(omission["affected_components"], gap["affected_components"])
            self.assertNotIn("initial_awareness", omission)
            self.assertNotIn("learner_belief", omission)
            self.assertEqual(positions[gap["gap_id"]]["initial_awareness"], gap["initial_awareness"])
        self.assertEqual(set(omissions), set(positions))

    def test_omission_does_not_automatically_raise_awareness_or_knowledge(self):
        initial = deepcopy(self.case["initial_conceptual_state"])
        for awareness in ("unaware", "notices_incompleteness", "identifies_missing_part"):
            with self.subTest(awareness=awareness):
                case = deepcopy(self.case)
                case["response_grounding"]["missing_parts"][0]["initial_awareness"] = awareness
                visible = self.prepare(case)
                context = visible["case_config"]["initial_response_context"]
                position = next(item for item in context["learner_starting_position"]
                                if item["gap_id"] == "operation-model")
                self.assertEqual(position["initial_awareness"], awareness)
                self.assertEqual(visible["case_config"]["initial_conceptual_state"], initial)
                self.assertEqual(visible["case_config"]["initial_explanation"], self.case["initial_explanation"])
                self.assertEqual(visible["history"], [])
                self.assertIsNone(visible["memory"])
                self.assertNotIn("repair_plan", context)
                self.assertNotIn("utterance", context)

    def test_counterfactual_missing_annotation_changes_context_without_inventing_a_learner_state(self):
        original = model.resolve_response_grounding(self.case)
        changed = deepcopy(self.case)
        changed["response_grounding"]["missing_parts"][0]["affected_components"] = ["K2"]
        changed["response_grounding"]["missing_parts"][0]["missing_part"] = "A different observed omission."
        projected = model.resolve_response_grounding(changed)
        self.assertNotEqual(projected["response_omissions"], original["response_omissions"])
        self.assertEqual(projected["already_present"], original["already_present"])
        self.assertEqual(projected["learner_starting_position"], original["learner_starting_position"])
        self.assertEqual(changed["initial_conceptual_state"], self.case["initial_conceptual_state"])

    def test_empty_feature_and_omission_lists_do_not_manufacture_gaps(self):
        annotation = self.case["response_grounding"]
        annotation["present_features"] = []
        annotation["missing_parts"] = []
        projected = model.resolve_response_grounding(self.case)
        self.assertEqual(projected["already_present"], [])
        self.assertEqual(projected["response_omissions"], [])
        self.assertEqual(projected["learner_starting_position"], [])

    def test_source_mismatch_is_rejected_and_declared_source_aliases_work(self):
        wrong = deepcopy(self.case)
        wrong["response_grounding"]["source_id"] = "ANOTHER_REAL_RESPONSE"
        with self.assertRaises(model.InputBoundaryError):
            model.resolve_response_grounding(wrong)
        for source_key in ("source_id", "example_id", "case_id"):
            with self.subTest(source_key=source_key):
                case = deepcopy(self.case)
                for key in ("source_id", "example_id", "case_id"):
                    case.pop(key, None)
                case[source_key] = "math-2"
                self.assertEqual(model.resolve_response_grounding(case)["source_id"], "math-2")

    def test_unknown_components_empty_evidence_and_duplicate_ids_are_rejected(self):
        mutations = [
            lambda a: a["missing_parts"][0].update(affected_components=["UNKNOWN_COMPONENT"]),
            lambda a: a["missing_parts"][0].update(affected_components=[]),
            lambda a: a["missing_parts"][0].update(affected_components=["K4", "K4"]),
            lambda a: a["missing_parts"][0].update(evidence=" "),
            lambda a: a["missing_parts"][0].update(learner_belief=" "),
            lambda a: a["present_features"][0].update(evidence=" "),
            lambda a: a["present_features"][0].update(feature_id=" "),
            lambda a: a["present_features"].append(deepcopy(a["present_features"][0])),
            lambda a: a["missing_parts"].append(deepcopy(a["missing_parts"][0])),
            lambda a: a.update(inference_limits=" "),
        ]
        for number, mutate in enumerate(mutations):
            with self.subTest(mutation=number):
                case = deepcopy(self.case)
                mutate(case["response_grounding"])
                with self.assertRaises(model.InputBoundaryError):
                    model.resolve_response_grounding(case)

    def test_unknown_annotation_fields_and_answer_keys_fail_closed(self):
        for location in ("annotation", "feature", "gap"):
            for key in ("correct_answer", "unapproved_instruction"):
                with self.subTest(location=location, field=key):
                    case = deepcopy(self.case)
                    annotation = case["response_grounding"]
                    target = {"annotation": annotation, "feature": annotation["present_features"][0],
                              "gap": annotation["missing_parts"][0]}[location]
                    target[key] = "DO_NOT_SEND_THIS_ANSWER"
                    with self.assertRaises(model.InputBoundaryError):
                        self.prepare(case)

    def test_required_awareness_and_evidence_fields_are_not_silently_inferred(self):
        for location, keys in (("annotation", ("source_id", "present_features", "missing_parts", "inference_limits")),
                               ("feature", ("feature_id", "observation", "evidence")),
                               ("gap", ("gap_id", "missing_part", "evidence", "affected_components",
                                        "initial_awareness", "learner_belief"))):
            for key in keys:
                with self.subTest(location=location, field=key):
                    case = deepcopy(self.case)
                    annotation = case["response_grounding"]
                    target = {"annotation": annotation, "feature": annotation["present_features"][0],
                              "gap": annotation["missing_parts"][0]}[location]
                    target.pop(key)
                    with self.assertRaises(model.InputBoundaryError):
                        model.resolve_response_grounding(case)

    def test_prepare_input_uses_only_validated_projection_and_filters_bypass_fields(self):
        self.case["initial_response_context"] = {"correct_answer": "BYPASS_SENTINEL"}
        self.case["unapproved_research_annotation"] = "RESEARCH_SENTINEL"
        visible = self.prepare()
        self.assertNotIn("response_grounding", visible["case_config"])
        self.assertNotIn("unapproved_research_annotation", visible["case_config"])
        self.assertNotIn("BYPASS_SENTINEL", json.dumps(visible))
        self.assertNotIn("RESEARCH_SENTINEL", json.dumps(visible))
        self.assertEqual(visible["case_config"]["initial_response_context"],
                         model.resolve_response_grounding(self.case))

    def test_legacy_case_without_annotation_remains_compatible_and_cannot_inject_context(self):
        self.case.pop("response_grounding")
        self.case.pop("response_conditioning", None)
        self.case["initial_response_context"] = {"correct_answer": "UNVALIDATED_CONTEXT"}
        original = deepcopy(self.case)
        self.assertIsNone(model.resolve_response_grounding(self.case))
        visible = self.prepare()
        self.assertNotIn("initial_response_context", visible["case_config"])
        self.assertEqual(visible["case_config"]["initial_conceptual_state"], original["initial_conceptual_state"])
        self.assertNotIn("UNVALIDATED_CONTEXT", json.dumps(visible))
        self.assertEqual(self.case, original)

    def test_projection_has_no_mutable_alias_back_into_research_annotation(self):
        before = deepcopy(self.case)
        projected = model.resolve_response_grounding(self.case)
        projected["already_present"][0]["observation"] = "Changed projected value."
        projected["response_omissions"][0]["affected_components"].clear()
        self.assertEqual(self.case, before)

    def test_dry_run_records_projected_context_without_calling_a_model(self):
        self.request_path.write_text(json.dumps(self.request), encoding="utf-8")
        output_path = self.folder / "response.json"
        with patch.object(model, "existing_client", side_effect=AssertionError("Offline test must not create a client")) as client:
            code = model.main(["--request", str(self.request_path), "--response", str(output_path), "--dry-run"])
        self.assertEqual(code, 0)
        client.assert_not_called()
        output = load(output_path)
        self.assertFalse(output["api"]["called"])
        self.assertIsNone(output["decision"])
        # Historical response hypotheses remain in the controller request.
        # Current actor input uses only the KM-owned simple knowledge state.
        visible = self.prepare()
        self.assertEqual(visible["case_config"]["initial_response_context"],
                         model.resolve_response_grounding(self.case))
        self.assertNotIn("initial_response_context", output["model_visible_input"]["case_config"])
        self.assertEqual(output["model_visible_input"]["knowledge_state"], {"known": [], "unknown": [], "possibly_known": []})


class ConfiguredCaseGroundingContracts(unittest.TestCase):
    def test_current_real_case_annotation_matches_its_source_and_components(self):
        case = load(HERE / "cases/math_2_numberline.json")
        self.assertIn("response_grounding", case, "The configured real response needs explicit grounding.")
        projected = model.resolve_response_grounding(case)
        self.assertEqual(projected["source_id"], case["source_id"])
        self.assertTrue(projected["already_present"])
        self.assertTrue(projected["response_omissions"])
        component_ids = {item["component_id"] for item in case["initial_conceptual_state"]["knowledge_components"]}
        for gap in projected["response_omissions"]:
            self.assertTrue(set(gap["affected_components"]).issubset(component_ids))
            self.assertTrue(gap["evidence"].strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
