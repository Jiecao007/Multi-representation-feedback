"""Offline multimodal provenance/compilation contracts, with non-number-line data."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

from prior_analysis_types import AnalysisBoundaryError, PriorAnalysis, compile_case, validate_analysis

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("multimodal_case_student_model", HERE / "student_model.py")
student_model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = student_model
spec.loader.exec_module(student_model)

TASK = "Explain how the lamp is connected to the battery and show a complete circuit."
RESPONSE = "The lamp is connected to the battery."


def circuit_analysis():
    return {
        "task_summary": TASK,
        "evidence": [
            {"id": "written_connection", "source": "student_text", "quote": RESPONSE,
             "figure_index": None, "region": None, "observation": "The student states that the lamp is connected to the battery."},
            {"id": "drawn_parts", "source": "student_figure", "quote": None,
             "figure_index": 0, "region": {"x": 0.1, "y": 0.2, "width": 0.7, "height": 0.5},
             "observation": "The response shows a battery and lamp with one wire; a return path is not visible."},
            {"id": "task_requirement", "source": "task_text", "quote": "show a complete circuit",
             "figure_index": None, "region": None, "observation": "The task requests a complete circuit."},
        ],
        "observations": [
            {"id": "parts_present", "kind": "demonstrated", "description": "The submitted forms identify the battery and lamp.",
             "evidence_ids": ["written_connection", "drawn_parts"]},
            {"id": "path_missing", "kind": "missing", "description": "The drawing does not show a complete return path.",
             "evidence_ids": ["drawn_parts", "task_requirement"]},
            {"id": "forms_unresolved", "kind": "conflicting", "description": "The written connection claim and visible incomplete path need clarification.",
             "evidence_ids": ["written_connection", "drawn_parts"]},
        ],
        "knowledge_components": [
            {"component_id": "recognizing_parts", "label": "Recognizing circuit parts", "state": "demonstrated", "inferred_status": "known",
             "statement": "Can identify the named battery and lamp in the submitted work.",
             "initial_limitation": "Only identification of the shown parts is established.",
             "learning_requirement": "New relationships require their own support.",
             "evidence_ids": ["written_connection", "drawn_parts"], "observation_ids": ["parts_present"],
             "observed_awareness": None},
            {"component_id": "continuity", "label": "Interpreting a complete circuit", "state": "not_demonstrated", "inferred_status": "tentative",
             "statement": "Has not established a complete path in the submitted drawing.",
             "initial_limitation": "The omitted path leaves the student's continuity understanding unresolved.",
             "learning_requirement": "A focused question or actual attempt could clarify this uncertainty.",
             "evidence_ids": ["drawn_parts", "task_requirement"], "observation_ids": ["path_missing"],
             "observed_awareness": None},
            {"component_id": "linking_forms", "label": "Relating the text and figure", "state": "uncertain", "inferred_status": "tentative",
             "statement": "Whether the text and visible path express the same relationship is unresolved.",
             "initial_limitation": "The shared meaning of the forms is not established.",
             "learning_requirement": "Needs a targeted comparison of the submitted forms.",
             "evidence_ids": ["written_connection", "drawn_parts"], "observation_ids": ["forms_unresolved"],
             "observed_awareness": None},
        ],
        "cross_representation": [
            {"id": "connection_consistency", "relation": "conflicting",
             "description": "The text names a connection while the drawing does not show a complete path.",
             "evidence_ids": ["written_connection", "drawn_parts"]},
        ],
        "overall_uncertainty": "A missing return line alone does not establish why it is missing.",
    }


def compile_fixture(analysis=None, **options):
    defaults = dict(case_id="circuit_example", source_id="student_circuit_a", task_text=TASK,
                    response_text=RESPONSE, response_figure_count=1)
    defaults.update(options)
    return compile_case(circuit_analysis() if analysis is None else analysis, **defaults)


class MultimodalAnalysisContracts(unittest.TestCase):
    def test_text_and_figure_compile_to_existing_profile_interface_without_math_ids(self):
        analysis = circuit_analysis()
        original = deepcopy(analysis)
        case = compile_fixture(analysis)
        self.assertEqual(analysis, original)
        self.assertEqual(case["initial_explanation"], RESPONSE)
        self.assertEqual(case["task_text"], TASK)
        self.assertEqual(case["initial_conceptual_state"]["misconception_type"], "uncertain")
        states = {c["component_id"]: c["status"] for c in case["initial_conceptual_state"]["knowledge_components"]}
        self.assertEqual(states, {"recognizing_parts": "known", "continuity": "tentative", "linking_forms": "tentative"})
        resolved = []
        for path in sorted((HERE / "profiles").glob("*.json")):
            profile = json.loads(path.read_text())
            resolved.append(student_model.resolve_profile(profile, case)["prior_knowledge"])
        self.assertEqual(len(resolved), 7)
        self.assertTrue(all(prior == resolved[0] for prior in resolved))
        self.assertEqual(resolved[0]["source_id"], "student_circuit_a")
        self.assertIn("cross_representation", case["provenance"])

    def test_missing_skill_keeps_uncertainty_without_extra_inability_or_awareness(self):
        analysis = circuit_analysis()
        before = deepcopy(analysis)
        case = compile_fixture(analysis)
        self.assertEqual(analysis, before)
        states = {c["component_id"]: c for c in case["initial_conceptual_state"]["knowledge_components"]}
        bindings = {c["component_id"]: c for c in case["response_conditioning"]["component_bindings"]}
        gaps = {g["gap_id"]: g for g in case["response_grounding"]["missing_parts"]}
        original = {c["component_id"]: c for c in analysis["knowledge_components"]}
        self.assertEqual(states["continuity"]["status"], "tentative")
        self.assertEqual(gaps["G_continuity"]["initial_awareness"], "unknown")
        self.assertNotIn("configured default", json.dumps(case))
        for cid, binding in bindings.items():
            self.assertEqual(binding["initial_limitation"], original[cid]["initial_limitation"])
            self.assertEqual(binding["learning_requirement"], original[cid]["learning_requirement"])
        self.assertNotIn("unavailable for independent use", json.dumps(case))
        self.assertEqual(case["provenance"]["prior_policy"], "response_inferred")
        self.assertNotIn("omission_policy", case["provenance"])

    def test_response_inference_is_required_instead_of_silently_recompiling_legacy_analysis(self):
        analysis = circuit_analysis()
        for c in analysis["knowledge_components"]:
            c.pop("inferred_status")
        self.assertTrue(PriorAnalysis.model_validate(analysis))
        with self.assertRaisesRegex(AnalysisBoundaryError, "Reanalyze the original"):
            compile_fixture(analysis)

    def test_omission_alone_cannot_be_promoted_to_knowledge_or_inability(self):
        for status in ("known", "unlearned"):
            with self.subTest(status=status):
                analysis = circuit_analysis()
                analysis["knowledge_components"][1]["inferred_status"] = status
                with self.assertRaises(AnalysisBoundaryError):
                    compile_fixture(analysis)

    def test_partial_or_conflicting_response_cannot_be_declared_known(self):
        analysis = circuit_analysis()
        analysis["knowledge_components"][2]["inferred_status"] = "known"
        with self.assertRaisesRegex(AnalysisBoundaryError, "demonstrated response evidence"):
            compile_fixture(analysis)

    def test_configured_omission_and_awareness_policies_are_rejected(self):
        for options in ({"omission_policy": "support_needed"}, {"omission_policy": "evidence_only"},
                        {"default_gap_awareness": "unaware"}):
            with self.subTest(options=options), self.assertRaisesRegex(AnalysisBoundaryError, "no longer used"):
                compile_fixture(**options)

    def test_contradicted_skill_preserves_the_inferred_belief_and_local_limits(self):
        analysis = circuit_analysis()
        component = analysis["knowledge_components"][2]
        component.update(state="contradicted", inferred_status="unlearned")
        case = compile_fixture(analysis)
        states = {c["component_id"]: c for c in case["initial_conceptual_state"]["knowledge_components"]}
        bindings = {c["component_id"]: c for c in case["response_conditioning"]["component_bindings"]}
        self.assertEqual(case["initial_explanation"], RESPONSE)
        self.assertEqual(states["linking_forms"]["status"], "unlearned")
        self.assertEqual(states["linking_forms"]["statement"], component["statement"])
        self.assertEqual(bindings["linking_forms"]["initial_limitation"], component["initial_limitation"])
        self.assertNotIn("operational_boundary_policy", case["provenance"])

    def test_figure_only_response_does_not_invent_a_written_explanation(self):
        analysis = circuit_analysis()
        analysis["evidence"] = [e for e in analysis["evidence"] if e["source"] != "student_text"]
        analysis["observations"] = [o for o in analysis["observations"] if o["id"] != "forms_unresolved"]
        analysis["observations"][0]["evidence_ids"] = ["drawn_parts"]
        analysis["knowledge_components"] = analysis["knowledge_components"][:2]
        analysis["knowledge_components"][0]["evidence_ids"] = ["drawn_parts"]
        analysis["cross_representation"] = []
        case = compile_fixture(analysis, response_text="")
        self.assertEqual(case["initial_explanation"], "")
        self.assertTrue(case["response_grounding"]["present_features"])
        self.assertEqual(case["provenance"]["cross_representation"], [])

    def test_text_only_response_and_explicit_awareness_are_preserved(self):
        text = "I can name the battery, but I do not know how to finish the drawing."
        analysis = {
            "task_summary": TASK,
            "evidence": [{"id": "uncertainty_text", "source": "student_text", "quote": text,
                          "figure_index": None, "region": None, "observation": "The student explicitly states uncertainty about finishing the drawing."}],
            "observations": [{"id": "uncertainty", "kind": "uncertain", "description": "Completion remains unclear to the student.", "evidence_ids": ["uncertainty_text"]}],
            "knowledge_components": [{"component_id": "completing_drawing", "label": "Completing the drawing", "state": "uncertain", "inferred_status": "unlearned",
                                      "statement": "Has not established how to finish the drawing.", "initial_limitation": "Cannot yet complete the missing part independently.",
                                      "learning_requirement": "Needs focused support with the unresolved part.", "evidence_ids": ["uncertainty_text"], "observation_ids": ["uncertainty"],
                                      "observed_awareness": "identifies_missing_part"}],
            "cross_representation": [], "overall_uncertainty": "The response does not specify the intended drawing change.",
        }
        case = compile_fixture(analysis, response_text=text, response_figure_count=0)
        self.assertEqual(case["initial_explanation"], text)
        self.assertEqual(case["response_grounding"]["missing_parts"][0]["initial_awareness"], "identifies_missing_part")
        self.assertEqual(case["response_grounding"]["missing_parts"][0]["learner_belief"], text)
        self.assertEqual(case["initial_conceptual_state"]["knowledge_components"][0]["status"], "unlearned")

    def test_figure_only_task_summary_does_not_become_original_text_quote_evidence(self):
        analysis = circuit_analysis()
        e = analysis["evidence"][2]
        e.update(source="task_figure", quote=None, figure_index=0, observation="The question figure requests a complete circuit.")
        case = compile_fixture(analysis, task_text="", task_figure_count=1)
        self.assertEqual(case["task_text"], TASK)
        self.assertIn("model summary", case["provenance"]["task_summary_basis"])
        forged = circuit_analysis()
        with self.assertRaises(AnalysisBoundaryError):
            compile_fixture(forged, task_text="", task_figure_count=1)

    def test_forged_quotes_bad_figure_indices_and_invalid_regions_are_rejected(self):
        mutations = [
            lambda a: a["evidence"][0].update(quote="A complete circuit is already drawn."),
            lambda a: a["evidence"][1].update(figure_index=1),
            lambda a: a["evidence"][1].update(figure_index=None),
            lambda a: a["evidence"][1].update(quote="invented OCR quote"),
            lambda a: a["evidence"][0].update(figure_index=0),
            lambda a: a["evidence"][1].update(region={"x": 0.8, "y": 0.1, "width": 0.4, "height": 0.2}),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                analysis = circuit_analysis()
                mutate(analysis)
                with self.assertRaises(AnalysisBoundaryError):
                    compile_fixture(analysis)

    def test_task_givens_alone_cannot_become_a_student_observation_or_knowledge(self):
        for target in ("observation", "knowledge"):
            analysis = circuit_analysis()
            if target == "observation":
                analysis["observations"][0]["evidence_ids"] = ["task_requirement"]
            else:
                analysis["knowledge_components"][0]["evidence_ids"] = ["task_requirement"]
            with self.subTest(target=target), self.assertRaises(AnalysisBoundaryError):
                compile_fixture(analysis)

    def test_task_context_can_qualify_a_claim_but_unlinked_student_evidence_cannot(self):
        analysis = circuit_analysis()
        # The task citation qualifies what was requested; the observed learner
        # claim remains supported by parts_present's student text and figure.
        analysis["knowledge_components"][0]["evidence_ids"].append("task_requirement")
        self.assertTrue(compile_fixture(analysis))
        analysis = circuit_analysis()
        analysis["evidence"].append({"id": "another_student_quote", "source": "student_text",
                                     "quote": "connected to the battery", "figure_index": None,
                                     "region": None, "observation": "Another segment of the submitted sentence."})
        analysis["knowledge_components"][0]["evidence_ids"].append("another_student_quote")
        with self.assertRaises(AnalysisBoundaryError):
            compile_fixture(analysis)

    def test_awareness_and_cross_form_claims_need_the_actual_student_modalities(self):
        analysis = circuit_analysis()
        analysis["knowledge_components"][1]["observed_awareness"] = "identifies_missing_part"
        with self.assertRaises(AnalysisBoundaryError):
            compile_fixture(analysis)
        analysis = circuit_analysis()
        analysis["cross_representation"][0]["evidence_ids"] = ["drawn_parts", "task_requirement"]
        with self.assertRaises(AnalysisBoundaryError):
            compile_fixture(analysis)

    def test_cross_form_conflict_cannot_remain_only_in_private_provenance(self):
        for relation in ("conflicting", "uncertain"):
            for mutation in ("omit_component", "declare_demonstrated", "omit_observation"):
                analysis = circuit_analysis()
                analysis["cross_representation"][0]["relation"] = relation
                if mutation == "omit_component":
                    analysis["knowledge_components"] = analysis["knowledge_components"][:2]
                elif mutation == "declare_demonstrated":
                    analysis["knowledge_components"][2]["state"] = "demonstrated"
                    analysis["knowledge_components"][2]["observation_ids"] = ["parts_present"]
                else:
                    analysis["knowledge_components"][2]["evidence_ids"] = ["written_connection", "drawn_parts", "task_requirement"]
                    analysis["knowledge_components"][2]["observation_ids"] = ["parts_present", "path_missing"]
                with self.subTest(relation=relation, mutation=mutation), self.assertRaises(AnalysisBoundaryError):
                    compile_fixture(analysis)
        # A correspondence observation is not itself a coordination mastery
        # diagnosis. Consistent pairs can be archived without a new difficulty.
        analysis = circuit_analysis()
        analysis["cross_representation"][0]["relation"] = "consistent"
        analysis["knowledge_components"] = analysis["knowledge_components"][:2]
        self.assertTrue(compile_fixture(analysis)["provenance"]["cross_representation"])

    def test_duplicate_dangling_and_unlinked_references_are_rejected(self):
        mutations = [
            lambda a: a["evidence"].append(deepcopy(a["evidence"][0])),
            lambda a: a["observations"][0].update(evidence_ids=["unknown"]),
            lambda a: a["knowledge_components"][0].update(observation_ids=["unknown"]),
            lambda a: a["knowledge_components"][0].update(observation_ids=["path_missing"]),
            lambda a: a["knowledge_components"].append(deepcopy(a["knowledge_components"][0])),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                analysis = circuit_analysis()
                mutate(analysis)
                with self.assertRaises(AnalysisBoundaryError):
                    compile_fixture(analysis)

    def test_unknown_fields_policies_and_empty_sources_fail_closed(self):
        analysis = circuit_analysis()
        analysis["correct_answer"] = "Do not send a solution."
        with self.assertRaises(AnalysisBoundaryError):
            compile_fixture(analysis)
        for options in ({"omission_policy": "always_expert"}, {"default_gap_awareness": "guessed"},
                        {"source_id": " "}, {"task_text": "", "task_figure_count": 0},
                        {"response_text": "", "response_figure_count": 0}):
            with self.subTest(options=options), self.assertRaises(AnalysisBoundaryError):
                compile_fixture(**options)


if __name__ == "__main__":
    unittest.main()
