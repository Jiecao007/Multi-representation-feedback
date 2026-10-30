"""Three grounded unsuccessful learner responses, or expressed frustration.

Typed local stubs only: no network, browser, or paid model calls.
"""
from copy import deepcopy
import tempfile
import unittest

from test_feedback import F, P, FakeClient, SCENE, assessment, reply, guidance


class GuidanceTriggerTests(unittest.TestCase):
    def setUp(self):
        F.SESSIONS.clear()

    def data(self, **changes):
        value = dict(trigger='submission', scene=deepcopy(SCENE), original_scene=deepcopy(SCENE),
                     explanation='Food needs energy.', task='Explain the represented transfers.',
                     goals=[], message='', edits=[])
        value.update(changes)
        return value

    def state(self, count=0, message='I think the arrow should end at twelve.'):
        state, _, _ = F.prepare(None, self.data())
        state, _, _ = F.prepare(state, dict(trigger='message', message=message))
        state.update(progress_focus=['c3', 'o3'], accuracy_focus=['c3', 'o3'], accuracy_started_at=1,
                     response_progress_focus=['c3', 'o3'], unsuccessful_response_count=count)
        return state

    def unsuccessful(self, message='I think the arrow should end at twelve.', **changes):
        values = dict(current_response_outcome='unsuccessful', outcome_evidence=message,
                      talk_move='invite_elaboration_reasoning')
        values.update(changes)
        return assessment(**values)

    def test_first_two_failures_do_not_trigger_and_third_does_on_current_response(self):
        message = 'I think the arrow should end at twelve.'
        for prior_count in (0, 1, 2):
            with self.subTest(prior_count=prior_count):
                state = self.state(prior_count, message)
                a = self.unsuccessful(message)
                projected = P.guidance_progress(a, state, message)
                self.assertEqual(projected['unsuccessful_responses'], prior_count + 1)
                self.assertEqual(projected['automatic_guidance_due'], prior_count == 2)
                move = P.select_move(a, state, 'message', message)
                if prior_count == 2:
                    self.assertEqual(move, 'provide_hints_guidance')
                else:
                    self.assertIn(move, P.THINKING_MOVES)

    def test_projection_is_pure_and_recording_is_once_per_version(self):
        message = 'I think the arrow should end at twelve.'
        state = self.state(1, message)
        a = self.unsuccessful(message)
        before = deepcopy(state)
        P.guidance_progress(a, state, message)
        P.guidance_progress(a, state, message)
        self.assertEqual(state, before)
        P.record_response_progress(a, state, message)
        self.assertEqual(state['unsuccessful_response_count'], 2)
        P.record_response_progress(a, state, message)
        self.assertEqual(state['unsuccessful_response_count'], 2)
        self.assertEqual(P.guidance_progress(a, state, message)['unsuccessful_responses'], 2)
        state['version'] += 1
        P.record_response_progress(a, state, message)
        self.assertEqual(state['unsuccessful_response_count'], 3)

    def test_success_resets_streak_while_uncertainty_and_status_do_not_add_failures(self):
        message = 'I am considering the connection.'
        for outcome in ('successful', 'uncertain', 'not_applicable'):
            with self.subTest(outcome=outcome):
                state = self.state(1, message)
                a = assessment(current_response_outcome=outcome, outcome_evidence=message)
                status = P.guidance_progress(a, state, message)
                expected=0 if outcome=='successful' else 1
                self.assertEqual(status['unsuccessful_responses'], expected)
                self.assertFalse(status['automatic_guidance_due'])
                P.record_response_progress(a, state, message)
                self.assertEqual(state['unsuccessful_response_count'], expected)

    def test_stuck_flags_repetition_and_many_teacher_questions_are_not_failed_responses(self):
        message = 'I am still thinking.'
        state = self.state(0, message)
        state.update(thinking_opportunity_count=99, issue_turn_count=99,
                     last_question_target='Explain the same connection again.')
        a = assessment(student_stuck=True, progress_status='stalled', talk_move='provide_hints_guidance',
                       current_question_target=state['last_question_target'])
        self.assertFalse(P.guidance_progress(a, state, message)['automatic_guidance_due'])
        self.assertIn(P.select_move(a, state, 'message', message), P.THINKING_MOVES)
        self.assertFalse(P.thinking_policy(a, state, message, 'provide_hints_guidance')['hint_allowed'])

    def test_outcome_requires_a_short_exact_quote_from_current_student(self):
        message = 'I think the arrow should end at twelve.'
        for evidence in ('', 'The learner was wrong.', 'I THINK the arrow should end at twelve.',
                         'I was unsure in the previous turn.'):
            with self.subTest(evidence=evidence):
                state = self.state(2, message)
                state['turns'] = [dict(student='I was unsure in the previous turn.', version=1)]
                a = self.unsuccessful(message, outcome_evidence=evidence)
                status = P.guidance_progress(a, state, message)
                self.assertFalse(status['outcome_grounded'])
                self.assertEqual(status['unsuccessful_responses'], 2)
                self.assertFalse(status['automatic_guidance_due'])
        long_message = ' '.join('word' + str(i) for i in range(26))
        self.assertFalse(P.guidance_progress(self.unsuccessful(long_message), self.state(2, long_message),
                                            long_message)['outcome_grounded'])

    def test_new_issue_resets_even_at_same_focus_and_does_not_count_old_issue_response(self):
        message = 'I think the arrow should end at twelve.'
        for changes in ({'focus_id': 'o1'}, {'criterion': 'c2'}, {'progress_status': 'new'}):
            with self.subTest(changes=changes):
                state = self.state(3, message)
                a = self.unsuccessful(message, **changes)
                status = P.guidance_progress(a, state, message)
                self.assertEqual(status['unsuccessful_responses'], 0)
                self.assertFalse(status['automatic_guidance_due'])
                P.record_response_progress(a, state, message)
                self.assertEqual(state['unsuccessful_response_count'], 0)
                self.assertEqual(state['response_progress_focus'], [a.criterion, a.focus_id])

    def test_question_rewording_does_not_reset_same_issue_failure_count(self):
        message = 'I think the arrow should end at twelve.'
        state = self.state(2, message)
        state['last_question_target'] = 'Compare the endpoints.'
        a = self.unsuccessful(message, current_question_target='Consider the movement length.')
        self.assertEqual(P.select_move(a, state, 'message', message), 'provide_hints_guidance')

    def test_third_failed_clarification_receives_help_without_an_accuracy_quiz(self):
        message = 'I still cannot explain what that mark means.'
        state = self.state(2, message)
        state.update(accuracy_focus=[], accuracy_started_at=0)
        a = self.unsuccessful(message, next_focus_kind='clarification', areas_for_improvement=[])
        self.assertEqual(P.select_move(a, state, 'message', message), 'provide_hints_guidance')
        self.assertTrue(P.diagnosis_policy(a, state, message, 'provide_hints_guidance')['allowed'])
        a.goal_unclear = True
        self.assertEqual(P.select_move(a, state, 'message', message), 'provide_hints_guidance')

    def test_declared_new_information_is_zero_before_help_and_one_during_help(self):
        state = self.state(0, 'I am considering the arrow.')
        ids = {o['id'] for o in state['committed']['scene']['objects']}
        a = assessment()
        question = reply('What does this direction represent?', False)
        self.assertFalse(F.reply_problem(question, state, a, ids, 'message', '', 'invite_elaboration_reasoning'))
        question.new_conceptual_information = ['The arrowhead is the transfer destination.']
        self.assertTrue(F.reply_problem(question, state, a, ids, 'message', '', 'invite_elaboration_reasoning'))
        state = self.state(0, 'I need a hint.')
        hint = guidance()
        hint.new_conceptual_information = ['The arrowhead is the transfer destination.']
        self.assertFalse(F.reply_problem(hint, state, a, ids, 'message', '', 'provide_hints_guidance'))
        hint.new_conceptual_information.append('Reverse this connection to correct the transfer.')
        self.assertTrue(F.reply_problem(hint, state, a, ids, 'message', '', 'provide_hints_guidance'))

    def test_initial_submission_and_begin_revision_are_not_unsuccessful_replies(self):
        message = 'I think the arrow should end at twelve.'
        initial, _, _ = F.prepare(None, self.data(message=message))
        initial.update(response_progress_focus=['c3', 'o3'], progress_focus=['c3', 'o3'])
        a = self.unsuccessful(message)
        self.assertEqual(P.guidance_progress(a, initial, message)['unsuccessful_responses'], 0)
        P.record_response_progress(a, initial, message)
        self.assertEqual(initial['unsuccessful_response_count'], 0)
        state = self.state(2, message)
        state['intent'] = 'begin_revision'
        self.assertEqual(P.guidance_progress(a, state, message)['unsuccessful_responses'], 2)
        P.record_response_progress(a, state, message)
        self.assertEqual(state['unsuccessful_response_count'], 2)

    def test_grounded_frustration_triggers_immediately_even_on_a_new_issue(self):
        message = 'I am frustrated because I keep trying and cannot make sense of this.'
        for changes in ({}, {'progress_status': 'new', 'focus_id': 'o1'}):
            with self.subTest(changes=changes):
                state = self.state(0, message)
                a = assessment(frustration_evidence=message, **changes)
                status = P.guidance_progress(a, state, message)
                self.assertTrue(status['frustration_present'])
                self.assertTrue(status['automatic_guidance_due'])
                self.assertEqual(P.select_move(a, state, 'message', message), 'provide_hints_guidance')

    def test_frustration_is_not_inferred_from_old_tutor_or_invented_quote(self):
        message = 'I am considering the arrow.'
        for evidence in ('', 'I am frustrated.', 'The learner appears upset.'):
            with self.subTest(evidence=evidence):
                state = self.state(0, message)
                state['turns'] = [dict(student='I am frustrated.', content='I am frustrated.', version=1)]
                a = assessment(student_stuck=True, frustration_evidence=evidence)
                status = P.guidance_progress(a, state, message)
                self.assertFalse(status['frustration_present'])
                self.assertFalse(status['automatic_guidance_due'])

    def test_bare_uncertainty_alone_is_not_grounded_affective_frustration(self):
        for message in ('I do not know.', 'I don’t know.', 'I am not sure.', 'Maybe?'):
            with self.subTest(message=message):
                state = self.state(0, message)
                a = assessment(current_response_outcome='uncertain', outcome_evidence=message,
                               frustration_evidence=message, student_stuck=True)
                status = P.guidance_progress(a, state, message)
                self.assertFalse(status['frustration_present'])
                self.assertFalse(status['automatic_guidance_due'])

    def test_explicit_hint_requests_still_bypass_the_automatic_threshold(self):
        for message, intent in (('Please give me a hint.', 'dialogue'),
                                ('I would like guidance.', 'dialogue'), ('I need a hint.', 'hint')):
            with self.subTest(message=message, intent=intent):
                state = self.state(0, message)
                state['intent'] = intent
                a = assessment(progress_status='new')
                self.assertEqual(P.select_move(a, state, 'message', message), 'provide_hints_guidance')
                self.assertTrue(P.thinking_policy(a, state, message, 'provide_hints_guidance')['hint_allowed'])
                self.assertEqual(P.guidance_progress(a, state, message)['unsuccessful_responses'], 0)

    def test_failed_writer_does_not_commit_response_and_retry_counts_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = F.handle(self.data(), FakeClient([assessment(), reply()]), tmp, 'offline-stub')
            sid = first['session_id']
            committed = F.SESSIONS[sid]['state']
            committed.update(progress_focus=['c3', 'o3'], accuracy_focus=['c3', 'o3'],
                             accuracy_started_at=1, response_progress_focus=['c3', 'o3'],
                             unsuccessful_response_count=2)
            before = deepcopy(committed)
            message = 'I still think the arrow should end at twelve.'
            a = self.unsuccessful(message)
            with self.assertRaises(RuntimeError):
                F.handle(dict(trigger='message', session_id=sid, message=message),
                         FakeClient([a, RuntimeError('Local writer stub failure')]), tmp, 'offline-stub')
            self.assertEqual(F.SESSIONS[sid]['state'], before)
            public = F.handle(dict(trigger='message', session_id=sid, message=message),
                              FakeClient([a, guidance()]), tmp, 'offline-stub')
            self.assertEqual(public['talk_move'], 'provide_hints_guidance')
            self.assertFalse(public['edit_enabled'])
            self.assertEqual(F.SESSIONS[sid]['state']['unsuccessful_response_count'], 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
