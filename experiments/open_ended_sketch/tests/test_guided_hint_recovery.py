"""Concrete assistance replaces repeated abstract questions after help requests.

Typed local stubs exercise real routing, validation and persistence. No model calls.
"""
from copy import deepcopy
import tempfile
import unittest

from test_feedback import F, P, SCENE, FakeClient, assessment, reply, guidance
from test_fast_dialogue import input_context, turn


class GuidedHintRecoveryTests(unittest.TestCase):
    def setUp(self):
        F.SESSIONS.clear()

    def data(self):
        return dict(trigger='submission', scene=deepcopy(SCENE), original_scene=deepcopy(SCENE),
                    explanation='Food needs energy.', task='Explain the represented transfers.',
                    goals=[], message='', edits=[])

    def state(self, message='I do not know.', **changes):
        state, _, _ = F.prepare(None, self.data())
        state.update(version=4, progress_focus=['c3', 'o3'],
                     issue_check_focus=['c3', 'o3'], issue_check_started_at=1,
                     accuracy_focus=['c3', 'o3'], accuracy_started_at=1,
                     thinking_focus=['c3', 'o3'], thinking_started_at=2,
                     response_progress_focus=['c3', 'o3'], stage='thinking-dialogue',
                     _current_trigger='message', _current_message=message)
        state.update(changes)
        return state

    def prior_candidate(self, **changes):
        values = dict(talk_move='build_on_prior_knowledge',
                      prior_knowledge_connection='Apply the known energy need to the represented transfer.',
                      prior_knowledge_evidence='Food needs energy.',
                      current_response_outcome='not_applicable', outcome_evidence='I need a hint.')
        values.update(changes)
        return assessment(**values)

    def cue(self):
        instruction = 'The arrowhead identifies the receiving end of a transfer.'
        return reply(instruction + ' Which end of this connection receives it?', False,
                     guidance_instruction=instruction, question_purpose='develop_reasoning',
                     new_conceptual_information=[instruction])

    def concrete(self):
        instruction = 'For this one connection, follow its line toward the arrowhead to identify the receiving end.'
        return guidance(instruction, question_purpose='none', new_conceptual_information=[instruction])

    def checked_session(self, directory, hint_count=0):
        first = F.handle(self.data(), FakeClient([assessment(), reply()]), directory, 'offline-review')
        sid = first['session_id']
        state = F.SESSIONS[sid]['state']
        state.update(version=3, progress_focus=['c3', 'o3'],
                     issue_check_focus=['c3', 'o3'], issue_check_started_at=1,
                     accuracy_focus=['c3', 'o3'], accuracy_started_at=1,
                     thinking_focus=['c3', 'o3'], thinking_started_at=2,
                     response_progress_focus=['c3', 'o3'], stage='thinking-dialogue',
                     hint_count=hint_count, assessment=self.prior_candidate().model_dump())
        return sid

    def test_explicit_direct_help_is_recognized_without_waiting_for_three_failures(self):
        for message in ('please directly tell me', "i don't know, please directly tell me",
                        "i don' t know, please directly tell me", 'please tell me what to do',
                        'Please explain the first step', 'Please explain this', 'Tell me the answer',
                        'I need help', 'Please help me understand', 'Can you help me',
                        '请直接告诉我', '给我提示', '帮帮我'):
            with self.subTest(message=message):
                state = self.state(message)
                self.assertTrue(P.hint_requested(state, message))
                self.assertEqual(P.select_move(self.prior_candidate(), state, 'message', message),
                                 'provide_hints_guidance')

    def test_quotes_negations_and_mentions_do_not_request_help(self):
        for message in ('"please directly tell me"', '“I need a hint”',
                        "Please don't tell me what to do.", 'Do not explain the first step.',
                        'I do not want a hint.', 'The button says "I need a hint".',
                        'You told me to ask for a hint.', 'I needed a hint earlier.',
                        'My teacher asked for help.', "I don't need help."):
            with self.subTest(message=message):
                self.assertFalse(P.hint_requested(self.state(message), message))

    def test_direct_help_mode_is_distinct_from_a_regular_hint(self):
        for message in ('Please directly tell me.', 'Please tell me what to do.',
                        'Please explain the first step.', 'Please explain this.',
                        'Tell me the answer.', '请直接告诉我'):
            with self.subTest(message=message):
                self.assertTrue(P.direct_help_requested(message))
                policy = P.thinking_policy(assessment(), self.state(message), message, 'provide_hints_guidance')
                self.assertEqual(policy['guidance_question_mode'], 'direct_statement')
                self.assertEqual(policy['guidance_level'], 'concrete_step')
        self.assertFalse(P.direct_help_requested('I need a hint.'))
        self.assertFalse(P.direct_help_requested('Can you give me a hint?'))

    def test_current_uncertainty_gets_a_cue_even_if_cached_assessment_claims_no_difficulty(self):
        for message in ("I don't know.", 'still don’t know', 'I do not understand.',
                        'I am not sure.', '我不知道', '还是不会', '我不懂'):
            with self.subTest(message=message):
                a = self.prior_candidate(student_stuck=False)
                state = self.state(message)
                self.assertTrue(P.learner_uncertainty(a, state, message))
                self.assertEqual(P.select_move(a, state, 'message', message), 'provide_hints_guidance')
                policy = P.thinking_policy(a, state, message, 'provide_hints_guidance')
                self.assertTrue(policy['hint_allowed'])
                self.assertEqual(policy['assistance_reason'], 'learner_uncertainty')
                self.assertEqual(policy['guidance_level'], 'focused_cue')
                self.assertEqual(policy['guidance_question_mode'], 'focused_application')
                self.assertFalse(policy['frustration_present'])

    def test_uncertainty_needs_a_current_same_issue_and_learning_contribution(self):
        message = 'I do not know.'
        for a, state in ((assessment(progress_status='new'), self.state(message)),
                         (assessment(focus_id='o1'), self.state(message)),
                         (assessment(), self.state(message, progress_focus=[])),
                         (assessment(), self.state(message, _current_trigger='submission')),
                         (assessment(), self.state(message, intent='begin_revision'))):
            with self.subTest(focus=a.focus_id, status=a.progress_status,
                              trigger=state['_current_trigger'], intent=state['intent']):
                self.assertFalse(P.learner_uncertainty(a, state, message))
        for message in ('"I do not know"', 'The label says "I don\'t know".',
                        'I do know what the arrow means.', 'I am not sure the save completed.'):
            with self.subTest(message=message):
                self.assertFalse(P.learner_uncertainty(assessment(), self.state(message), message))

    def test_unsuccessful_hint_gets_a_more_concrete_step_on_the_same_issue(self):
        message = "still don't know"
        state = self.state(message, hint_count=1)
        policy = P.thinking_policy(self.prior_candidate(), state, message, 'provide_hints_guidance')
        self.assertEqual(policy['prior_guidance_count'], 1)
        self.assertEqual(policy['guidance_level'], 'concrete_step')
        self.assertEqual(P.select_move(self.prior_candidate(), state, 'message', message), 'provide_hints_guidance')
        changed = self.prior_candidate(focus_id='o1', progress_status='new')
        self.assertEqual(P.thinking_policy(changed, state, message, 'provide_hints_guidance')['prior_guidance_count'], 0)

    def test_regular_hint_can_include_real_help_and_one_small_application_question(self):
        message = 'I need a hint.'
        state = self.state(message, intent='hint')
        ids = {o['id'] for o in SCENE['objects']} | {r['id'] for r in SCENE['relations']}
        self.assertFalse(F.reply_problem(self.cue(), state, assessment(), ids, 'message', '', 'provide_hints_guidance'))
        question_only = reply('How could that idea help you here?', False, question_purpose='develop_reasoning')
        self.assertTrue(F.reply_problem(question_only, state, assessment(), ids, 'message', '', 'provide_hints_guidance'))

    def test_direct_request_receives_a_statement_instead_of_another_quiz(self):
        message = 'Please directly tell me.'
        state = self.state(message)
        ids = {o['id'] for o in SCENE['objects']} | {r['id'] for r in SCENE['relations']}
        self.assertFalse(F.reply_problem(self.concrete(), state, assessment(), ids, 'message', '', 'provide_hints_guidance'))
        self.assertTrue(F.reply_problem(self.cue(), state, assessment(), ids, 'message', '', 'provide_hints_guidance'))

    def test_first_uncertainty_receives_a_cue_and_a_small_question(self):
        state = self.state()
        ids = {o['id'] for o in SCENE['objects']} | {r['id'] for r in SCENE['relations']}
        self.assertFalse(F.reply_problem(self.cue(), state, assessment(), ids, 'message', '', 'provide_hints_guidance'))
        self.assertTrue(F.reply_problem(self.concrete(), state, assessment(), ids, 'message', '', 'provide_hints_guidance'))
        state['hint_count'] = 1
        self.assertFalse(F.reply_problem(self.concrete(), state, assessment(), ids, 'message', '', 'provide_hints_guidance'))

    def test_assistance_keeps_one_bounded_teaching_point_and_full_solution_off(self):
        message = 'Please explain the first step.'
        state = self.state(message)
        a = assessment()
        limits = P.disclosure_policy(a, state, message, 'provide_hints_guidance')
        self.assertEqual(limits['max_new_conceptual_steps'], 1)
        self.assertFalse(limits['full_solution_allowed'])
        ids = {o['id'] for o in SCENE['objects']} | {r['id'] for r in SCENE['relations']}
        partial = self.concrete()
        self.assertFalse(F.reply_problem(partial, state, a, ids, 'message', '', 'provide_hints_guidance'))
        partial.new_conceptual_information.append('Then change the next relationship to complete the diagram.')
        self.assertTrue(F.reply_problem(partial, state, a, ids, 'message', '', 'provide_hints_guidance'))

    def test_refresh_current_response_removes_stale_help_and_frustration_evidence(self):
        message = "still don't know"
        state = self.state(message)
        a = self.prior_candidate(frustration_evidence='I was frustrated earlier.', student_stuck=False)
        P.refresh_response_evidence(a, state, message)
        self.assertEqual(a.current_response_outcome, 'unsuccessful')
        self.assertEqual(a.outcome_evidence, message)
        self.assertTrue(a.student_stuck)
        self.assertEqual(a.frustration_evidence, '')
        for message in ('I need a hint.', 'Please directly tell me.'):
            with self.subTest(message=message):
                a = self.prior_candidate(current_response_outcome='unsuccessful', outcome_evidence='old wrong answer')
                P.refresh_response_evidence(a, self.state(message), message)
                self.assertEqual(a.current_response_outcome, 'not_applicable')
                self.assertEqual(a.outcome_evidence, '')
        message = 'I am inspecting the arrow.'
        a = self.prior_candidate(current_response_outcome='successful', outcome_evidence='old correct answer')
        P.refresh_response_evidence(a, self.state(message), message)
        self.assertEqual(a.current_response_outcome, 'uncertain')
        self.assertEqual(a.outcome_evidence, '')

    def test_uncertainty_counts_once_even_when_model_carried_stale_outcome(self):
        message = "still don't know"
        state = self.state(message)
        a = self.prior_candidate()
        self.assertEqual(P.guidance_progress(a, state, message)['unsuccessful_responses'], 1)
        self.assertFalse(P.guidance_progress(a, state, message)['automatic_guidance_due'])
        P.record_response_progress(a, state, message)
        P.record_response_progress(a, state, message)
        self.assertEqual(state['unsuccessful_response_count'], 1)
        state['version'] += 1
        P.record_response_progress(a, state, message)
        self.assertEqual(state['unsuccessful_response_count'], 2)

    def test_closure_and_explicit_revision_still_have_priority(self):
        message = 'I do not know.'
        self.assertEqual(P.select_move(assessment(closing_requested=True), self.state(message), 'message', message),
                         'invite_dialogue')
        self.assertEqual(P.select_move(assessment(), self.state(message, intent='begin_revision'), 'message', message),
                         'propose_revision_plan')

    def test_full_and_fast_paths_keep_the_useful_guidance_instead_of_rewriting_to_prior(self):
        for fast in (False, True):
            for message in ("still don't know", "i don't know, please directly tell me"):
                with self.subTest(fast=fast, message=message), tempfile.TemporaryDirectory() as directory:
                    sid = self.checked_session(directory, hint_count=1)
                    candidate = self.prior_candidate()
                    r = self.concrete()
                    values = [turn(candidate, r, 'provide_hints_guidance')] if fast else [candidate, r]
                    client = FakeClient(values)
                    options = dict(fast_dialogue_model='offline-fast') if fast else {}
                    public = F.handle(dict(trigger='message', session_id=sid, message=message), client,
                                      directory, 'offline-review', **options)
                    self.assertEqual(public['talk_move'], 'provide_hints_guidance')
                    self.assertEqual(public['content'], r.content)
                    self.assertEqual(len(client.calls), 1 if fast else 2, 'Useful guidance must not be rewritten to prior knowledge.')
                    self.assertFalse(public['edit_enabled'])
                    saved = F.SESSIONS[sid]['state']['assessment']
                    self.assertNotEqual(saved['outcome_evidence'], 'I need a hint.')
                    self.assertEqual(saved['talk_moves'], ['provide_hints_guidance'])
                    if not fast:
                        policy = input_context(client.calls[1])['thinking_policy']
                        self.assertEqual(policy['guidance_level'], 'concrete_step')

    def test_hint_button_interval_does_not_block_followup_learning_help(self):
        with tempfile.TemporaryDirectory() as directory:
            sid = self.checked_session(directory)
            hint = F.handle(dict(trigger='message', session_id=sid, intent='hint', message='I need a hint.'),
                            FakeClient([assessment(), self.cue()]), directory, 'offline-review')
            self.assertEqual(hint['hint_turns_remaining'], 2)
            with self.assertRaisesRegex(F.FeedbackError, '2 more turns'):
                F.handle(dict(trigger='message', session_id=sid, intent='hint', message='I need a hint.'),
                         FakeClient([]), directory, 'offline-review')
            follow = F.handle(dict(trigger='message', session_id=sid, message='Please directly tell me.'),
                              FakeClient([self.prior_candidate(), self.concrete()]), directory, 'offline-review')
            self.assertEqual(follow['talk_move'], 'provide_hints_guidance')
            self.assertEqual(follow['hint_turns_remaining'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
