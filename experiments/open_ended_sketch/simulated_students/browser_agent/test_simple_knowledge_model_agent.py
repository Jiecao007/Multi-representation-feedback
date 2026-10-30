"""Offline checks of optional knowledge lists, cadence and stored-state integrity."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from knowledge_model_agent import KnowledgeAgentBoundaryError, KnowledgeModelAgent, KnowledgeInitialization, normalize_knowledge, public_moves

CASE = {"id": "simple", "task_text": "Relate A and B.", "initial_explanation": "I labeled A and B."}
UPTAKE = {"level": "average", "definition": "Interpret local support.", "operational_behavior": {}}
EMPTY = {"known": [], "unknown": [], "possibly_known": []}

def observation(*texts):
    return {"messages": [{"index": i * 2, "role": "assistant", "text": text} for i, text in enumerate(texts)], "visible_text": "Whole page."}

def agent(knowledge=None):
    result = KnowledgeModelAgent(CASE, owner_id="P1:one", knowledge_profile=UPTAKE)
    result.initialize({"knowledge_state": knowledge or {}})
    return result

def check(value, move, knowledge=None, **kwargs):
    return value.check_move(move, {"move_id": move["move_id"], "knowledge_state": knowledge or value.project()}, **kwargs)

class SimpleKnowledgeContracts(unittest.TestCase):
    def test_optional_null_missing_and_empty_buckets(self):
        self.assertEqual(normalize_knowledge({}), EMPTY)
        self.assertEqual(normalize_knowledge({"known": None, "unknown": None, "possibly_known": []}), EMPTY)
        self.assertIsNone(KnowledgeInitialization.model_validate({"knowledge_state": {}}).knowledge_state.known)

    def test_no_forced_component_catalogue_or_unknown_knowledge(self):
        value = agent({"known": ["Can identify A and B."]})
        self.assertEqual(value.project()["unknown"], [])
        self.assertEqual(value.project()["possibly_known"], [])
        self.assertNotIn("components", value.state)
        self.assertEqual(value.state["revision"], 0)

    def test_initial_payload_excludes_imposed_prior_and_later_feedback(self):
        case = {**CASE, "initial_conceptual_state": {"initial_belief": "IMPOSED"}}
        value = KnowledgeModelAgent(case, {"prior": "IMPOSED"})
        payload = value.initialization_payload({"student_response_text": "Original response.", "feedback": "LATER",
            "submission_evidence": {"gap": "IMPOSED"}, "figures": [{"role": "student_response_figure"}]})
        self.assertNotIn("IMPOSED", json.dumps(payload))
        self.assertNotIn("LATER", json.dumps(payload))
        self.assertEqual(payload["initial_response"]["student_response_text"], "Original response.")
        self.assertTrue(payload["initial_response"]["initialization_excludes_feedback"])

    def test_initialization_exactly_once(self):
        value = agent()
        with self.assertRaises(KnowledgeAgentBoundaryError): value.initialize({"knowledge_state": {}})

    def test_wrong_provisional_belief_is_not_automatically_repaired(self):
        belief = "The student thinks a dotted comparison line is a route step."
        value = agent({"possibly_known": [belief]})
        self.assertEqual(value.project()["possibly_known"], [belief])
        self.assertEqual(value.project()["known"], [])

    def test_delivery_errors_and_student_messages_are_not_teacher_moves(self):
        visible = observation("Actual move.")
        visible["messages"] += [{"index": 1, "role": "user", "text": "Attempt."},
                                {"index": 2, "role": "assistant", "error": True, "text": "Failed draft."}]
        self.assertEqual([m["move_id"] for m in public_moves(visible)], ["message:0"])

    def test_payload_contains_state_and_context_without_permission_protocol(self):
        value = agent({"known": ["A is a label."]})
        visible = observation("Use an arrow.")
        payload = value.move_payload(public_moves(visible)[0], visible, [])
        self.assertEqual(payload["previous_knowledge_state"], value.project())
        self.assertEqual(payload["move"]["text"], "Use an arrow.")
        self.assertNotIn("current_turn", json.dumps(payload))
        self.assertNotIn("response_permissions", json.dumps(payload))

    def test_changed_move_preserves_full_returned_state_and_increments_revision(self):
        value = agent({"known": ["A is a label."]})
        visible = observation("This arrow means the local relation.")
        receipt = check(value, public_moves(visible)[0], {"known": ["A is a label.", "This arrow means the relation."]}, observation=visible)
        self.assertEqual(receipt["decision"], "update")
        self.assertEqual(value.state["revision"], 1)
        self.assertEqual(value.state["event_revision"], 1)
        self.assertEqual(len(value.project()["known"]), 2)

    def test_unchanged_move_is_still_a_complete_once_only_check(self):
        value = agent(); visible = observation("What does A mean?"); move = public_moves(visible)[0]
        receipt = check(value, move)
        self.assertEqual(receipt["decision"], "no_change")
        self.assertTrue(receipt["check_complete"])
        self.assertEqual(value.state["revision"], 0)
        self.assertEqual(value.state["event_revision"], 1)
        self.assertEqual(value.pending_moves(visible), [])
        with self.assertRaises(KnowledgeAgentBoundaryError): check(value, move)

    def test_wrong_move_reply_does_not_partially_mutate_memory(self):
        value = agent(); before = deepcopy(value.state); move = public_moves(observation("Actual."))[0]
        with self.assertRaises(KnowledgeAgentBoundaryError):
            value.check_move(move, {"move_id": "message:99", "knowledge_state": {"known": ["Injected."]}})
        self.assertEqual(before, value.state)

    def test_backlog_checks_are_chronological_and_hide_later_screen(self):
        value = agent(); visible = observation("Earlier.", "Later."); first, second = public_moves(visible)
        with self.assertRaises(KnowledgeAgentBoundaryError): value.move_payload(second, visible, [])
        payload = value.move_payload(first, visible, [])
        self.assertEqual(set(payload["observation"]), {"messages"})
        self.assertEqual([m["index"] for m in payload["observation"]["messages"]], [0])
        check(value, first)
        self.assertEqual(value.pending_moves(visible), [second])

    def test_actions_after_current_move_are_not_earlier_evidence(self):
        value = agent(); visible = observation("Earlier.", "Later."); first, second = public_moves(visible)
        event = {"step": 1, "action": {"type": "add_connection"}, "result": {"ok": True},
                 "learning_observation": {"action_context_move_id": "message:0"}}
        self.assertEqual(value.move_payload(first, visible, [event])["history"], [])
        check(value, first)
        self.assertEqual(len(value.move_payload(second, visible, [event])["history"]), 1)

    def test_delivered_student_attempt_survives_subsequent_tutor_failure(self):
        value = agent(); visible = {"messages": [{"index": 4, "role": "assistant", "text": "Review your attempt."}]}
        event = {"step": 1, "action": {"type": "send_message", "text": "I tried an arrow."}, "result": {"ok": False},
            "learning_observation": {"learner_message_delivered": True, "user_message_indices": [1], "feedback_message_indices": []}}
        payload = value.move_payload(public_moves(visible)[0], visible, [event])
        self.assertEqual(payload["history"][0]["action"]["text"], "I tried an arrow.")

    def test_previously_checked_text_cannot_be_rewritten(self):
        value = agent(); visible = observation("Actual."); check(value, public_moves(visible)[0])
        with self.assertRaises(KnowledgeAgentBoundaryError): value.pending_moves(observation("Changed."))

    def test_state_is_saved_before_run_method_returns(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"; value = KnowledgeModelAgent(CASE, owner_id="one")
            value.run_initialize(lambda payload, schema: schema.model_validate({"knowledge_state": {"known": ["A."]}}), memory_path=path)
            self.assertEqual(json.loads(path.read_text()), value.state)
            visible = observation("Question.")
            value.run_move(lambda payload, schema: schema.model_validate({"move_id": payload["move"]["move_id"],
                "knowledge_state": payload["previous_knowledge_state"]}), public_moves(visible)[0], visible, [], memory_path=path)
            self.assertEqual(json.loads(path.read_text())["processed_move_ids"], ["message:0"])
            self.assertFalse(path.with_name("memory.json.tmp").exists())

    def test_resume_is_bound_to_case_owner_and_uptake(self):
        value = agent()
        self.assertEqual(KnowledgeModelAgent(CASE, owner_id="P1:one", knowledge_profile=UPTAKE, persisted=value.state).state, value.state)
        for owner, case, uptake in [("other", CASE, UPTAKE), ("P1:one", {**CASE, "initial_explanation": "Other."}, UPTAKE),
                                   ("P1:one", CASE, {**UPTAKE, "level": "low"})]:
            with self.assertRaises(KnowledgeAgentBoundaryError):
                KnowledgeModelAgent(case, owner_id=owner, knowledge_profile=uptake, persisted=value.state)

    def test_old_formats_and_tampered_state_fail(self):
        value = agent(); forged = deepcopy(value.state); forged["knowledge_state"]["known"].append("Injected.")
        with self.assertRaises(KnowledgeAgentBoundaryError):
            KnowledgeModelAgent(CASE, owner_id="P1:one", knowledge_profile=UPTAKE, persisted=forged)
        for version in ["knowledge-model-agent-v2", "knowledge-model-agent-v3"]:
            with self.assertRaises(KnowledgeAgentBoundaryError): KnowledgeModelAgent(CASE, persisted={"format": version})

    def test_projection_has_only_copied_three_categories(self):
        value = agent({"known": ["A."]}); projected = value.learner_projection()
        self.assertEqual(set(projected), set(EMPTY)); projected["known"].append("Not saved.")
        self.assertEqual(value.project()["known"], ["A."])
        self.assertEqual(value.memory_component_states(), [])

    def test_blank_statements_fail_but_exact_duplicates_are_normalized(self):
        with self.assertRaises(KnowledgeAgentBoundaryError): normalize_knowledge({"unknown": [" "]})
        self.assertEqual(normalize_knowledge({"known": [" A ", "A"]})["known"], ["A"])

if __name__ == "__main__": unittest.main()
