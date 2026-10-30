"""Offline reference and permission checks, without semantic entailment claims."""
from copy import deepcopy
import unittest

from learner_grounding import grounding_issues


class LearnerGroundingContracts(unittest.TestCase):
    def setUp(self):
        self.knowledge = {
            "components": [
                {"component_id": "parts", "available_knowledge": [
                    {"scope_id": "scope:local-parts", "statement": "The two local parts can be identified."}],
                 "provisional_beliefs": []},
                {"component_id": "relation", "available_knowledge": [],
                 "provisional_beliefs": [
                     {"belief_id": "belief:local-direction", "statement": "This mark might show the relation."}]},
            ],
            "current_turn": {
                "given_facts": [{"fact_id": "given:current-anchor", "statement": "Use the shown starting point."}],
                "response_permissions": {"answer_mode": "supported", "can_attempt": True},
            },
        }
        self.observation = {"elements": [{"id": "part-a"}, {"id": "part-b"}],
                            "dialogs": [{"id": "connectionDialog"}, {"id": "libraryDialog"}]}
        self.history = [{"step": 3, "action": {"type": "select", "id": "part-a"}}]

    def entry(self, **changes):
        value = {"target": "action.text", "statement": "The two local parts can be identified.",
                 "scope_ids": ["scope:local-parts"], "given_fact_ids": [],
                 "belief_ids": [], "observation_refs": []}
        value.update(changes)
        return value

    def reply(self, mode="supported_answer", *, action=None, entries=None):
        return {"action": action or {"type": "send_message", "text": "I can identify those parts."},
                "response_mode": mode,
                "content_grounding": [self.entry()] if entries is None else entries}

    def issues(self, reply, *, knowledge=None):
        return grounding_issues(reply, self.knowledge if knowledge is None else knowledge,
                                self.observation, self.history)

    def test_positive_scope_and_current_given_fact_are_exact_valid_references(self):
        for entry in (self.entry(), self.entry(scope_ids=[], given_fact_ids=["given:current-anchor"])):
            with self.subTest(entry=entry):
                self.assertEqual(self.issues(self.reply(entries=[entry])), [])

    def test_component_name_cannot_stand_in_for_a_positive_scope(self):
        issues = self.issues(self.reply(entries=[self.entry(scope_ids=["parts"])]))
        self.assertTrue(any("Unknown scope_ids: parts" in issue for issue in issues))

    def test_unknown_scope_and_stale_question_fact_are_rejected(self):
        for field, unknown in (("scope_ids", "scope:not-saved"),
                               ("given_fact_ids", "given:previous-question")):
            with self.subTest(field=field):
                entry = self.entry(**{field: [unknown]})
                self.assertTrue(any("Unknown " + field in issue
                                    for issue in self.issues(self.reply(entries=[entry]))))

    def test_literal_observation_references_use_available_ids_and_action_steps(self):
        for ref in ("task", "element:part-a", "dialog:connectionDialog", "action:3"):
            with self.subTest(reference=ref):
                entry = self.entry(scope_ids=[], observation_refs=[ref])
                self.assertEqual(self.issues(self.reply(entries=[entry])), [])
        for ref in ("element:not-visible", "dialog:not-open", "action:4", "message:teacher-1"):
            with self.subTest(reference=ref):
                entry = self.entry(scope_ids=[], observation_refs=[ref])
                self.assertTrue(any("Unknown observation_refs" in issue
                                    for issue in self.issues(self.reply(entries=[entry]))))

    def test_grounding_target_must_be_an_existing_populated_action_field(self):
        reply = self.reply(action={"type": "send_message", "text": "I can identify those parts.", "label": None})
        for target in ("utterance", "action.missing", "action.label", "action.to.x", "action.type"):
            with self.subTest(target=target):
                reply["content_grounding"] = [self.entry(target=target)]
                self.assertTrue(any("target" in issue.lower() for issue in self.issues(reply)))

    def test_all_populated_connection_parameters_need_their_own_grounding(self):
        action = {"type": "add_connection", "from": "part-a", "to": "part-b", "shape": "straight",
                  "direction": "forward", "label": "local"}
        entries = [self.entry(target="action." + field) for field in ("from", "to", "shape", "direction", "label")]
        self.assertEqual(self.issues(self.reply("supported_action", action=action, entries=entries)), [])
        for field in ("from", "to", "shape", "direction", "label"):
            with self.subTest(omitted=field):
                partial = [entry for entry in entries if entry["target"] != "action." + field]
                self.assertTrue(any("Ungrounded content fields: action." + field in issue
                                    for issue in self.issues(self.reply("supported_action", action=action, entries=partial))))
        type_only = self.reply("supported_action", action=action, entries=[self.entry(target="action.type")])
        self.assertTrue(any("Ungrounded content fields" in issue for issue in self.issues(type_only)))

    def test_editing_connection_endpoints_also_needs_exact_field_grounding(self):
        action = {"type": "edit_connection", "id": "existing-link", "from": "part-b", "to": "part-a"}
        entries = [self.entry(target="action.from"), self.entry(target="action.to")]
        self.assertEqual(self.issues(self.reply("supported_action", action=action, entries=entries)), [])
        self.assertTrue(any("action.to" in issue for issue in self.issues(
            self.reply("supported_action", action=action, entries=entries[:1]))))

    def test_supported_content_needs_grounding_and_an_actual_reference(self):
        self.assertTrue(self.issues(self.reply(entries=[])))
        entry = self.entry(scope_ids=[])
        self.assertTrue(any("supported claim requires" in issue.lower()
                            for issue in self.issues(self.reply(entries=[entry]))))

    def test_each_supported_grounding_entry_needs_its_own_reference(self):
        reply = self.reply(entries=[self.entry(), self.entry(scope_ids=[])])
        self.assertTrue(any("supported claim requires" in issue.lower() for issue in self.issues(reply)))

    def test_saved_partial_or_clarification_permission_forbids_full_answer(self):
        for permission in ("partial", "clarification"):
            with self.subTest(permission=permission):
                self.knowledge["current_turn"]["response_permissions"]["answer_mode"] = permission
                self.assertTrue(any("outside the saved" in issue for issue in self.issues(self.reply())))
                self.assertEqual(self.issues(self.reply("partial_answer")), [])
                self.assertEqual(self.issues(self.reply("clarification", entries=[self.entry(scope_ids=[])])), [])

    def test_question_can_identify_an_unsupported_target_without_asserting_an_answer(self):
        reply = self.reply("clarification", action={"type": "send_message", "text": "How should I connect them?"},
                           entries=[self.entry(statement="Asking how to represent the connection.", scope_ids=[])])
        self.assertEqual(self.issues(reply), [])

    def test_provisional_attempt_needs_saved_permission(self):
        reply = self.reply("provisional_attempt", entries=[self.entry(
            scope_ids=[], belief_ids=["belief:local-direction"])])
        self.assertEqual(self.issues(reply), [])
        self.knowledge["current_turn"]["response_permissions"]["can_attempt"] = False
        self.assertTrue(any("does not permit" in issue for issue in self.issues(reply)))

    def test_missing_current_permission_does_not_authorize_a_provisional_attempt(self):
        knowledge = deepcopy(self.knowledge)
        knowledge["current_turn"] = None
        reply = self.reply("provisional_attempt", entries=[self.entry(
            scope_ids=[], belief_ids=["belief:local-direction"])])
        self.assertTrue(any("does not permit" in issue for issue in self.issues(reply, knowledge=knowledge)))

    def test_provisional_belief_id_must_exist_and_cannot_be_laundered_as_a_scope(self):
        unknown = self.reply("provisional_attempt", entries=[self.entry(
            scope_ids=[], belief_ids=["belief:invented"])])
        self.assertTrue(any("Unknown belief_ids" in issue for issue in self.issues(unknown)))
        as_scope = self.reply("provisional_attempt", entries=[self.entry(scope_ids=["belief:local-direction"])])
        self.assertTrue(any("Unknown scope_ids" in issue for issue in self.issues(as_scope)))

    def test_belief_reference_is_allowed_only_in_provisional_mode(self):
        for mode in ("supported_answer", "supported_action", "partial_answer", "clarification"):
            with self.subTest(mode=mode):
                reply = self.reply(mode, entries=[self.entry(belief_ids=["belief:local-direction"])])
                self.assertTrue(any("only support a provisional attempt" in issue for issue in self.issues(reply)))

    def test_mechanical_navigation_can_have_empty_grounding(self):
        for action in ({"type": "select", "id": "part-a"}, {"type": "show_feedback", "messageIndex": 1},
                       {"type": "begin_revision"}, {"type": "cancel_dialog", "id": "connectionDialog"}):
            with self.subTest(action=action):
                self.assertEqual(self.issues(self.reply("navigation", action=action, entries=[])), [])

    def test_chat_and_new_diagram_relations_cannot_hide_in_navigation_or_stop(self):
        for action in ({"type": "send_message", "text": "The result is now established."},
                       {"type": "add_text", "text": "result"},
                       {"type": "add_connection", "from": "part-a", "to": "part-b"},
                       {"type": "reshape_connection", "id": "link-a", "to": {"x": 5, "y": 2}}):
            for mode in ("navigation", "stop"):
                with self.subTest(action=action, mode=mode):
                    self.assertTrue(any("cannot be classified" in issue
                                        for issue in self.issues(self.reply(mode, action=action, entries=[]))))

    def test_stop_action_requires_stop_mode_and_accepts_optional_exit_text(self):
        for action in ({"type": "stop"}, {"type": "stop", "text": "I want to stop here."}):
            with self.subTest(action=action):
                self.assertEqual(self.issues(self.reply("stop", action=action, entries=[])), [])
                self.assertTrue(any("must use stop mode" in issue
                                    for issue in self.issues(self.reply("navigation", action=action, entries=[]))))

    def test_stop_mode_cannot_label_an_unrelated_mechanical_action(self):
        reply = self.reply("stop", action={"type": "select", "id": "part-a"}, entries=[])
        self.assertTrue(any("Stop mode requires a stop action" in issue for issue in self.issues(reply)))

    def test_coordinate_size_and_deletion_changes_cannot_bypass_grounding_as_navigation(self):
        actions = [({"type": "move", "id": "part-a", "to": {"x": 5, "y": 2}}, ["to"]),
                   ({"type": "move", "id": "part-a", "dx": 4, "dy": 0}, ["dx", "dy"]),
                   ({"type": "resize", "id": "part-a", "direction": "larger", "steps": 2}, ["direction", "steps"]),
                   ({"type": "delete", "id": "part-a"}, ["id"])]
        for action, fields in actions:
            with self.subTest(action=action):
                self.assertTrue(self.issues(self.reply("navigation", action=action, entries=[])))
                entries = [self.entry(target="action." + field) for field in fields]
                self.assertEqual(self.issues(self.reply("supported_action", action=action, entries=entries)), [])

    def test_library_inspection_is_navigation_but_selecting_an_item_is_content(self):
        inspect = {"type": "add_object", "topic": "visible-category", "label": None}
        self.assertEqual(self.issues(self.reply("navigation", action=inspect, entries=[])), [])
        select = {"type": "add_object", "topic": "visible-category", "label": "Visible item"}
        self.assertTrue(self.issues(self.reply("navigation", action=select, entries=[])))
        entries = [self.entry(target="action.label", statement="Selecting the visible library item.",
                              scope_ids=[], observation_refs=["dialog:libraryDialog"])]
        self.assertEqual(self.issues(self.reply("supported_action", action=select, entries=entries)), [])

    def test_submission_without_reason_is_navigation_but_written_reason_needs_grounding(self):
        submit = {"type": "submit_revisions", "reason": None}
        self.assertEqual(self.issues(self.reply("navigation", action=submit, entries=[])), [])
        submit["reason"] = "I revised the local connection."
        self.assertTrue(self.issues(self.reply("navigation", action=submit, entries=[])))
        entries = [self.entry(target="action.reason", scope_ids=[], observation_refs=["action:3"])]
        self.assertEqual(self.issues(self.reply("supported_action", action=submit, entries=entries)), [])

    def test_validator_is_read_only_and_does_not_promote_provisional_beliefs(self):
        original = deepcopy((self.knowledge, self.observation, self.history))
        reply = self.reply("provisional_attempt", entries=[self.entry(
            scope_ids=[], belief_ids=["belief:local-direction"])])
        self.assertEqual(self.issues(reply), [])
        self.assertEqual((self.knowledge, self.observation, self.history), original)


if __name__ == "__main__":
    unittest.main()
