"""Offline process and edit-delivery regressions for the PH_007 tutor failure.

The circuit is the curated example used in the 2026-10-27 user trial. The long
failed reply and its local instruction below retain the recorded wording from
feedback_turn_55715528651a4ec78e9e5eea172f9a22. Typed local stubs make every
agent call observable; these checks do not contact a model or run a learner.
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
from test_three_agent_runtime import FakeClient, context

FIXTURE = HERE / 'results/curated_ph007_ans_02'
SCENE = json.loads((FIXTURE / 'PH_007_ans_02.scene.json').read_text())
TASK = json.loads((FIXTURE / 'PH_007_ans_02.input_manifest.json').read_text())['task']
ISSUE = 'a2_total_current'
LOCAL_INSTRUCTION = (
    'For example, place it on the wire from the right junction back toward the '
    'switch, where current from both bulbs has rejoined.'
)
FAILED_ACKNOWLEDGMENT = (
    'You’ve identified that A₂ is currently on the L₂ branch; the remaining '
    'challenge is finding a path shared by both bulbs.'
)
FAILED_CONTENT = (
    'A₂ must be on one shared path, not just on L₂’s branch. '
    + LOCAL_INSTRUCTION + ' Which branch currents would pass through A₂ there?'
)


def assessment(**changes):
    value = dict(
        learning_goal='Distinguish branch current from total current.',
        criteria=[dict(criterion='c1', status='developing', level='developing',
                       evidence='A₁ is in series with L₁; A₂ is on the L₂ branch.')],
        strengths=[dict(description='A₁ is correctly placed to measure L₁ current.',
                        evidence='A₁ and L₁ lie on the same unbranched path.',
                        focus_ids=['a1', 'wire_a1_l1', 'l1'])],
        missing_parts=[dict(id=ISSUE, criterion='c1',
                            description='A₂ needs to measure both branches’ total current.',
                            evidence='The L₁ branch bypasses A₂.',
                            focus_ids=['a2', 'wire_a2_l2', 'l2'])],
    )
    value.update(changes)
    return EvaluationResult(**value)


def reply(opening=False, **changes):
    value = dict(
        content='Did you place it there to measure L₁’s current?' if opening
                else 'Which current does A₂ measure in its current position?',
        acknowledgment='Nice work placing A₁ in series with L₁!' if opening else '',
        talk_moves=['recognize_strengths'] if opening else ['press_for_accuracy'],
        issue_id=ISSUE, stage='recognition' if opening else 'inquiry',
        focus_ids=['a1', 'wire_a1_l1', 'l1'] if opening else ['a2', 'wire_a2_l2', 'l2'],
        acknowledgment_ids=['a1', 'wire_a1_l1', 'l1'] if opening else [],
        visual_action='highlight', visual_delivery='automatic',
        edit_instruction='', next_step='explain',
        question_target='Identify which current A₂ measures.',
    )
    value.update(changes)
    return TutorTurn(**value)


def submission():
    return dict(trigger='submission', scene=deepcopy(SCENE), original_scene=deepcopy(SCENE),
                explanation='', task=TASK, goals=['Measure branch and total current.'],
                source_id='sketchjudge-ph007', message='', edits=[])


class ThreeAgentProcessRecoveryTests(unittest.TestCase):
    def setUp(self):
        F.SESSIONS.clear()

    def handle(self, data, client, directory):
        return F.handle(data, client, directory, 'evaluation-model', fast_dialogue_model='fast-tutor')

    def start(self, directory):
        client = FakeClient([assessment(), reply(opening=True)])
        return self.handle(submission(), client, directory), client

    def state(self, sid):
        return F.SESSIONS[sid]['state']

    def help_data(self, sid, **changes):
        value = dict(trigger='message', session_id=sid, intent='hint', message='I need a hint.')
        value.update(changes)
        return value

    def test_short_warm_opening_is_delivered_unchanged_in_two_agent_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            public, client = self.start(directory)
            self.assertEqual(public['content'], reply(opening=True).acknowledgment + ' ' + reply(opening=True).content)
            self.assertLessEqual(len(public['content'].split()), 30)
            self.assertEqual(public['content'].count('?'), 1)
            self.assertEqual(public['stage'], 'recognition')
            self.assertEqual(public['agents_called'], ['evaluation', 'tutor'])
            self.assertEqual(len(client.calls), 2)

    def test_normal_confirmation_prompts_check_and_keeps_check_stage_in_one_call(self):
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory)
            sid = first['session_id']
            before = deepcopy(self.state(sid)['learner_model']['evaluation'])
            candidate = reply(stage='inquiry')
            client = FakeClient([candidate])
            public = self.handle(dict(trigger='message', session_id=sid,
                                      message='Yes, A₁ measures L₁ current.'), client, directory)
            process = context(client.calls[0])['interaction']
            self.assertEqual(process['expected_stage'], 'inquiry')
            self.assertIn('press_for_accuracy', process['allowed_moves'])
            self.assertNotIn('invite_elaboration_reasoning', process['allowed_moves'])
            self.assertEqual(public['stage'], 'inquiry')
            self.assertEqual(public['talk_moves'], ['press_for_accuracy'])
            self.assertEqual(public['content'], candidate.content)
            self.assertEqual(self.state(sid)['learner_model']['evaluation'], before)
            self.assertEqual(public['agents_called'], ['tutor'])
            self.assertEqual(len(client.calls), 1)

            support = FakeClient([reply(content='Why does the L₁ branch bypass A₂?',
                                        talk_moves=['invite_elaboration_reasoning'],
                                        stage='thinking-dialogue')])
            follow = self.handle(dict(trigger='message', session_id=sid,
                                      message='A₂ only measures L₂ current.'), support, directory)
            self.assertEqual(context(support.calls[0])['interaction']['expected_stage'], 'thinking-dialogue')
            self.assertEqual(follow['stage'], 'thinking-dialogue')
            self.assertEqual(follow['agents_called'], ['tutor'])
            self.assertEqual(len(support.calls), 1)

    def test_meaning_check_after_highlight_retains_separate_revoice_and_clarification(self):
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory)
            client = FakeClient([reply(content='You mean A₁ belongs to that bulb. Which bulb do you mean?',
                                       talk_moves=['revoice', 'ask_for_clarification'],
                                       stage='inquiry',
                                       move_evidence=dict(revoice_need='Check the intended meter-to-bulb relation.',
                                                          revoice_evidence='It belongs to that bulb.',
                                                          clarification_need='Identify the bulb that that bulb refers to.'))])
            public = self.handle(dict(trigger='message', session_id=first['session_id'],
                                      message='It belongs to that bulb.'), client, directory)
            self.assertEqual(public['stage'], 'inquiry')
            self.assertEqual(public['talk_moves'], ['revoice', 'ask_for_clarification'])
            self.assertEqual(public['agents_called'], ['tutor'])

    def test_button_hint_or_frustration_can_bypass_initial_check_without_reassessment(self):
        for changes in ({'intent': 'hint', 'message': 'I need a hint.'},
                        {'message': 'I am frustrated.', 'intent': 'dialogue'}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                first, _ = self.start(directory)
                client = FakeClient([reply(content='The current must pass through an ammeter for it to be measured.',
                                           talk_moves=['provide_hints_guidance'],
                                           stage='thinking-dialogue')])
                public = self.handle(self.help_data(first['session_id'], **changes), client, directory)
                self.assertEqual(public['stage'], 'thinking-dialogue')
                self.assertEqual(public['talk_moves'], ['provide_hints_guidance'])
                self.assertEqual(public['agents_called'], ['tutor'])
                self.assertFalse(public['evaluation_updated'])
                self.assertEqual(len(client.calls), 1)

    def test_actual_revision_review_returns_to_support_instead_of_new_highlight_or_check(self):
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory)
            sid = first['session_id']
            F.begin_revision(dict(session_id=sid))
            changed = deepcopy(SCENE)
            changed['objects'][0]['label'] = 'Relabeled battery'
            review = FakeClient([
                assessment(revision_outcome='unsuccessful',
                           revision_evidence='The battery label changed; A₂ remains on the L₂ branch.'),
                reply(content='A₂ remains on the L₂ branch. Which wire carries current from both bulbs?',
                      talk_moves=['invite_elaboration_reasoning'], stage='thinking-dialogue'),
            ])
            public = self.handle(dict(trigger='workspace-complete', session_id=sid, scene=changed,
                                      explanation='', edits=[]), review, directory)
            process = context(review.calls[1])['interaction']
            self.assertEqual(process['expected_stage'], 'thinking-dialogue')
            self.assertIn('invite_elaboration_reasoning', process['allowed_moves'])
            self.assertEqual(public['stage'], 'thinking-dialogue')
            self.assertEqual(public['agents_called'], ['evaluation', 'tutor'])
            self.assertEqual(public['drawing_version'], 2)
            self.assertEqual(len(review.calls), 2)

    def test_missing_edit_field_uses_exact_visible_instruction_and_opens_editing(self):
        candidate = reply(content=LOCAL_INSTRUCTION, talk_moves=['provide_hints_guidance'],
                          stage='thinking-dialogue', question_target='',
                          focus_ids=['right_junction', 'wire_right_supply', 'switch', 'a2'])
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory)
            sid = first['session_id']
            before = deepcopy(self.state(sid))
            client = FakeClient([candidate])
            public = self.handle(self.help_data(sid), client, directory)
            self.assertEqual(public['content'], LOCAL_INSTRUCTION)
            self.assertEqual(public['guidance_instruction'], LOCAL_INSTRUCTION)
            self.assertTrue(public['edit_enabled'])
            self.assertEqual(public['next_step'], 'revise')
            self.assertEqual(public['stage'], 'revision-planning')
            self.assertEqual(self.state(sid)['committed'], before['committed'])
            self.assertEqual(self.state(sid)['learner_model']['evaluation'], before['learner_model']['evaluation'])
            self.assertEqual(public['agents_called'], ['tutor'])
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(candidate.edit_instruction, '')
            log = next(Path(directory).glob('feedback_turn_*/canonicalization.json'))
            changed_fields = {change['field'] for change in json.loads(log.read_text())['changes']}
            self.assertEqual(changed_fields, {'edit_instruction', 'next_step', 'stage'})

    def test_paraphrased_edit_field_is_replaced_only_by_visible_local_instruction(self):
        candidate = reply(content=LOCAL_INSTRUCTION, talk_moves=['provide_hints_guidance'],
                          stage='thinking-dialogue', question_target='',
                          edit_instruction='Move A₂ to a shared wire.',
                          focus_ids=['right_junction', 'wire_right_supply', 'switch', 'a2'])
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory)
            client = FakeClient([candidate])
            public = self.handle(self.help_data(first['session_id']), client, directory)
            self.assertEqual(public['guidance_instruction'], LOCAL_INSTRUCTION)
            self.assertEqual(public['content'], LOCAL_INSTRUCTION)
            self.assertEqual(len(client.calls), 1)

    def test_conceptual_hint_or_edit_question_does_not_open_editing(self):
        for content in ('A₂ measures the current through its own branch.',
                        'Where could you move A₂ so both branch currents pass through it?'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                first, _ = self.start(directory)
                client = FakeClient([reply(content=content, talk_moves=['provide_hints_guidance'],
                                           stage='thinking-dialogue')])
                public = self.handle(self.help_data(first['session_id']), client, directory)
                self.assertEqual(public['guidance_instruction'], '')
                self.assertFalse(public['edit_enabled'])
                self.assertEqual(public['content'], content)
                self.assertEqual(len(client.calls), 1)

    def test_recorded_long_reply_stays_rejected_after_mechanical_edit_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory)
            sid = first['session_id']
            before = deepcopy(self.state(sid))
            candidate = reply(content=FAILED_CONTENT, acknowledgment=FAILED_ACKNOWLEDGMENT,
                              talk_moves=['provide_hints_guidance'], stage='thinking-dialogue',
                              focus_ids=['right_junction', 'wire_right_supply', 'switch', 'a2'],
                              acknowledgment_ids=['a2', 'wire_a2_l2', 'l2'])
            self.assertEqual(len((candidate.acknowledgment + ' ' + candidate.content).split()), 63)
            client = FakeClient([candidate])
            with self.assertRaises(F.FeedbackError):
                self.handle(self.help_data(sid), client, directory)
            self.assertEqual(self.state(sid), before)
            self.assertEqual(len(client.calls), 1)
            validation = next(Path(directory).glob('feedback_turn_*/validation.json'))
            self.assertIn('45', json.loads(validation.read_text())['problem'])

    def test_edit_recovery_with_unknown_optional_visual_still_opens_the_visible_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory)
            sid = first['session_id']
            before = deepcopy(self.state(sid))
            candidate = reply(content=LOCAL_INSTRUCTION, talk_moves=['provide_hints_guidance'],
                              stage='thinking-dialogue', focus_ids=['invented_wire'])
            client = FakeClient([candidate])
            public = self.handle(self.help_data(sid), client, directory)
            self.assertEqual(public['content'], LOCAL_INSTRUCTION)
            self.assertEqual(public['guidance_instruction'], LOCAL_INSTRUCTION)
            self.assertTrue(public['edit_enabled'])
            self.assertEqual(public['visual_action'], 'none')
            self.assertEqual(public['focus_ids'], [])
            self.assertEqual(self.state(sid)['committed'], before['committed'])
            self.assertEqual(self.state(sid)['learner_model'], before['learner_model'])
            self.assertEqual(len(client.calls), 1)

    def test_exact_instruction_recovery_does_not_mutate_source_turn_or_formal_assessment(self):
        state, _, _ = F.prepare(None, submission())
        state['learner_model']['evaluation'] = dict(result=assessment().model_dump())
        candidate = reply(content=LOCAL_INSTRUCTION, talk_moves=['provide_hints_guidance'],
                          stage='thinking-dialogue')
        original_state, original_turn = deepcopy(state), candidate.model_dump()
        repaired = canonical_tutor(candidate, state)
        self.assertEqual(repaired.edit_instruction, LOCAL_INSTRUCTION)
        self.assertEqual(repaired.content, candidate.content)
        self.assertEqual(candidate.model_dump(), original_turn)
        self.assertEqual(state, original_state)
        self.assertEqual(validate_tutor(repaired, state), '')


if __name__ == '__main__':
    unittest.main()
