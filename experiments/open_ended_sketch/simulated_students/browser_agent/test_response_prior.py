"""Response-bound starting knowledge contracts; no model or browser requests."""
from copy import deepcopy
import base64
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("response_prior_student", HERE / "student_model.py")
model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = model
spec.loader.exec_module(model)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


class ResponsePriorContracts(unittest.TestCase):
    def setUp(self):
        self.case = load(HERE / "cases/math_2_numberline.json")
        self.profile = load(HERE / "profiles/p1_average.json")

    def test_all_profiles_share_the_same_submission_bound_prior(self):
        expected = model.resolve_prior_knowledge(self.case)
        before = deepcopy(self.case)
        self.assertEqual(expected["source_id"], self.case["source_id"])
        components = {c["component_id"]: c for c in expected["components"]}
        self.assertEqual(components["K1"]["response_evidence_ids"], ["feature:F1", "feature:F2"])
        self.assertEqual(components["K3"]["response_evidence_ids"], ["gap:G1"])
        self.assertEqual(components["K4"]["response_evidence_ids"], ["gap:G1"])
        self.assertEqual(components["K5"]["response_evidence_ids"], ["gap:G2"])
        for path in (HERE / "profiles").glob("*.json"):
            profile = load(path)
            original = deepcopy(profile)
            self.assertEqual(model.resolve_profile(profile, self.case)["prior_knowledge"], expected)
            self.assertEqual(profile, original)
        self.assertEqual(self.case, before)

    def test_status_and_statement_come_from_configured_knowledge_not_ability_levels(self):
        prior = model.resolve_profile(self.profile, self.case)["prior_knowledge"]
        states = {c["component_id"]: c for c in self.case["initial_conceptual_state"]["knowledge_components"]}
        for component in prior["components"]:
            original = states[component["component_id"]]
            self.assertEqual(component["status"], original["status"])
            self.assertEqual(component["statement"], original["statement"])
            self.assertTrue(component["initial_limitation"].strip())
            self.assertTrue(component["learning_requirement"].strip())
        self.assertEqual({c["component_id"] for c in prior["components"] if c["status"] == "unlearned"}, {"K3", "K4", "K5"})

    def test_mismatched_response_and_unlinked_or_duplicate_components_are_rejected(self):
        mutations = [
            lambda c: c["response_conditioning"].update(source_id="other-response"),
            lambda c: c["response_conditioning"]["component_bindings"].pop(),
            lambda c: c["response_conditioning"]["component_bindings"].append(deepcopy(c["response_conditioning"]["component_bindings"][0])),
            lambda c: c["response_conditioning"]["component_bindings"][0].update(response_feature_ids=["not-present"]),
            lambda c: c["response_conditioning"]["component_bindings"][0].update(response_feature_ids=[], response_gap_ids=["G1"]),
            lambda c: c["response_conditioning"]["component_bindings"][2].update(response_gap_ids=["G2"]),
            lambda c: c["response_conditioning"]["component_bindings"][2].update(response_gap_ids=[]),
            lambda c: c["response_conditioning"]["component_bindings"][2].update(response_gap_ids=[], response_feature_ids=["F1"]),
            lambda c: c["response_conditioning"]["component_bindings"][0].update(response_feature_ids=["F1", "F1"]),
            lambda c: c["response_conditioning"]["component_bindings"][0].update(component_id="unknown"),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                case = deepcopy(self.case)
                mutate(case)
                with self.assertRaises(model.InputBoundaryError):
                    model.resolve_profile(self.profile, case)

    def test_explicit_conditioning_cannot_silently_infer_an_assumption_or_skip_grounding(self):
        mutations = [
            lambda c: c.pop("response_grounding"),
            lambda c: c["response_conditioning"].update(constructed=False),
            lambda c: c["response_conditioning"].update(assumption=" "),
            lambda c: c["initial_conceptual_state"].update(constructed=False),
            lambda c: c["response_conditioning"]["component_bindings"][0].update(initial_limitation=" "),
            lambda c: c["response_conditioning"]["component_bindings"][0].update(learning_requirement=" "),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                case = deepcopy(self.case)
                mutate(case)
                with self.assertRaises(model.InputBoundaryError):
                    model.resolve_profile(self.profile, case)

    def test_unknown_conditioning_fields_cannot_carry_an_answer_key(self):
        for target in ("root", "component"):
            case = deepcopy(self.case)
            value = case["response_conditioning"] if target == "root" else case["response_conditioning"]["component_bindings"][0]
            value["correct_answer"] = "NOT_LEARNER_INPUT"
            with self.subTest(target=target), self.assertRaises(model.InputBoundaryError):
                model.resolve_profile(self.profile, case)

    def test_prior_is_rebuilt_in_real_input_and_raw_profile_overrides_do_not_enter(self):
        with tempfile.TemporaryDirectory() as folder:
            request_path = Path(folder) / "request.json"
            image = Path(folder) / "visible.png"
            image.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j2ioAAAAASUVORK5CYII="))
            profile = deepcopy(self.profile)
            profile["prior_knowledge"] = {"correct_answer": "BYPASS_SENTINEL"}
            case = deepcopy(self.case)
            case["prior_knowledge"] = {"correct_answer": "BYPASS_SENTINEL"}
            request = {"profile": profile, "case_config": case,
                       "observation": {"screenshot_path": str(image), "messages": []},
                       "history": [], "memory": None}
            visible, _, _ = model.prepare_input(request, request_path)
            self.assertEqual(visible["profile"]["prior_knowledge"], model.resolve_prior_knowledge(self.case))
            self.assertNotIn("BYPASS_SENTINEL", json.dumps(visible))
            self.assertNotIn("response_conditioning", visible["case_config"])
            self.assertIn("initial_response_context", visible["case_config"])

    def test_legacy_cases_do_not_acquire_an_inability_assumption_from_omissions(self):
        self.case.pop("response_conditioning")
        self.assertIsNone(model.resolve_prior_knowledge(self.case))
        self.assertNotIn("prior_knowledge", model.resolve_profile(self.profile, self.case))


if __name__ == "__main__":
    unittest.main()
