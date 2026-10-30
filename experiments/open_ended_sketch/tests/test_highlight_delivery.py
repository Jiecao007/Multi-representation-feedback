"""Delivery regressions for the recorded PH_007 optional-visual failure.

The failed response below is copied from feedback_turn_d9aee9f386af4fc496743c1c54212e85.
All calls use typed local stubs. The original model artifacts remain unchanged.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'app'))

import feedback as F
from agent_types import EvaluationResult, TutorTurn
from learner_model import project_learner_model
from highlight_plan import selected_highlight
from test_three_agent_runtime import FakeClient, context
from test_three_agent_process_recovery import assessment, reply, submission, ISSUE


RECORDED_TUTOR = json.loads(r'''{
  "content": "Right—A₂ doesn’t measure all the current in its current position: L₁’s current bypasses it, so it measures only L₂’s branch current. Where could A₂ go so both branch currents pass through it?",
  "acknowledgment": "",
  "talk_moves": ["invite_elaboration_reasoning"],
  "issue_id": "a2_total_current",
  "stage": "thinking-dialogue",
  "focus_ids": ["a2", "wire_l2_a2", "wire_a2_l2", "left_junction", "right_junction"],
  "acknowledgment_ids": [],
  "visual_action": "none",
  "visual_delivery": "none",
  "mechanism_paths": [],
  "mechanism_condition": "",
  "edit_instruction": "",
  "next_step": "explain",
  "question_target": "Identify a common-path position for A₂ where current from both branches passes through it.",
  "progress": "other",
  "memory_updates": [],
  "move_evidence": {
    "revoice_need": "", "revoice_evidence": "", "clarification_need": "",
    "reflection_target": "", "reflection_evidence": "", "reflection_reference": "",
    "reflection_reference_source": "none", "reflection_need": "",
    "prior_knowledge_mode": "established", "prior_knowledge_connection": "",
    "prior_knowledge_evidence": "", "prior_knowledge_activation_evidence": "",
    "reasoning_gap": "Determine where A₂ must be placed so current from both parallel branches passes through it.",
    "readiness_evidence": "", "plan_mode": "invite"
  }
}''')


def recorded_reply(**changes):
    value = deepcopy(RECORDED_TUTOR)
    value.update(changes)
    return TutorTurn.model_validate(value)


class HighlightDeliveryTests(unittest.TestCase):
    def setUp(self):
        F.SESSIONS.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def handle(self, data, values):
        client = FakeClient(values)
        result = F.handle(data, client, self.directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
        return result, client

    def start(self, checked=True, evaluation=None, opening=None):
        first, _ = self.handle(submission(), [evaluation or assessment(), opening or reply(opening=True)])
        if checked:
            self.handle(dict(trigger='message', session_id=first['session_id'], message='Yes, that was my intention.'),
                        [reply()])
        return first['session_id']

    def state(self, sid):
        return F.SESSIONS[sid]['state']

    def message(self, sid, text="A2 didn't measure all of them?"):
        return dict(trigger='message', session_id=sid, message=text)

    def assert_no_visual(self, public):
        self.assertEqual(public['visual_action'], 'none')
        self.assertEqual(public['visual_delivery'], 'none')
        self.assertEqual(public['focus_ids'], [])
        self.assertEqual(public['acknowledgment_ids'], [])
        self.assertEqual(public['mechanism_paths'], [])

    def test_recorded_dormant_five_targets_deliver_the_original_text_in_one_tutor_call(self):
        sid = self.start()
        before = deepcopy(self.state(sid))
        candidate = recorded_reply()
        original = candidate.model_dump()
        self.assertEqual(len(candidate.content.split()), 32)
        public, client = self.handle(self.message(sid), [candidate])
        self.assertEqual(public['content'], RECORDED_TUTOR['content'])
        self.assertEqual(public['talk_move'], 'invite_elaboration_reasoning')
        self.assertEqual(public['stage'], 'thinking-dialogue')
        self.assertEqual(public['agents_called'], ['tutor'])
        self.assertEqual(len(client.calls), 1)
        self.assert_no_visual(public)
        self.assertEqual(self.state(sid)['version'], before['version'] + 1)
        self.assertEqual(self.state(sid)['current_issue_id'], before['current_issue_id'])
        self.assertEqual(self.state(sid)['learner_model'], before['learner_model'])
        self.assertEqual(self.state(sid)['committed'], before['committed'])
        self.assertEqual(self.state(sid)['consecutive_difficulties'], before['consecutive_difficulties'])
        self.assertEqual(candidate.model_dump(), original)
        folder = max(self.directory.glob('feedback_turn_*'), key=lambda p: p.stat().st_mtime_ns)
        self.assertTrue((folder / 'canonicalization.json').exists())
        self.assertFalse((folder / 'validation.json').exists())

    def test_invalid_active_visual_degrades_to_text_without_inventing_targets(self):
        for changes in (
            dict(visual_action='highlight', visual_delivery='automatic', focus_ids=['invented_wire']),
            dict(visual_action='highlight', visual_delivery='on-request'),
            dict(visual_action='trace', visual_delivery='automatic', focus_ids=['a2'],
                 mechanism_paths=[dict(label='Current route', steps=[dict(relation_id='invented_wire', direction='forward')])]),
        ):
            with self.subTest(changes=changes):
                sid = self.start()
                before = deepcopy(self.state(sid)['learner_model'])
                public, client = self.handle(self.message(sid), [recorded_reply(**changes)])
                self.assertEqual(public['content'], RECORDED_TUTOR['content'])
                self.assert_no_visual(public)
                self.assertEqual(len(client.calls), 1)
                self.assertEqual(self.state(sid)['learner_model'], before)

    def test_visual_cleanup_does_not_allow_an_initial_check_to_be_skipped(self):
        sid = self.start(checked=False)
        before = deepcopy(self.state(sid))
        client = FakeClient([recorded_reply()])
        with self.assertRaises(F.FeedbackError):
            F.handle(self.message(sid, 'Yes.'), client, self.directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
        self.assertEqual(self.state(sid), before)
        self.assertEqual(len(client.calls), 1)

    def test_visual_cleanup_does_not_grant_unproven_prior_knowledge(self):
        sid = self.start()
        before = deepcopy(self.state(sid))
        candidate = recorded_reply(talk_moves=['build_on_prior_knowledge'],
            move_evidence=dict(prior_knowledge_connection='Apply the common-path principle to this meter.',
                               prior_knowledge_evidence='I know all branch currents pass through the common path.'))
        client = FakeClient([candidate])
        with self.assertRaises(F.FeedbackError):
            F.handle(self.message(sid), client, self.directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
        self.assertEqual(self.state(sid), before)
        self.assertEqual(len(client.calls), 1)

    def test_visual_cleanup_does_not_make_an_invisible_edit_instruction_usable(self):
        sid = self.start()
        before = deepcopy(self.state(sid))
        candidate = recorded_reply(content='A₂ measures current in its own branch.',
                                  talk_moves=['provide_hints_guidance'],
                                  edit_instruction='Move A₂ to the common path.', next_step='revise')
        client = FakeClient([candidate])
        with self.assertRaises(F.FeedbackError):
            F.handle(self.message(sid, 'I need help.'), client, self.directory,
                     'evaluation-model', fast_dialogue_model='fast-tutor')
        self.assertEqual(self.state(sid), before)
        self.assertEqual(len(client.calls), 1)

    def planned_evaluation(self, **changes):
        first = assessment().strengths[0]
        plan = dict(feature=first.description, evidence=first.evidence,
                    focus_ids=list(first.focus_ids), related_issue_id=ISSUE,
                    selection_reason='A₁ provides a useful branch-current comparison for the A₂ issue.',
                    praise='Great job placing A₁ in series with L₁!',
                    question='Did you place it there to measure L₁’s current?')
        plan.update(changes)
        strengths = [first.model_dump(), dict(
            description='The switch is in the common path.',
            evidence='The switch lies in the path shared by both bulb branches.',
            focus_ids=['switch', 'wire_right_supply'])]
        return assessment(strengths=strengths, highlight_plan=plan), plan

    def test_evaluation_highlight_is_preserved_in_shared_memory_and_actual_tutor_input(self):
        evaluated, plan = self.planned_evaluation()
        candidate = reply(opening=True, acknowledgment=plan['praise'], content=plan['question'])
        public, client = self.handle(submission(), [evaluated, candidate])
        state = self.state(public['session_id'])
        self.assertEqual(state['learner_model']['evaluation']['result']['highlight_plan'], plan)
        projected = project_learner_model(state['learner_model'])
        self.assertEqual(projected['evaluation']['result']['highlight_plan'], plan)
        actual = context(client.calls[1])
        self.assertEqual(actual['opening_highlight']['praise'], plan['praise'])
        self.assertEqual(actual['opening_highlight']['question'], plan['question'])
        self.assertEqual(actual['opening_highlight']['focus_ids'], plan['focus_ids'])
        self.assertEqual(public['content'], plan['praise'] + ' ' + plan['question'])
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(public['agents_called'], ['evaluation', 'tutor'])

    def test_opening_schema_prevents_fast_tutor_selecting_a_different_strength(self):
        evaluated, plan = self.planned_evaluation()
        wrong = reply(opening=True,
                      acknowledgment='Great job putting the switch in the common path!',
                      content='Can you identify the shared junctions?',
                      focus_ids=['switch', 'wire_right_supply'],
                      acknowledgment_ids=['switch', 'wire_right_supply'])
        client = FakeClient([evaluated, wrong])
        with self.assertRaises(F.FeedbackError):
            F.handle(submission(), client, self.directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
        self.assertEqual(F.SESSIONS, {})
        self.assertEqual(len(client.calls), 2)
        schema = client.calls[1]['text_format'].model_json_schema()['properties']
        self.assertEqual(schema['acknowledgment'].get('const'), plan['praise'])
        self.assertEqual(schema['content'].get('const'), plan['question'])
        self.assertTrue(list(self.directory.glob('feedback_turn_*/validation.json')))

    def test_approved_opening_uses_evaluation_targets_even_if_tutor_supplies_the_switch(self):
        evaluated, plan = self.planned_evaluation()
        candidate = reply(opening=True, acknowledgment=plan['praise'], content=plan['question'],
                          focus_ids=['switch', 'wire_right_supply'],
                          acknowledgment_ids=['switch', 'wire_right_supply'])
        original = candidate.model_dump()
        public, client = self.handle(submission(), [evaluated, candidate])
        self.assertEqual(public['content'], plan['praise'] + ' ' + plan['question'])
        self.assertEqual(public['focus_ids'], plan['focus_ids'])
        self.assertEqual(public['acknowledgment_ids'], plan['focus_ids'])
        self.assertEqual(public['visual_action'], 'highlight')
        self.assertEqual(candidate.model_dump(), original)
        self.assertEqual(len(client.calls), 2)

    def test_regular_dialogue_after_the_selected_highlight_remains_one_tutor_call(self):
        evaluated, plan = self.planned_evaluation()
        sid = self.start(checked=False, evaluation=evaluated,
                         opening=reply(opening=True, acknowledgment=plan['praise'], content=plan['question']))
        before = deepcopy(self.state(sid)['learner_model'])
        public, client = self.handle(self.message(sid, 'Yes, A₁ measures L₁.'), [reply()])
        self.assertEqual(public['talk_move'], 'press_for_accuracy')
        self.assertEqual(public['stage'], 'inquiry')
        self.assertEqual(public['agents_called'], ['tutor'])
        self.assertEqual(len(client.calls), 1)
        self.assertFalse(context(client.calls[0]).get('opening_highlight'))
        self.assertEqual(self.state(sid)['learner_model'], before)

    def test_unsupported_selected_plan_falls_back_to_an_evidenced_feature_without_rewriting_evaluation(self):
        for changes in (dict(focus_ids=['invented_wire']), dict(related_issue_id='different_issue'),
                        dict(feature='The whole circuit is correct.')):
            with self.subTest(changes=changes):
                evaluated, _ = self.planned_evaluation(**changes)
                original = evaluated.model_dump()
                fallback = selected_highlight(original, submission()['scene'])
                self.assertEqual(fallback['source'], 'first_strength_fallback')
                self.assertTrue(fallback['bind_opening'])
                self.assertEqual(fallback['focus_ids'], ['a1', 'wire_a1_l1', 'l1'])
                self.assertEqual(fallback['feature'], evaluated.strengths[0].description)
                self.assertTrue(fallback['fallback_reason'])
                self.assertEqual(evaluated.model_dump(), original)

    def test_legacy_assessment_without_a_plan_remains_compatible_without_manufacturing_memory(self):
        evaluated = assessment()
        before = evaluated.model_dump()
        fallback = selected_highlight(before, submission()['scene'])
        self.assertEqual(fallback['source'], 'first_strength_fallback')
        self.assertFalse(fallback['bind_opening'])
        self.assertEqual(fallback['focus_ids'], evaluated.strengths[0].focus_ids)
        self.assertEqual(evaluated.model_dump(), before)
        first, client = self.handle(submission(), [evaluated, reply(opening=True)])
        self.assertEqual(first['content'], reply(opening=True).acknowledgment + ' ' + reply(opening=True).content)
        self.assertIsNone(self.state(first['session_id'])['learner_model']['evaluation']['result']['highlight_plan'])
        self.assertEqual(len(client.calls), 2)


if __name__ == '__main__':
    unittest.main()
