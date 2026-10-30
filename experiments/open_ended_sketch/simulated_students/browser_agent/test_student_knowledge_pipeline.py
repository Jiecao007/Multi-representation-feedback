"""Legacy observer/actor/gate contracts, preserved for historical source compatibility.

These tests verify isolation, persistence, rejection and audit plumbing. They do
not establish that an LLM assessor classifies learning evidence faithfully. No
browser, feedback server, SDK client or external API is contacted.
"""
from __future__ import annotations

import ast
import base64
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import student_model_legacy as model


# A complete, public one-pixel PNG; no real student image or private state.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQAAAABJRU5ErkJggg=="
)
CASE = {
    "id": "pipeline-generic-task", "source_id": "pipeline-response-a",
    "task_text": "Show how the two labeled parts relate.",
    "initial_explanation": "I labeled the two parts.",
    "initial_conceptual_state": {"constructed": True, "misconception_type": "uncertain", "knowledge_components": [
        {"component_id": "parts", "label": "Visible labeled parts", "status": "known",
         "statement": "Can identify the two already labeled parts."},
        {"component_id": "relation", "label": "Expressing a relationship", "status": "unlearned",
         "statement": "The relationship and its diagrammatic convention are not established."},
    ]},
}


def action(kind="send_message", **fields):
    result = {name: None for name in model.Action.model_fields}
    result["from"] = result.pop("from_id")
    result.update(type=kind, **fields)
    return result


def candidate(text="I am not sure how to connect them.", *, command=None):
    if command is not None:
        return {"action": command, "utterance": None}
    return {"action": action(text=text), "utterance": text}


def classify_plain(payload):
    return {"events": [{"event_id": event["event_id"], "kind": "plain_question", "updates": []}
                       for event in payload["new_public_events"]]}


def classify_local_support(payload):
    event = payload["new_public_events"][0]
    return {"events": [{"event_id": event["event_id"], "kind": "concrete_hint", "updates": [{
        "component_id": "relation", "kind": "support_received",
        "statement": "A directed connection can show this local relationship.",
        "evidence_quote": "A directed connection can show this relationship.",
        "support_event_ids": [], "confirmation_event_id": None,
    }]}]}


def gate_reply(*, updates=True, accepted=True, reject_path=None, omitted_path=None,
               unknown_component=False):
    """Script a separate gate's exhaustive answer to its requested audit paths."""
    def reply(payload):
        checks = []
        for target, paths in payload["required_checks"].items():
            for path in paths:
                if path == omitted_path:
                    continue
                supported = updates if target == "knowledge_update" else accepted
                if reject_path is not None and target == "candidate":
                    supported = path != reject_path
                checks.append({"target": target, "path": path,
                               "component_ids": ["foreign-component"] if unknown_component else ["relation"],
                               "supported": supported,
                               "explanation": "GATE_EXPLANATION_MUST_NOT_TEACH_THE_ACTOR"})
        return {"updates_supported": updates, "candidate_supported": accepted,
                "checks": checks, "summary": "GATE_SUMMARY_MUST_NOT_TEACH_THE_ACTOR"}
    return reply


class ScriptedClient:
    """An injected parse endpoint; exhausting the script is a test failure."""
    def __init__(self, script):
        self.script = list(script)
        self.payloads = []
        self.responses = SimpleNamespace(parse=Mock(side_effect=self._parse))

    def _parse(self, **kwargs):
        if not self.script:
            raise AssertionError("Unexpected extra model request or retry.")
        expected_schema, reply = self.script.pop(0)
        if kwargs["text_format"] is not expected_schema:
            raise AssertionError("A role received the wrong response schema.")
        content = kwargs["input"][0]["content"]
        payload = json.loads(content[0]["text"])
        self.payloads.append((expected_schema, payload))
        if isinstance(reply, Exception):
            raise reply
        parsed = reply(payload) if callable(reply) else deepcopy(reply)
        parsed = expected_schema.model_validate(parsed)
        return SimpleNamespace(status="completed", output_parsed=parsed,
                               output_text=parsed.model_dump_json(by_alias=True),
                               id="mock-response-" + str(len(self.payloads)),
                               model="mock-model", _request_id="mock-request", usage=None)


