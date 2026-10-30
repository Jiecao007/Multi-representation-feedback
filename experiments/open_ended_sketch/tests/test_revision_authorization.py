"""Archived authorization contract; live permission also has three-agent/UI tests."""
from copy import deepcopy
import threading
import unittest
from unittest.mock import patch

from test_feedback import F, SCENE, assessment
from test_question_image import dispatch
from test_student_server import server


class RevisionAuthorizationTests(unittest.TestCase):
    def setUp(self):
        F.SESSIONS.clear()
        historical = patch.object(server, 'feedback', F)
        historical.start()
        self.addCleanup(historical.stop)

    def session(self,pending=False):
        state,_,_=F.prepare(None,dict(trigger='submission',scene=SCENE,explanation='Initial reasoning.',task='A generic task.'))
        state.update(version=8,drawing_version=2,stage='thinking-dialogue',assessment=assessment().model_dump(),
                     awaiting_revision_reason=pending,revision_reason='Existing learner reason.',
                     turns=[dict(version=8,student='My existing idea.',content='Existing tutor reply.')])
        entry={'state':state,'lock':threading.Lock()};F.SESSIONS[state['id']]=entry
        return state['id'],entry

    def test_authorization_changes_only_edit_permission_without_a_new_turn(self):
        sid,entry=self.session();before=deepcopy(entry['state'])
        result=F.begin_revision({'session_id':sid})
        self.assertEqual(result,dict(session_id=sid,edit_enabled=True,awaiting_revision_reason=False))
        self.assertEqual(entry['state'],{**before,'edit_enabled':True})

    def test_authorization_preserves_pending_reason_and_repeated_calls_are_idempotent(self):
        sid,entry=self.session(pending=True);before=deepcopy(entry['state'])
        first=F.begin_revision({'session_id':sid});second=F.begin_revision({'session_id':sid})
        self.assertEqual(first,second)
        self.assertTrue(first['awaiting_revision_reason'])
        self.assertEqual(entry['state'],{**before,'edit_enabled':True})

    def test_missing_or_unknown_session_cannot_authorize_edits(self):
        sid,entry=self.session();before=deepcopy(entry['state'])
        for data in ({},{'session_id':''},{'session_id':'missing'}):
            with self.subTest(data=data),self.assertRaisesRegex(F.FeedbackError,'session is unavailable'):
                F.begin_revision(data)
        self.assertEqual(entry['state'],before)

    def test_busy_session_fails_without_mutating_permission(self):
        sid,entry=self.session();before=deepcopy(entry['state'])
        entry['lock'].acquire()
        try:
            with self.assertRaisesRegex(F.FeedbackError,'already being prepared'):
                F.begin_revision({'session_id':sid})
            self.assertEqual(entry['state'],before)
        finally:
            entry['lock'].release()

    def test_http_authorization_never_creates_client_or_generates_feedback(self):
        sid,entry=self.session();before=deepcopy(entry['state'])
        with patch.object(server,'client') as client,patch.object(server.feedback,'handle') as handle:
            status,result=dispatch('/api/begin-revision',{'session_id':sid})
            self.assertEqual(status,200)
            self.assertEqual(result,dict(session_id=sid,edit_enabled=True,awaiting_revision_reason=False))
            client.assert_not_called();handle.assert_not_called()
        self.assertEqual(entry['state'],{**before,'edit_enabled':True})

    def test_http_unavailable_session_is_reported_without_a_model_call(self):
        with patch.object(server,'client') as client,patch.object(server.feedback,'handle') as handle:
            status,result=dispatch('/api/begin-revision',{'session_id':'missing'})
            self.assertEqual(status,400)
            self.assertIn('session is unavailable',result['error'])
            client.assert_not_called();handle.assert_not_called()

    def test_end_revision_changes_only_permission_and_preserves_pending_reason(self):
        sid,entry=self.session(pending=True);F.begin_revision({'session_id':sid})
        before=deepcopy(entry['state'])
        result=F.end_revision({'session_id':sid})
        self.assertEqual(result,dict(session_id=sid,edit_enabled=False,awaiting_revision_reason=True))
        self.assertEqual(entry['state'],{**before,'edit_enabled':False})
        self.assertEqual(F.end_revision({'session_id':sid}),result)
        self.assertEqual(entry['state'],{**before,'edit_enabled':False})

    def test_end_then_resume_preserves_existing_dialogue_and_committed_work(self):
        sid,entry=self.session();before=deepcopy(entry['state'])
        F.begin_revision({'session_id':sid});F.end_revision({'session_id':sid})
        self.assertEqual(entry['state'],before)
        F.begin_revision({'session_id':sid})
        self.assertEqual(entry['state'],{**before,'edit_enabled':True})

    def test_end_revision_rejects_missing_session_and_busy_lock_without_mutation(self):
        sid,entry=self.session();F.begin_revision({'session_id':sid});before=deepcopy(entry['state'])
        for data in ({},{'session_id':''},{'session_id':'missing'}):
            with self.subTest(data=data),self.assertRaisesRegex(F.FeedbackError,'session is unavailable'):
                F.end_revision(data)
        entry['lock'].acquire()
        try:
            with self.assertRaisesRegex(F.FeedbackError,'already being prepared'):
                F.end_revision({'session_id':sid})
        finally:
            entry['lock'].release()
        self.assertEqual(entry['state'],before)

    def test_http_end_revision_never_creates_client_or_generates_feedback(self):
        sid,entry=self.session(pending=True);F.begin_revision({'session_id':sid});before=deepcopy(entry['state'])
        with patch.object(server,'client') as client,patch.object(server.feedback,'handle') as handle:
            status,result=dispatch('/api/end-revision',{'session_id':sid})
            self.assertEqual(status,200)
            self.assertEqual(result,dict(session_id=sid,edit_enabled=False,awaiting_revision_reason=True))
            client.assert_not_called();handle.assert_not_called()
        self.assertEqual(entry['state'],{**before,'edit_enabled':False})

    def test_http_end_revision_unavailable_session_has_no_model_call(self):
        with patch.object(server,'client') as client,patch.object(server.feedback,'handle') as handle:
            status,result=dispatch('/api/end-revision',{'session_id':'missing'})
            self.assertEqual(status,400)
            self.assertIn('session is unavailable',result['error'])
            client.assert_not_called();handle.assert_not_called()


if __name__=='__main__':
    unittest.main()
