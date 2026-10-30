"""Offline contracts for the stateful two-agent Knowledge Model Agent.

Scripted agent replies test public evidence, storage and check cadence. They do
not certify the semantic accuracy of an LLM and make no API/browser calls.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from knowledge_model_agent_scoped_v3 import (
    KnowledgeModelAgent, KnowledgeAgentBoundaryError, KnowledgeInitialization,
    KnowledgeMoveCheck, public_moves, scope_id, fact_id, belief_id, digest,
)


CASE = {"id": "generic-response", "task_text": "Show the relationship between two parts.",
        "initial_explanation": "I labeled the parts.",
        "initial_conceptual_state": {"knowledge_components": [
            {"component_id": "parts", "status": "known", "statement": "Can identify the two labeled parts."},
            {"component_id": "relation", "status": "unlearned", "statement": "The connecting relation is not established."}]}}

UPTAKE = {"level": "average", "definition": "Understanding and applying delivered feedback.",
          "operational_behavior": {"typical_response": "Can use an explicit local cue."}}


def agent():
    result = KnowledgeModelAgent(CASE, owner_id="P1:one")
    result.initialize({"initial_state_summary": "Labeled parts only.", "components": [
        {"component_id": "parts", "status": "known", "evidence_summary": "Two labels are present.", "remaining_uncertainty": ""},
        {"component_id": "relation", "status": "unlearned", "evidence_summary": "No relation was supplied.", "remaining_uncertainty": "The connecting relation."}]})
    return result


def observation(text="How could you connect the two parts?", index=0):
    return {"messages": [{"index": index, "role": "assistant", "text": text, "error": False}],
            "elements": [], "visible_text": text}


def update(kind="local_support", refs=None, quote="A directed connection can show this relation.", status="tentative"):
    return {"component_id": "relation", "kind": kind, "status": status,
            "statement": "A directed connection can express this local relation.",
            "evidence": refs or [{"reference": "message:0", "quote": quote}],
            "remaining_uncertainty": "Other relationships remain unestablished."}


def reply(mid="message:0", kind="plain_question", updates=None):
    updates = updates or []
    return {"move_id": mid, "classification": kind, "decision": "update" if updates else "no_change",
            "updates": updates, "memory_summary": "Checked this move.",
            "current_turn": {"understood_request": "Consider the requested relationship.",
                "understood_propositions": [], "unresolved_relations": ["The connecting relation."],
                "relevant_scope_ids": [], "new_scope_update_indices": [], "given_facts": [],
                "response_permissions": {"answer_mode": "clarification", "can_attempt": False,
                                         "clarification_target": "A cue about the connecting relation."}}}


def positive_initial(statement="Can identify the two labeled parts."):
    return {"statement": statement, "evidence": [{"source": "student_text",
            "quote": "I labeled the parts.", "figure_index": None,
            "observation": "The Response explicitly describes labeling the parts."}]}


def attempt(step=1, text="I tried connecting the two parts.", feedback=2, ok=True):
    return {"step": step, "action": {"type": "send_message", "text": text},
            "result": {"ok": ok, **({} if ok else {"error": "Tutor delivery failed."})},
            "learning_observation": {"content_attempt": True, "user_message_indices": [feedback-1],
                                     "feedback_message_indices": [feedback], "learner_message_delivered": True}}


class KnowledgeAgentContracts(unittest.TestCase):
    def test_initialization_is_real_agent_call_then_atomic_storage(self):
        a = KnowledgeModelAgent(CASE, owner_id="P1:one")
        calls=[]
        def model(payload, schema):
            calls.append((payload, schema))
            return KnowledgeInitialization(initial_state_summary="Initial reading.", components=[
                {"component_id": "parts", "status": "known", "evidence_summary": "Labels.", "remaining_uncertainty": "",
                 "positive_scopes": [positive_initial()]},
                {"component_id": "relation", "status": "unlearned", "evidence_summary": "No connection.", "remaining_uncertainty": "Connecting relation.",
                 "positive_scopes": []}])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"knowledge_model_agent_memory.json"
            a.run_initialize(model, {"text": CASE["initial_explanation"]}, memory_path=path)
            self.assertEqual(json.loads(path.read_text()), a.state)
            self.assertFalse(path.with_name(path.name+".tmp").exists())
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][0]["mode"],"initialize")
        self.assertTrue(a.state["initialized"])

    def test_initialization_does_not_promote_shared_prior_from_model_expertise(self):
        a=KnowledgeModelAgent(CASE,owner_id="P1:one")
        receipt=a.initialize({"initial_state_summary":"Claims expertise.","components":[
            {"component_id":"relation","status":"known","evidence_summary":"I can solve it.","remaining_uncertainty":""}]})
        self.assertEqual(a.state["components"][1]["status"],"unlearned")
        self.assertEqual(a.state["components"][1]["available_knowledge"],[])
        self.assertTrue(receipt["warnings"])

    def test_initialization_is_exactly_once(self):
        a=agent()
        with self.assertRaises(KnowledgeAgentBoundaryError):a.initialize({})

    def test_plain_question_no_knowledge_change_but_check_is_complete(self):
        a=agent();obs=observation();move=a.pending_moves(obs)[0];before=a.state["content_sha256"]
        receipt=a.check_move(move,reply(),observation=obs,history=[])
        self.assertTrue(receipt["check_complete"])
        self.assertEqual(before,a.state["content_sha256"])
        self.assertEqual(a.state["revision"],0)
        self.assertEqual(a.state["processed_move_ids"],["message:0"])

    def test_same_move_not_rechecked_after_editor_only_action(self):
        a=agent();obs=observation();move=a.pending_moves(obs)[0]
        a.check_move(move,reply(),observation=obs,history=[])
        self.assertEqual(a.pending_moves(obs,[{"step":1,"action":{"type":"select"},"result":{"ok":True}}]),[])
        with self.assertRaises(KnowledgeAgentBoundaryError):a.check_move(move,reply(),observation=obs,history=[])

    def test_distinct_delivered_messages_each_require_one_check(self):
        a=agent();obs=observation();obs["messages"].append({"index":2,"role":"assistant","text":"Explain your labels."})
        for move in a.pending_moves(obs):a.check_move(move,reply(move["move_id"]),observation=obs,history=[])
        self.assertEqual(a.state["processed_move_ids"],["message:0","message:2"])

    def test_error_drafts_do_not_become_moves(self):
        obs=observation();obs["messages"][0]["error"]=True
        self.assertEqual(public_moves(obs),[])

    def test_concrete_hint_creates_only_local_tentative_scope(self):
        a=agent();obs=observation("A directed connection can show this relation.");move=a.pending_moves(obs)[0]
        a.check_move(move,reply(kind="concrete_hint",updates=[update()]),observation=obs,history=[])
        c=a.state["components"][1]
        self.assertEqual(c["status"],"tentative")
        self.assertEqual(len(c["available_knowledge"]),1)
        self.assertIn("Other relationships",c["remaining_uncertainty"])
        self.assertEqual(c["independent_evidence"],[])

    def test_question_support_patch_is_rejected_without_stopping_check(self):
        a=agent();obs=observation();move=a.pending_moves(obs)[0]
        u=update(quote=obs["messages"][0]["text"])
        receipt=a.check_move(move,reply(updates=[u]),observation=obs,history=[])
        self.assertEqual(receipt["decision"],"no_change")
        self.assertTrue(receipt["check_complete"])
        self.assertTrue(receipt["rejected_updates"])
        self.assertEqual(a.state["revision"],0)

    def test_invalid_quote_does_not_discard_another_valid_patch(self):
        a=agent();obs=observation("A directed connection can show this relation.");move=a.pending_moves(obs)[0]
        bad=update(quote="This quote was never delivered.")
        receipt=a.check_move(move,reply(kind="concrete_hint",updates=[bad,update()]),observation=obs,history=[])
        self.assertEqual(len(receipt["accepted_updates"]),1)
        self.assertEqual(len(receipt["rejected_updates"]),1)

    def test_same_batch_feedback_and_attempt_need_no_anchor_protocol(self):
        a=agent();obs=observation("That independent connection expresses the relation.",2);move=a.pending_moves(obs)[0]
        history=[attempt()]
        refs=[{"reference":"message:2","quote":obs["messages"][0]["text"]},
              {"reference":"action:1","quote":"I tried connecting the two parts."}]
        u=update("independent_application",refs,status="known")
        receipt=a.check_move(move,reply("message:2","attempt_feedback",[u]),observation=obs,history=history)
        self.assertEqual(len(receipt["accepted_updates"]),1)
        self.assertEqual(a.state["components"][1]["status"],"known")

    def test_missing_attempt_reference_is_conservative_patch_warning(self):
        a=agent();obs=observation("A directed connection can show this relation.");move=a.pending_moves(obs)[0]
        receipt=a.check_move(move,reply(kind="attempt_feedback",updates=[update()]),observation=obs,history=[])
        self.assertTrue(receipt["check_complete"])
        self.assertEqual(receipt["decision"],"no_change")
        self.assertIn("actual completed attempt",receipt["rejected_updates"][0]["reason"])

    def test_new_instruction_in_mixed_feedback_does_not_need_prior_attempt(self):
        a=agent()
        text=("You correctly found the endpoint. Show the movement with a directed "
              "connection from the starting part to the ending part.")
        obs=observation(text);move=a.pending_moves(obs)[0]
        u=update(quote="Show the movement with a directed connection from the starting part to the ending part.")
        u["evidence_basis"]="instructional_content"
        receipt=a.check_move(move,reply(kind="attempt_feedback",updates=[u]),observation=obs,history=[])
        self.assertEqual(len(receipt["accepted_updates"]),1)
        self.assertEqual(receipt["rejected_updates"],[])
        scope=a.state["components"][1]["available_knowledge"][0]
        self.assertEqual(scope["evidence_basis"],"instructional_content")
        self.assertEqual(scope["event_ids"],["message:0"])
        self.assertEqual(a.state["components"][1]["status"],"tentative")
        self.assertEqual(a.state["components"][1]["independent_evidence"],[])

    def test_p1_connected_arrow_instruction_is_saved_before_next_learner_read(self):
        a=agent()
        text=("You correctly traced the card moves and found that you land on 2. "
              "How will you show the three card moves as connected arrows from "
              "0 to −6, then 6, and finally 2?")
        obs=observation(text,20);move=a.pending_moves(obs)[0]
        u=update(refs=[{"reference":"message:20","quote":
            "show the three card moves as connected arrows from 0 to −6, then 6, and finally 2"}])
        u.update(evidence_basis="instructional_content",statement=
            "The supplied plan is connected arrows from 0 to −6, then 6, and finally 2.")
        def model(payload,schema):
            self.assertEqual(payload["move"]["move_id"],"message:20")
            return KnowledgeMoveCheck.model_validate(reply("message:20","attempt_feedback",[u]))
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"knowledge_model_agent_memory.json"
            receipt=a.run_move(model,move,obs,[],memory_path=path)
            saved=json.loads(path.read_text())
            self.assertEqual(saved,a.state)
            self.assertEqual(len(saved["components"][1]["available_knowledge"]),1)
            self.assertEqual(a.project()["components"],saved["components"])
        self.assertTrue(receipt["check_complete"])
        self.assertEqual(a.pending_moves(obs),[])

    def test_confirmation_patch_still_requires_actual_attempt(self):
        a=agent();obs=observation("Your connection expresses the intended relation.")
        move=a.pending_moves(obs)[0]
        u=update(quote=obs["messages"][0]["text"])
        u["evidence_basis"]="attempt_confirmation"
        receipt=a.check_move(move,reply(kind="attempt_feedback",updates=[u]),observation=obs,history=[])
        self.assertEqual(receipt["accepted_updates"],[])
        self.assertIn("actual completed attempt",receipt["rejected_updates"][0]["reason"])

    def test_confirmation_patch_requires_feedback_link_to_cited_attempt(self):
        a=agent();obs=observation("Your connection expresses the intended relation.",4)
        move=a.pending_moves(obs)[0]
        history=[attempt(feedback=2)]
        u=update(refs=[{"reference":"message:4","quote":obs["messages"][0]["text"]},
                       {"reference":"action:1","quote":"I tried connecting the two parts."}])
        u["evidence_basis"]="attempt_confirmation"
        receipt=a.check_move(move,reply("message:4","attempt_feedback",[u]),observation=obs,history=history)
        self.assertEqual(receipt["accepted_updates"],[])
        self.assertIn("not linked",receipt["rejected_updates"][0]["reason"])

    def test_confirmed_local_support_accepts_linked_action_and_current_feedback(self):
        a=agent();obs=observation("Your connection expresses the intended relation.",2)
        move=a.pending_moves(obs)[0]
        u=update(refs=[{"reference":"message:2","quote":obs["messages"][0]["text"]},
                       {"reference":"action:1","quote":"I tried connecting the two parts."}])
        u["evidence_basis"]="attempt_confirmation"
        receipt=a.check_move(move,reply("message:2","attempt_feedback",[u]),observation=obs,history=[attempt()])
        self.assertEqual(len(receipt["accepted_updates"]),1)
        self.assertEqual(a.state["components"][1]["status"],"tentative")

    def test_mixed_message_keeps_instruction_when_confirmation_lacks_attempt(self):
        a=agent();obs=observation("Your idea works. A directed connection can show this relation.")
        move=a.pending_moves(obs)[0]
        instruction=update();instruction["evidence_basis"]="instructional_content"
        confirmation=update(quote="Your idea works.");confirmation["evidence_basis"]="attempt_confirmation"
        receipt=a.check_move(move,reply(kind="attempt_feedback",updates=[confirmation,instruction]),observation=obs,history=[])
        self.assertEqual(len(receipt["accepted_updates"]),1)
        self.assertEqual(len(receipt["rejected_updates"]),1)
        self.assertEqual(receipt["accepted_updates"][0]["evidence_basis"],"instructional_content")

    def test_explicit_basis_does_not_turn_plain_question_into_instruction(self):
        a=agent();obs=observation();move=a.pending_moves(obs)[0]
        u=update(quote=obs["messages"][0]["text"]);u["evidence_basis"]="instructional_content"
        receipt=a.check_move(move,reply(updates=[u]),observation=obs,history=[])
        self.assertEqual(receipt["accepted_updates"],[])
        self.assertIn("does not supply new knowledge",receipt["rejected_updates"][0]["reason"])

    def test_instruction_cannot_be_declared_independent_mastery(self):
        a=agent();obs=observation("A directed connection can show this relation.")
        move=a.pending_moves(obs)[0]
        u=update("independent_application",status="known");u["evidence_basis"]="instructional_content"
        receipt=a.check_move(move,reply(kind="concrete_hint",updates=[u]),observation=obs,history=[])
        self.assertEqual(receipt["accepted_updates"],[])
        self.assertIn("does not match",receipt["rejected_updates"][0]["reason"])

    def test_past_instruction_alone_is_not_another_current_exposure(self):
        a=agent();obs=observation("A directed connection can show this relation.")
        first=a.pending_moves(obs)[0]
        a.check_move(first,reply(kind="concrete_hint",updates=[update()]),observation=obs,history=[])
        obs["messages"].append({"index":2,"role":"assistant","text":"Here is a new local explanation."})
        move=a.pending_moves(obs)[0]
        u=update();u["evidence_basis"]="instructional_content"
        receipt=a.check_move(move,reply("message:2","concrete_explanation",[u]),observation=obs,history=[])
        self.assertEqual(receipt["accepted_updates"],[])
        self.assertIn("current delivered move",receipt["rejected_updates"][0]["reason"])

    def test_tutor_delivery_failure_does_not_erase_rendered_student_attempt(self):
        a=agent();obs=observation("Please inspect your attempted relation.",4);move=a.pending_moves(obs)[0]
        history=[attempt(feedback=2,ok=False)]
        payload=a.move_payload(move,obs,history)
        self.assertIn("action:1",[item["reference"] for item in payload["available_evidence"]])

    def test_failed_or_noop_diagram_action_is_not_attempt(self):
        a=agent();obs=observation();move=a.pending_moves(obs)[0]
        history=[{"step":1,"action":{"type":"move","id":"a"},"result":{"ok":True},
                  "learning_observation":{"noop":True,"content_attempt":False}}]
        self.assertNotIn("action:1",[item["reference"] for item in a.move_payload(move,obs,history)["available_evidence"]])

    def test_delayed_show_is_evidence_for_next_move_not_second_check(self):
        a=agent();obs=observation();move=a.pending_moves(obs)[0]
        a.check_move(move,reply(),observation=obs,history=[])
        history=[{"step":1,"action":{"type":"show_feedback"},"result":{"ok":True},"learning_observation":{
            "visible_support_revealed":True,"message_index":0,"visible_text":"Relation shown.","visible_elements":[{"id":"a"}]}}]
        self.assertEqual(a.pending_moves(obs,history),[])
        obs["messages"].append({"index":2,"role":"assistant","text":"What does the shown relation mean?"})
        payload=a.move_payload(a.pending_moves(obs,history)[0],obs,history)
        shown=next(item for item in payload["available_evidence"] if item["reference"]=="figure:1")
        self.assertTrue(shown["deferred_to_next_move"])

    def test_persist_restore_owner_and_case_binding(self):
        a=agent();copy=KnowledgeModelAgent(CASE,owner_id="P1:one",persisted=a.state)
        self.assertEqual(copy.state,a.state)
        for kwargs in [{"owner_id":"P2:two"},{"case_config":{**CASE,"task_text":"Another task."}}]:
            values={"case_config":CASE,"owner_id":"P1:one","persisted":a.state};values.update(kwargs)
            with self.assertRaises(KnowledgeAgentBoundaryError):KnowledgeModelAgent(**values)

    def test_unchanged_expanded_uptake_profile_can_restore_its_memory(self):
        a=KnowledgeModelAgent(CASE,owner_id="P1:one",knowledge_profile=UPTAKE)
        restored=KnowledgeModelAgent(CASE,owner_id="P1:one",knowledge_profile=deepcopy(UPTAKE),persisted=a.state)
        self.assertEqual(restored.state,a.state)
        self.assertEqual(len(a.state["knowledge_profile_binding"]),64)
        self.assertNotIn("Understanding and applying delivered feedback",json.dumps(a.state))
        self.assertNotIn("operational_behavior",json.dumps(a.state))

    def test_same_learner_cannot_resume_after_uptake_level_or_definition_changes(self):
        a=KnowledgeModelAgent(CASE,owner_id="P1:one",knowledge_profile=UPTAKE)
        variants=[{**UPTAKE,"level":"low"},
                  {**UPTAKE,"definition":"Changed interpretation of uptake."},
                  {**UPTAKE,"operational_behavior":{"typical_response":"Only an explicit part is usable."}}]
        for profile in variants:
            with self.subTest(profile=profile),self.assertRaisesRegex(KnowledgeAgentBoundaryError,"uptake profile"):
                KnowledgeModelAgent(CASE,owner_id="P1:one",knowledge_profile=profile,persisted=a.state)

    def test_role_scoped_run_rejects_unbound_historical_memory(self):
        historical=agent()
        with self.assertRaisesRegex(KnowledgeAgentBoundaryError,"uptake profile"):
            KnowledgeModelAgent(CASE,owner_id="P1:one",knowledge_profile=UPTAKE,persisted=historical.state)
        # Existing offline clients that never supplied a role profile remain
        # usable; the active runtime always supplies its selected uptake.
        restored=KnowledgeModelAgent(CASE,owner_id="P1:one",persisted=historical.state)
        self.assertEqual(restored.state,historical.state)

    def test_modified_memory_is_rejected(self):
        a=agent();state=deepcopy(a.state);state["components"][1]["status"]="known"
        with self.assertRaises(KnowledgeAgentBoundaryError):KnowledgeModelAgent(CASE,owner_id="P1:one",persisted=state)

    def test_changed_checked_move_is_rejected(self):
        a=agent();obs=observation();move=a.pending_moves(obs)[0]
        a.check_move(move,reply(),observation=obs,history=[])
        obs["messages"][0]["text"]="Changed old message."
        with self.assertRaises(KnowledgeAgentBoundaryError):a.pending_moves(obs)

    def test_ui_attempt_from_same_or_later_move_waits_for_next_move(self):
        a=agent();obs=observation();move=a.pending_moves(obs)[0]
        history=[{"step":1,"action":{"type":"add_connection","from":"a","to":"b"},
                  "result":{"ok":True,"result":{"id":"connection-1"}},
                  "learning_observation":{"content_attempt":True,"diagram_changed":True,
                                           "action_context_move_id":"message:0"}}]
        self.assertNotIn("action:1",[item["reference"] for item in a.move_payload(move,obs,history)["available_evidence"]])
        a.check_move(move,reply(),observation=obs,history=history)
        obs["messages"].append({"index":2,"role":"assistant","text":"What did the new connection show?"})
        payload=a.move_payload(a.pending_moves(obs)[0],obs,history)
        self.assertIn("action:1",[item["reference"] for item in payload["available_evidence"]])

    def test_legacy_ui_attempt_without_temporal_receipt_is_conservative(self):
        a=agent();obs=observation();move=a.pending_moves(obs)[0]
        history=[{"step":1,"action":{"type":"add_text","text":"a"},
                  "result":{"ok":True,"result":{"id":"a"}},
                  "learning_observation":{"content_attempt":True,"diagram_changed":True}}]
        self.assertNotIn("action:1",[item["reference"] for item in a.move_payload(move,obs,history)["available_evidence"]])

    def test_run_move_calls_agent_once_then_saves_before_return(self):
        a=agent();obs=observation();move=a.pending_moves(obs)[0];calls=[]
        def model(payload,schema):calls.append((payload,schema));return KnowledgeMoveCheck.model_validate(reply())
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"memory.json";receipt=a.run_move(model,move,obs,[],memory_path=path)
            self.assertTrue(receipt["check_complete"])
            self.assertEqual(json.loads(path.read_text()),a.state)
        self.assertEqual(len(calls),1)

    def test_learner_projection_excludes_free_agent_summary(self):
        a=agent();a.state["agent_memory"]["latest_move_summary"]="Untrusted extra knowledge."
        self.assertNotIn("agent_memory",a.project())
        self.assertNotIn("Untrusted extra knowledge",json.dumps(a.project()))

    def test_tentative_absence_is_not_a_positive_scope_or_proven_inability(self):
        case=deepcopy(CASE)
        case["initial_conceptual_state"]["knowledge_components"][1].update(
            status="tentative",statement="The connecting relation is not established by this Response.")
        a=KnowledgeModelAgent(case,owner_id="P7:one")
        self.assertEqual(a.state["components"][1]["available_knowledge"],[])
        a.initialize({"initial_state_summary":"Only labels are evidenced.","components":[
            {"component_id":"parts","status":"known","evidence_summary":"Labels.","remaining_uncertainty":""},
            {"component_id":"relation","status":"tentative","evidence_summary":"Not demonstrated.",
             "remaining_uncertainty":"The Response does not establish the relation."}]})
        projected=a.learner_projection()["components"][1]
        self.assertEqual(projected["status"],"tentative")
        self.assertEqual(projected["available_knowledge"],[])
        self.assertIn("does not establish",projected["evidence_uncertainty"])
        self.assertNotIn("statement",projected)

    def test_semantic_initialization_keeps_positive_partial_separate_from_uncertainty(self):
        case=deepcopy(CASE)
        case["initial_conceptual_state"]["knowledge_components"][0].update(status="tentative",
            statement="The Response labels parts but does not establish their relationship.")
        a=KnowledgeModelAgent(case,owner_id="P7:one")
        a.initialize({"initial_state_summary":"Labels only.","components":[
            {"component_id":"parts","status":"tentative","evidence_summary":"Labels.",
             "remaining_uncertainty":"The relation is not demonstrated.","positive_scopes":[positive_initial()]},
            {"component_id":"relation","status":"unlearned","evidence_summary":"No relation.",
             "remaining_uncertainty":"No evidence of the relation.","positive_scopes":[]}]},
            public_initial_context={"student_response_text":CASE["initial_explanation"]},require_current=True)
        component=a.state["components"][0]
        self.assertEqual(component["status"],"tentative")
        self.assertEqual(component["available_knowledge"][0]["statement"],"Can identify the two labeled parts.")
        self.assertEqual(component["available_knowledge"][0]["scope_id"],scope_id("parts","Can identify the two labeled parts."))
        self.assertEqual(len(component["available_knowledge"]),1)
        self.assertEqual(a.state["components"][1]["available_knowledge"],[])

    def test_initial_positive_scope_requires_actual_student_response_not_task_or_expertise(self):
        a=KnowledgeModelAgent(CASE,owner_id="P1:one")
        invented=positive_initial("Can solve the entire relationship.")
        invented["evidence"][0]["quote"]="Show the relationship between two parts."
        receipt=a.initialize({"initial_state_summary":"A claimed solution.","components":[
            {"component_id":"parts","status":"known","evidence_summary":"A claim.",
             "remaining_uncertainty":"", "positive_scopes":[invented]},
            {"component_id":"relation","status":"unlearned","evidence_summary":"No relation.",
             "remaining_uncertainty":"No evidence.","positive_scopes":[]}]},
             public_initial_context={"student_response_text":CASE["initial_explanation"]},require_current=True)
        self.assertEqual(a.state["components"][0]["available_knowledge"],[])
        self.assertTrue(receipt["warnings"])

    def test_current_initialization_rejects_missing_positive_scope_distinction(self):
        a=KnowledgeModelAgent(CASE,owner_id="P1:one")
        before=deepcopy(a.state)
        def model(payload,schema):
            return KnowledgeInitialization(initial_state_summary="Historical notes.",components=[
                {"component_id":"parts","status":"known","evidence_summary":"Labels.","remaining_uncertainty":""},
                {"component_id":"relation","status":"unlearned","evidence_summary":"No relation.","remaining_uncertainty":"Unknown."}])
        with self.assertRaisesRegex(KnowledgeAgentBoundaryError,"positive_scopes"):
            a.run_initialize(model,{"student_response_text":CASE["initial_explanation"]})
        self.assertEqual(a.state,before)

    def test_current_move_call_requires_interpretation_before_consuming_move(self):
        a=agent();obs=observation();move=a.pending_moves(obs)[0];before=deepcopy(a.state)
        historical=reply();historical.pop("current_turn")
        with self.assertRaisesRegex(KnowledgeAgentBoundaryError,"current_turn"):
            a.run_move(lambda payload,schema:KnowledgeMoveCheck.model_validate(historical),move,obs,[])
        self.assertEqual(a.state,before)

    def test_no_change_stores_interpreted_conditional_given_without_learning_a_method(self):
        a=agent();obs=observation("Starting at the first part, how could you express the relation?")
        move=a.pending_moves(obs)[0];r=reply();turn=r["current_turn"]
        turn.update(understood_request="Consider how to express the relation, beginning at the first part.",
            given_facts=[{"statement":"The first part is the supplied starting point.",
                          "evidence":[{"reference":"message:0","quote":"Starting at the first part"}]}],
            understood_propositions=[{"statement":"Use the supplied first part as this question's starting point.",
                                      "scope_refs":[],"given_fact_indices":[0]}])
        before=a.state["content_sha256"]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"memory.json"
            a.run_move(lambda payload,schema:KnowledgeMoveCheck.model_validate(r),move,obs,[],memory_path=path)
            saved=json.loads(path.read_text())
        self.assertEqual(saved["content_sha256"],before)
        self.assertEqual(saved["components"][1]["available_knowledge"],[])
        current=saved["current_turn"]
        self.assertEqual(current["given_facts"][0]["fact_id"],fact_id("message:0","The first part is the supplied starting point."))
        self.assertEqual(current["understood_propositions"][0]["given_fact_ids"],[current["given_facts"][0]["fact_id"]])
        self.assertEqual(current["response_permissions"]["answer_mode"],"clarification")
        self.assertEqual(saved["move_checks"][0]["current_turn"],current)

    def test_new_positive_update_is_resolved_to_exact_scope_before_learner_read(self):
        a=agent();obs=observation("A directed connection can show this relation.");move=a.pending_moves(obs)[0]
        r=reply(kind="concrete_hint",updates=[update()]);r["current_turn"].update(
            understood_request="Try the supplied local connection convention.",unresolved_relations=[],
            new_scope_update_indices=[0],understood_propositions=[{
                "statement":"A directed connection can express this local relation.",
                "scope_refs":["update:0"],"given_fact_indices":[]}],
            response_permissions={"answer_mode":"supported","can_attempt":True,"clarification_target":None})
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"memory.json"
            receipt=a.run_move(lambda payload,schema:KnowledgeMoveCheck.model_validate(r),move,obs,[],memory_path=path)
            saved=json.loads(path.read_text())
        expected=scope_id("relation",update()["statement"])
        self.assertEqual(saved["current_turn"]["relevant_scope_ids"],[expected])
        self.assertEqual(a.learner_projection()["current_turn"]["understood_propositions"][0]["scope_ids"],[expected])
        self.assertEqual(receipt["interpretation_warnings"],[])
        self.assertNotIn("update:0",json.dumps(a.learner_projection()))

    def test_component_id_and_rejected_update_do_not_unlock_requested_relation(self):
        a=agent();obs=observation();move=a.pending_moves(obs)[0]
        r=reply(updates=[update(quote=obs["messages"][0]["text"])])
        r["current_turn"].update(relevant_scope_ids=["parts","relation"],new_scope_update_indices=[0],
            understood_propositions=[{"statement":"The requested relation is fully understood.",
                                      "scope_refs":["update:0"],"given_fact_indices":[]}],
            response_permissions={"answer_mode":"supported","can_attempt":True,"clarification_target":None})
        receipt=a.check_move(move,r,observation=obs,history=[])
        self.assertTrue(receipt["interpretation_warnings"])
        self.assertEqual(a.state["current_turn"]["relevant_scope_ids"],[])
        self.assertEqual(a.state["current_turn"]["understood_propositions"],[])
        self.assertEqual(a.state["current_turn"]["response_permissions"]["answer_mode"],"clarification")
        self.assertEqual(a.state["components"][1]["available_knowledge"],[])

    def test_attempt_cannot_be_given_fact_or_proposition_scope(self):
        a=agent();obs=observation("What does your attempted connection mean?",2);move=a.pending_moves(obs)[0]
        provisional=update("attempt_record",refs=[{"reference":"action:1","quote":"I tried connecting the two parts."}],status="unlearned")
        r=reply("message:2",updates=[provisional]);r["current_turn"].update(
            new_scope_update_indices=[0],given_facts=[{"statement":"The attempt proves the relation.",
                "evidence":[{"reference":"action:1","quote":"I tried connecting the two parts."}]}],
            understood_propositions=[{"statement":"The attempt is correct.","scope_refs":["update:0"],"given_fact_indices":[0]}])
        receipt=a.check_move(move,r,observation=obs,history=[attempt()])
        self.assertEqual(len(a.state["components"][1]["attempted_beliefs"]),1)
        self.assertEqual(a.state["components"][1]["available_knowledge"],[])
        self.assertEqual(a.state["current_turn"]["given_facts"],[])
        self.assertEqual(a.state["current_turn"]["understood_propositions"],[])
        self.assertTrue(receipt["interpretation_warnings"])

    def test_actor_projection_keeps_semantic_content_without_raw_evidence_or_seed_prose(self):
        a=agent();obs=observation("An exact Teacher phrase: A directed connection can show this relation.")
        move=a.pending_moves(obs)[0];r=reply(kind="concrete_hint",updates=[update()])
        r["current_turn"]["given_facts"]=[{"statement":"A local convention was supplied.",
            "evidence":[{"reference":"message:0","quote":"An exact Teacher phrase"}]}]
        a.check_move(move,r,observation=obs,history=[])
        internal=json.dumps(a.project());projected=json.dumps(a.learner_projection())
        self.assertIn("An exact Teacher phrase",internal)
        for value in ["source_quotes","response_evidence","initial_statement","evidence_summary","An exact Teacher phrase"]:
            self.assertNotIn(value,projected)
        self.assertIn("A directed connection can express this local relation.",projected)

    def test_scope_identity_is_content_stable_but_not_whole_component_identity(self):
        a=agent();b=KnowledgeModelAgent(CASE,owner_id="P7:two")
        b.initialize(a.state["initialization"]["reply"])
        self.assertEqual(a.state["components"][0]["available_knowledge"][0]["scope_id"],
                         b.state["components"][0]["available_knowledge"][0]["scope_id"])
        self.assertNotEqual(scope_id("parts","Can identify the two labeled parts."),
                            scope_id("parts","Can explain the relation between the parts."))

    def test_scope_id_tampering_is_rejected_even_if_outer_digest_is_recomputed(self):
        a=agent();state=deepcopy(a.state)
        state["components"][0]["available_knowledge"][0]["scope_id"]="scope:invented"
        state["state_sha256"]=digest({key:value for key,value in state.items() if key!="state_sha256"})
        with self.assertRaisesRegex(KnowledgeAgentBoundaryError,"scope identity"):
            KnowledgeModelAgent(CASE,owner_id="P1:one",persisted=state)

    def test_v2_state_is_explicitly_rejected_instead_of_silently_resumed(self):
        state=deepcopy(agent().state);state["format"]="knowledge-model-agent-v2"
        with self.assertRaisesRegex(KnowledgeAgentBoundaryError,"state format"):
            KnowledgeModelAgent(CASE,owner_id="P1:one",persisted=state)

    def test_later_independent_confirmation_preserves_exact_scope_identity(self):
        a=agent();obs=observation("A directed connection can show this relation.")
        move=a.pending_moves(obs)[0]
        a.check_move(move,reply(kind="concrete_hint",updates=[update()]),observation=obs,history=[])
        original_id=a.state["components"][1]["available_knowledge"][0]["scope_id"]
        obs["messages"].append({"index":2,"role":"assistant","text":"That independent connection expresses the relation."})
        move=a.pending_moves(obs)[0]
        u=update("independent_application",refs=[
            {"reference":"message:2","quote":"That independent connection expresses the relation."},
            {"reference":"action:1","quote":"I tried connecting the two parts."}],status="known")
        receipt=a.check_move(move,reply("message:2","attempt_feedback",[u]),observation=obs,history=[attempt()])
        component=a.state["components"][1]
        self.assertEqual(component["status"],"known")
        self.assertEqual(len(component["available_knowledge"]),1)
        self.assertEqual(component["available_knowledge"][0]["scope_id"],original_id)
        self.assertEqual(component["available_knowledge"][0]["event_ids"],["message:0","message:2","action:1"])
        self.assertEqual(len(component["independent_evidence"]),1)
        self.assertEqual(len(receipt["accepted_updates"]),1)

    def test_invalid_interpretation_does_not_leave_unsaved_partial_update(self):
        a=agent();obs=observation("A directed connection can show this relation.");move=a.pending_moves(obs)[0]
        r=reply(kind="concrete_hint",updates=[update()]);r["current_turn"]["understood_request"]=" "
        before=deepcopy(a.state)
        with self.assertRaisesRegex(KnowledgeAgentBoundaryError,"request description"):
            a.check_move(move,r,observation=obs,history=[])
        self.assertEqual(a.state,before)

    def test_response_evidenced_initial_belief_stays_provisional_and_separate(self):
        case=deepcopy(CASE)
        case["initial_explanation"]="I think the second part causes the first."
        a=KnowledgeModelAgent(case,owner_id="P7:one")
        statement="The second part may cause the first."
        a.initialize({"initial_state_summary":"The Response proposes a causal direction.","components":[
            {"component_id":"parts","status":"known","evidence_summary":"Named parts.",
             "remaining_uncertainty":"", "positive_scopes":[],"provisional_beliefs":[]},
            {"component_id":"relation","status":"unlearned","evidence_summary":"Tentative causal claim.",
             "remaining_uncertainty":"Whether this direction is correct is not established.",
             "positive_scopes":[],"provisional_beliefs":[{"statement":statement,"evidence":[{
                 "source":"student_text","quote":case["initial_explanation"],"figure_index":None,
                 "observation":"The Response explicitly proposes the second-to-first direction."}]}]}]},
             public_initial_context={"student_response_text":case["initial_explanation"]},require_current=True)
        component=a.learner_projection()["components"][1]
        self.assertEqual(component["status"],"unlearned")
        self.assertEqual(component["available_knowledge"],[])
        self.assertEqual(component["provisional_beliefs"],[{"belief_id":belief_id("relation",statement),
            "statement":statement,"basis":"response_provisional_belief"}])


if __name__ == "__main__":
    unittest.main()
