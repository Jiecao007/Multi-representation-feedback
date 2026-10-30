"""Task figures remain immutable task context across assessment and revision."""
from copy import deepcopy
import json
import tempfile
import unittest

from pydantic import ValidationError
from test_feedback import F, SCENE, FakeClient, assessment, reply


GIVEN='data:image/png;base64,dGVzdA=='


def context(call):
    return json.loads(call['input'][0]['content'][0]['text'])


class QuestionFeedbackTests(unittest.TestCase):
    def setUp(self):
        F.SESSIONS.clear()

    def data(self):
        return dict(trigger='submission',scene=deepcopy(SCENE),original_scene=deepcopy(SCENE),
                    explanation='Food needs energy.',task='',goals=[],edits=[])

    def start(self,tmp):
        client=FakeClient([assessment(task_figure_context='The given figure supplies the required constraints.'),reply()])
        public=F.handle(self.data(),client,tmp,'test-review',question_image=GIVEN)
        return public,client

    def begin(self,tmp,sid):
        candidate=reply('Revise this connection, then explain your change.',False,
                        revision_plan='Revise this connection and explain its transfer direction.',
                        revision_plan_ids=['o3'],next_step='revise')
        return F.handle(dict(trigger='message',session_id=sid,intent='begin_revision',message='Begin a revision.'),
                        FakeClient([assessment(),candidate]),tmp,'test-review')

    def test_empty_task_text_uses_separate_given_figure_without_altering_student_scene(self):
        with tempfile.TemporaryDirectory() as tmp:
            public,client=self.start(tmp)
            state=F.SESSIONS[public['session_id']]['state']
            self.assertEqual(len(client.calls),2)
            evaluator_parts=client.calls[0]['input'][0]['content']
            self.assertEqual([part['type'] for part in evaluator_parts],['input_text','input_text','input_image'])
            self.assertIn('QUESTION IMAGE',evaluator_parts[1]['text'])
            self.assertIn('not the student response',evaluator_parts[1]['text'])
            self.assertEqual(evaluator_parts[2]['image_url'],GIVEN)
            input_context=context(client.calls[0])
            self.assertEqual(input_context['task'],'')
            self.assertTrue(input_context['task_figure_present'])
            self.assertNotIn('data:image',json.dumps(input_context))
            normalized=F.validate_sketch(SCENE).model_dump()
            self.assertEqual(state['committed']['scene'],normalized)
            self.assertEqual(state['original']['scene'],normalized)
            self.assertEqual(state['question_image'],GIVEN)
            self.assertEqual(context(client.calls[1])['task_figure_context'],state['task_figure_context'])
            self.assertNotIn('task_figure_context',public)
            self.assertNotIn('data:image',json.dumps(public))

    def test_full_review_reuses_original_figure_and_refreshes_text_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            first,_=self.start(tmp);sid=first['session_id']
            self.begin(tmp,sid)
            changed=deepcopy(SCENE);changed['objects'][0]['label']='Student revision'
            cache='The given figure requires the revised model to keep its original constraints.'
            client=FakeClient([assessment(task_figure_context=cache),
                               reply('How does this change better represent your idea?',
                                     acknowledgment='You revised the label.',acknowledgment_ids=['o1'])])
            public=F.handle(dict(trigger='workspace-complete',session_id=sid,scene=changed,explanation='Food needs energy.',
                                 task='UNTRUSTED REPLACEMENT',edits=[]),client,tmp,'test-review',
                            question_image='data:image/png;base64,cmVwbGFjZW1lbnQ=')
            self.assertEqual(len(client.calls),2)
            parts=client.calls[0]['input'][0]['content']
            self.assertEqual([part['image_url'] for part in parts if part['type']=='input_image'],[GIVEN])
            self.assertNotIn('UNTRUSTED REPLACEMENT',json.dumps(context(client.calls[0])))
            state=F.SESSIONS[sid]['state']
            self.assertEqual(state['question_image'],GIVEN)
            self.assertEqual(state['task_figure_context'],cache)
            self.assertEqual(context(client.calls[1])['task_figure_context'],cache)
            self.assertEqual(state['committed']['scene']['objects'][0]['label'],'Student revision')
            self.assertTrue(public['awaiting_revision_reason'])

    def test_no_figure_does_not_cache_invented_task_image_givens(self):
        with tempfile.TemporaryDirectory() as tmp:
            public=F.handle(self.data(),FakeClient([assessment(task_figure_context='UNSUPPORTED GIVENS'),reply()]),tmp,'test-review')
            state=F.SESSIONS[public['session_id']]['state']
            self.assertEqual(state['task_figure_context'],'')
            self.assertIsNone(state['question_image'])

    def test_private_cached_figure_description_has_bounded_size(self):
        self.assertEqual(len(assessment(task_figure_context='x'*2000).task_figure_context),2000)
        with self.assertRaises(ValidationError):
            assessment(task_figure_context='x'*2001)


if __name__=='__main__':
    unittest.main()
