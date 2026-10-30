"""Pending valid assessments survive Tutor failures without committing work.

All agent responses are local typed stubs. These checks exercise actual runtime
routing and rollback; they do not make external model calls.
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
from agent_api import AgentError
from test_three_agent_runtime import FakeClient, SCENE, contract_types
from test_feedback_full_process import assessment, opening, turn, M2
from agent_types import EvaluationResult, TutorTurn


class PendingEvaluationDeliveryTests(unittest.TestCase):
    def setUp(self):
        F.SESSIONS.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def call(self, data, values, model='evaluation-model'):
        client = FakeClient(values)
        result = F.handle(data, client, self.directory, model,
                          fast_dialogue_model='fast-tutor')
        return result, client

    def start(self):
        initial = dict(trigger='submission', scene=deepcopy(SCENE), original_scene=deepcopy(SCENE),
                       explanation='', task='Show transfer direction and explain quantity.',
                       goals=['Explain transfer direction and quantity.'], source_id='pending-assessment-fixture',
                       message='', edits=[])
        first, _ = self.call(initial, [assessment(), opening()])
        sid = first['session_id']
        F.begin_revision(dict(session_id=sid))
        scene = deepcopy(F.SESSIONS[sid]['state']['committed']['scene'])
        scene['objects'][0]['label'] += ' revised'
        data = dict(trigger='workspace-complete', session_id=sid, scene=scene, explanation='', edits=[])
        return sid, data

    def review_result(self):
        return assessment(parts=[M2], outcome='successful',
                          revision_evidence='The submitted transfer direction now agrees with the intended receiver.')

    def review_reply(self, **changes):
        values = dict(acknowledgment='Nice work correcting the transfer direction!',
                      content='How does the quantity connect to this transfer?')
        values.update(changes)
        return turn(issue='m2', **values)

    def fail_after_valid_evaluation(self, sid, data):
        before = deepcopy(F.SESSIONS[sid]['state'])
        memory_path = self.directory / 'learner_models' / (sid + '.json')
        saved_memory = memory_path.read_bytes()
        # A response aimed at the retired issue remains a real delivery error.
        invalid = turn(issue='m1', acknowledgment='Nice work correcting the direction!')
        client = FakeClient([self.review_result(), invalid])
        with self.assertRaises(F.FeedbackError):
            F.handle(data, client, self.directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
        self.assertEqual(contract_types(client), [EvaluationResult, TutorTurn])
        self.assertEqual(F.SESSIONS[sid]['state'], before)
        self.assertIn('pending_evaluation', F.SESSIONS[sid])
        self.assertEqual(memory_path.read_bytes(), saved_memory)
        failed_run = self.directory / F.SESSIONS[sid]['pending_evaluation']['source_artifact']
        self.assertFalse((failed_run / 'session.json').exists())
        self.assertFalse((failed_run / 'learner_model_update.json').exists())
        self.assertFalse((failed_run / 'public_reply.json').exists())
        return before

    def test_identical_retry_calls_only_tutor_and_commits_the_cached_review_once(self):
        sid, data = self.start()
        before = self.fail_after_valid_evaluation(sid, data)
        pending = deepcopy(F.SESSIONS[sid]['pending_evaluation'])
        self.assertNotIn('pending_evaluation', before)
        result, client = self.call(data, [self.review_reply()])
        self.assertEqual(contract_types(client), [TutorTurn])
        self.assertEqual(result['agents_called'], ['tutor'])
        self.assertEqual(result['api_calls'], 1)
        self.assertTrue(result['evaluation_updated'])
        self.assertEqual(result['drawing_version'], before['drawing_version'] + 1)
        self.assertEqual(result['version'], before['version'] + 1)
        self.assertEqual(result['acknowledgment'], 'Nice work correcting the transfer direction!')
        self.assertEqual(F.SESSIONS[sid]['state']['committed']['scene'], data['scene'])
        self.assertNotIn('pending_evaluation', F.SESSIONS[sid])
        records = [json.loads(p.read_text()) for p in self.directory.glob('feedback_turn_*/evaluation_cache.json')]
        reused = [r for r in records if r['status'] == 'reused']
        self.assertEqual(len(reused), 1)
        self.assertEqual(reused[0]['source_artifact'], pending['source_artifact'])
        self.assertEqual(reused[0]['evaluation_api_calls'], 0)
        for p in self.directory.glob('feedback_turn_*/session.json'):
            self.assertNotIn('pending_evaluation', json.loads(p.read_text()))

    def test_cached_review_does_not_bypass_successful_correction_praise(self):
        sid, data = self.start()
        before = self.fail_after_valid_evaluation(sid, data)
        client = FakeClient([self.review_reply(acknowledgment='')])
        with self.assertRaises(F.FeedbackError):
            F.handle(data, client, self.directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
        self.assertEqual(contract_types(client), [TutorTurn])
        self.assertEqual(F.SESSIONS[sid]['state'], before)
        self.assertIn('pending_evaluation', F.SESSIONS[sid])
        result, retry = self.call(data, [self.review_reply()])
        self.assertEqual(contract_types(retry), [TutorTurn])
        self.assertTrue(result['evaluation_updated'])

    def test_invalid_evaluation_or_evaluation_api_failure_cannot_enter_the_cache(self):
        failures = [assessment(parts=[M2], outcome='not_reviewed'), AgentError('Local Evaluation failure.')]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                sid, data = self.start()
                before = deepcopy(F.SESSIONS[sid]['state'])
                client = FakeClient([failure])
                with self.assertRaises(F.FeedbackError):
                    F.handle(data, client, self.directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
                self.assertEqual(contract_types(client), [EvaluationResult])
                self.assertEqual(F.SESSIONS[sid]['state'], before)
                self.assertNotIn('pending_evaluation', F.SESSIONS[sid])
                result, retry = self.call(data, [self.review_result(), self.review_reply()])
                self.assertEqual(contract_types(retry), [EvaluationResult, TutorTurn])
                self.assertTrue(result['evaluation_updated'])

    def test_changed_submission_inputs_do_not_reuse_a_pending_assessment(self):
        for change in ('geometry', 'explanation', 'edits'):
            with self.subTest(change=change):
                sid, data = self.start()
                self.fail_after_valid_evaluation(sid, data)
                old_key = F.SESSIONS[sid]['pending_evaluation']['key']
                changed = deepcopy(data)
                if change == 'geometry':
                    changed['scene']['objects'][0]['bbox']['x'] += 11
                elif change == 'explanation':
                    changed['explanation'] = 'The arrow points toward its receiver.'
                else:
                    changed['edits'] = [dict(kind='rename', id=changed['scene']['objects'][0]['id'])]
                result, client = self.call(changed, [self.review_result(), self.review_reply()])
                self.assertEqual(contract_types(client), [EvaluationResult, TutorTurn])
                self.assertTrue(result['evaluation_updated'])
                stored = [json.loads(p.read_text()) for p in self.directory.glob('feedback_turn_*/evaluation_cache.json')]
                self.assertTrue(any(r['status'] == 'stored' and r['key'] != old_key for r in stored))

    def test_successful_ordinary_dialogue_clears_the_pending_assessment(self):
        sid, data = self.start()
        before = self.fail_after_valid_evaluation(sid, data)
        reply, dialogue = self.call(dict(trigger='message', session_id=sid, message='I am reconsidering my transfer.'),
                                    [turn(issue='m1')])
        self.assertEqual(contract_types(dialogue), [TutorTurn])
        self.assertFalse(reply['evaluation_updated'])
        self.assertEqual(F.SESSIONS[sid]['state']['committed'], before['committed'])
        self.assertEqual(F.SESSIONS[sid]['state']['learner_model']['evaluation'], before['learner_model']['evaluation'])
        self.assertNotIn('pending_evaluation', F.SESSIONS[sid])
        result, client = self.call(data, [self.review_result(), self.review_reply()])
        self.assertEqual(contract_types(client), [EvaluationResult, TutorTurn])
        self.assertTrue(result['evaluation_updated'])

    def test_evaluation_model_change_requires_a_fresh_assessment(self):
        sid, data = self.start()
        self.fail_after_valid_evaluation(sid, data)
        result, client = self.call(data, [self.review_result(), self.review_reply()], model='different-evaluation-model')
        self.assertEqual(contract_types(client), [EvaluationResult, TutorTurn])
        self.assertEqual(client.calls[0]['model'], 'different-evaluation-model')
        self.assertTrue(result['evaluation_updated'])


if __name__ == '__main__':
    unittest.main()
