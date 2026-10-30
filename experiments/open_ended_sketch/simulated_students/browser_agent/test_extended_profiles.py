"""Offline contracts for P5-P7 contrasts; no model or browser calls."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("extended_profile_student_model", HERE / "student_model.py")
model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = model
spec.loader.exec_module(model)


def load(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


class ExtendedProfileContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = load("profiles/p1_average.json")
        cls.case = load("cases/math_2_numberline.json")
        cls.catalogue = load("profile_dimensions.json")
        cls.profiles = [
            ("P5", load("profiles/p5_low_diagrammatic_expression.json"), {"diagrammatic_representation"}),
            ("P6", load("profiles/p6_low_coordination_translation.json"), {"coordination_translation"}),
            ("P7", load("profiles/p7_combined_support_needs.json"), set(cls.baseline["dimensions"])),
        ]

    def test_only_selected_levels_and_profile_id_differ_from_baseline(self):
        for pid, profile, low_components in self.profiles:
            with self.subTest(profile=pid):
                selected = deepcopy(profile)
                baseline = deepcopy(self.baseline)
                self.assertEqual(selected.pop("id"), pid)
                self.assertEqual(baseline.pop("id"), "P1")
                self.assertEqual(set(selected), set(baseline))
                self.assertEqual(set(selected["dimensions"]), set(baseline["dimensions"]))
                for name, configuration in selected["dimensions"].items():
                    self.assertEqual(configuration, {
                        "level": "low" if name in low_components else "average",
                    })
                    configuration["level"] = "average"
                self.assertEqual(selected, baseline,
                                 "A shared instruction, case reference, or unselected trait changed.")

    def test_resolved_levels_do_not_change_shared_case_or_other_components(self):
        baseline = model.resolve_profile(self.baseline, self.case)
        initial_case = deepcopy(self.case)
        for pid, profile, low_components in self.profiles:
            with self.subTest(profile=pid):
                original_profile = deepcopy(profile)
                resolved = model.resolve_profile(profile, self.case)
                self.assertEqual(profile, original_profile)
                self.assertEqual(self.case, initial_case)
                self.assertEqual(resolved["case_dimensions"], baseline["case_dimensions"])
                self.assertEqual(resolved["constructs"], baseline["constructs"])
                self.assertEqual(resolved["shared_communication_style"], baseline["shared_communication_style"])
                self.assertNotIn("compatibility", resolved)
                for name, component in resolved["dimensions"].items():
                    if name not in low_components:
                        self.assertEqual(component, baseline["dimensions"][name])
                    else:
                        self.assertEqual(component["level"], "low")
                        self.assertEqual(component["operational_behavior"],
                                         self.catalogue["dimensions"][name]["levels"]["low"])

    def test_p6_preserves_both_expression_levels_under_the_same_three_component_construct(self):
        profile = next(profile for pid, profile, _ in self.profiles if pid == "P6")
        resolved = model.resolve_profile(profile, self.case)
        components = resolved["constructs"]["representation_ability"]["components"]
        self.assertEqual(set(components), {
            "textual_expression", "diagrammatic_expression", "coordination_and_translation",
        })
        self.assertEqual(resolved["dimensions"][components["textual_expression"]]["level"], "average")
        self.assertEqual(resolved["dimensions"][components["diagrammatic_expression"]]["level"], "average")
        self.assertEqual(resolved["dimensions"][components["coordination_and_translation"]]["level"], "low")


if __name__ == "__main__":
    unittest.main(verbosity=2)
