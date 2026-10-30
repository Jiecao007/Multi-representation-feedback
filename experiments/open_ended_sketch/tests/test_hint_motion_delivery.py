"""Offline delivery regression for the actual 2026-10-27 number-line Hint.

RECORDED_TUTOR preserves output_text from
app/runs/feedback_turn_ee6b9af03b044e5a808f4237551fa2ea/tutor.response.json.
RECORDED_INPUT retains the relevant task/issue/dialogue context from that run.
The same curated math-2 drawing is replayed with typed local model stubs;
historical run artifacts are neither required nor modified, and no API is called.
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
from interaction_contract import visible_edit_command, visible_edit_instruction
from test_three_agent_runtime import FakeClient, context
from test_tutor_visual_grounding import RECORDED_EVALUATION, initial_data


RECORDED_INPUT = {
    'source_id': 'math-2',
    'student_message': 'I need a hint.',
    'current_issue': {
        'id': 'model_card_addition', 'criterion': 'c2',
        'description': 'The model needs to show how the three signed card values combine, rather than only providing a labeled axis.',
        'evidence': 'No arithmetic movements or other addition representation appear. One valid sequence would connect 0, −6, 6, and 2.',
        'focus_ids': ['number_line_axis'],
    },
    'last_dialogue': {
        'student': '6',
        'tutor': 'You correctly found 6 after moving 12 steps right. From 6, which direction would the −4 card move you, and where would you land?',
        'talk_moves': ['invite_elaboration_reasoning'],
    },
    'interaction': {
        'intent': 'hint', 'process_phase': 'help', 'expected_stage': 'thinking-dialogue',
        'allowed_moves': ['provide_hints_guidance'], 'edit_enabled': False,
        'hint_turns_remaining': 2, 'consecutive_difficulties': 0,
    },
}

RECORDED_TUTOR = json.loads(r'''{
  "content": "For the −4 card, start at 6 and move four steps left. Which number do you reach?",
  "acknowledgment": "",
  "talk_moves": ["provide_hints_guidance"],
  "issue_id": "model_card_addition",
  "stage": "thinking-dialogue",
  "focus_ids": ["label_plus6", "label_minus4"],
  "acknowledgment_ids": [],
  "visual_action": "none", "visual_delivery": "none",
  "mechanism_paths": [], "mechanism_condition": "",
  "edit_instruction": "", "next_step": "explain",
  "question_target": "Determine where moving four steps left from 6 lands for the −4 card.",
  "progress": "other", "memory_updates": [],
  "move_evidence": {
    "revoice_need": "", "revoice_evidence": "", "clarification_need": "",
    "reflection_target": "", "reflection_evidence": "", "reflection_reference": "",
    "reflection_reference_source": "none", "reflection_need": "",
    "prior_knowledge_mode": "established", "prior_knowledge_connection": "",
    "prior_knowledge_evidence": "", "prior_knowledge_activation_evidence": "",
    "reasoning_gap": "", "readiness_evidence": "", "plan_mode": "invite"
  }
}''')


def recorded_tutor(**changes):
    value = deepcopy(RECORDED_TUTOR)
    value.update(changes)
    return TutorTurn.model_validate(value)


def assessment():
    # Reuse the same curated scene's three-criterion fixture, with this run's
    # exact active issue. Its second issue is retained as a priority-lock check.
    value = deepcopy(RECORDED_EVALUATION)
    value['missing_parts'][0] = deepcopy(RECORDED_INPUT['current_issue'])
    value['missing_parts'][1]['id'] = 'state_card_sum'
    return EvaluationResult.model_validate(value)


class VisibleEditMeaningTests(unittest.TestCase):
    def test_calculation_and_mental_response_changes_keep_the_drawing_view_only(self):
        for content in (
            RECORDED_TUTOR['content'],
            'Move four steps left.',
            'Start at 6 and move four steps left.',
            'For the −4 card, move 4 units left.',
            'Move twenty-four steps left.',
            'Move 1/2 unit left.',
            'Move 2.5 units right.',
            'Move 2e3 steps right.',
            'Move from 6 to 2.',
            'Move left from 6.',
            'Add these numbers.',
            'Add −6, 12, and −4.',
            'Change your explanation to describe that movement.',
            'Revise your reasoning about the final position.',
        ):
            with self.subTest(content=content):
                self.assertFalse(visible_edit_command(content))
                self.assertEqual(visible_edit_instruction(content), '')

    def test_actual_graphical_moves_are_detected_and_copied_exactly(self):
        for instruction in (
            'Move A₂ to the common path.',
            'Move the arrow four steps left.',
            'Move the endpoint to 2.',
            'For the −4 card, move the arrow four steps left.',
            'For the −4 card, draw an arrow from 6 to 2.',
            'For the −4 card, use Connect to draw an arrow from 6 to 2.',
        ):
            with self.subTest(instruction=instruction):
                content = instruction + ' What does that arrow represent?'
                self.assertTrue(visible_edit_command(content))
                self.assertEqual(visible_edit_instruction(content), instruction)

    def test_decimal_coordinates_remain_in_the_exact_visible_instruction(self):
        for instruction in (
            'Place the point at -2.5 on the number line.',
            'For this card, place the point at −2.5 on the number line.',
            'Draw an arrow from −2.5 to 1.5.',
        ):
            with self.subTest(instruction=instruction):
                self.assertTrue(visible_edit_command(instruction))
                self.assertEqual(visible_edit_instruction(instruction + ' What does it represent?'), instruction)

    def test_questions_and_hypotheticals_do_not_grant_edit_permission(self):
        for content in (
            'Could you move A₂ to the common path?',
            'Move A₂ to the common path?',
            'Imagine you move A₂ to the common path.',
            'Imagine the branches, and move A₂ into their common path.',
            'Suppose you draw an arrow from 6 to 2.',
            'If you move the endpoint, what changes?',
        ):
            with self.subTest(content=content):
                self.assertFalse(visible_edit_command(content))
                self.assertEqual(visible_edit_instruction(content), '')


class HintMotionDeliveryTests(unittest.TestCase):
    def setUp(self):
        F.SESSIONS.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def handle(self, data, replies):
        client = FakeClient(replies)
        public = F.handle(data, client, self.directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
        return public, client

    def state(self, sid):
        return F.SESSIONS[sid]['state']

    def message(self, sid, message, intent='dialogue'):
        return dict(trigger='message', session_id=sid, message=message, intent=intent)

    def start(self, checked=True):
        opening = recorded_tutor(
            acknowledgment='Nice work placing negative numbers to the left of zero!',
            content='Can you find −6 on your number line?',
            talk_moves=['recognize_strengths'], stage='recognition',
            focus_ids=['number_line_axis', 'label_minus10', 'label_zero', 'label_plus10'],
            acknowledgment_ids=['number_line_axis', 'label_minus10', 'label_zero', 'label_plus10'])
        first, _ = self.handle(initial_data(), [assessment(), opening])
        sid = first['session_id']
        if checked:
            self.handle(self.message(sid, 'Left of zero.'), [recorded_tutor(
                content='How does your current drawing show the three card additions?',
                talk_moves=['press_for_accuracy'], stage='inquiry')])
            last = RECORDED_INPUT['last_dialogue']
            self.handle(self.message(sid, last['student']), [recorded_tutor(
                content=last['tutor'], talk_moves=last['talk_moves'], stage='thinking-dialogue')])
        return sid

    def hint(self, sid, candidate=None):
        return self.handle(self.message(sid, RECORDED_INPUT['student_message'], 'hint'),
                           [candidate or recorded_tutor()])

    def test_exact_recorded_hint_delivers_once_without_reassessment_or_editing(self):
        sid = self.start()
        before = deepcopy(self.state(sid))
        candidate = recorded_tutor()
        original = candidate.model_dump()
        public, client = self.hint(sid, candidate)
        self.assertEqual(public['content'], RECORDED_TUTOR['content'])
        self.assertEqual(public['talk_moves'], ['provide_hints_guidance'])
        self.assertEqual(public['stage'], 'thinking-dialogue')
        self.assertEqual(public['current_issue_id'], RECORDED_INPUT['current_issue']['id'])
        self.assertEqual(public['agents_called'], ['tutor'])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]['model'], 'fast-tutor')
        self.assertFalse(public['evaluation_updated'])
        self.assertFalse(public['edit_enabled'])
        self.assertFalse(public['guidance_requires_edit'])
        self.assertEqual(public['guidance_instruction'], '')
        self.assertEqual(public['next_step'], 'explain')
        self.assertEqual(public['hint_turns_remaining'], 2)
        self.assertTrue(public['hint_request_pending'])
        self.assertEqual(public['visual_action'], 'none')
        self.assertEqual(public['focus_ids'], [])
        state = self.state(sid)
        self.assertEqual(state['version'], before['version'] + 1)
        self.assertEqual(state['guidance_count'], before['guidance_count'] + 1)
        self.assertEqual(state['current_issue_id'], before['current_issue_id'])
        self.assertEqual(state['learner_model'], before['learner_model'])
        self.assertEqual(state['committed'], before['committed'])
        self.assertEqual(candidate.model_dump(), original)
        actual = context(client.calls[0])
        self.assertEqual(actual['student_message'], RECORDED_INPUT['student_message'])
        self.assertEqual(actual['current_issue'], RECORDED_INPUT['current_issue'])
        for key, value in RECORDED_INPUT['interaction'].items():
            self.assertEqual(actual['interaction'][key], value, key)
        folder = max(self.directory.glob('feedback_turn_*'), key=lambda path: path.stat().st_mtime_ns)
        self.assertFalse((folder / 'validation.json').exists())

    def test_hint_cooldown_is_committed_once_and_rejected_repeat_makes_no_model_call(self):
        sid = self.start()
        self.hint(sid)
        before = deepcopy(self.state(sid))
        client = FakeClient([])
        with self.assertRaises(F.FeedbackError):
            F.handle(self.message(sid, 'I need a hint.', 'hint'), client, self.directory,
                     'evaluation-model', fast_dialogue_model='fast-tutor')
        self.assertEqual(client.calls, [])
        self.assertEqual(self.state(sid), before)

    def test_prefixed_and_decimal_graphical_hints_open_editing_with_the_exact_sentence(self):
        for instruction in (
            'For the −4 card, draw an arrow from 6 to 2.',
            'Place the point at −2.5 on the number line.',
        ):
            with self.subTest(instruction=instruction):
                sid = self.start()
                before = deepcopy(self.state(sid))
                public, client = self.hint(sid, recorded_tutor(content=instruction))
                self.assertEqual(public['content'], instruction)
                self.assertEqual(public['guidance_instruction'], instruction)
                self.assertTrue(public['edit_enabled'])
                self.assertTrue(public['guidance_requires_edit'])
                self.assertEqual(public['next_step'], 'revise')
                self.assertEqual(public['stage'], 'revision-planning')
                self.assertEqual(public['hint_turns_remaining'], 2)
                self.assertEqual(public['agents_called'], ['tutor'])
                self.assertEqual(len(client.calls), 1)
                self.assertEqual(self.state(sid)['learner_model'], before['learner_model'])
                self.assertEqual(self.state(sid)['committed'], before['committed'])

    def assert_rejected_unchanged(self, sid, data, candidate):
        before = deepcopy(self.state(sid))
        client = FakeClient([candidate])
        with self.assertRaises(F.FeedbackError):
            F.handle(data, client, self.directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(self.state(sid), before)

    def test_hint_does_not_allow_the_tutor_to_switch_to_a_lower_priority_issue(self):
        sid = self.start()
        self.assert_rejected_unchanged(sid, self.message(sid, 'I need a hint.', 'hint'),
                                       recorded_tutor(issue_id='state_card_sum'))

    def test_conceptual_hint_does_not_make_an_invisible_edit_instruction_usable(self):
        sid = self.start()
        self.assert_rejected_unchanged(sid, self.message(sid, 'I need a hint.', 'hint'),
            recorded_tutor(edit_instruction='Draw an arrow from 6 to 2.', next_step='revise'))

    def test_conceptual_motion_does_not_allow_the_initial_check_to_be_skipped(self):
        sid = self.start(checked=False)
        self.assert_rejected_unchanged(sid, self.message(sid, 'Left of zero.'), recorded_tutor(
            talk_moves=['invite_elaboration_reasoning'],
            move_evidence=dict(reasoning_gap='Determine the endpoint for the −4 card.')))

    def test_supporting_learning_still_requires_grounded_prior_knowledge_evidence(self):
        sid = self.start()
        self.assert_rejected_unchanged(sid, self.message(sid, 'Maybe left.'), recorded_tutor(
            talk_moves=['build_on_prior_knowledge'],
            move_evidence=dict(prior_knowledge_connection='Use the known negative-card direction.',
                               prior_knowledge_evidence='I already know negative cards move left.')))


if __name__ == '__main__':
    unittest.main()
