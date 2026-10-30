"""Offline transport contracts for the simple two-Agent knowledge-state loop.

Scripted responses verify scheduling, state ownership and saved evidence. They
are not empirical evidence of a language model obeying a knowledge boundary.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import student_model as model

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQAAAABJRU5ErkJggg==")
KNOWN = "The student can identify the two labeled parts."
SUPPORTED = "A directed connection can show this local relation."
CASE = {"id": "two-agent-generic", "source_id": "two-agent-response",
        "task_text": "Show how two labeled parts relate.", "initial_explanation": "I labeled the parts.",
        # Old researcher hypotheses remain in the controller request for source
        # compatibility; current KM initialization must not inherit them.
        "initial_conceptual_state": {"constructed": True, "misconception_type": "uncertain",
            "initial_belief": "HISTORICAL_SEED_SHOULD_NOT_REACH_KM", "knowledge_components": [
                {"component_id": "parts", "status": "known", "statement": KNOWN},
                {"component_id": "relation", "status": "unlearned", "statement": "IMPOSED_UNKNOWN_SEED"}]}}


def initial_reply(_payload):
    return {"knowledge_state": {"known": [KNOWN]}}


def no_change(payload):
    return {"move_id": payload["move"]["move_id"],
            "knowledge_state": deepcopy(payload["previous_knowledge_state"])}


def support_reply(payload):
    state = deepcopy(payload["previous_knowledge_state"])
    state["possibly_known"].append(SUPPORTED)
    return {"move_id": payload["move"]["move_id"], "knowledge_state": state}


def learner_reply(_payload):
    action = {field.alias or name: None for name, field in model.Action.model_fields.items()}
    action.update(type="send_message", text="I can see the labels. How should I connect them?")
    return {"action": action, "utterance": action["text"],
            "episodic_memory": {"last_action": "Asked about the connection.", "pending_question": "How to connect the parts."}}


class ScriptedClient:
    def __init__(self, replies, callback=None):
        self.replies = list(replies)
        self.calls = []
        self.callback = callback
        self.responses = SimpleNamespace(parse=self.parse)

    def parse(self, **kwargs):
        if not self.replies:
            raise AssertionError("Unexpected additional model call.")
        payload = json.loads(kwargs["input"][0]["content"][0]["text"])
        self.calls.append({"payload": payload, "schema": kwargs["text_format"].__name__, "kwargs": kwargs})
        if self.callback:
            self.callback(payload, kwargs["text_format"])
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        value = reply(payload) if callable(reply) else reply
        parsed = kwargs["text_format"].model_validate(value)
        number = len(self.calls)
        return SimpleNamespace(status="completed", output_parsed=parsed,
            output_text=json.dumps(value), id="scripted-response-" + str(number),
            model=kwargs["model"], _request_id="scripted-request-" + str(number),
            usage=SimpleNamespace(model_dump=lambda: {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}))


class TwoAgentPipelineContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.case = deepcopy(CASE)
        figures = {}
        for filename in ("task.png", "student.png", "interface.png"):
            path = self.directory / filename
            path.write_bytes(PNG)
            figures[filename] = {"path": str(path), "sha256": hashlib.sha256(PNG).hexdigest()}
        self.case["provenance"] = {"task_figures": [figures["task.png"]], "student_figures": [figures["student.png"]]}
        profile = json.loads((HERE / "profiles/p1_average.json").read_text())
        self.request = {"profile": profile, "learner_instance_id": "one-instance", "case_config": self.case,
            "observation": {"screenshot_path": str(self.directory / "interface.png"),
                "visible_text": "Visible current Feedback interface.",
                "messages": [{"index": 0, "role": "assistant", "text": "How could you connect the parts?", "error": False}],
                "elements": [], "controls": [], "canvas": None},
            "history": [], "memory": None, "learner_knowledge_model": None}
        self.request_path = self.directory / "step_01_request.json"

    def run_pipeline(self, replies, *, request=None, step=1, callback=None, dry=False):
        request = deepcopy(request or self.request)
        request_path = self.directory / ("step_" + str(step).zfill(2) + "_request.json")
        request_path.write_text(json.dumps(request))
        visible, screenshot, image_url = model.prepare_input(request, request_path)
        client = ScriptedClient(replies, callback)
        output = {"decision": None, "api": {"called": False}, "error": None}
        model.run_two_agent_decision(request, visible, screenshot, image_url,
            self.directory / ("step_" + str(step).zfill(2) + "_response.json"),
            "gpt-6-sol", "low", output, client=client, dry_run=dry, request_path=request_path)
        return output, client

    def test_exact_initialize_move_actor_order_with_two_semantic_roles(self):
        result, client = self.run_pipeline([initial_reply, no_change, learner_reply])
        self.assertEqual([call["schema"] for call in client.calls],
                         ["KnowledgeInitialization", "KnowledgeMoveCheck", "LearnerAgentReply"])
        self.assertEqual([call["role"] for call in result["api_calls"]],
                         ["knowledge_model_initialize", "knowledge_model_move_0", "learner_agent"])
        self.assertEqual({call["agent"] for call in result["api_calls"]}, {"KnowledgeModelAgent", "LearnerAgent"})
        self.assertNotIn("gate", result["knowledge_audit"])
        self.assertEqual(result["status"], "ok")

    def test_initialize_sees_original_response_figures_not_current_teacher_screen_or_imposed_prior(self):
        _, client = self.run_pipeline([initial_reply, no_change, learner_reply])
        initial = client.calls[0]
        labels = [x["text"] for x in initial["kwargs"]["input"][0]["content"] if x["type"] == "input_text"][1:]
        self.assertEqual(len(labels), 2)
        self.assertTrue(any("task_figure" in x for x in labels))
        self.assertTrue(any("student_response_figure" in x for x in labels))
        self.assertFalse(any("current_learner_visible_interface" in x for x in labels))
        payload = initial["payload"]
        self.assertTrue(payload["initial_response"]["initialization_excludes_feedback"])
        self.assertNotIn("profile", payload)
        self.assertIn("I labeled the parts.", json.dumps(payload))
        for forbidden in ("How could you connect", "HISTORICAL_SEED_SHOULD_NOT_REACH_KM", "IMPOSED_UNKNOWN_SEED", "initial_components", "prior_knowledge"):
            self.assertNotIn(forbidden, json.dumps(payload))

    def test_state_is_saved_before_learner_reads_its_three_optional_buckets(self):
        observed = []
        def callback(payload, schema):
            if schema.__name__ == "LearnerAgentReply":
                stored = json.loads((self.directory / "knowledge_model_agent_memory.json").read_text())
                observed.append(stored)
                self.assertTrue(stored["initialized"])
                self.assertEqual(stored["processed_move_ids"], ["message:0"])
                self.assertEqual(stored["knowledge_state"], payload["knowledge_state"])
                self.assertEqual(set(payload["knowledge_state"]), {"known", "unknown", "possibly_known"})
        result, _ = self.run_pipeline([initial_reply, no_change, learner_reply], callback=callback)
        self.assertEqual(len(observed), 1)
        self.assertEqual(result["knowledge_audit"]["learner_read_state_sha256"], observed[0]["state_sha256"])
        self.assertEqual(observed[0]["knowledge_state"], {"known": [KNOWN], "unknown": [], "possibly_known": []})

    def test_profile_ownership_is_enforced_in_all_actual_agent_inputs(self):
        request = deepcopy(self.request)
        request["profile"] = json.loads((HERE / "profiles/p7_combined_support_needs.json").read_text())
        _, client = self.run_pipeline([initial_reply, no_change, learner_reply], request=request)
        self.assertNotIn("profile", client.calls[0]["payload"])
        for call in client.calls[1:2]:
            profile = call["payload"]["profile"]
            self.assertEqual(set(profile["dimensions"]), {"feedback_processing"})
            self.assertEqual(profile["dimensions"]["feedback_processing"]["level"], "low")
            self.assertNotIn("prior_knowledge", profile)
            self.assertNotIn("shared_communication_style", profile)
        actor = client.calls[-1]["payload"]
        self.assertEqual(set(actor["profile"]["dimensions"]), {
            "task_motivation", "textual_representation", "diagrammatic_representation", "coordination_translation"})
        self.assertNotIn("feedback_processing", json.dumps(actor["profile"]))
        self.assertNotIn("prior_knowledge", actor["profile"])
        self.assertNotIn("initial_conceptual_state", actor["case_config"])
        self.assertNotIn("initial_response_context", actor["case_config"])
        self.assertTrue(actor["profile"]["composite_characteristics"])

    def test_support_updates_knowledge_before_actor_call(self):
        request = deepcopy(self.request)
        request["observation"]["messages"][0]["text"] = SUPPORTED
        def callback(payload, schema):
            if schema.__name__ == "LearnerAgentReply":
                saved = json.loads((self.directory / "knowledge_model_agent_memory.json").read_text())
                self.assertEqual(saved["knowledge_state"]["possibly_known"], [SUPPORTED])
                self.assertEqual(saved["knowledge_state"], payload["knowledge_state"])
        result, client = self.run_pipeline([initial_reply, support_reply, learner_reply], request=request, callback=callback)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(client.calls), 3)

    def test_learner_reads_teacher_question_but_it_is_not_automatically_added_to_state(self):
        request = deepcopy(self.request)
        question = "TEACHER_QUESTION_CONTEXT"
        request["observation"]["messages"][0]["text"] = question
        result, client = self.run_pipeline([initial_reply, no_change, learner_reply], request=request)
        actor = client.calls[-1]
        self.assertIn(question, json.dumps(actor["payload"]["observation"]))
        self.assertNotIn(question, json.dumps(actor["payload"]["knowledge_state"]))
        self.assertEqual(result["learner_knowledge_model"]["knowledge_state"], {"known": [KNOWN], "unknown": [], "possibly_known": []})
        self.assertIn("current_learner_visible_interface", json.dumps(actor["kwargs"]["input"][0]["content"][1]))
        for obsolete in ("current_turn", "response_permissions", "scope_id", "fact_id", "content_grounding"):
            self.assertNotIn(obsolete, json.dumps(actor["payload"]["knowledge_state"]))

    def test_learner_schema_has_only_action_utterance_and_episodic_memory(self):
        self.assertEqual(set(model.LearnerAgentReply.model_fields), {"action", "utterance", "episodic_memory"})
        invalid = learner_reply({})
        invalid["knowledge_state"] = {"known": ["Unauthorized knowledge update."]}
        with self.assertRaises(Exception):
            model.LearnerAgentReply.model_validate(invalid)

    def test_observed_literal_text_is_separate_from_legacy_locator_description(self):
        request = deepcopy(self.request)
        original = {"id": "n2", "kind": "object", "label": "Written number 2", "texts": ["2"]}
        request["observation"]["elements"] = [deepcopy(original)]
        _, client = self.run_pipeline([initial_reply, no_change, learner_reply], request=request)
        for call in client.calls[1:]:
            observation = call["payload"].get("observation", call["payload"].get("public_observation"))
            element = observation["elements"][0]
            self.assertEqual(element["texts"], ["2"])
            self.assertEqual(element["locator_description"], "Written number 2")
            self.assertNotIn("label", element)
        self.assertEqual(request["observation"]["elements"][0], original)

    def test_repeated_ui_observation_skips_initialization_and_move_agent(self):
        first, _ = self.run_pipeline([initial_reply, no_change, learner_reply])
        request = deepcopy(self.request)
        request["learner_knowledge_model"] = first["learner_knowledge_model"]
        request["history"] = [{"step": 1, "action": {"type": "select", "id": "a"}, "result": {"ok": True}}]
        second, client = self.run_pipeline([learner_reply], request=request, step=2)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(second["knowledge_audit"]["checks"], [])
        self.assertEqual(first["learner_knowledge_model"]["state_sha256"], second["learner_knowledge_model"]["state_sha256"])

    def test_multiple_new_moves_each_checked_once_in_index_order(self):
        request = deepcopy(self.request)
        request["observation"]["messages"].append({"index": 2, "role": "assistant", "text": "What does your label mean?"})
        result, client = self.run_pipeline([initial_reply, no_change, no_change, learner_reply], request=request)
        moves = [x for x in client.calls if x["schema"] == "KnowledgeMoveCheck"]
        self.assertEqual([x["payload"]["move"]["move_id"] for x in moves], ["message:0", "message:2"])
        self.assertEqual(result["learner_knowledge_model"]["processed_move_ids"], ["message:0", "message:2"])
        earlier_images = [x for x in moves[0]["kwargs"]["input"][0]["content"] if x["type"] == "input_image"]
        self.assertEqual(earlier_images, [])
        observation = moves[0]["payload"]["observation"]
        self.assertEqual([x["index"] for x in observation["messages"]], [0])
        self.assertEqual(set(observation), {"messages"})

    def test_backlog_does_not_read_a_future_action(self):
        request = deepcopy(self.request)
        request["observation"]["messages"].append({"index": 2, "role": "assistant", "text": "Inspect the connection you tried."})
        request["history"] = [{"step": 1, "action": {"type": "add_connection", "from": "a", "to": "b"},
            "result": {"ok": True, "result": {"id": "one"}},
            "learning_observation": {"content_attempt": True, "diagram_changed": True, "action_context_move_id": "message:0"}}]
        _, client = self.run_pipeline([initial_reply, no_change, no_change, learner_reply], request=request)
        moves = [x for x in client.calls if x["schema"] == "KnowledgeMoveCheck"]
        self.assertEqual(moves[0]["payload"]["history"], [])
        self.assertEqual([x["step"] for x in moves[1]["payload"]["history"]], [1])

    def test_unchanged_question_check_keeps_knowledge_without_filling_unknown_bucket(self):
        result, _ = self.run_pipeline([initial_reply, no_change, learner_reply])
        state = result["learner_knowledge_model"]
        self.assertEqual(state["knowledge_state"], {"known": [KNOWN], "unknown": [], "possibly_known": []})
        self.assertEqual(state["revision"], 0)
        self.assertEqual(state["processed_move_ids"], ["message:0"])

    def test_missing_and_null_initial_buckets_are_valid(self):
        for number, state in enumerate(({}, {"known": None, "unknown": None, "possibly_known": None}), start=1):
            with self.subTest(state=state):
                result, _ = self.run_pipeline([{"knowledge_state": state}, no_change, learner_reply], step=number)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["learner_knowledge_model"]["knowledge_state"], {"known": [], "unknown": [], "possibly_known": []})

    def test_case_needs_no_predefined_knowledge_components(self):
        request = deepcopy(self.request)
        request["case_config"].pop("initial_conceptual_state")
        result, client = self.run_pipeline([initial_reply, no_change, learner_reply], request=request)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["learner_knowledge_model"]["knowledge_state"]["known"], [KNOWN])
        self.assertNotIn("initial_components", json.dumps(client.calls[0]["payload"]))

    def test_actual_student_message_survives_later_tutor_delivery_failure(self):
        request = deepcopy(self.request)
        request["observation"]["messages"] = [{"index": 4, "role": "assistant", "text": "Inspect the connection you tried."}]
        request["history"] = [{"step": 1, "action": {"type": "send_message", "text": "I tried connecting those parts."},
            "result": {"ok": False, "error": "Tutor delivery validation failed."},
            "learning_observation": {"content_attempt": True, "learner_message_delivered": True,
                "user_message_indices": [1], "feedback_message_indices": []}}]
        _, client = self.run_pipeline([initial_reply, no_change, learner_reply], request=request)
        move = next(x for x in client.calls if x["schema"] == "KnowledgeMoveCheck")
        self.assertEqual(move["payload"]["history"][0]["action"]["text"], "I tried connecting those parts.")

    def test_failed_tutor_draft_is_not_a_move(self):
        request = deepcopy(self.request)
        request["observation"]["messages"].append({"index": 2, "role": "assistant", "text": "Draft not delivered.", "error": True})
        result, client = self.run_pipeline([initial_reply, no_change, learner_reply], request=request)
        self.assertEqual(result["learner_knowledge_model"]["processed_move_ids"], ["message:0"])
        self.assertEqual(len(client.calls), 3)

    def test_learner_failure_keeps_completed_and_saved_knowledge_update(self):
        request = deepcopy(self.request)
        request["observation"]["messages"][0]["text"] = SUPPORTED
        visible, screenshot, image_url = model.prepare_input(request, self.request_path)
        output = {"decision": None, "api": {"called": False}, "error": None}
        client = ScriptedClient([initial_reply, support_reply, RuntimeError("Scripted learner endpoint failure.")])
        with self.assertRaises(RuntimeError):
            model.run_two_agent_decision(request, visible, screenshot, image_url,
                self.directory / "step_01_response.json", "gpt-6-sol", "low", output,
                client=client, request_path=self.request_path)
        stored = json.loads((self.directory / "knowledge_model_agent_memory.json").read_text())
        self.assertTrue(output["knowledge_audit"]["check_complete"])
        self.assertEqual(stored, output["learner_knowledge_model"])
        self.assertEqual(stored["knowledge_state"]["possibly_known"], [SUPPORTED])
        self.assertEqual(len(client.calls), 3)

    def test_all_calls_have_exact_prompt_input_schema_image_and_response_sidecars(self):
        result, _ = self.run_pipeline([initial_reply, no_change, learner_reply])
        for call in result["api_calls"]:
            prefix = self.directory / call["sidecar_prefix"]
            for suffix in (".prompt.md", ".input.json", ".schema.json", ".images.json", ".response.json"):
                self.assertTrue(prefix.with_suffix(suffix).is_file())
            self.assertEqual(hashlib.sha256(prefix.with_suffix(".prompt.md").read_bytes()).hexdigest(), call["prompt_sha256"])
        self.assertTrue((self.directory / "step_01_knowledge_model_initialize.image_0.png").is_file())
        self.assertTrue((self.directory / "step_01_knowledge_model_initialize.image_1.png").is_file())
        self.assertFalse(list(self.directory.glob("*gate*")))
        self.assertFalse(list(self.directory.glob("*observer*")))

    def test_existing_sidecar_cannot_be_overwritten_or_trigger_model_call(self):
        marker = self.directory / "step_01_knowledge_model_initialize.prompt.md"
        marker.write_text("Existing exact evidence.")
        visible, screenshot, image_url = model.prepare_input(self.request, self.request_path)
        client = ScriptedClient([])
        with self.assertRaises(model.InputBoundaryError):
            model.run_two_agent_decision(self.request, visible, screenshot, image_url,
                self.directory / "step_01_response.json", "gpt-6-sol", "low", {}, client=client, request_path=self.request_path)
        self.assertEqual(marker.read_text(), "Existing exact evidence.")
        self.assertEqual(client.calls, [])

    def test_legacy_actor_memory_cannot_upgrade_knowledge_or_enter_actor_payload(self):
        request = deepcopy(self.request)
        request["memory"] = {"current_understanding": "UNTRUSTED_SOLUTION", "component_states": [{"component_id": "relation", "status": "known"}]}
        request["history"] = [{"step": 1, "action": {"type": "select"}, "result": {"ok": True},
            "memory_update": {"current_understanding": "UNTRUSTED_SOLUTION"}}]
        result, client = self.run_pipeline([initial_reply, no_change, learner_reply], request=request)
        self.assertNotIn("UNTRUSTED_SOLUTION", json.dumps(client.calls[-1]["payload"]))
        self.assertEqual(result["learner_knowledge_model"]["knowledge_state"]["known"], [KNOWN])

    def test_dry_run_calls_no_agent_or_saves_fictional_state(self):
        result, client = self.run_pipeline([], dry=True)
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(client.calls, [])
        self.assertFalse((self.directory / "knowledge_model_agent_memory.json").exists())

    def test_seven_profiles_copy_one_cached_initialization(self):
        cache = self.directory / "shared_initial_cache"
        initial_states, cache_keys, model_initializations = [], set(), 0
        for step, file in enumerate(sorted((HERE / "profiles").glob("*.json")), 1):
            request = deepcopy(self.request)
            request["profile"] = json.loads(file.read_text())
            request["initial_knowledge_cache_dir"] = str(cache)
            replies = [no_change, learner_reply]
            if step == 1:
                replies.insert(0, initial_reply)
            result, client = self.run_pipeline(replies, request=request, step=step)
            self.assertEqual(result["status"], "ok")
            model_initializations += sum(call["schema"] == "KnowledgeInitialization" for call in client.calls)
            initial_states.append(result["learner_knowledge_model"]["initialization"]["reply"]["knowledge_state"])
            cache_keys.add(result["initial_knowledge_cache"]["key"])
            self.assertEqual(result["initial_knowledge_cache"]["hit"], step != 1)
            self.assertNotIn("initial_knowledge_cache_dir", result["model_visible_input"])
        self.assertEqual(model_initializations, 1)
        self.assertEqual(len(initial_states), 7)
        self.assertTrue(all(state == initial_states[0] for state in initial_states))
        self.assertEqual(len(cache_keys), 1)

    def test_later_teacher_updates_stay_private_and_do_not_change_cached_k0(self):
        request = deepcopy(self.request)
        request["initial_knowledge_cache_dir"] = str(self.directory / "shared_initial_cache")
        first, _ = self.run_pipeline([initial_reply, no_change, learner_reply], request=request)
        request["profile"] = json.loads((HERE / "profiles/p7_combined_support_needs.json").read_text())
        request["observation"]["messages"][0]["text"] = "A directed connection can show this local relation."
        second, client = self.run_pipeline([support_reply, learner_reply], request=request, step=2)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(first["learner_knowledge_model"]["knowledge_state"]["possibly_known"], [])
        self.assertEqual(second["learner_knowledge_model"]["knowledge_state"]["possibly_known"], [SUPPORTED])
        entry = json.loads(Path(second["initial_knowledge_cache"]["path"]).read_text())
        self.assertEqual(entry["knowledge_state"]["possibly_known"], [])
        self.assertNotEqual(first["learner_knowledge_model"]["owner_id"], second["learner_knowledge_model"]["owner_id"])

    def test_dry_run_does_not_create_or_read_initial_cache(self):
        request = deepcopy(self.request)
        request["initial_knowledge_cache_dir"] = str(self.directory / "not_created")
        result, client = self.run_pipeline([], request=request, dry=True)
        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(client.calls)
        self.assertFalse((self.directory / "not_created").exists())


if __name__ == "__main__":
    unittest.main()
