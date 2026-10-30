"""Offline input-projection contracts; no browser or model API requests.

These check that reducing repeated input does not remove learner conditions,
executed results, evidence references, or unique learner-visible information.
They do not establish that the model behaves identically after compaction.
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
spec = importlib.util.spec_from_file_location("student_input_compaction_contracts", HERE / "student_model.py")
model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = model
spec.loader.exec_module(model)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def apply_memory_delta(previous, operations):
    """Apply the supported RFC 6902 operations independently of the encoder."""
    result = deepcopy(previous)
    for operation in operations:
        op, path = operation["op"], operation["path"]
        if op not in {"add", "remove", "replace"}:
            raise AssertionError("Unexpected memory patch operation: " + op)
        if path == "":
            if op == "remove":
                raise AssertionError("A memory snapshot cannot be removed at its root.")
            result = deepcopy(operation["value"])
            continue
        if not path.startswith("/"):
            raise AssertionError("Memory patch paths must be JSON pointers.")
        parts = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]
        parent = result
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        key = parts[-1]
        if isinstance(parent, list):
            index = len(parent) if key == "-" else int(key)
            if op == "add":
                parent.insert(index, deepcopy(operation["value"]))
            elif op == "remove":
                parent.pop(index)
            else:
                parent[index] = deepcopy(operation["value"])
        elif op == "remove":
            del parent[key]
        else:
            if op == "replace" and key not in parent:
                raise AssertionError("replace must target an existing member.")
            parent[key] = deepcopy(operation["value"])
    return result


def memory(statuses):
    return {
        "current_understanding": "I can identify labels but am still considering their meaning.",
        "unresolved_question": "How does the drawing represent the operation?",
        "next_intention": "Inspect a relevant part before choosing a change.",
        "component_states": [
            {"component_id": component_id, "status": status,
             "statement": "Constructed state for " + component_id,
             "evidence": [{"source": "visible_message", "reference": "message:7",
                           "support": "The displayed question concerns this relationship."}]}
            for component_id, status in statuses.items()
        ],
    }


def visible_fixture():
    states = [
        {"K1": "known", "K2": "known", "K3": "unlearned"},
        {"K1": "known", "K2": "known", "K3": "tentative"},
        {"K1": "tentative", "K2": "known", "K3": "tentative"},
    ]
    return {
        "profile": {"id": "P1", "constructed_profile": True,
                    "dimensions": {"task_motivation": {"level": "average",
                        "definition": "Willingness to invest effort.",
                        "operational_behavior": "Responds but may need encouragement."}}},
        "case_config": {
            "task_text": "Inspect the diagram.",
            "initial_explanation": "I drew the labelled line.",
            "initial_conceptual_state": {"constructed": True, "knowledge_components": [
                {"component_id": "K1", "status": "known", "statement": "Recognizes labels."},
                {"component_id": "K2", "status": "tentative", "statement": "Uncertain relationship."},
                {"component_id": "K3", "status": "unlearned", "statement": "No operation model yet."},
            ]},
            "initial_response_context": {
                "response_omissions": [{"gap_id": "operation", "missing_part": "Operation marks absent."}],
                "learner_starting_position": [{"gap_id": "operation", "initial_awareness": "unaware"}],
            },
        },
        "observation": {
            "visible_text": "\nInspect   the diagram.\nExplore the relationship.\nWhich part?Show\n"
                            "Begin a revision\nWritten zero\nShare your thinking.\n"
                            "Connection options\nMeaning\nCurrent mark\nCurve\n"
                            "Connection saved; one mark remains unsubmitted.\n",
            "task": "Inspect the diagram.", "goal": "Explore the relationship.",
            "messages": [{"index": 7, "role": "assistant", "text": "Which part?",
                          "error": False, "show_available": True},
                         {"index": 12, "role": "user", "text": "Maybe this one.",
                          "error": False, "show_available": False}],
            "controls": [{"id": "begin", "label": "Begin a revision", "disabled": False,
                          "pressed": "", "optional": None}],
            "elements": [{"id": "label_zero", "kind": "object", "label": "Written zero",
                          "texts": ["0"], "selected": False, "highlighted": False,
                          "bounds": {"x": 12.3456789, "y": 0.0, "width": 21.2345678, "height": 3.456789},
                          "canvas_bounds": {"x": 0.0, "y": 10.1234567, "width": 20.9876543, "height": 0.0},
                          "points": [{"x": 0.0, "y": 10.1234567}], "arrow_start": False}],
            "handles": [{"id": "edge", "endpoint": "source", "control": 0,
                         "screen_center": {"x": 10.9876543, "y": 0.0},
                         "canvas_center": {"x": 0.0, "y": 99.1234567}}],
            "dialogs": [{"id": "connectionDialog", "title": "Connection options",
                         "text": "Connection options\nMeaning\nCurrent mark\nCurve",
                         "fields": [{"id": "connectionLabel", "label": "Meaning", "value": "Current mark"},
                                    {"id": "connectionShape", "label": "", "value": "curved",
                                     "options": [{"value": "curved", "label": "Curve"}]}]}],
            "canvas": {"editable": False, "coordinate_system": "sceneRoot SVG coordinates",
                       "screen_bounds": {"x": 0.0, "y": 55.123456789, "width": 999.87654321, "height": 400.0},
                       "screen_transform": {"a": 0.9043283319796906, "b": 0.0, "c": 0.0,
                                            "d": 0.16442333798741365, "e": 45.733129932152465,
                                            "f": 610.0582323136169}},
            "status": {"chat": "Share your thinking.", "draft": ""}, "stopped": False,
        },
        "history": [
            {"step": 2, "action": {"type": "send_message", "text": "Maybe this one.", "id": None},
             "result": {"ok": True, "result": {}}, "utterance": "Maybe this one.", "memory_update": memory(states[0])},
            {"step": 5, "action": {"type": "reshape_connection", "id": "edge", "control": 0,
                                    "to": {"x": 1.23456789, "y": 2.0}, "endpoint": None},
             "result": {"ok": False, "error": "The canvas is view only.", "result": {}},
             "utterance": "", "memory_update": memory(states[1])},
            {"step": 8, "action": {"type": "select", "id": "label_zero", "text": None},
             "result": {"ok": True, "result": {"id": "label_zero"}},
             "utterance": "A nonduplicate recorded comment.", "memory_update": memory(states[2])},
        ],
        "memory": memory(states[-1]),
    }


class InputProjectionContracts(unittest.TestCase):
    def setUp(self):
        self.visible = visible_fixture()

    def test_projection_is_fresh_and_preserves_conditions_and_latest_memory_exactly(self):
        original = deepcopy(self.visible)
        projected = model.compact_input(self.visible)
        self.assertEqual(self.visible, original)
        self.assertIsNot(projected, self.visible)
        self.assertEqual(list(projected), ["profile", "case_config", "history", "memory", "observation"])
        for field in ("profile", "case_config", "memory"):
            self.assertEqual(projected[field], original[field], field)
        projected["profile"]["dimensions"]["task_motivation"]["level"] = "low"
        projected["memory"]["component_states"][0]["evidence"][0]["reference"] = "message:99"
        projected["observation"]["messages"][0]["text"] = "Changed only in projected input"
        self.assertEqual(self.visible, original, "Nested projection values alias the original request.")

    def test_history_keeps_steps_results_failures_and_relevant_action_values(self):
        projected = model.compact_input(self.visible)
        self.assertEqual([event["step"] for event in projected["history"]], [2, 5, 8])
        for before, after in zip(self.visible["history"], projected["history"]):
            self.assertEqual(after["result"], before["result"])
            self.assertEqual(after["action"], {key: value for key, value in before["action"].items()
                                               if value is not None})
            self.assertNotIn("memory_update", after)
        self.assertFalse(projected["history"][1]["result"]["ok"])
        self.assertEqual(projected["history"][1]["action"]["control"], 0)
        self.assertNotIn("utterance", projected["history"][0])
        self.assertNotIn("utterance", projected["history"][1])
        self.assertEqual(projected["history"][2]["utterance"], "A nonduplicate recorded comment.")

    def test_memory_deltas_reconstruct_every_original_snapshot_including_status_regression(self):
        projected = model.compact_input(self.visible)
        reconstructed = {}
        for before, after in zip(self.visible["history"], projected["history"]):
            self.assertNotIn("component_changes", after)
            self.assertIn("memory_delta", after)
            reconstructed = apply_memory_delta(reconstructed, after["memory_delta"])
            self.assertEqual(reconstructed, before["memory_update"])
        self.assertEqual(projected["memory"]["component_states"], self.visible["memory"]["component_states"])

    def test_unchanged_status_does_not_erase_changed_beliefs_or_evidence(self):
        second = self.visible["history"][1]["memory_update"]
        second["current_understanding"] = "I can describe positions, but the operation remains unclear."
        second["unresolved_question"] = "Which relationship does the arrow express?"
        second["next_intention"] = "Check the direction before editing."
        component = second["component_states"][1]
        self.assertEqual(component["status"], self.visible["history"][0]["memory_update"]["component_states"][1]["status"])
        component["statement"] = "A position label alone does not show the operation."
        component["evidence"].append({"source": "completed_action", "reference": "action:2",
                                      "support": "I inspected a part, but have not revised it."})
        # The next snapshot retracts an explanation and removes an old citation.
        third = self.visible["history"][2]["memory_update"]
        third["component_states"][1]["statement"] = "I am uncertain what this relationship means."
        third["component_states"][1]["evidence"] = []
        self.visible["memory"] = deepcopy(third)
        projected = model.compact_input(self.visible)
        reconstructed = {}
        for before, after in zip(self.visible["history"], projected["history"]):
            reconstructed = apply_memory_delta(reconstructed, after["memory_delta"])
            self.assertEqual(reconstructed, before["memory_update"])
        self.assertEqual(projected["memory"], third)

    def test_memory_delta_handles_arrays_pointer_escaping_and_falsey_values_losslessly(self):
        previous = {"a/b": {"~key": [{"statement": "Earlier", "evidence": ["message:7"]},
                                      None, False, 0, "remove this"]},
                    "obsolete": "removed member"}
        current = {"a/b": {"~key": [{"statement": "Revised", "evidence": []}, None, False, 0]},
                   "new/key~": {"value": None, "flag": False, "count": 0}}
        original_previous, original_current = deepcopy(previous), deepcopy(current)
        delta = model._memory_delta(previous, current)
        self.assertEqual(apply_memory_delta(previous, delta), current)
        self.assertEqual(previous, original_previous)
        self.assertEqual(current, original_current)
        encoded_paths = [operation["path"] for operation in delta]
        self.assertTrue(any("~1" in path for path in encoded_paths))
        self.assertTrue(any("~0" in path for path in encoded_paths))
        self.assertTrue(any(operation["op"] == "remove" for operation in delta))
        self.assertTrue(any(operation["op"] == "add" for operation in delta))
        grown = deepcopy(current)
        grown["a/b"]["~key"].extend([{"evidence": ["message:12", "action:8"]}, 0, False, None])
        self.assertEqual(apply_memory_delta(current, model._memory_delta(current, grown)), grown)
        self.assertEqual(model._memory_delta(grown, grown), [])

    def test_memory_delta_distinguishes_false_zero_and_number_type_changes(self):
        for before, after in ((False, 0), (0, False), (1, 1.0), (None, "")):
            with self.subTest(before=repr(before), after=repr(after)):
                previous, current = {"value": before}, {"value": after}
                delta = model._memory_delta(previous, current)
                reconstructed = apply_memory_delta(previous, delta)
                self.assertTrue(delta)
                self.assertIs(type(reconstructed["value"]), type(after))
                self.assertEqual(json.dumps(reconstructed), json.dumps(current))

    def test_memory_delta_never_costs_more_json_than_one_root_replacement(self):
        projected = model.compact_input(self.visible)
        for original, event in zip(self.visible["history"], projected["history"]):
            replacement = [{"op": "replace", "path": "", "value": original["memory_update"]}]
            self.assertLessEqual(len(model.serialize_input(event["memory_delta"])),
                                 len(model.serialize_input(replacement)))
        dense = deepcopy(self.visible)
        before = {"current_understanding": "a", "unresolved_question": "b", "next_intention": "c",
                  "component_states": []}
        after = {"current_understanding": "d", "unresolved_question": "e", "next_intention": "f",
                 "component_states": [{"component_id": "K1", "status": "tentative",
                                       "statement": "Unsure.", "evidence": []}]}
        dense["history"][0]["memory_update"] = before
        dense["history"][1]["memory_update"] = after
        dense["history"] = dense["history"][:2]
        dense["memory"] = deepcopy(after)
        events = model.compact_input(dense)["history"]
        expected = [{"op": "replace", "path": "", "value": after}]
        self.assertEqual(events[1]["memory_delta"], expected)
        self.assertEqual(apply_memory_delta(before, events[1]["memory_delta"]), after)

    def test_messages_evidence_and_unique_notices_survive_without_reindexing(self):
        projected = model.compact_input(self.visible)
        self.assertEqual(projected["observation"]["messages"], self.visible["observation"]["messages"])
        self.assertEqual([item["index"] for item in projected["observation"]["messages"]], [7, 12])
        residual = projected["observation"]["visible_text"]
        self.assertIn("Connection saved; one mark remains unsubmitted.", residual)
        for duplicate in ("Inspect", "Which part?", "Begin a revision", "Written zero", "Share your thinking.",
                          "Connection options", "Meaning", "Current mark", "Curve"):
            self.assertNotIn(duplicate, residual)
        evidence = projected["memory"]["component_states"][0]["evidence"]
        self.assertEqual(evidence, self.visible["memory"]["component_states"][0]["evidence"])

    def test_task_deduplication_requires_normalized_equality_and_keeps_changed_task(self):
        self.visible["observation"]["task"] = "  Inspect   the diagram. \n"
        projected = model.compact_input(self.visible)
        self.assertNotIn("task", projected["observation"])
        self.visible["observation"]["task"] = "Inspect the diagram and explain the change."
        projected = model.compact_input(self.visible)
        self.assertEqual(projected["observation"]["task"], self.visible["observation"]["task"])

    def test_geometry_rounding_keeps_ids_zero_and_false_and_transform_precision(self):
        projected = model.compact_input(self.visible)["observation"]
        original = self.visible["observation"]
        element = projected["elements"][0]
        self.assertEqual(element["id"], "label_zero")
        self.assertEqual(element["bounds"]["x"], round(original["elements"][0]["bounds"]["x"], 2))
        self.assertLessEqual(abs(element["bounds"]["x"] - original["elements"][0]["bounds"]["x"]), 0.005)
        self.assertEqual(element["points"][0]["y"], round(original["elements"][0]["points"][0]["y"], 2))
        self.assertEqual(projected["handles"][0]["canvas_center"]["y"], 99.12)
        self.assertEqual(projected["handles"][0]["control"], 0)
        self.assertFalse(element["selected"])
        self.assertFalse(element["arrow_start"])
        self.assertFalse(projected["controls"][0]["disabled"])
        self.assertEqual(projected["controls"][0]["pressed"], "")
        self.assertEqual(projected["status"]["draft"], "")
        self.assertFalse(projected["canvas"]["editable"])
        for key, value in original["canvas"]["screen_transform"].items():
            self.assertEqual(projected["canvas"]["screen_transform"][key], round(value, 6))
        self.assertNotEqual(projected["canvas"]["screen_transform"]["a"],
                            round(original["canvas"]["screen_transform"]["a"], 2))

    def test_compact_serialization_preserves_data_without_extra_json_whitespace(self):
        projected = model.compact_input(self.visible)
        serialized = model.serialize_input(projected)
        self.assertEqual(serialized, json.dumps(projected, ensure_ascii=False, separators=(",", ":")))
        self.assertEqual(json.loads(serialized), projected)

    def test_only_geometry_numbers_are_rounded(self):
        # Future numerical form values must not silently become edited answers.
        value = 1.23456789123
        self.visible["observation"]["dialogs"][0]["fields"][0]["value"] = value
        projected = model.compact_input(self.visible)
        self.assertEqual(projected["observation"]["dialogs"][0]["fields"][0]["value"], value)
        self.assertEqual(projected["history"][1]["action"]["to"]["x"], 1.23456789)

    def test_reprojection_keeps_memory_deltas_and_unique_notices(self):
        projected = model.compact_input(self.visible)
        self.assertEqual(model.compact_input(projected), projected)


class PreparedInputProjectionContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.request_path = self.folder / "request.json"
        self.png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j2ioAAAAASUVORK5CYII=")
        (self.folder / "visible.png").write_bytes(self.png)
        self.request = {
            "profile": load(HERE / "profiles/p1_average.json"),
            "case_config": load(HERE / "cases/math_2_numberline.json"),
            "observation": {"screenshot_path": "visible.png", "visible_text": "A unique visible notice.",
                            "messages": [], "controls": [], "elements": [], "canvas": None},
            "history": [], "memory": None,
        }

    def test_prepare_input_preserves_original_request_and_exact_screenshot_bytes(self):
        original = deepcopy(self.request)
        visible, provenance, image_url = model.prepare_input(self.request, self.request_path)
        self.assertEqual(self.request, original)
        self.assertEqual(base64.b64decode(image_url.split(",", 1)[1], validate=True), self.png)
        self.assertEqual(provenance["bytes"], len(self.png))
        self.assertNotIn("screenshot_path", visible["observation"])
        self.assertEqual(visible["case_config"]["initial_conceptual_state"],
                         self.request["case_config"]["initial_conceptual_state"])
        self.assertEqual(visible["case_config"]["initial_response_context"],
                         model.resolve_response_grounding(self.request["case_config"]))

    def test_private_fields_in_discarded_memory_are_rejected_before_compaction(self):
        self.request["history"] = [{"step": 1, "action": {"type": "select", "id": "label_zero"},
                                    "result": {"ok": True},
                                    "memory_update": {"private_assessment": "MUST_NOT_BE_SILENTLY_DISCARDED"}}]
        with self.assertRaises(model.InputBoundaryError):
            model.prepare_input(self.request, self.request_path)

    def test_projected_input_is_checked_again_after_compaction(self):
        original_compact = model.compact_input

        def compromised_projection(visible):
            projected = original_compact(visible)
            projected["history"].append({"private_assessment": "MUST_NOT_ENTER_MODEL_INPUT"})
            return projected

        with patch.object(model, "compact_input", side_effect=compromised_projection):
            with self.assertRaises(model.InputBoundaryError):
                model.prepare_input(self.request, self.request_path)

    def test_dry_run_records_projection_without_calling_client_or_rewriting_request(self):
        self.request_path.write_text(json.dumps(self.request, ensure_ascii=False), encoding="utf-8")
        original_bytes = self.request_path.read_bytes()
        response_path = self.folder / "response.json"
        with patch.object(model, "existing_client", side_effect=AssertionError("No API in offline projection test")) as client:
            exit_code = model.main(["--request", str(self.request_path), "--response", str(response_path), "--dry-run"])
        client.assert_not_called()
        self.assertEqual(exit_code, 0)
        self.assertEqual(self.request_path.read_bytes(), original_bytes)
        result = load(response_path)
        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(result["api"]["called"])
        self.assertIsNone(result["decision"])
        self.assertTrue(result["input_projection"]["version"])
        self.assertEqual(result["model_visible_input"]["case_config"]["initial_explanation"],
                         self.request["case_config"]["initial_explanation"])


if __name__ == "__main__":
    unittest.main()
