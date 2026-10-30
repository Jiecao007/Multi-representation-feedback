"""Trusted local case recovery preserves submissions without model calls."""
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_feedback import F, SCENE, assessment
from test_student_server import server
from case_resume import prepare_resume


class CaseResumeTests(unittest.TestCase):
    def fixture(self,root):
        state,_,_=F.prepare(None,dict(trigger='submission',scene=SCENE,source_id='resume-example',
                                     explanation='Original learner explanation.',task='A generic transfer task.',
                                     goals=['Explain the relationship.']))
        state.update(version=2,drawing_version=2,stage='revision-explanation',edit_enabled=True,
                     awaiting_revision_reason=True,revision_reason='Previous submitted reason.',
                     assessment=assessment().model_dump(),accuracy_focus=[],accuracy_started_at=0,
                     thinking_focus=[],thinking_started_at=0,progress_focus=['c1','o1'],issue_turn_count=1)
        state['previous_submission']=deepcopy(state['committed'])
        state['committed']['scene']['objects'][0]['label']='Committed correction'
        draft=deepcopy(state['committed']);draft['scene']['objects'][0]['label']='Unsubmitted private draft'
        turns=[dict(version=1,drawing_version=1,content='First tutor feedback.'),
               dict(version=2,drawing_version=2,content='Latest tutor feedback.')]
        state['turns']=deepcopy(turns)
        case=dict(source={'id':'resume-example'},feedback_session=state['id'],feedback_turns=turns,
                  committed_work=deepcopy(state['committed']),original_model=deepcopy(state['original']['scene']),
                  current_draft=draft,interaction_log=[dict(role='user',text='Existing learner idea.'),
                  dict(role='assistant',text='An earlier delivery failed.',error=True),
                  dict(role='assistant',text='Latest tutor feedback.')],
                  workspace_state={'revision_reason':'Unfinished typed revision reason.'})
        payload=dict(record={'id':'resume-example','width':1000,'height':1000},scene=deepcopy(SCENE),original='data:image/png;base64,fixture')
        artifacts=Path(root)/'runs';folder=artifacts/'feedback_turn_current';folder.mkdir(parents=True)
        artifact=folder/'session.json';artifact.write_text(json.dumps(state))
        backup=Path(root)/'case.exploration.json';backup.write_text(json.dumps(case))
        return state,case,payload,artifacts,artifact,backup

    def write(self,path,value):path.write_text(json.dumps(value))

    def test_restore_preserves_case_and_backend_context_but_starts_view_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            state,case,payload,artifacts,artifact,backup=self.fixture(tmp)
            before_files=(artifact.read_bytes(),backup.read_bytes());loader=Mock(return_value=payload)
            bundle,restored=prepare_resume(backup,artifacts,loader)
            loader.assert_called_once_with('resume-example')
            self.assertEqual(restored,{**state,'edit_enabled':False})
            self.assertEqual(bundle['case'],case);self.assertEqual(bundle['payload'],payload)
            self.assertFalse(bundle['state']['edit_enabled']);self.assertTrue(bundle['state']['awaiting_revision_reason'])
            self.assertEqual(bundle['state']['revision_reason'],'Unfinished typed revision reason.')
            self.assertEqual(bundle['state']['initial_explanation'],'Original learner explanation.')
            self.assertEqual(bundle['state']['learning_requirements'],['Explain the relationship.'])
            self.assertEqual((artifact.read_bytes(),backup.read_bytes()),before_files)
            bundle['payload']['scene']['title']='Changed returned payload'
            self.assertEqual(payload['scene']['title'],SCENE['title'],'Recovery must return independent data')
            self.assertEqual(restored['previous_submission'],state['previous_submission'])

    def test_revision_reason_falls_back_to_latest_backend_and_unconfigured_goals_stay_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            state,case,payload,artifacts,artifact,backup=self.fixture(tmp)
            case.pop('workspace_state');state['goals_configured']=False
            self.write(artifact,state);self.write(backup,case)
            bundle,_=prepare_resume(backup,artifacts,Mock(return_value=payload))
            self.assertEqual(bundle['state']['revision_reason'],state['revision_reason'])
            self.assertEqual(bundle['state']['learning_requirements'],[])

    def test_newest_matching_version_wins_over_mtime_and_other_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            state,case,payload,artifacts,artifact,backup=self.fixture(tmp)
            older=deepcopy(state);older['version']=1
            old=artifacts/'feedback_turn_older';old.mkdir();self.write(old/'session.json',older)
            os.utime(old/'session.json',(artifact.stat().st_mtime+100,artifact.stat().st_mtime+100))
            other=deepcopy(state);other['id']='feedback_'+'a'*32;other['version']=99
            folder=artifacts/'feedback_turn_other';folder.mkdir();self.write(folder/'session.json',other)
            _,restored=prepare_resume(backup,artifacts,Mock(return_value=payload))
            self.assertEqual(restored['version'],2);self.assertEqual(restored['id'],state['id'])

    def test_invalid_session_or_absent_completed_turn_cannot_restore(self):
        for change in ({'feedback_session':'../unsafe'},{'feedback_session':'feedback_invalid'},{'feedback_turns':[]}):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                _,case,payload,artifacts,_,backup=self.fixture(tmp);case.update(change);self.write(backup,case)
                loader=Mock(return_value=payload)
                with self.assertRaises(ValueError):prepare_resume(backup,artifacts,loader)
                loader.assert_not_called()

    def test_missing_backend_session_and_stale_versions_are_refused(self):
        for problem in ('missing','version','drawing_version'):
            with self.subTest(problem=problem),tempfile.TemporaryDirectory() as tmp:
                _,case,payload,artifacts,artifact,backup=self.fixture(tmp)
                if problem=='missing':artifact.unlink()
                else:case['feedback_turns'][-1][problem]=1;self.write(backup,case)
                loader=Mock(return_value=payload)
                with self.assertRaises(ValueError):prepare_resume(backup,artifacts,loader)
                loader.assert_not_called()

    def test_committed_mismatch_is_not_replaced_by_a_private_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            _,case,payload,artifacts,_,backup=self.fixture(tmp)
            case['committed_work']=deepcopy(case['current_draft']);self.write(backup,case)
            loader=Mock(return_value=payload)
            with self.assertRaisesRegex(ValueError,'match the saved submission'):prepare_resume(backup,artifacts,loader)
            loader.assert_not_called()

    def test_invalid_original_committed_or_draft_geometry_is_rejected(self):
        for location in ('state-original','state-committed','case-original','case-draft'):
            with self.subTest(location=location),tempfile.TemporaryDirectory() as tmp:
                state,case,payload,artifacts,artifact,backup=self.fixture(tmp)
                broken=deepcopy(SCENE);broken['objects'][0]['bbox']['width']=-1
                if location=='state-original':state['original']['scene']=broken
                if location=='state-committed':state['committed']['scene']=broken;case['committed_work']=deepcopy(state['committed'])
                if location=='case-original':case['original_model']=broken
                if location=='case-draft':case['current_draft']['scene']=broken
                self.write(artifact,state);self.write(backup,case);loader=Mock(return_value=payload)
                with self.assertRaises(ValueError):prepare_resume(backup,artifacts,loader)
                loader.assert_not_called()

    def test_original_payload_is_required_and_must_match_the_backend_source(self):
        for returned in (None,{'record':{'id':'a-different-source'}}):
            with self.subTest(payload=returned),tempfile.TemporaryDirectory() as tmp:
                _,_,_,artifacts,_,backup=self.fixture(tmp)
                with self.assertRaisesRegex(ValueError,'original drawing'):prepare_resume(backup,artifacts,Mock(return_value=returned))

    def test_http_recovery_is_one_shot_without_a_model_or_feedback_call(self):
        bundle={'payload':{'record':{'id':'resume-example'}},'case':{'interaction_log':[]},'state':{'edit_enabled':False}}
        holder=SimpleNamespace(resume_case=deepcopy(bundle))
        handler=SimpleNamespace(path='/api/resume-case',server=holder,allowed=lambda:True,json=Mock(),send_bytes=Mock())
        with patch.object(server,'client') as client,patch.object(server.feedback,'handle') as handle:
            server.Handler.do_GET(handler)
            handler.json.assert_called_once_with(200,bundle);self.assertIsNone(holder.resume_case)
            server.Handler.do_GET(handler)
            handler.send_bytes.assert_called_once_with(204,b'','application/json')
            client.assert_not_called();handle.assert_not_called()


if __name__=='__main__':unittest.main()
