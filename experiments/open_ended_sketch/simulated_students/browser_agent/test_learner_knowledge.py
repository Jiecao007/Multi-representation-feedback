"""Meaningful controller contracts, with no model or browser calls."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from learner_knowledge import (KnowledgeBoundaryError, KnowledgeUpdateProposal,
                               initialize_knowledge_model, pending_learning_events,
                               public_learning_events, apply_learning_proposal,
                               validate_knowledge_model, project_knowledge_model,
                               memory_component_states, _hash)


CASE = {"id": "generic-task", "source_id": "response-a", "task_text": "Explain the relationship in the submitted representation.",
        "initial_explanation": "These are the parts I drew.", "initial_conceptual_state": {"knowledge_components": [
            {"component_id": "part", "label": "Visible parts", "status": "known", "statement": "Can identify the already labeled parts."},
            {"component_id": "relation", "label": "Represented relation", "status": "unlearned", "statement": "The relationship and its representation are not established."}]}}
PRIOR = {"components": [
    {**c, "initial_limitation": "Do not independently supply an unestablished relationship or procedure.",
     "learning_requirement": "Relevant local explanation, hint, or feedback on an actual attempt."}
    for c in CASE["initial_conceptual_state"]["knowledge_components"]]}


def message(index, text, *, error=False):
    return {"index": index, "role": "assistant", "text": text, "error": error}


def patch(kind="support_received", quote="A connection represents a relationship.", statement="A connection can express a relationship.", **overrides):
    value = {"component_id": "relation", "kind": kind, "statement": statement,
             "evidence_quote": quote, "support_event_ids": [], "confirmation_event_id": None}
    value.update(overrides)
    return value


def proposal(events, updates=None, kinds=None):
    updates, kinds = updates or {}, kinds or {}
    return {"events": [{"event_id": event["event_id"],
                        "kind": kinds.get(event["event_id"], "plain_question"),
                        "updates": updates.get(event["event_id"], [])} for event in events]}


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.state = initialize_knowledge_model(CASE, PRIOR, owner_id="P1/session-a")

    def apply_support(self):
        observation = {"messages": [message(0, "A connection represents a relationship. What do you notice?")]}
        events = pending_learning_events(self.state, observation, [])
        proposed = proposal(events, {"message:0": [patch()]}, {"message:0": "concrete_explanation"})
        return apply_learning_proposal(self.state, proposed, events), observation

    def test_initial_model_comes_from_case_and_bound_prior(self):
        other = initialize_knowledge_model(CASE, PRIOR, owner_id="P4/session-b")
        self.assertEqual(other["components"], self.state["components"])
        self.assertEqual(self.state["components"][1]["status"], "unlearned")
        self.assertEqual(self.state["components"][1]["available_knowledge"], [])
        self.assertNotEqual(other["owner_id"], self.state["owner_id"])

    def test_plain_question_changes_only_seen_event_ledger(self):
        obs = {"messages": [message(0, "How could you show the relationship?")]}
        events = pending_learning_events(self.state, obs, [])
        result = apply_learning_proposal(self.state, proposal(events), events)
        self.assertEqual(result["components"], self.state["components"])
        self.assertEqual(result["content_sha256"], self.state["content_sha256"])
        self.assertEqual(result["revision"], 0)
        self.assertEqual(result["event_revision"], 1)
        self.assertEqual(pending_learning_events(result, obs, []), [])

    def test_plain_question_cannot_have_a_knowledge_patch(self):
        obs = {"messages": [message(0, "How could you show the relationship?")]}
        events = public_learning_events(obs, [])
        with self.assertRaisesRegex(KnowledgeBoundaryError, "cannot update"):
            apply_learning_proposal(self.state, proposal(events, {"message:0": [patch(quote="relationship")]}), events)

    def test_praise_does_not_create_knowledge(self):
        events = public_learning_events({"messages": [message(0, "Good effort!")]}, [])
        result = apply_learning_proposal(self.state, proposal(events, kinds={"message:0": "praise_or_acknowledgment"}), events)
        self.assertEqual(result["content_sha256"], self.state["content_sha256"])

    def test_concrete_support_releases_only_recorded_local_scope(self):
        result, _ = self.apply_support()
        relation = result["components"][1]
        self.assertEqual(relation["status"], "tentative")
        self.assertEqual(len(relation["available_knowledge"]), 1)
        self.assertEqual(relation["available_knowledge"][0]["statement"], "A connection can express a relationship.")
        self.assertEqual(relation["initial_limitation"], PRIOR["components"][1]["initial_limitation"])
        self.assertIn("outside", relation["unresolved_scope"])
        self.assertEqual(relation["independent_evidence"], [])
        self.assertEqual(self.state["revision"], 0, "Applying an update must not mutate its input model.")

    def test_repeated_explanation_is_not_additional_learning(self):
        first, obs = self.apply_support()
        obs["messages"].append(message(2, "A connection represents a relationship. What do you notice?"))
        events = pending_learning_events(first, obs, [])
        proposed = proposal(events, {"message:2": [patch()]}, {"message:2": "concrete_hint"})
        result = apply_learning_proposal(first, proposed, events)
        self.assertEqual(result["revision"], first["revision"])
        self.assertEqual(result["content_sha256"], first["content_sha256"])

    def test_same_phrase_can_support_a_different_local_relation(self):
        first, obs = self.apply_support()
        obs["messages"].append(message(2, "A connection represents a relationship. What do you notice?"))
        events = pending_learning_events(first, obs, [])
        proposed = proposal(events, {"message:2": [patch(statement="A connection can express the newly discussed local relation.")]},
                            {"message:2": "concrete_hint"})
        result = apply_learning_proposal(first, proposed, events)
        self.assertEqual(len(result["components"][1]["available_knowledge"]), 2)

    def test_explaining_an_identical_already_known_scope_adds_no_content(self):
        statement = self.state["components"][0]["statement"]
        events = public_learning_events({"messages": [message(0, "These are the already labeled parts.")]}, [])
        p = proposal(events, {"message:0": [patch(component_id="part", quote="already labeled parts",
            statement=statement)]}, {"message:0": "concrete_explanation"})
        result = apply_learning_proposal(self.state, p, events)
        self.assertEqual(result["content_sha256"], self.state["content_sha256"])
        self.assertEqual(result["revision"], 0)
        self.assertEqual(result["processed_event_ids"], ["message:0"])

    def test_explanation_can_be_embedded_in_a_question_turn(self):
        result, _ = self.apply_support()
        self.assertEqual(result["revision"], 1, "Question punctuation must not erase an explicit preceding explanation.")

    def test_fabricated_quote_is_rejected(self):
        obs = {"messages": [message(0, "A connection represents a relationship.")]}
        events = public_learning_events(obs, [])
        p = proposal(events, {"message:0": [patch(quote="Here is the complete solution.")]}, {"message:0": "concrete_explanation"})
        with self.assertRaisesRegex(KnowledgeBoundaryError, "exact"):
            apply_learning_proposal(self.state, p, events)

    def test_unknown_component_and_unavailable_source_are_rejected(self):
        events = public_learning_events({"messages": [message(0, "A connection represents a relationship.")]}, [])
        for override in [{"component_id": "foreign"}, {"support_event_ids": ["message:999"]}]:
            with self.subTest(override=override), self.assertRaises(KnowledgeBoundaryError):
                apply_learning_proposal(self.state, proposal(events, {"message:0": [patch(**override)]}, {"message:0": "concrete_hint"}), events)

    def test_error_reply_is_not_a_learning_source(self):
        obs = {"messages": [message(0, "A connection represents a relationship.", error=True)]}
        self.assertEqual(public_learning_events(obs, []), [])

    def test_failed_actions_and_noncontent_clicks_do_not_qualify(self):
        actions = [{"step": 1, "action": {"type": "add_connection", "label": "trial"}, "result": {"ok": False, "error": "failed"}},
                   {"step": 2, "action": {"type": "show_feedback"}, "result": {"ok": True}},
                   {"step": 3, "action": {"type": "select", "id": "part"}, "result": {"ok": True}},
                   {"step": 4, "action": {"type": "cancel_dialog"}, "result": {"ok": True}}]
        self.assertEqual(public_learning_events({}, actions), [])

    def test_explicit_noop_overrides_legacy_creation_result(self):
        history = [{"step": 1, "action": {"type": "add_connection"},
                    "result": {"ok": True, "result": {"id": "existing"}},
                    "learning_observation": {"diagram_changed": False, "content_attempt": False}}]
        self.assertEqual(public_learning_events({}, history), [])

    def test_legacy_creation_needs_an_actual_created_identifier(self):
        history = [{"step": 1, "action": {"type": "add_object"}, "result": {"ok": True, "result": {}}},
                   {"step": 2, "action": {"type": "add_connection", "label": "trial"}, "result": {"ok": True, "result": {"id": "created"}}}]
        self.assertEqual([e["event_id"] for e in public_learning_events({}, history)], ["action:2"])

    def visual_fixture(self):
        obs = {"messages": [message(0, "Look at this connection.")]}
        history = [{"step": 1, "action": {"type": "show_feedback", "messageIndex": 0}, "result": {"ok": True},
                    "learning_observation": {"content_attempt": False, "diagram_changed": False,
                        "visible_support_revealed": True, "message_index": 0,
                        "visible_text": "Look at this connection.",
                        "visible_elements": [{"id": "public-connection", "kind": "connection",
                                              "label": "represented relation", "highlighted": True}]}}]
        return obs, history

    def test_real_revealed_figure_is_a_support_source_not_a_student_attempt(self):
        obs, history = self.visual_fixture()
        events = public_learning_events(obs, history)
        self.assertEqual(events[1]["source"], "tutor_visual")
        self.assertEqual(events[1]["event_id"], "action:1")
        p = proposal(events, {"action:1": [patch(quote="represented relation",
            statement="This shown connection expresses this particular relation.")]},
            {"message:0": "other", "action:1": "concrete_hint"})
        result = apply_learning_proposal(self.state, p, events)
        self.assertEqual(result["components"][1]["status"], "tentative")
        self.assertEqual(result["components"][1]["attempted_beliefs"], [])
        self.assertEqual(memory_component_states(result)[1]["evidence"][0]["source"], "completed_action")
        self.assertEqual(validate_knowledge_model(CASE, PRIOR, result, obs, history, owner_id="P1/session-a"), result)

    def test_show_click_or_unchanged_reference_is_not_visual_support(self):
        obs, history = self.visual_fixture()
        history[0]["learning_observation"].pop("visible_support_revealed")
        self.assertEqual([event["event_id"] for event in public_learning_events(obs, history)], ["message:0"])
        history[0]["learning_observation"]["visible_support_revealed"] = False
        self.assertEqual([event["event_id"] for event in public_learning_events(obs, history)], ["message:0"])

    def test_failed_or_noop_show_cannot_be_a_visual_source(self):
        obs, history = self.visual_fixture()
        history[0]["result"]["ok"] = False
        self.assertEqual([event["event_id"] for event in public_learning_events(obs, history)], ["message:0"])
        history[0]["result"]["ok"] = True
        history[0]["learning_observation"]["noop"] = True
        self.assertEqual([event["event_id"] for event in public_learning_events(obs, history)], ["message:0"])

    def test_revealed_highlight_alone_need_not_change_knowledge(self):
        obs, history = self.visual_fixture()
        events = public_learning_events(obs, history)
        result = apply_learning_proposal(self.state, proposal(events, kinds={"message:0": "other", "action:1": "other"}), events)
        self.assertEqual(result["content_sha256"], self.state["content_sha256"])

    def test_a_revealed_figure_cannot_itself_confirm_independent_application(self):
        obs, history = self.visual_fixture()
        events = public_learning_events(obs, history)
        p = proposal(events, {"action:1": [patch("independent_application", quote="represented relation",
            support_event_ids=["action:1"], confirmation_event_id="action:1")]},
            {"message:0": "other", "action:1": "attempt_feedback"})
        with self.assertRaisesRegex(KnowledgeBoundaryError, "explicit attempt feedback"):
            apply_learning_proposal(self.state, p, events)

    def test_revealed_figure_requires_a_real_tutor_message_and_visible_elements(self):
        obs, history = self.visual_fixture()
        history[0]["learning_observation"]["message_index"] = 99
        with self.assertRaisesRegex(KnowledgeBoundaryError, "actual public message"):
            public_learning_events(obs, history)
        history[0]["learning_observation"]["message_index"] = 0
        history[0]["learning_observation"]["visible_elements"] = []
        with self.assertRaisesRegex(KnowledgeBoundaryError, "visible elements"):
            public_learning_events(obs, history)

    def test_altered_revealed_figure_invalidates_persisted_evidence(self):
        obs, history = self.visual_fixture()
        events = public_learning_events(obs, history)
        result = apply_learning_proposal(self.state, proposal(events, kinds={"message:0": "other", "action:1": "other"}), events)
        history[0]["learning_observation"]["visible_elements"][0]["label"] = "a substituted representation"
        with self.assertRaisesRegex(KnowledgeBoundaryError, "visible history"):
            validate_knowledge_model(CASE, PRIOR, result, obs, history, owner_id="P1/session-a")

    def test_completed_attempt_records_provisional_belief_without_mastery(self):
        history = [{"step": 1, "action": {"type": "send_message", "text": "Maybe these parts connect."}, "result": {"ok": True}}]
        events = public_learning_events({}, history)
        p = proposal(events, {"action:1": [patch("attempt_observed", quote="Maybe these parts connect.", statement="Thinks the two parts may connect.")]}, {"action:1": "completed_attempt"})
        result = apply_learning_proposal(self.state, p, events)
        relation = result["components"][1]
        self.assertEqual(relation["status"], "unlearned")
        self.assertEqual(relation["available_knowledge"], [])
        self.assertEqual(len(relation["attempted_beliefs"]), 1)

    def independent_fixture(self, confirmation_kind="attempt_feedback", feedback_indices=None):
        obs = {"messages": [message(2, "Your attempted relationship is correct.")]}
        history = [{"step": 1, "action": {"type": "send_message", "text": "These parts connect."}, "result": {"ok": True},
                    "learning_observation": {"content_attempt": True, "feedback_message_indices": feedback_indices if feedback_indices is not None else [2]}}]
        events = public_learning_events(obs, history)
        p = proposal(events, {"action:1": [patch("independent_application", quote="These parts connect.", statement="Can express this particular connection.", support_event_ids=["message:2"], confirmation_event_id="message:2")]},
                     {"action:1": "completed_attempt", "message:2": confirmation_kind})
        return obs, history, events, p

    def test_attempt_feedback_can_establish_local_knowledge_without_prior_hint(self):
        _, _, events, p = self.independent_fixture()
        result = apply_learning_proposal(self.state, p, events)
        relation = result["components"][1]
        self.assertEqual(relation["status"], "known")
        self.assertEqual(relation["available_knowledge"][0]["statement"], "Can express this particular connection.")
        self.assertEqual(relation["initial_limitation"], self.state["components"][1]["initial_limitation"])

    def test_praise_cannot_replace_explicit_attempt_feedback(self):
        _, _, events, p = self.independent_fixture("praise_or_acknowledgment")
        with self.assertRaisesRegex(KnowledgeBoundaryError, "explicit attempt feedback"):
            apply_learning_proposal(self.state, p, events)

    def test_foreign_feedback_cannot_confirm_a_completed_attempt(self):
        _, _, events, p = self.independent_fixture(feedback_indices=[10])
        with self.assertRaisesRegex(KnowledgeBoundaryError, "not feedback on this"):
            apply_learning_proposal(self.state, p, events)

    def delayed_fixture(self):
        history = [{"step": 1, "action": {"type": "send_message", "text": "These parts connect."},
                    "result": {"ok": True}, "learning_observation": {"content_attempt": True,
                        "user_message_indices": [1], "feedback_message_indices": []}}]
        events = public_learning_events({}, history)
        first = apply_learning_proposal(self.state, proposal(events, {"action:1": [
            patch("attempt_observed", quote="These parts connect.", statement="Believes these parts connect.")]},
            {"action:1": "completed_attempt"}), events)
        obs = {"messages": [message(2, "Your attempted relationship is correct.")]}
        events = pending_learning_events(first, obs, history)
        p = proposal(events, {"message:2": [patch("independent_application",
            quote="Your attempted relationship is correct.", statement="Can express this particular connection.",
            support_event_ids=["action:1", "message:2"], confirmation_event_id="message:2")]},
            {"message:2": "attempt_feedback"})
        return first, obs, history, events, p

    def test_later_feedback_can_confirm_already_recorded_provisional_attempt(self):
        first, obs, history, events, p = self.delayed_fixture()
        result = apply_learning_proposal(first, p, events)
        relation = result["components"][1]
        self.assertEqual(relation["status"], "known")
        self.assertEqual(relation["independent_evidence"][0]["event_ids"], ["action:1", "message:2"])
        self.assertEqual(result["processed_event_ids"], ["action:1", "message:2"])
        self.assertEqual(first["event_ledger"][0], result["event_ledger"][0], "Later feedback must not rewrite an earlier receipt.")
        self.assertEqual(validate_knowledge_model(CASE, PRIOR, result, obs, history, owner_id="P1/session-a"), result)

    def test_later_feedback_cannot_bind_an_older_attempt_when_newer_attempt_exists(self):
        first, obs, history, _, p = self.delayed_fixture()
        history.append({"step": 2, "action": {"type": "send_message", "text": "A different attempt."},
                        "result": {"ok": True}})
        events = pending_learning_events(first, obs, history)
        p["events"].append({"event_id": "action:2", "kind": "completed_attempt", "updates": []})
        with self.assertRaisesRegex(KnowledgeBoundaryError, "latest completed"):
            apply_learning_proposal(first, p, events)

    def test_intervening_necessary_question_does_not_replace_latest_substantive_attempt(self):
        first, obs, history, _, p = self.delayed_fixture()
        history.append({"step": 2, "action": {"type": "send_message", "text": "Which connection?"},
                        "result": {"ok": True}})
        events = pending_learning_events(first, obs, history)
        p["events"].append({"event_id": "action:2", "kind": "other", "updates": []})
        result = apply_learning_proposal(first, p, events)
        self.assertEqual(result["components"][1]["status"], "known")

    def test_necessary_question_alone_cannot_supply_an_attempt_for_mastery(self):
        first, obs, history, _, p = self.delayed_fixture()
        history.append({"step": 2, "action": {"type": "send_message", "text": "Which connection?"},
                        "result": {"ok": True}})
        events = pending_learning_events(first, obs, history)
        p["events"].append({"event_id": "action:2", "kind": "other", "updates": []})
        p["events"][0]["updates"][0]["support_event_ids"] = ["action:2", "message:2"]
        with self.assertRaisesRegex(KnowledgeBoundaryError, "exactly one"):
            apply_learning_proposal(first, p, events)

    def test_attempt_feedback_exposure_also_needs_a_substantive_attempt(self):
        first, obs, history, _, _ = self.delayed_fixture()
        history.append({"step": 2, "action": {"type": "send_message", "text": "Which connection?"},
                        "result": {"ok": True}})
        events = pending_learning_events(first, obs, history)
        p = proposal(events, {"message:2": [patch(quote="Your attempted relationship is correct.",
            support_event_ids=["action:2"])]}, {"message:2": "attempt_feedback", "action:2": "other"})
        with self.assertRaisesRegex(KnowledgeBoundaryError, "bind a completed attempt"):
            apply_learning_proposal(first, p, events)

    def test_later_feedback_cannot_be_a_preexisting_or_earlier_message(self):
        first, _, history, _, _ = self.delayed_fixture()
        obs = {"messages": [message(0, "Your attempted relationship is correct.")]}
        events = pending_learning_events(first, obs, history)
        p = proposal(events, {"message:0": [patch("independent_application",
            quote="Your attempted relationship is correct.", support_event_ids=["action:1", "message:0"],
            confirmation_event_id="message:0")]}, {"message:0": "attempt_feedback"})
        with self.assertRaisesRegex(KnowledgeBoundaryError, "newly delivered"):
            apply_learning_proposal(first, p, events)

    def test_later_feedback_must_explicitly_bind_one_earlier_action(self):
        first, _, _, events, p = self.delayed_fixture()
        p["events"][0]["updates"][0]["support_event_ids"] = ["message:2"]
        with self.assertRaisesRegex(KnowledgeBoundaryError, "exactly one"):
            apply_learning_proposal(first, p, events)

    def test_later_feedback_cannot_use_praise_as_confirmation(self):
        first, _, _, events, p = self.delayed_fixture()
        p["events"][0]["kind"] = "praise_or_acknowledgment"
        with self.assertRaisesRegex(KnowledgeBoundaryError, "cannot update"):
            apply_learning_proposal(first, p, events)

    def test_an_unexecuted_proposed_action_cannot_be_evidence(self):
        with self.assertRaisesRegex(KnowledgeBoundaryError, "exactly once"):
            apply_learning_proposal(self.state, {"events": [{"event_id": "action:99", "kind": "completed_attempt", "updates": []}]}, [])

    def test_each_new_event_must_be_classified_once(self):
        events = public_learning_events({"messages": [message(0, "What do you notice?")]}, [])
        with self.assertRaisesRegex(KnowledgeBoundaryError, "exactly once"):
            apply_learning_proposal(self.state, {"events": []}, events)

    def test_event_cannot_be_reapplied(self):
        first, obs = self.apply_support()
        events = public_learning_events(obs, [])
        with self.assertRaisesRegex(KnowledgeBoundaryError, "twice"):
            apply_learning_proposal(first, proposal(events), events)

    def test_persisted_state_replays_against_exact_public_history(self):
        result, obs = self.apply_support()
        validated = validate_knowledge_model(CASE, PRIOR, result, obs, [], owner_id="P1/session-a")
        self.assertEqual(validated, result)

    def test_modified_component_is_rejected_even_with_recomputed_digest(self):
        result, obs = self.apply_support()
        result["components"][1]["status"] = "known"
        result["state_sha256"] = _hash({k: v for k, v in result.items() if k != "state_sha256"})
        with self.assertRaisesRegex(KnowledgeBoundaryError, "ledger replay"):
            validate_knowledge_model(CASE, PRIOR, result, obs, [], owner_id="P1/session-a")

    def test_simple_persisted_tampering_is_rejected(self):
        result, obs = self.apply_support()
        result["revision"] += 1
        with self.assertRaisesRegex(KnowledgeBoundaryError, "altered"):
            validate_knowledge_model(CASE, PRIOR, result, obs, [], owner_id="P1/session-a")

    def test_changed_source_text_invalidates_persisted_evidence(self):
        result, obs = self.apply_support()
        obs["messages"][0]["text"] = "How could you show the relationship?"
        with self.assertRaisesRegex(KnowledgeBoundaryError, "visible history"):
            validate_knowledge_model(CASE, PRIOR, result, obs, [], owner_id="P1/session-a")

    def test_foreign_case_and_owner_are_rejected(self):
        other = deepcopy(CASE)
        other["task_text"] = "A different task."
        for case, owner in [(other, "P1/session-a"), (CASE, "P2/session-a")]:
            with self.subTest(owner=owner), self.assertRaisesRegex(KnowledgeBoundaryError, "different case or owner"):
                validate_knowledge_model(case, PRIOR, self.state, {}, [], owner_id=owner)

    def test_changed_figure_provenance_or_response_evidence_changes_case_binding(self):
        for added in [{"provenance": {"student_crop_sha256": "different-submitted-figure"}},
                      {"provenance": {"task_figure_sha256": "different-task-figure"}},
                      {"response_grounding": {"present_features": [{"observation": "A different relationship is visible."}]}}]:
            other = {**deepcopy(CASE), **added}
            with self.subTest(added=added), self.assertRaisesRegex(KnowledgeBoundaryError, "different case or owner"):
                validate_knowledge_model(other, PRIOR, self.state, {}, [], owner_id="P1/session-a")

    def test_projection_excludes_update_ledger_and_legacy_memory_is_compatible(self):
        result, _ = self.apply_support()
        projected = project_knowledge_model(result)
        self.assertNotIn("event_ledger", projected)
        self.assertEqual(projected["components"], result["components"])
        states = memory_component_states(result)
        self.assertEqual([s["component_id"] for s in states], ["part", "relation"])
        for state in states:
            self.assertEqual(set(state), {"component_id", "status", "statement", "evidence"})
            for evidence in state["evidence"]:
                self.assertEqual(set(evidence), {"source", "reference", "support"})
        self.assertEqual(states[1]["evidence"][0]["reference"], "message:0")

    def test_empty_pending_batch_is_an_exact_noop(self):
        self.assertEqual(apply_learning_proposal(self.state, {"events": []}, []), self.state)

    def test_strict_proposal_cannot_directly_set_status(self):
        with self.assertRaises(Exception):
            KnowledgeUpdateProposal.model_validate({"events": [], "status": "known"})


if __name__ == "__main__":
    unittest.main()
