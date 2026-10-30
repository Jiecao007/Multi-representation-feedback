"""Offline regression for the real 2026-10-27 opening visual-ID failure.

The model's output_text JSON below is preserved from
app/runs/feedback_turn_acc60da10fb9411c899f7a7f871ffa20. The curated math-2
scene is byte-for-byte equivalent as JSON to that run's submitted scene.
Only local typed stubs run here; no model or transformation call is made.
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
from interaction_contract import canonical_tutor, validate_tutor
from test_three_agent_runtime import FakeClient, context, contract_types

RECORDED_EVALUATION = json.loads(r'''{
  "learning_goal": "Add positive and negative integers and represent their combined effect on a number line.",
  "task_summary": "David drew cards −6, 12, and −4 in the Integer Card Game. Find their sum and model the answer on a number line. The task figure provides a number-line scaffold labeled from −10 to 10.",
  "criteria": [
    {
      "criterion": "c1",
      "status": "developing",
      "level": "developing",
      "evidence": "A student-drawn axis, ticks, and integer labels provide a number-line setup, but no card operations or final answer are marked."
    },
    {
      "criterion": "c2",
      "status": "developing",
      "level": "developing",
      "evidence": "Negative labels lie left of zero and positive labels right, consistent with the scaffold. No movements connect the three card values to a resulting position."
    },
    {
      "criterion": "c3",
      "status": "not-yet-visible",
      "level": "not-yet-demonstrated",
      "evidence": "No sum, calculation, or explanation is submitted. The ordinary axis label 2 does not identify it as the answer."
    }
  ],
  "strengths": [
    {
      "description": "The student has prepared a number-line representation with negative and positive values on opposite sides of zero.",
      "evidence": "The drawing includes an axis with end arrowheads and ordered labels spanning −10 to 10, following the provided scaffold.",
      "focus_ids": [
        "number_line_axis",
        "label_minus10",
        "label_zero",
        "label_plus10"
      ]
    }
  ],
  "missing_parts": [
    {
      "id": "model_card_changes",
      "criterion": "c2",
      "description": "The model does not yet show how the signed card values change position: from 0, left 6, right 12, then left 4.",
      "evidence": "Only the number-line setup is visible; its end arrowheads are not arithmetic jumps.",
      "focus_ids": [
        "number_line_axis"
      ]
    },
    {
      "id": "identify_sum",
      "criterion": "c3",
      "description": "The sum of 2 needs to be identified as the result and connected to the calculation or number-line endpoint.",
      "evidence": "The explanation is empty, and no numerical answer or distinguished endpoint appears in the drawing.",
      "focus_ids": []
    }
  ],
  "uncertainties": [
    "The crowded label immediately left of zero is provisionally read as −1.",
    "Exact label-to-tick associations are unclear; uneven hand-drawn spacing alone does not establish a conceptual error."
  ],
  "revision_outcome": "not_reviewed",
  "revision_evidence": ""
}''')

RECORDED_TUTOR = json.loads(r'''{
  "content": "How does your number line show negative and positive values on opposite sides of zero?",
  "acknowledgment": "You’ve prepared a number line with ordered labels spanning −10 to 10, placing negative and positive values on opposite sides of zero.",
  "talk_moves": [
    "recognize_strengths"
  ],
  "issue_id": "model_card_changes",
  "stage": "recognition",
  "focus_ids": [
    "number_line_axis",
    "label_minus10",
    "label_zero",
    "label_plus10"
  ],
  "acknowledgment_ids": [
    "c1"
  ],
  "visual_action": "highlight",
  "visual_delivery": "automatic",
  "mechanism_paths": [],
  "mechanism_condition": "",
  "edit_instruction": "",
  "next_step": "explain",
  "question_target": "Have the student briefly explain how the number line places negative and positive values relative to zero.",
  "progress": "other",
  "memory_updates": []
}''')

SCENE = json.loads((HERE / 'results/curated_math_2/math-2.scene.json').read_text())
MANIFEST = json.loads((HERE / 'results/curated_math_2/math-2.input_manifest.json').read_text())
STRENGTH_IDS = RECORDED_EVALUATION['strengths'][0]['focus_ids']


def recorded_evaluation():
    return EvaluationResult.model_validate(deepcopy(RECORDED_EVALUATION))


def recorded_tutor(**changes):
    value = deepcopy(RECORDED_TUTOR)
    value.update(changes)
    return TutorTurn.model_validate(value)


def initial_data():
    return dict(trigger='submission', scene=deepcopy(SCENE), original_scene=deepcopy(SCENE),
                explanation='', task=MANIFEST['task'], goals=[], source_id=MANIFEST['id'],
                message='', edits=[])


def evaluated_state():
    state, _, _ = F.prepare(None, initial_data())
    state['learner_model']['evaluation'] = dict(result=deepcopy(RECORDED_EVALUATION))
    return state


class TutorVisualGroundingTests(unittest.TestCase):
    def setUp(self):
        F.SESSIONS.clear()

    def assert_visual_disabled(self, result, original):
        self.assertEqual(result.content, original.content)
        self.assertEqual(result.acknowledgment, original.acknowledgment)
        self.assertEqual(result.focus_ids, [])
        self.assertEqual(result.acknowledgment_ids, [])
        self.assertEqual(result.visual_action, 'none')
        self.assertEqual(result.visual_delivery, 'none')

    def test_real_reply_fails_for_criterion_id_then_uses_existing_strength_targets(self):
        state = evaluated_state()
        original = recorded_tutor()
        self.assertIn('existing submitted parts', validate_tutor(original, state, initial=True))
        repaired = canonical_tutor(original, state, initial=True)
        self.assertEqual(repaired.acknowledgment_ids, STRENGTH_IDS)
        self.assertEqual(validate_tutor(repaired, state, initial=True), '')

    def test_missing_or_known_criterion_only_ack_targets_use_same_supported_focus(self):
        state = evaluated_state()
        for ids in ([], ['c1'], ['c2', 'c3'], ['c1', STRENGTH_IDS[0]]):
            with self.subTest(acknowledgment_ids=ids):
                result = canonical_tutor(recorded_tutor(acknowledgment_ids=ids), state, initial=True)
                self.assertEqual(result.acknowledgment_ids, STRENGTH_IDS)
                self.assertEqual(result.focus_ids, STRENGTH_IDS)
                self.assertEqual(validate_tutor(result, state, initial=True), '')

    def test_unknown_or_mixed_ack_target_disables_visual_without_inventing_a_replacement(self):
        state = evaluated_state()
        for ids in (['c99'], ['invented_object'], ['c1', 'invented_object']):
            with self.subTest(acknowledgment_ids=ids):
                original = recorded_tutor(acknowledgment_ids=ids)
                self.assertTrue(validate_tutor(original, state, initial=True))
                result = canonical_tutor(original, state, initial=True)
                self.assert_visual_disabled(result, original)
                self.assertEqual(validate_tutor(result, state, initial=True), '')

    def test_unknown_focus_does_not_become_a_recognized_visual_target(self):
        state = evaluated_state()
        ids = [*STRENGTH_IDS[:3], 'invented_object']
        original = recorded_tutor(focus_ids=ids)
        result = canonical_tutor(original, state, initial=True)
        self.assert_visual_disabled(result, original)
        self.assertEqual(validate_tutor(result, state, initial=True), '')

    def test_existing_focus_without_strength_evidence_is_not_used_for_acknowledgment(self):
        state = evaluated_state()
        unsupported = next(item['id'] for item in SCENE['objects'] if item['id'] not in STRENGTH_IDS)
        for focus in ([unsupported], [*STRENGTH_IDS[:2], unsupported]):
            with self.subTest(focus_ids=focus):
                original = recorded_tutor(focus_ids=focus)
                result = canonical_tutor(original, state, initial=True)
                self.assert_visual_disabled(result, original)
                self.assertEqual(validate_tutor(result, state, initial=True), '')

    def test_mixed_acknowledgment_does_not_discard_an_unrelated_existing_target(self):
        state = evaluated_state()
        unsupported = next(item['id'] for item in SCENE['objects'] if item['id'] not in STRENGTH_IDS)
        ids = ['c1', unsupported]
        original = recorded_tutor(acknowledgment_ids=ids)
        result = canonical_tutor(original, state, initial=True)
        self.assert_visual_disabled(result, original)
        self.assertEqual(validate_tutor(result, state, initial=True), '')

    def test_opening_focus_must_be_covered_by_one_strength(self):
        state = evaluated_state()
        first, second = deepcopy(RECORDED_EVALUATION['strengths'][0]), deepcopy(RECORDED_EVALUATION['strengths'][0])
        first['focus_ids'], second['focus_ids'] = STRENGTH_IDS[:2], STRENGTH_IDS[2:]
        state['learner_model']['evaluation']['result']['strengths'] = [first, second]
        original = recorded_tutor()
        result = canonical_tutor(original, state, initial=True)
        self.assert_visual_disabled(result, original)
        self.assertEqual(validate_tutor(result, state, initial=True), '')

    def test_absent_strength_evidence_is_not_replaced_with_missing_part_focus(self):
        state = evaluated_state()
        state['learner_model']['evaluation']['result']['strengths'] = []
        # The same axis remains in missing_parts: that is not evidence of a strength.
        turn = recorded_tutor(focus_ids=['number_line_axis'])
        result = canonical_tutor(turn, state, initial=True)
        self.assert_visual_disabled(result, turn)
        self.assertEqual(validate_tutor(result, state, initial=True), '')

    def test_missing_formal_evaluation_does_not_invent_strength_grounding(self):
        state = evaluated_state()
        state['learner_model']['evaluation'] = None
        original = recorded_tutor()
        result = canonical_tutor(original, state, initial=True)
        self.assert_visual_disabled(result, original)
        self.assertEqual(validate_tutor(result, state, initial=True), '')

    def test_empty_focus_does_not_expand_to_every_known_strength(self):
        original = recorded_tutor(focus_ids=[])
        result = canonical_tutor(original, evaluated_state(), initial=True)
        self.assertEqual(result.focus_ids, [])
        self.assert_visual_disabled(result, original)

    def test_repair_preserves_model_reply_and_formal_evaluation_without_mutating_inputs(self):
        state = evaluated_state()
        turn = recorded_tutor()
        original_state = deepcopy(state)
        original_turn = turn.model_dump()
        result = canonical_tutor(turn, state, initial=True)
        self.assertIsNot(result, turn)
        self.assertEqual(turn.model_dump(), original_turn)
        self.assertEqual(state, original_state)
        expected = deepcopy(original_turn)
        expected['acknowledgment_ids'] = STRENGTH_IDS
        self.assertEqual(result.model_dump(), expected)

    def test_valid_explicit_acknowledgment_targets_are_preserved(self):
        state = evaluated_state()
        ids = list(reversed(STRENGTH_IDS))
        turn = recorded_tutor(acknowledgment_ids=ids)
        result = canonical_tutor(turn, state, initial=True)
        self.assertEqual(result.model_dump(), turn.model_dump())
        self.assertEqual(validate_tutor(result, state, initial=True), '')

    def test_noninitial_turn_does_not_borrow_strength_targets(self):
        state = evaluated_state()
        for ids in ([], ['c1']):
            with self.subTest(acknowledgment_ids=ids):
                turn = recorded_tutor(acknowledgment_ids=ids)
                result = canonical_tutor(turn, state, initial=False)
                if ids:
                    self.assert_visual_disabled(result, turn)
                    self.assertEqual(validate_tutor(result, state, initial=False), '')
                else:
                    self.assertEqual(result.model_dump(), turn.model_dump())

    def test_other_opening_move_does_not_borrow_strength_targets(self):
        turn = recorded_tutor(talk_moves=['press_for_accuracy'])
        result = canonical_tutor(turn, evaluated_state(), initial=True)
        self.assert_visual_disabled(result, turn)
        self.assertTrue(validate_tutor(result, evaluated_state(), initial=True))

    def test_actual_initial_input_and_outputs_deliver_in_exactly_two_calls(self):
        evaluation, turn = recorded_evaluation(), recorded_tutor()
        originals = (deepcopy(evaluation.model_dump()), deepcopy(turn.model_dump()))
        client = FakeClient([evaluation, turn])
        with tempfile.TemporaryDirectory() as directory:
            public = F.handle(initial_data(), client, directory, 'evaluation-model',
                              fast_dialogue_model='fast-tutor')
            self.assertEqual(len(client.calls), 2)
            self.assertEqual(contract_types(client), [EvaluationResult, TutorTurn])
            self.assertEqual(public['agents_called'], ['evaluation', 'tutor'])
            self.assertEqual(public['api_calls'], 2)
            self.assertEqual(public['acknowledgment_ids'], STRENGTH_IDS)
            self.assertEqual(public['focus_ids'], STRENGTH_IDS)
            self.assertEqual(public['highlight_ids'], STRENGTH_IDS)
            self.assertEqual(public['visual_action'], 'highlight')
            self.assertEqual(public['talk_move'], 'recognize_strengths')
            self.assertEqual(public['acknowledgment'], RECORDED_TUTOR['acknowledgment'])
            self.assertEqual(public['follow_up'], RECORDED_TUTOR['content'])
            self.assertEqual(context(client.calls[0])['submitted_work'],
                             dict(scene=SCENE, explanation='', edits=[]))
            state = F.SESSIONS[public['session_id']]['state']
            self.assertEqual(state['learner_model']['evaluation']['result'], evaluation.model_dump())
            self.assertEqual((evaluation.model_dump(), turn.model_dump()), originals)

    def test_unknown_visual_target_disables_optional_visual_without_a_model_rewrite(self):
        client = FakeClient([recorded_evaluation(), recorded_tutor(acknowledgment_ids=['invented_object'])])
        with tempfile.TemporaryDirectory() as directory:
            public = F.handle(initial_data(), client, directory, 'evaluation-model',
                              fast_dialogue_model='fast-tutor')
            self.assertEqual(len(client.calls), 2)
            self.assertEqual(public['content'], RECORDED_TUTOR['acknowledgment'] + ' ' + RECORDED_TUTOR['content'])
            self.assertEqual(public['visual_action'], 'none')
            self.assertEqual(public['focus_ids'], [])
            validations = list(Path(directory).glob('feedback_turn_*/validation.json'))
            self.assertEqual(validations, [])
            self.assertTrue(list(Path(directory).glob('feedback_turn_*/canonicalization.json')))


if __name__ == '__main__':
    unittest.main()