OBSERVER = model.KnowledgeUpdateProposal
ACTOR = model.LearnerActionProposal
GATE = model.KnowledgeGateVerdict


class StudentKnowledgePipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="learner-pipeline-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.screenshot = self.directory / "public.png"
        self.screenshot.write_bytes(PNG)
        self.request_path = self.directory / "step_01_request.json"
        self.response_path = self.directory / "step_01_response.json"
        self.request = {
            "profile": json.loads((HERE / "profiles/p1_average.json").read_text()),
            "learner_instance_id": "offline-pipeline-session", "case_config": deepcopy(CASE),
            "observation": {
                "screenshot_path": str(self.screenshot),
                "visible_text": "How could you show their relationship?",
                "messages": [{"index": 0, "role": "assistant",
                              "text": "How could you show their relationship?", "error": False}],
                "elements": [{"id": "part-a", "kind": "object", "texts": ["A"]},
                             {"id": "part-b", "kind": "object", "texts": ["B"]}],
                "controls": [], "dialogs": [], "status": {},
            },
            "history": [], "memory": None, "learner_knowledge_model": None,
        }

    def run_script(self, script, *, request=None, response_path=None):
        request = deepcopy(request or self.request)
        visible, screenshot, image_url = model.prepare_input(request, self.request_path)
        output = {"decision": None, "error": None, "api": {"called": False}}
        client = ScriptedClient(script)
        model.run_controlled_decision(
            request, visible, screenshot, image_url, response_path or self.response_path,
            "mock-model", "low", output, client=client,
        )
        self.assertEqual(client.script, [], "Expected role calls did not all occur.")
        return output, client

    def with_hint(self):
        request = deepcopy(self.request)
        text = "A directed connection can show this relationship. Which part would you connect?"
        request["observation"]["messages"][0]["text"] = text
        request["observation"]["visible_text"] = text
        return request

    def test_plain_question_does_not_supply_knowledge_and_memory_is_excluded(self):
        request = deepcopy(self.request)
        sentinel = "UNSUPPORTED_MEMORY_SENTINEL"
        request["memory"] = {"current_understanding": sentinel, "component_states": [
            {"component_id": "relation", "status": "known", "statement": sentinel}]}
        request["history"] = [{"step": 1, "action": {"type": "select", "id": "part-a"},
                               "result": {"ok": True}, "memory_update": deepcopy(request["memory"])}]
        output, client = self.run_script([
            (OBSERVER, classify_plain), (ACTOR, candidate()), (GATE, gate_reply()),
        ], request=request)
        audit = output["knowledge_audit"]
        self.assertEqual(output["status"], "ok")
        self.assertTrue(audit["update_validated"])
        self.assertEqual(audit["after"]["components"], audit["before"]["components"])
        self.assertEqual(audit["after"]["content_sha256"], audit["before"]["content_sha256"])
        self.assertEqual(audit["after"]["revision"], 0)
        self.assertEqual(audit["after"]["event_revision"], 1)
        self.assertEqual(output["decision"]["memory"]["component_states"][1]["status"], "unlearned")
        for _schema, payload in client.payloads:
            self.assertNotIn(sentinel, json.dumps(payload))
        self.assertNotIn("memory", output["model_visible_input"])

    def test_supported_candidate_after_one_rejection_gets_no_worked_correction(self):
        bad = candidate("I know the complete new procedure without help.")
        safe = candidate()
        output, client = self.run_script([
            (OBSERVER, classify_plain), (ACTOR, bad),
            (GATE, gate_reply(accepted=False, reject_path="candidate.action.text")),
            (ACTOR, safe), (GATE, gate_reply()),
        ])
        self.assertEqual(output["status"], "ok")
        self.assertEqual(len(output["candidate_attempts"]), 2)
        self.assertEqual(output["decision"]["action"]["text"], safe["action"]["text"])
        retry_input = client.payloads[3][1]
        feedback = retry_input["previous_candidate_rejection"]
        self.assertEqual(feedback["fields"], [{"path": "candidate.action.text", "component_ids": ["relation"]}])
        self.assertNotIn("GATE_EXPLANATION", json.dumps(retry_input))
        self.assertNotIn("GATE_SUMMARY", json.dumps(retry_input))
        self.assertNotIn(bad["action"]["text"], json.dumps(feedback))
        self.assertEqual(output["learner_knowledge_model"]["revision"], 0)

    def test_unsupported_utterance_and_parameter_only_diagram_both_fail_closed(self):
        variants = [
            (candidate("I can now perform the entire unknown procedure."), "candidate.action.text"),
            (candidate(command=action("add_connection", **{
                "from": "part-a", "to": "part-b", "direction": "forward", "label": "relation"})),
             "candidate.action.direction"),
        ]
        for index, (proposal, rejected_path) in enumerate(variants):
            with self.subTest(action=proposal["action"]["type"]):
                output, client = self.run_script([
                    (OBSERVER, classify_plain), (ACTOR, proposal),
                    (GATE, gate_reply(accepted=False, reject_path=rejected_path)),
                    (ACTOR, proposal), (GATE, gate_reply(accepted=False, reject_path=rejected_path)),
                ], response_path=self.directory / ("blocked_" + str(index) + "_response.json"))
                self.assertEqual(output["status"], "knowledge_gate_rejected")
                self.assertIsNone(output["decision"])
                self.assertTrue(output["error"]["retry_performed"])
                self.assertFalse(output["knowledge_audit"]["gate"]["approved"])
                self.assertEqual(client.responses.parse.call_count, 5)
                self.assertEqual(output["learner_knowledge_model"]["revision"], 0)
                self.assertEqual(len(output["candidate_attempts"]), 2)

    def test_received_local_support_survives_rejected_candidates_and_is_not_relearned(self):
        request = self.with_hint()
        bad = candidate("That one hint taught me every remaining relationship.")
        output, _ = self.run_script([
            (OBSERVER, classify_local_support), (ACTOR, bad),
            (GATE, gate_reply(accepted=False)), (ACTOR, bad), (GATE, gate_reply(accepted=False)),
        ], request=request)
        state = output["learner_knowledge_model"]
        self.assertEqual(output["status"], "knowledge_gate_rejected")
        self.assertTrue(output["knowledge_audit"]["update_validated"])
        self.assertIsNone(output["decision"])
        self.assertEqual(state["revision"], 1)
        self.assertEqual(state["components"][1]["status"], "tentative")
        self.assertEqual(len(state["components"][1]["available_knowledge"]), 1)
        self.assertEqual(state["components"][1]["independent_evidence"], [])
        request["learner_knowledge_model"] = state
        next_output, client = self.run_script([
            (ACTOR, candidate("I could try the connection you suggested.")), (GATE, gate_reply()),
        ], request=request, response_path=self.directory / "step_02_response.json")
        self.assertEqual(client.responses.parse.call_count, 2, "The same delivered hint must not call the observer twice.")
        self.assertEqual(next_output["learner_knowledge_model"], state)

    def test_semantically_rejected_update_rolls_back_and_does_not_retry_actor(self):
        output, client = self.run_script([
            (OBSERVER, classify_local_support), (ACTOR, candidate()),
            (GATE, gate_reply(updates=False)),
        ], request=self.with_hint())
        self.assertEqual(output["status"], "knowledge_update_rejected")
        self.assertFalse(output["knowledge_audit"]["update_validated"])
        self.assertNotEqual(output["knowledge_audit"]["proposed_after"]["revision"], 0)
        self.assertEqual(output["learner_knowledge_model"], output["knowledge_audit"]["before"])
        self.assertEqual(output["knowledge_audit"]["after"], output["knowledge_audit"]["before"])
        self.assertIsNone(output["decision"])
        self.assertEqual(client.responses.parse.call_count, 3)

    def test_gate_cannot_approve_without_exact_patch_and_parameter_coverage(self):
        proposal = candidate(command=action("add_connection", **{
            "from": "part-a", "to": "part-b", "direction": "forward", "label": "relation"}))
        output, _ = self.run_script([
            (OBSERVER, classify_plain), (ACTOR, proposal),
            (GATE, gate_reply(omitted_path="candidate.action.to")),
            (ACTOR, proposal), (GATE, gate_reply(omitted_path="candidate.action.to")),
        ])
        self.assertEqual(output["status"], "knowledge_gate_rejected")
        self.assertFalse(output["knowledge_audit"]["gate"]["approved"])
        self.assertIn({"target": "candidate", "missing_path": "candidate.action.to"},
                      output["knowledge_audit"]["gate"]["structural_issues"])
        output, _ = self.run_script([
            (OBSERVER, classify_local_support), (ACTOR, candidate()),
            (GATE, gate_reply(omitted_path="learning_proposal.events[0].updates[0]")),
        ], request=self.with_hint(), response_path=self.directory / "omitted_patch_response.json")
        self.assertEqual(output["status"], "knowledge_update_rejected")
        self.assertEqual(output["learner_knowledge_model"]["revision"], 0)

    def test_unknown_gate_component_cannot_validate_an_update(self):
        output, _ = self.run_script([
            (OBSERVER, classify_plain), (ACTOR, candidate()),
            (GATE, gate_reply(unknown_component=True)),
        ])
        self.assertEqual(output["status"], "knowledge_update_rejected")
        self.assertFalse(output["knowledge_audit"]["update_validated"])
        self.assertIsNone(output["decision"])

    def test_all_roles_save_prompts_inputs_schemas_and_raw_responses(self):
        output, client = self.run_script([
            (OBSERVER, classify_plain), (ACTOR, candidate()), (GATE, gate_reply()),
        ])
        expected_roles = ["learning_observer", "learner_candidate_1", "knowledge_gate_1"]
        self.assertEqual([record["role"] for record in output["api_calls"]], expected_roles)
        for record, (schema, payload) in zip(output["api_calls"], client.payloads):
            stem = self.directory / record["sidecar_prefix"]
            prompt = stem.with_suffix(".prompt.md").read_bytes()
            self.assertEqual(hashlib.sha256(prompt).hexdigest(), record["prompt_sha256"])
            self.assertEqual(json.loads(stem.with_suffix(".input.json").read_text()), payload)
            self.assertEqual(json.loads(stem.with_suffix(".schema.json").read_text()), schema.model_json_schema(by_alias=True))
            response = json.loads(stem.with_suffix(".response.json").read_text())
            self.assertEqual(json.loads(response["raw_output_text"]), response["parsed"])
            self.assertEqual(record["automatic_retries"], 0)
            self.assertEqual(record["screenshot"]["sha256"], hashlib.sha256(PNG).hexdigest())
        actor_schema = json.loads((self.directory / "step_01_learner_candidate_1.schema.json").read_text())
        self.assertEqual(set(actor_schema["properties"]), {"action", "utterance"})
        for call in client.responses.parse.call_args_list:
            self.assertFalse(call.kwargs["store"])
            content = call.kwargs["input"][0]["content"]
            self.assertEqual(content[1]["type"], "input_image")
            self.assertEqual(base64.b64decode(content[1]["image_url"].split(",", 1)[1]), PNG)

    def test_api_exception_is_not_retried_and_failure_sidecars_are_retained(self):
        visible, screenshot, image_url = model.prepare_input(self.request, self.request_path)
        client = ScriptedClient([(OBSERVER, RuntimeError("scripted-service-failure"))])
        output = {"decision": None, "error": None, "api": {"called": False}}
        with self.assertRaisesRegex(RuntimeError, "scripted-service-failure"):
            model.run_controlled_decision(self.request, visible, screenshot, image_url,
                                          self.response_path, "mock-model", "low", output, client=client)
        self.assertEqual(client.responses.parse.call_count, 1)
        self.assertFalse(output["knowledge_audit"]["update_validated"])
        self.assertIsNone(output["decision"])
        saved = json.loads((self.directory / "step_01_learning_observer.response.json").read_text())
        self.assertEqual(saved["api"]["error_type"], "RuntimeError")
        self.assertIsNone(saved["parsed"])

    def test_existing_role_evidence_is_preserved_before_any_new_request(self):
        visible, screenshot, image_url = model.prepare_input(self.request, self.request_path)
        original = b"Original audit evidence must remain byte-for-byte unchanged.\n"
        for index, suffix in enumerate((".prompt.md", ".input.json", ".schema.json", ".response.json")):
            with self.subTest(existing_sidecar=suffix):
                directory = self.directory / ("existing_role_" + str(index))
                directory.mkdir()
                preserved = directory / ("step_01_learning_observer" + suffix)
                preserved.write_bytes(original)
                output = {"decision": None, "error": None, "api": {"called": False}}
                client = ScriptedClient([])
                with self.assertRaisesRegex(model.InputBoundaryError, "already exists"):
                    model.run_controlled_decision(
                        self.request, visible, screenshot, image_url, directory / "step_01_response.json",
                        "mock-model", "low", output, client=client,
                    )
                client.responses.parse.assert_not_called()
                self.assertEqual(preserved.read_bytes(), original)
                self.assertEqual(set(directory.iterdir()), {preserved}, "No companion artifact may be overwritten or created.")
                self.assertIsNone(output["decision"])

    def test_main_refuses_an_existing_response_without_client_or_artifact_changes(self):
        original = b"Original exported response, even if not JSON, must be preserved.\n"
        self.response_path.write_bytes(original)
        self.request_path.write_text(json.dumps(self.request))
        before = {path.name: path.read_bytes() for path in self.directory.iterdir()}
        with patch.object(model, "existing_client") as factory, redirect_stdout(io.StringIO()) as stdout:
            code = model.main(["--request", str(self.request_path), "--response", str(self.response_path)])
        self.assertEqual(code, 1)
        factory.assert_not_called()
        self.assertEqual(json.loads(stdout.getvalue())["status"], "output_exists")
        after = {path.name: path.read_bytes() for path in self.directory.iterdir()}
        self.assertEqual(after, before)

    def test_sdk_client_configuration_has_zero_automatic_retries(self):
        # Inspect the local factory without importing the app or reading a key.
        tree = ast.parse((HERE.parents[1] / "app/server.py").read_text())
        factory = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "client")
        constructors = [node for node in ast.walk(factory) if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name) and node.func.id == "OpenAI"]
        self.assertEqual(len(constructors), 1)
        retries = next(keyword.value for keyword in constructors[0].keywords if keyword.arg == "max_retries")
        self.assertIsInstance(retries, ast.Constant)
        self.assertEqual(retries.value, 0)

    def test_dry_run_makes_no_role_call_or_supported_knowledge_claim(self):
        visible, screenshot, image_url = model.prepare_input(self.request, self.request_path)
        output = {"decision": None, "error": None, "api": {"called": False}}
        model.run_controlled_decision(self.request, visible, screenshot, image_url,
                                      self.response_path, "mock-model", "low", output,
                                      client=None, dry_run=True)
        self.assertEqual(output["status"], "dry_run")
        self.assertEqual(output["api_calls"], [])
        self.assertFalse(output["knowledge_audit"]["update_validated"])
        self.assertFalse(output["knowledge_audit"]["gate"]["approved"])
        self.assertIsNone(output["decision"])


if __name__ == "__main__":
    unittest.main()
