"""Bounded revision success is independent of broader issue completion.

All Evaluation and Tutor responses are typed local stubs. These checks exercise
context provenance, persistence, routing and transaction boundaries, not model
assessment quality or actual student learning.
"""
from copy import deepcopy
import json
import unittest

import test_feedback_full_process as fixtures
from test_three_agent_runtime import FakeClient, context

F = fixtures.F
M1, M2 = fixtures.M1, fixtures.M2
assessment, turn = fixtures.assessment, fixtures.turn
LOCAL_INSTRUCTION = 'Label the first connection transfer.'


class LocalRevisionReviewTests(unittest.TestCase):
    # Reuse runtime helpers without importing another TestCase into discovery.
    setUp = fixtures.FullFeedbackProcessTests.setUp
    data = fixtures.FullFeedbackProcessTests.data
    call = fixtures.FullFeedbackProcessTests.call
    start = fixtures.FullFeedbackProcessTests.start
    state = fixtures.FullFeedbackProcessTests.state
    message = fixtures.FullFeedbackProcessTests.message
    checked = fixtures.FullFeedbackProcessTests.checked

    def local_edit_ready(self):
        sid = self.checked()
        self.message(
            sid, 'I need a hint.',
            turn('provide_hints_guidance', content=LOCAL_INSTRUCTION,
                 edit_instruction=LOCAL_INSTRUCTION, next_step='revise',
                 question_target=''),
            intent='hint',
        )
        self.assertTrue(self.state(sid)['edit_enabled'])
        return sid

    def changed_scene(self, sid):
        scene = deepcopy(self.state(sid)['committed']['scene'])
        scene['relations'][0]['verbatim_text'] = 'transfer'
        return scene

    def submit(self, sid, result, response, scene=None):
        return self.call(
            dict(trigger='workspace-complete', session_id=sid,
                 scene=self.changed_scene(sid) if scene is None else scene,
                 explanation='The first connection is now labeled transfer.', edits=[]),
            [result, response],
        )

    def test_correct_local_edit_can_leave_the_same_broader_issue_unresolved(self):
        sid = self.local_edit_ready()
        local_success = assessment(
            [M2, M1], 'successful', addressed_issue_status='unresolved',
            revision_evidence='The requested connection label was added correctly; the broader direction issue remains.',
        )
        response = turn(
            acknowledgment='Nice revision! The requested connection label is correct.',
            content='How does the arrow direction fit the transfer?',
        )
        public, client = self.submit(sid, local_success, response)

        evaluated = context(client.calls[0])
        self.assertEqual(evaluated['addressed_issue']['id'], 'm1')
        self.assertTrue('revision_target' in evaluated, 'Evaluation must receive a bounded revision target.')
        self.assertIn(LOCAL_INSTRUCTION, json.dumps(evaluated['revision_target']))
        self.assertIn('m1', json.dumps(evaluated['revision_target']))
        formal = self.state(sid)['learner_model']['evaluation']['result']
        self.assertEqual(formal['revision_outcome'], 'successful')
        self.assertEqual(formal['addressed_issue_status'], 'unresolved')
        self.assertEqual(formal['criteria'][0]['status'], 'developing')
        self.assertEqual([p['id'] for p in formal['missing_parts']], ['m2', 'm1'])
        self.assertEqual(self.state(sid)['current_issue_id'], 'm1')
        self.assertEqual(public['stage'], 'thinking-dialogue')
        self.assertTrue(public['acknowledgment'])
        interaction = context(client.calls[1])['interaction']
        self.assertEqual(interaction['review_outcome'], 'successful')
        self.assertFalse(interaction['all_issues_resolved'])
        self.assertFalse(interaction['check_required'])
        self.assertEqual(len(client.calls), 2)

    def test_successful_local_edit_and_resolved_issue_advance_directly_to_next_support(self):
        sid = self.local_edit_ready()
        result = assessment(
            [M2], 'successful', addressed_issue_status='resolved',
            revision_evidence='The submitted connection label resolves the addressed direction issue.',
        )
        public, client = self.submit(
            sid, result,
            turn(issue='m2', acknowledgment='Nice revision! That connection now represents the transfer.',
                 content='How does the quantity fit your model?'),
        )
        self.assertEqual(self.state(sid)['current_issue_id'], 'm2')
        self.assertEqual(public['stage'], 'thinking-dialogue')
        interaction = context(client.calls[1])['interaction']
        self.assertFalse(interaction['check_required'])
        self.assertFalse(interaction['all_issues_resolved'])

    def test_wrong_local_edit_stays_on_same_issue_despite_reordered_other_gaps(self):
        sid = self.local_edit_ready()
        scene = self.changed_scene(sid)
        scene['relations'][0]['verbatim_text'] = 'wrong label'
        result = assessment(
            [M2, M1], 'unsuccessful', addressed_issue_status='unresolved',
            revision_evidence='The submitted label does not match the requested transfer label.',
        )
        public, client = self.submit(
            sid, result,
            turn(content='The label still differs from the requested change. Which transfer should it name?'),
            scene=scene,
        )
        self.assertEqual(self.state(sid)['current_issue_id'], 'm1')
        self.assertEqual(public['stage'], 'thinking-dialogue')
        self.assertEqual(context(client.calls[1])['interaction']['review_outcome'], 'unsuccessful')
        self.assertFalse(context(client.calls[1])['interaction']['check_required'])

    def test_uncertain_local_result_uses_meaning_check_within_support(self):
        sid = self.local_edit_ready()
        result = assessment(
            [M2, M1], 'uncertain', addressed_issue_status='uncertain',
            revision_evidence='The intended referent of the new connection label is unclear.',
        )
        public, client = self.submit(
            sid, result,
            turn('ask_for_clarification', content='Which transfer does this new label refer to?',
                 move_evidence=dict(clarification_need='Identify the new label referent.')),
        )
        self.assertEqual(self.state(sid)['current_issue_id'], 'm1')
        self.assertEqual(public['stage'], 'thinking-dialogue')
        self.assertTrue(context(client.calls[1])['interaction']['review_clarification_required'])

    def test_unchanged_submission_does_not_evaluate_or_claim_new_local_success(self):
        sid = self.local_edit_ready()
        before = deepcopy(self.state(sid)['learner_model']['evaluation'])
        scene = deepcopy(self.state(sid)['committed']['scene'])
        public, client = self.call(
            dict(trigger='workspace-complete', session_id=sid, scene=scene,
                 explanation='I intend to label the first connection.', edits=[]),
            [turn(content='What does the first connection currently represent?')],
        )
        self.assertEqual(public['agents_called'], ['tutor'])
        self.assertEqual(len(client.calls), 1)
        self.assertFalse(public['evaluation_updated'])
        self.assertEqual(self.state(sid)['learner_model']['evaluation'], before)
        # An unchanged Review changes click must not consume the pending target.
        F.begin_revision(dict(session_id=sid))
        _, review = self.submit(
            sid,
            assessment([M1, M2], 'successful', addressed_issue_status='unresolved',
                       revision_evidence='The subsequently submitted connection label is correct.'),
            turn(acknowledgment='Nice revision! The requested label is correct.',
                 content='How does the direction fit this transfer?'),
        )
        evaluated = context(review.calls[0])
        self.assertTrue('revision_target' in evaluated, 'An unchanged submission must preserve the pending local target.')
        self.assertIn(LOCAL_INSTRUCTION, json.dumps(evaluated['revision_target']))

    def test_successful_local_edit_does_not_permit_premature_closing(self):
        sid = self.local_edit_ready()
        before = deepcopy(self.state(sid))
        result = assessment(
            [M1, M2], 'successful', addressed_issue_status='unresolved',
            revision_evidence='The local connection label is correct; the broader issue remains.',
        )
        client = FakeClient([
            result,
            turn('invite_dialogue', issue='', stage='dialogue',
                 acknowledgment='Nice revision!', content='What else would you like to ask?'),
        ])
        with self.assertRaises((F.FeedbackError, ValueError)):
            F.handle(dict(trigger='workspace-complete', session_id=sid,
                          scene=self.changed_scene(sid), explanation='', edits=[]),
                     client, self.directory, 'local-evaluation', fast_dialogue_model='local-fast-tutor')
        self.assertEqual(self.state(sid), before)
        self.assertEqual(len(client.calls), 2)

    def test_local_success_still_requires_specific_praise_when_broader_issue_remains(self):
        sid = self.local_edit_ready()
        before = deepcopy(self.state(sid))
        result = assessment(
            [M1, M2], 'successful', addressed_issue_status='unresolved',
            revision_evidence='The connection label is correct; remaining direction work is unresolved.',
        )
        client = FakeClient([result, turn(content='How does the direction fit this transfer?')])
        with self.assertRaises((F.FeedbackError, ValueError)):
            F.handle(dict(trigger='workspace-complete', session_id=sid,
                          scene=self.changed_scene(sid), explanation='', edits=[]),
                     client, self.directory, 'local-evaluation', fast_dialogue_model='local-fast-tutor')
        self.assertEqual(self.state(sid), before)
        self.assertEqual(len(client.calls), 2)

    def test_legacy_success_with_same_issue_remaining_does_not_erase_that_issue(self):
        sid = self.local_edit_ready()
        legacy_result = assessment(
            [M2, M1], 'successful',
            revision_evidence='The requested connection label was correctly added.',
        )
        public, _ = self.submit(
            sid, legacy_result,
            turn(acknowledgment='Nice revision! The connection label is correct.',
                 content='How does the arrow direction fit this transfer?'),
        )
        self.assertEqual(self.state(sid)['current_issue_id'], 'm1')
        self.assertEqual(public['stage'], 'thinking-dialogue')
        self.assertEqual(self.state(sid)['learner_model']['evaluation']['result']['revision_outcome'], 'successful')

    def test_explicit_broader_status_contradictions_are_rejected_before_tutor(self):
        invalid = (
            assessment([M1, M2], 'successful', addressed_issue_status='resolved'),
            assessment([M2], 'successful', addressed_issue_status='unresolved'),
            assessment([M2], 'unsuccessful', addressed_issue_status='resolved'),
        )
        for result in invalid:
            with self.subTest(local=result.revision_outcome, broader=result.addressed_issue_status,
                              gaps=[part.id for part in result.missing_parts]):
                F.SESSIONS.clear()
                sid = self.local_edit_ready()
                before = deepcopy(self.state(sid))
                client = FakeClient([result])
                with self.assertRaises(F.FeedbackError):
                    F.handle(dict(trigger='workspace-complete', session_id=sid,
                                  scene=self.changed_scene(sid), explanation='', edits=[]),
                             client, self.directory, 'local-evaluation', fast_dialogue_model='local-fast-tutor')
                self.assertEqual(len(client.calls), 1)
                self.assertEqual(self.state(sid), before)

    def test_correct_local_edit_with_uncertain_broader_meaning_praises_then_clarifies(self):
        sid = self.local_edit_ready()
        result = assessment(
            [M1, M2], 'successful', addressed_issue_status='uncertain',
            revision_evidence='The requested label was correctly added; its broader transfer interpretation remains unclear.',
        )
        public, client = self.submit(
            sid, result,
            turn('ask_for_clarification', acknowledgment='Nice revision! The requested label is correct.',
                 content='Which transfer does that label refer to?',
                 move_evidence=dict(clarification_need='Identify the broader transfer interpretation.')),
        )
        self.assertEqual(public['stage'], 'thinking-dialogue')
        self.assertTrue(public['acknowledgment'])
        self.assertEqual(self.state(sid)['current_issue_id'], 'm1')
        interaction = context(client.calls[1])['interaction']
        self.assertEqual(interaction['review_outcome'], 'successful')
        self.assertTrue(interaction['review_clarification_required'])

    def test_failed_tutor_delivery_keeps_local_target_and_reuses_identical_evaluation(self):
        sid = self.local_edit_ready()
        before = deepcopy(self.state(sid))
        scene = self.changed_scene(sid)
        data = dict(trigger='workspace-complete', session_id=sid, scene=scene,
                    explanation='The first connection is now labeled transfer.', edits=[])
        result = assessment(
            [M1, M2], 'successful', addressed_issue_status='unresolved',
            revision_evidence='The requested label was added correctly; broader direction work remains.',
        )
        first = FakeClient([result, turn(content='How does the direction fit this transfer?')])
        with self.assertRaises((F.FeedbackError, ValueError)):
            F.handle(data, first, self.directory, 'local-evaluation', fast_dialogue_model='local-fast-tutor')
        self.assertEqual(len(first.calls), 2)
        self.assertEqual(self.state(sid), before)
        self.assertTrue('revision_target' in context(first.calls[0]), 'The failed delivery must retain its evaluated local target.')
        self.assertIn(LOCAL_INSTRUCTION, json.dumps(context(first.calls[0])['revision_target']))

        retry = FakeClient([
            turn(acknowledgment='Nice revision! The requested connection label is correct.',
                 content='How does the direction fit this transfer?'),
        ])
        public = F.handle(data, retry, self.directory, 'local-evaluation', fast_dialogue_model='local-fast-tutor')
        self.assertEqual(len(retry.calls), 1)
        self.assertEqual(public['agents_called'], ['tutor'])
        self.assertTrue(public['evaluation_updated'])
        self.assertEqual(self.state(sid)['current_issue_id'], 'm1')
        self.assertEqual(self.state(sid)['learner_model']['evaluation']['result']['revision_outcome'], 'successful')


if __name__ == '__main__':
    unittest.main()
