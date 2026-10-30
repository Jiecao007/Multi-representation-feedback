"""Offline contracts for shared-variable profile ownership and composition."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from profile_prompt import project_profile


HERE = Path(__file__).resolve().parent


class ProfileProjectionContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogue = json.loads((HERE / "profile_dimensions.json").read_text())
        cls.profiles = [json.loads(path.read_text()) for path in sorted((HERE / "profiles").glob("*.json"))]

    def expanded(self, raw):
        result = {"id": raw["id"], "constructed_profile": True, "dimensions": {}}
        for name, setting in raw["dimensions"].items():
            definition = self.catalogue["dimensions"][name]
            result["dimensions"][name] = {
                "level": setting["level"], "definition": definition["definition"],
                "operational_behavior": deepcopy(definition["levels"][setting["level"]])}
        result.update(prior_knowledge={"components": [{"component_id": "seed", "status": "tentative"}]},
                      case_dimensions={"misconception_type": "case-only"},
                      constructs=deepcopy(self.catalogue["constructs"]),
                      shared_communication_style=deepcopy(self.catalogue["shared_communication_style"]))
        return result

    def test_all_seven_profiles_split_assigned_variables(self):
        self.assertEqual({p["id"] for p in self.profiles}, {"P1", "P2", "P3", "P4", "P5", "P6", "P7"})
        for raw in self.profiles:
            with self.subTest(profile=raw["id"]):
                full = self.expanded(raw)
                knowledge = project_profile(full, "knowledge_model")
                learner = project_profile(full, "learner")
                self.assertEqual(set(knowledge["dimensions"]), {"feedback_processing"})
                self.assertEqual(set(learner["dimensions"]), {
                    "task_motivation", "textual_representation", "diagrammatic_representation", "coordination_translation"})
                self.assertEqual(set(knowledge["demand_contracts"]), set(knowledge["dimensions"]))
                self.assertEqual(set(learner["demand_contracts"]), set(learner["dimensions"]))
                self.assertEqual(knowledge["prior_knowledge"], full["prior_knowledge"])
                self.assertNotIn("prior_knowledge", learner)
                for projected in (knowledge, learner):
                    self.assertNotIn("case_dimensions", projected)
                    self.assertTrue(projected["composite_characteristics"])
                self.assertNotIn("constructs", knowledge)
                self.assertNotIn("shared_communication_style", knowledge)

    def test_selected_level_definitions_are_preserved(self):
        for raw in self.profiles:
            full = self.expanded(raw)
            for role in ("knowledge_model", "learner"):
                projected = project_profile(full, role)
                for name, value in projected["dimensions"].items():
                    self.assertEqual(value, full["dimensions"][name])

    def test_projection_is_independent_of_profile_identifier(self):
        full = self.expanded(self.profiles[0]); renamed = deepcopy(full)
        renamed["id"] = "an-unseen-combination"
        for role in ("knowledge_model", "learner"):
            left = project_profile(full, role); right = project_profile(renamed, role)
            left.pop("id"); right.pop("id")
            self.assertEqual(left, right)

    def test_actor_has_no_uptake_or_initial_knowledge_channel(self):
        full = self.expanded(next(p for p in self.profiles if p["id"] == "P7"))
        full["unrequested_override"] = "not an allowed field"
        learner = project_profile(full, "learner")
        serialized = json.dumps(learner)
        for forbidden in ("feedback_processing", "feedback uptake", "prior_knowledge", "case-only", "unrequested_override"):
            self.assertNotIn(forbidden, serialized)

    def test_knowledge_role_has_no_effort_or_expression_channel(self):
        full = self.expanded(next(p for p in self.profiles if p["id"] == "P7"))
        knowledge = project_profile(full, "knowledge_model")
        serialized = json.dumps(knowledge)
        for forbidden in ("task_motivation", "textual_representation", "diagrammatic_representation",
                          "coordination_translation", "representation_ability"):
            self.assertNotIn(forbidden, serialized)

    def test_low_uptake_does_not_change_actor_profile(self):
        p1 = self.expanded(next(p for p in self.profiles if p["id"] == "P1"))
        p3 = self.expanded(next(p for p in self.profiles if p["id"] == "P3"))
        left = project_profile(p1, "learner"); right = project_profile(p3, "learner")
        left.pop("id"); right.pop("id")
        self.assertEqual(left, right)
        self.assertNotEqual(project_profile(p1, "knowledge_model")["dimensions"],
                            project_profile(p3, "knowledge_model")["dimensions"])

    def test_projection_and_returned_values_do_not_alias_input(self):
        full = self.expanded(self.profiles[0]); original = deepcopy(full)
        learner = project_profile(full, "learner")
        knowledge = project_profile(full, "knowledge_model")
        learner["dimensions"]["task_motivation"]["operational_behavior"]["application_notes"].append("changed")
        learner["demand_contracts"]["task_motivation"]["without_support"] = "changed"
        knowledge["prior_knowledge"]["components"][0]["status"] = "known"
        self.assertEqual(full, original)
        self.assertNotEqual(self.catalogue["demand_contracts"]["task_motivation"]["levels"]["average"]["without_support"],
                            "changed")

    def test_every_owned_contract_has_a_demand_support_and_boundary(self):
        self.assertEqual(set(self.catalogue["demand_contracts"]), set(self.catalogue["dimensions"]))
        for raw in self.profiles:
            for role in ("knowledge_model", "learner"):
                projected = project_profile(self.expanded(raw), role)
                for name, contract in projected["demand_contracts"].items():
                    with self.subTest(profile=raw["id"], role=role, dimension=name):
                        self.assertEqual(set(contract), {
                            "demand", "support_to_check", "without_support", "with_support", "outside_demand"})
                        self.assertTrue(all(isinstance(value, str) and value.strip() for value in contract.values()))
                        selected = projected["dimensions"][name]["level"]
                        self.assertEqual(contract["without_support"],
                                         self.catalogue["demand_contracts"][name]["levels"][selected]["without_support"])

    def test_changing_one_level_changes_only_its_owned_contract(self):
        baseline = self.expanded(next(p for p in self.profiles if p["id"] == "P1"))
        for name in self.catalogue["dimensions"]:
            changed = deepcopy(baseline)
            changed["dimensions"][name] = {
                "level": "low", "definition": self.catalogue["dimensions"][name]["definition"],
                "operational_behavior": deepcopy(self.catalogue["dimensions"][name]["levels"]["low"])}
            for role in ("knowledge_model", "learner"):
                old = project_profile(baseline, role)["demand_contracts"]
                new = project_profile(changed, role)["demand_contracts"]
                for owned in old:
                    with self.subTest(changed=name, role=role, owned=owned):
                        if owned == name:
                            self.assertNotEqual(old[owned]["without_support"], new[owned]["without_support"])
                        else:
                            self.assertEqual(old[owned], new[owned])

    def test_low_contracts_separate_effort_expression_encoding_and_coordination(self):
        contracts = self.catalogue["demand_contracts"]
        self.assertEqual(len({value["demand"] for value in contracts.values()}), len(contracts))
        self.assertEqual(len({value["support_to_check"] for value in contracts.values()}), len(contracts))
        low = {name: value["levels"]["low"] for name, value in contracts.items()}
        # The catalogue commits to distinct observable support needs, rather
        # than allowing every level to be fluent whenever the model prefers it.
        self.assertIn("unrequested checking", low["task_motivation"]["without_support"])
        self.assertIn("explanatory link or reference left implicit", low["textual_representation"]["without_support"])
        self.assertIn("encoding choice unresolved", low["diagrammatic_representation"]["without_support"])
        self.assertIn("dependent revision unresolved", low["coordination_translation"]["without_support"])
        self.assertIn("implicit referent, bridge, or dependent part unresolved", low["feedback_processing"]["without_support"])
        for name, contract in low.items():
            with self.subTest(dimension=name):
                self.assertFalse(contract["without_support"].startswith("May "))
                self.assertNotEqual(contract["without_support"], contracts[name]["levels"]["average"]["without_support"])

    def test_support_can_remove_local_barrier_without_prescribed_errors_or_delays(self):
        contracts = self.catalogue["demand_contracts"]
        for name in ("feedback_processing", "diagrammatic_representation", "coordination_translation"):
            with self.subTest(dimension=name):
                self.assertIn("immediately", contracts[name]["levels"]["low"]["with_support"])
        text = contracts["textual_representation"]["levels"]["low"]
        self.assertIn("explicitly", text["with_support"])
        self.assertIn("Clear labels and simple identification", text["outside_demand"])
        motivation = contracts["task_motivation"]["levels"]["low"]["outside_demand"]
        self.assertIn("No required refusal", motivation)
        self.assertIn("completed successfully", motivation)

    def test_combined_characteristics_are_demand_sensitive(self):
        combined = self.expanded(next(p for p in self.profiles if p["id"] == "P7"))
        description = " ".join(project_profile(combined, "learner")["composite_characteristics"])
        self.assertIn("current demand", description)
        self.assertIn("no required error", description)
        self.assertNotIn("24", description)
        self.assertNotIn("must stop", description)

    def test_rejects_unknown_role_and_unexpanded_profile(self):
        full = self.expanded(self.profiles[0])
        with self.assertRaises(ValueError): project_profile(full, "tutor")
        with self.assertRaises(ValueError): project_profile(self.profiles[0], "learner")
        full["dimensions"]["feedback_processing"]["level"] = "expert"
        with self.assertRaises(ValueError): project_profile(full, "knowledge_model")


if __name__ == "__main__":
    unittest.main()
