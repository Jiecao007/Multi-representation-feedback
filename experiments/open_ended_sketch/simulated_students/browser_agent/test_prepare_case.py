"""Offline preparation contracts: modalities, one call, provenance, and failures."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("multimodal_preparer_contracts", HERE / "prepare_case.py")
preparer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = preparer
spec.loader.exec_module(preparer)
from prior_analysis_types import PriorAnalysis


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def analysis_for(request):
    """A typed stub about a circuit; no copied number-line diagnosis or solution."""
    response = request["student_response"]
    evidence = []
    ids = []
    if response["text"].strip():
        evidence.append({"id": "E_TEXT", "source": "student_text", "quote": response["text"],
                         "figure_index": None, "region": None,
                         "observation": "The learner describes the path in their own words."})
        ids.append("E_TEXT")
    if response["figure_paths"]:
        evidence.append({"id": "E_FIGURE", "source": "student_figure", "quote": None,
                         "figure_index": 0, "region": None,
                         "observation": "The response contains a drawn path."})
        ids.append("E_FIGURE")
    observations = [
        {"id": "O_PRESENT", "kind": "demonstrated", "description": "The response names or depicts a path.", "evidence_ids": ids},
        {"id": "O_GAP", "kind": "missing", "description": "The response does not explain the lighting behavior.", "evidence_ids": ids},
    ]
    components = [
        {"component_id": "PATH_RECOGNITION", "label": "Recognizing the represented path", "state": "demonstrated", "inferred_status": "known",
         "statement": "Can describe or depict a local path.", "initial_limitation": "Only this path is demonstrated.",
         "learning_requirement": "Further circuit relationships need their own support.",
         "evidence_ids": ids, "observation_ids": ["O_PRESENT"], "observed_awareness": None},
        {"component_id": "LIGHTING_EXPLANATION", "label": "Explaining the lighting behavior", "state": "not_demonstrated", "inferred_status": "tentative",
         "statement": "Has not yet established an explanation for the lighting behavior.",
         "initial_limitation": "The response leaves understanding of the lighting behavior unresolved.",
         "learning_requirement": "A focused question or actual attempt could clarify this unresolved understanding.",
         "evidence_ids": ids, "observation_ids": ["O_GAP"], "observed_awareness": None},
    ]
    cross = ([{"id": "X_LOCAL", "relation": "consistent", "description": "The text and figure refer to the same local path.",
               "evidence_ids": ["E_TEXT", "E_FIGURE"]}] if len(ids) == 2 else [])
    return PriorAnalysis.model_validate({"task_summary": "Explain the lighting behavior in the given circuit.",
        "evidence": evidence, "observations": observations, "knowledge_components": components,
        "cross_representation": cross, "overall_uncertainty": "The explanation of the lighting behavior is not established."})


def api_response(analysis, *, status="completed", parsed=True):
    usage_data = {"input_tokens": 30, "output_tokens": 20, "total_tokens": 50,
                  "input_tokens_details": {"cached_tokens": 0}}
    usage = SimpleNamespace(input_tokens=30, output_tokens=20, total_tokens=50,
                            model_dump=lambda **_kwargs: usage_data)
    return SimpleNamespace(status=status, output_parsed=analysis if parsed else None,
        id="resp_offline_contract", model="gpt-6-astra", _request_id="offline-contract",
        usage=usage, output_text=analysis.model_dump_json() if parsed else "",
        incomplete_details=None, output=[],
        model_dump=lambda **_kwargs: {"id": "resp_offline_contract", "model": "gpt-6-astra",
            "status": status, "usage": usage_data, "output_parsed": analysis.model_dump() if parsed else None})


class PrepareCaseContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        for name, color in [("task.png", "red"), ("response.png", "blue"), ("response2.png", "green")]:
            Image.new("RGB", (3, 2), color).save(self.folder / name)
        self.request_path = self.folder / "request.json"
        self.request = {"case_id": "circuit_response", "source_id": "circuit_source",
            "task": {"text": "Explain whether the lamp lights.", "figure_paths": ["task.png"]},
            "student_response": {"text": "  I drew a closed path.\nI do not know whether it lights.  ",
                                 "figure_paths": ["response.png"]}}

    def write_request(self):
        self.request_path.write_text(json.dumps(self.request, ensure_ascii=False), encoding="utf-8")

    def run_main(self, response=None, *, extra=(), client_origin="https://api.openai.com/v1/"):
        self.write_request()
        client = SimpleNamespace(base_url=client_origin,
                                 responses=SimpleNamespace(parse=Mock(return_value=response or api_response(analysis_for(self.request)))))
        out = self.folder / "prepared"
        with patch.object(preparer, "existing_project_client", return_value=client) as factory:
            code = preparer.main(["--request", str(self.request_path), "--out", str(out), *extra])
        return code, out, client, factory

    def test_text_figure_and_combined_inputs_preserve_original_text_and_image_roles(self):
        for mode in ("text", "figure", "combined"):
            with self.subTest(mode=mode):
                request = deepcopy(self.request)
                if mode == "text":
                    request["student_response"]["figure_paths"] = []
                elif mode == "figure":
                    request["student_response"]["text"] = ""
                before = deepcopy(request)
                _validated, context, images = preparer.build_input(request, self.request_path)
                self.assertEqual(request, before)
                self.assertEqual(context["student_response"]["text"], request["student_response"]["text"])
                self.assertEqual(context["task"]["text"], request["task"]["text"])
                self.assertEqual([image["source"] for image in images],
                                 ["task_figure"] + ([] if mode == "text" else ["student_figure"]))
                for image in images:
                    source = Path(image["path"])
                    self.assertEqual(image["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
                    self.assertTrue(image["data_url"].startswith("data:image/png;base64,"))
                    self.assertEqual((image["width"], image["height"]), (3, 2))
                self.assertNotIn("data:image", json.dumps(context))

    def test_multiple_student_figures_are_distinct_from_the_task_scaffold(self):
        self.request["student_response"]["figure_paths"].append("response2.png")
        _validated, context, images = preparer.build_input(self.request, self.request_path)
        self.assertEqual([(image["source"], image["figure_index"]) for image in images],
                         [("task_figure", 0), ("student_figure", 0), ("student_figure", 1)])
        self.assertEqual(len(context["student_response"]["figures"]), 2)
        self.assertNotEqual(images[0]["sha256"], images[1]["sha256"])

    def test_figure_only_task_does_not_invent_original_task_text(self):
        self.request["task"]["text"] = ""
        _validated, context, images = preparer.build_input(self.request, self.request_path)
        self.assertEqual(context["task"]["text"], "")
        self.assertEqual(images[0]["source"], "task_figure")

    def test_missing_task_or_student_response_is_rejected_before_client_creation(self):
        for key in ("task", "student_response"):
            with self.subTest(key=key):
                self.request[key] = {"text": " ", "figure_paths": []}
                self.write_request()
                out = self.folder / ("invalid_" + key)
                with patch.object(preparer, "existing_project_client", side_effect=AssertionError("No API")) as factory:
                    code = preparer.main(["--request", str(self.request_path), "--out", str(out)])
                self.assertNotEqual(code, 0)
                factory.assert_not_called()
                self.assertFalse((out / "generated_case.json").exists())
                self.request = deepcopy(self.request)
                self.request[key] = {"text": "Supplied text.", "figure_paths": []}

    def test_missing_invalid_or_unsupported_image_never_reaches_the_client(self):
        (self.folder / "invalid.png").write_bytes(b"not an image")
        (self.folder / "notes.txt").write_text("not an image")
        for name in ("missing.png", "invalid.png", "notes.txt"):
            with self.subTest(name=name):
                self.request["student_response"]["figure_paths"] = [name]
                self.write_request()
                out = self.folder / ("bad_" + name.replace(".", "_"))
                with patch.object(preparer, "existing_project_client", side_effect=AssertionError("No API")) as factory:
                    code = preparer.main(["--request", str(self.request_path), "--out", str(out)])
                self.assertNotEqual(code, 0)
                factory.assert_not_called()
                self.assertFalse((out / "generated_case.json").exists())

    def test_unapproved_answer_key_field_cannot_enter_preparation(self):
        self.request["correct_answer"] = "PRIVATE_SENTINEL"
        self.write_request()
        with patch.object(preparer, "existing_project_client", side_effect=AssertionError("No API")) as factory:
            code = preparer.main(["--request", str(self.request_path), "--out", str(self.folder / "invalid")])
        self.assertNotEqual(code, 0)
        factory.assert_not_called()

    def test_legacy_omission_override_is_rejected_before_client_creation(self):
        self.request["omission_policy"] = "support_needed"
        self.write_request()
        out = self.folder / "old_policy"
        with patch.object(preparer, "existing_project_client", side_effect=AssertionError("No API")) as factory:
            code = preparer.main(["--request", str(self.request_path), "--out", str(out)])
        self.assertNotEqual(code, 0)
        factory.assert_not_called()
        self.assertFalse((out / "generated_case.json").exists())

    def test_dry_run_archives_input_without_creating_client_analysis_or_case(self):
        self.write_request()
        out = self.folder / "dry_run"
        original = self.request_path.read_bytes()
        with patch.object(preparer, "existing_project_client", side_effect=AssertionError("No API")) as factory:
            code = preparer.main(["--request", str(self.request_path), "--out", str(out), "--dry-run"])
        self.assertEqual(code, 0)
        factory.assert_not_called()
        self.assertEqual(self.request_path.read_bytes(), original)
        record = read(out / "preparation_record.json")
        self.assertEqual(record["status"], "dry_run")
        self.assertFalse(record["api"]["called"])
        self.assertFalse((out / "analysis.response.json").exists())
        self.assertFalse((out / "generated_case.json").exists())

    def test_one_multimodal_call_produces_exact_response_and_shared_seven_profile_prior(self):
        original = deepcopy(self.request)
        code, out, client, factory = self.run_main()
        self.assertEqual(code, 0)
        factory.assert_called_once()
        client.responses.parse.assert_called_once()
        kwargs = client.responses.parse.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-6-astra")
        self.assertFalse(kwargs["store"])
        blocks = kwargs["input"][0]["content"]
        self.assertEqual(sum(block["type"] == "input_image" for block in blocks), 2)
        self.assertIn(original["student_response"]["text"], json.loads(blocks[0]["text"])["student_response"]["text"])
        self.assertEqual([block["detail"] for block in blocks if block["type"] == "input_image"], ["original", "original"])
        case = read(out / "generated_case.json")
        self.assertEqual(case["initial_explanation"], original["student_response"]["text"])
        self.assertEqual(case["source_id"], original["source_id"])
        self.assertEqual(case["provenance"]["prior_policy"], "response_inferred")
        self.assertNotIn("simulation_policy", json.loads(blocks[0]["text"]))
        self.assertEqual(json.loads(blocks[0]["text"])["prior_policy"], "response_inferred")
        self.assertEqual(case["provenance"]["student_crop_sha256"], hashlib.sha256((self.folder / "response.png").read_bytes()).hexdigest())
        resolved = read(out / "resolved_profiles.json")
        self.assertEqual(set(resolved), {"P1", "P2", "P3", "P4", "P5", "P6", "P7"})
        prior = resolved["P1"]["prior_knowledge"]
        self.assertTrue(all(profile["prior_knowledge"] == prior for profile in resolved.values()))
        self.assertEqual(resolved["P4"]["dimensions"]["textual_representation"]["level"], "low")
        self.assertEqual(resolved["P5"]["dimensions"]["diagrammatic_representation"]["level"], "low")
        for name in ("analysis.response.json", "analysis.json", "analysis.prompt.md", "analysis.schema.json", "analysis.input.json"):
            self.assertTrue((out / name).is_file(), name)
        self.assertEqual(read(out / "preparation_record.json")["status"], "prepared")

    def test_figure_only_response_keeps_empty_explanation(self):
        self.request["student_response"]["text"] = ""
        code, out, client, _factory = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(read(out / "generated_case.json")["initial_explanation"], "")
        client.responses.parse.assert_called_once()

    def test_text_only_response_needs_no_image_and_keeps_its_original_text(self):
        self.request["task"]["figure_paths"] = []
        self.request["student_response"]["figure_paths"] = []
        code, out, client, _factory = self.run_main()
        self.assertEqual(code, 0)
        self.assertFalse(any(block["type"] == "input_image" for block in client.responses.parse.call_args.kwargs["input"][0]["content"]))
        self.assertEqual(read(out / "generated_case.json")["initial_explanation"], self.request["student_response"]["text"])

    def test_incomplete_or_unparsed_response_is_saved_once_without_a_compiled_case(self):
        for index, (status, parsed) in enumerate((("incomplete", False), ("completed", False))):
            with self.subTest(status=status):
                self.write_request()
                response = api_response(analysis_for(self.request), status=status, parsed=parsed)
                client = SimpleNamespace(base_url="https://api.openai.com/v1/", responses=SimpleNamespace(parse=Mock(return_value=response)))
                out = self.folder / ("incomplete_" + str(index))
                with patch.object(preparer, "existing_project_client", return_value=client):
                    code = preparer.main(["--request", str(self.request_path), "--out", str(out)])
                self.assertNotEqual(code, 0)
                client.responses.parse.assert_called_once()
                self.assertTrue((out / "analysis.response.json").exists())
                self.assertFalse((out / "generated_case.json").exists())

    def test_semantically_unbound_analysis_is_saved_but_not_retried_or_compiled(self):
        analysis = analysis_for(self.request).model_copy(deep=True)
        analysis.evidence[0].quote = "A fabricated student statement."
        code, out, client, _factory = self.run_main(api_response(analysis))
        self.assertNotEqual(code, 0)
        client.responses.parse.assert_called_once()
        self.assertEqual(read(out / "preparation_record.json")["status"], "invalid_analysis")
        self.assertTrue((out / "analysis.response.json").exists())
        self.assertFalse((out / "generated_case.json").exists())

    def test_unexpected_api_origin_is_rejected_before_a_model_request(self):
        code, out, client, _factory = self.run_main(client_origin="https://example.invalid/v1/")
        self.assertNotEqual(code, 0)
        client.responses.parse.assert_not_called()
        self.assertFalse((out / "generated_case.json").exists())

    def test_existing_output_is_not_overwritten_or_used_to_repeat_a_call(self):
        self.write_request()
        out = self.folder / "existing"
        out.mkdir()
        marker = out / "preserve.txt"
        marker.write_text("previous evidence")
        with patch.object(preparer, "existing_project_client", side_effect=AssertionError("No repeated call")) as factory:
            code = preparer.main(["--request", str(self.request_path), "--out", str(out)])
        self.assertNotEqual(code, 0)
        factory.assert_not_called()
        self.assertEqual(marker.read_text(), "previous evidence")

    def test_selected_profile_subset_is_expanded_from_the_same_case(self):
        path = HERE / "profiles/p6_low_coordination_translation.json"
        code, out, client, _factory = self.run_main(extra=("--profile", str(path)))
        self.assertEqual(code, 0)
        resolved = read(out / "resolved_profiles.json")
        self.assertEqual(set(resolved), {"P6"})
        self.assertEqual(resolved["P6"]["dimensions"]["coordination_translation"]["level"], "low")
        self.assertEqual(resolved["P6"]["dimensions"]["textual_representation"]["level"], "average")
        client.responses.parse.assert_called_once()

    def test_reuse_same_inputs_compiles_without_new_client_and_preserves_origin(self):
        code, source, _client, _factory = self.run_main()
        self.assertEqual(code, 0)
        original_record = read(source / "preparation_record.json")
        # A saved valid typed analysis can originate from a failed compilation;
        # recovery must preserve that original status rather than rewrite it.
        original_record["status"] = "invalid_analysis"
        (source / "preparation_record.json").write_text(json.dumps(original_record), encoding="utf-8")
        hashes = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in source.rglob("*") if p.is_file()}
        out = self.folder / "reused"
        with patch.object(preparer, "existing_project_client", side_effect=AssertionError("No API on reuse")) as factory:
            code = preparer.main(["--request", str(self.request_path), "--out", str(out),
                                  "--reuse-analysis", str(source)])
        self.assertEqual(code, 0)
        factory.assert_not_called()
        record = read(out / "preparation_record.json")
        self.assertEqual(record["status"], "prepared")
        self.assertFalse(record["api"]["called"])
        self.assertNotIn("usage", record["api"])
        self.assertFalse(record["reused_analysis"]["new_model_call"])
        self.assertEqual(record["reused_analysis"]["original_status"], "invalid_analysis")
        self.assertEqual(record["reused_analysis"]["original_response_id"], "resp_offline_contract")
        self.assertEqual(read(out / "generated_case.json")["provenance"]["analysis_response_id"], "resp_offline_contract")
        self.assertFalse((out / "analysis.response.json").exists())
        for name in ("analysis.prompt.md", "analysis.schema.json", "analysis.response.json", "preparation_record.json"):
            self.assertEqual((out / ("source_" + name)).read_bytes(), (source / name).read_bytes())
        self.assertEqual(hashes, {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in source.rglob("*") if p.is_file()})

    def test_reuse_refuses_legacy_policy_even_when_original_response_matches(self):
        code, source, _client, _factory = self.run_main()
        self.assertEqual(code, 0)
        saved = read(source / "analysis.input.json")
        saved.pop("prior_policy")
        saved["simulation_policy"] = {"omission_policy": "support_needed", "default_gap_awareness": "unaware"}
        (source / "analysis.input.json").write_text(json.dumps(saved))
        out = self.folder / "legacy_reuse"
        with patch.object(preparer, "existing_project_client", side_effect=AssertionError("No API")) as factory:
            code = preparer.main(["--request", str(self.request_path), "--out", str(out), "--reuse-analysis", str(source)])
        self.assertNotEqual(code, 0)
        factory.assert_not_called()
        record = read(out / "preparation_record.json")
        self.assertIn("earlier imposed prior policy", record["error"]["message"])
        self.assertFalse((out / "generated_case.json").exists())

    def test_reuse_refuses_changed_prompt_or_schema_contract(self):
        code, source, _client, _factory = self.run_main()
        self.assertEqual(code, 0)
        for filename, replacement in [("analysis.prompt.md", "Old imposed inability instructions."),
                                      ("analysis.schema.json", "{}")]:
            with self.subTest(filename=filename):
                path = source / filename
                original = path.read_bytes()
                path.write_text(replacement)
                out = self.folder / ("changed_" + filename.replace(".", "_"))
                with patch.object(preparer, "existing_project_client", side_effect=AssertionError("No API")) as factory:
                    code = preparer.main(["--request", str(self.request_path), "--out", str(out), "--reuse-analysis", str(source)])
                self.assertNotEqual(code, 0)
                factory.assert_not_called()
                self.assertIn("prompt/schema differs", read(out / "preparation_record.json")["error"]["message"])
                self.assertFalse((out / "generated_case.json").exists())
                path.write_bytes(original)

    def test_reuse_refuses_changed_original_task_or_student_text_before_client(self):
        code, source, _client, _factory = self.run_main()
        self.assertEqual(code, 0)
        original = deepcopy(self.request)
        for part in ("task", "student_response"):
            with self.subTest(part=part):
                self.request = deepcopy(original)
                self.request[part]["text"] += " New text not seen by the saved analysis."
                self.write_request()
                out = self.folder / ("reuse_changed_" + part)
                with patch.object(preparer, "existing_project_client", side_effect=AssertionError("No API on rejected reuse")) as factory:
                    code = preparer.main(["--request", str(self.request_path), "--out", str(out),
                                          "--reuse-analysis", str(source)])
                self.assertNotEqual(code, 0)
                factory.assert_not_called()
                self.assertEqual(read(out / "preparation_record.json")["status"], "invalid_analysis")
                self.assertFalse(read(out / "preparation_record.json")["api"]["called"])
                self.assertFalse((out / "generated_case.json").exists())

    def test_reuse_refuses_changed_image_bytes_even_at_the_same_path(self):
        code, source, _client, _factory = self.run_main()
        self.assertEqual(code, 0)
        Image.new("RGB", (3, 2), "yellow").save(self.folder / "response.png")
        out = self.folder / "reuse_changed_image"
        with patch.object(preparer, "existing_project_client", side_effect=AssertionError("No API on rejected reuse")) as factory:
            code = preparer.main(["--request", str(self.request_path), "--out", str(out),
                                  "--reuse-analysis", str(source)])
        self.assertNotEqual(code, 0)
        factory.assert_not_called()
        record = read(out / "preparation_record.json")
        self.assertEqual(record["status"], "invalid_analysis")
        self.assertFalse(record["api"]["called"])
        self.assertFalse((out / "generated_case.json").exists())


if __name__ == "__main__":
    unittest.main()
