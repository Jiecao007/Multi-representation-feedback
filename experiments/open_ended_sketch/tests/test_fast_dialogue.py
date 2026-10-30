"""One-call text tutoring stays compact, grounded, and state-safe. No API calls."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from test_feedback import F, SCENE, FakeClient, assessment, reply, guidance, paths


def turn(a=None, r=None, move='press_for_accuracy'):
    return F.FastDialogueTurn(assessment=a or assessment(), selected_talk_move=move, reply=r or reply(ack=False))


def input_context(call):
    return json.loads(call['input'][0]['content'][0]['text'])


class FastDialogueTests(unittest.TestCase):
    def setUp(self):
        F.SESSIONS.clear()

    def data(self, **changes):
        data=dict(trigger='submission', scene=deepcopy(SCENE), original_scene=deepcopy(SCENE),
                  explanation='Food needs energy.', task='Explain the transfers in this model.', goals=[], message='', edits=[])
        data.update(changes)
        return data

    def run_feedback(self, data, client, tmp, **options):
        return F.handle(data, client, tmp, 'test-review', fast_dialogue_model='test-fast', **options)

    def start(self, tmp, **options):
        return self.run_feedback(self.data(), FakeClient([assessment(), reply()]), tmp, **options)

    def begin(self, tmp, sid):
        candidate=reply('Revise this connection using the transfer direction, then explain your reason.', False,
                        revision_plan='Revise this connection and explain how it represents the transfer.', revision_plan_ids=['o3'], next_step='revise')
        return self.run_feedback(dict(trigger='message', session_id=sid, intent='begin_revision', message='Begin a revision.'),
                                 FakeClient([turn(r=candidate, move='propose_revision_plan')]), tmp)

    def pending_reason(self, tmp, sid):
        self.begin(tmp, sid)
        scene=deepcopy(SCENE)
        scene['objects'][0]['label']='Student revision'
        self.run_feedback(dict(trigger='workspace-complete', session_id=sid, scene=scene, explanation='', edits=[]),
                          FakeClient([assessment(), reply('How does this change better represent your idea?',
                                                         acknowledgment='You revised the label.', acknowledgment_ids=['o1'])]), tmp)
        return F.SESSIONS[sid]['state']['committed']['scene']

    def test_single_fast_call_uses_compact_committed_topology_without_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            figure_context='The given figure supplies the task constraints; the student model supplies the response.'
            first_client=FakeClient([assessment(task_figure_context=figure_context), reply()])
            first=self.run_feedback(self.data(), first_client, tmp, question_image='data:image/png;base64,dGVzdA==')
            self.assertEqual(len(first_client.calls), 2)
            self.assertTrue(any(p['type']=='input_image' for p in first_client.calls[0]['input'][0]['content']))
            client=FakeClient([turn()])
            public=self.run_feedback(dict(trigger='message', session_id=first['session_id'], message='It needs energy to grow.'), client, tmp)
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(client.calls[0]['model'], 'test-fast')
            self.assertIs(client.calls[0]['text_format'], F.FastDialogueTurn)
            self.assertEqual(client.calls[0]['reasoning'], {'effort':'low'})
            self.assertEqual(public['api_calls'], 1)
            content=client.calls[0]['input'][0]['content']
            self.assertEqual([part['type'] for part in content], ['input_text'])
            context=input_context(client.calls[0])
            self.assertNotIn('original', context)
            self.assertNotIn('source_id', context)
            self.assertNotIn('previous_submission', context)
            self.assertNotIn('edits', context['committed'])
            self.assertEqual(context['task_figure_context'],figure_context)
            self.assertIn('routing_state', context)
            self.assertIn('accuracy_started_at',context['routing_state'])
            self.assertIn('thinking_opportunity_count',context['routing_state'])
            self.assertTrue(all('version' in contribution for contribution in context['dialogue']))
            self.assertNotIn('glyphs', context['committed']['scene']['objects'][0])
            self.assertEqual([r['id'] for r in context['committed']['scene']['relations']], [r['id'] for r in SCENE['relations']])
            self.assertLess(len(json.dumps(context)), len(json.dumps(input_context(first_client.calls[0]))))

    def test_task_figure_without_cached_givens_uses_full_image_assessment(self):
        with tempfile.TemporaryDirectory() as tmp:
            given='data:image/png;base64,dGVzdA=='
            first=self.run_feedback(self.data(),FakeClient([assessment(),reply()]),tmp,question_image=given)
            self.assertEqual(F.SESSIONS[first['session_id']]['state']['task_figure_context'],'')
            context_text='The task figure specifies the starting model and its required constraints.'
            client=FakeClient([assessment(task_figure_context=context_text),reply(ack=False)])
            public=self.run_feedback(dict(trigger='message',session_id=first['session_id'],message='It needs energy.'),client,tmp)
            self.assertEqual(len(client.calls),2)
            self.assertIs(client.calls[0]['text_format'],F.Assessment)
            parts=client.calls[0]['input'][0]['content']
            self.assertEqual([part['image_url'] for part in parts if part['type']=='input_image'],[given])
            self.assertEqual(public['api_calls'],2)
            self.assertEqual(F.SESSIONS[first['session_id']]['state']['task_figure_context'],context_text)

    def test_fast_assessment_cannot_replace_cached_given_figure_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            cached='The task figure specifies the starting model and its required constraints.'
            first=self.run_feedback(self.data(),FakeClient([assessment(task_figure_context=cached),reply()]),tmp,
                                    question_image='data:image/png;base64,dGVzdA==')
            client=FakeClient([turn(assessment(task_figure_context='UNVERIFIED REPLACEMENT'))])
            self.run_feedback(dict(trigger='message',session_id=first['session_id'],message='It needs energy.'),client,tmp)
            self.assertEqual(len(client.calls),1)
            self.assertTrue(input_context(client.calls[0])['task_figure_present'])
            self.assertEqual(input_context(client.calls[0])['task_figure_context'],cached)
            self.assertEqual(F.SESSIONS[first['session_id']]['state']['task_figure_context'],cached)

    def test_restored_figure_session_without_cache_migrates_and_uses_full_assessment(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=self.run_feedback(self.data(),FakeClient([assessment(),reply()]),tmp,
                                    question_image='data:image/png;base64,dGVzdA==')
            state=F.SESSIONS[first['session_id']]['state']
            state.pop('task_figure_context')
            client=FakeClient([assessment(task_figure_context='The given figure supplies the task constraints.'),reply(ack=False)])
            self.run_feedback(dict(trigger='message',session_id=first['session_id'],message='It needs energy.'),client,tmp)
            self.assertEqual(len(client.calls),2)
            self.assertEqual(F.SESSIONS[first['session_id']]['state']['task_figure_context'],
                             'The given figure supplies the task constraints.')

    def test_fast_path_ignores_unsubmitted_drawing_and_replacement_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            state=deepcopy(F.SESSIONS[sid]['state'])
            draft=deepcopy(SCENE)
            draft['objects'][0]['label']='PRIVATE DRAFT'
            client=FakeClient([turn()])
            public=self.run_feedback(dict(trigger='message', session_id=sid, message='It needs energy.',
                                          scene=draft, explanation='PRIVATE DRAFT', task='UNTRUSTED REPLACEMENT'), client, tmp)
            serialized=json.dumps(input_context(client.calls[0]))
            self.assertNotIn('PRIVATE DRAFT', serialized)
            self.assertNotIn('UNTRUSTED REPLACEMENT', serialized)
            self.assertEqual(F.SESSIONS[sid]['state']['committed'], state['committed'])
            self.assertEqual(public['drawing_version'], 1)

    def test_legacy_path_still_uses_separate_evaluator_and_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            client=FakeClient([assessment(), reply(ack=False)])
            public=F.handle(dict(trigger='message', session_id=sid, message='It needs energy.'), client, tmp, 'test-review')
            self.assertEqual(len(client.calls), 2)
            self.assertIs(client.calls[0]['text_format'], F.Assessment)
            self.assertIs(client.calls[1]['text_format'], F.TutorReply)
            self.assertEqual(public['api_calls'], 2)

    def test_changed_model_review_retains_full_assessment_and_two_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            self.begin(tmp, sid)
            changed=deepcopy(SCENE)
            changed['objects'][0]['label']='Student revision'
            client=FakeClient([assessment(revision_reason_sufficient=True, revision_resolved=True,
                                          next_focus_kind='none', areas_for_improvement=[], ambiguities=[]),
                               reply('Any further questions?', acknowledgment='You revised the source label.', acknowledgment_ids=['o1'])])
            public=self.run_feedback(dict(trigger='workspace-complete', session_id=sid, scene=changed, explanation='', edits=[],
                                          revision_reason='The new label names the source of this transfer.'), client, tmp)
            self.assertEqual(len(client.calls), 2)
            self.assertEqual([call['model'] for call in client.calls], ['test-review', 'test-review'])
            context=input_context(client.calls[0])
            self.assertIn('original', context)
            self.assertIn('edits', context['committed'])
            self.assertEqual(public['talk_move'], 'invite_dialogue')
            self.assertFalse(public['edit_enabled'])

    def test_hint_is_direct_instruction_in_one_call_without_edit_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            client=FakeClient([turn(r=guidance(), move='provide_hints_guidance')])
            public=self.run_feedback(dict(trigger='message', session_id=sid, intent='hint', message='I need a hint.'), client, tmp)
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(public['talk_move'], 'provide_hints_guidance')
            self.assertNotIn('?', public['content'])
            self.assertFalse(public['edit_enabled'])
            self.assertIn(public['guidance_instruction'], public['content'])
            self.assertTrue(public['hint_request_pending'])
            self.assertEqual(public['hint_turns_remaining'],2)
            before=deepcopy(F.SESSIONS[sid]['state'])
            blocked=FakeClient([])
            with self.assertRaisesRegex(F.FeedbackError,'Dialogue question for 2 more turns'):
                self.run_feedback(dict(trigger='message',session_id=sid,intent='hint',message='I need a hint.'),blocked,tmp)
            self.assertEqual(blocked.calls,[])
            self.assertEqual(F.SESSIONS[sid]['state'],before)
            # Failed delivery must not unlock the button or discard the last hint.
            with self.assertRaisesRegex(RuntimeError,'offline'):
                self.run_feedback(dict(trigger='message',session_id=sid,message='The source supplies the energy.'),
                                  FakeClient([RuntimeError('offline')]),tmp)
            self.assertEqual(F.SESSIONS[sid]['state'],before)
            answered=self.run_feedback(dict(trigger='message',session_id=sid,message='The source supplies the energy.'),
                                       FakeClient([turn()]),tmp)
            self.assertTrue(answered['hint_request_pending'])
            self.assertEqual(answered['hint_turns_remaining'],1)
            blocked=FakeClient([])
            with self.assertRaisesRegex(F.FeedbackError,'Dialogue question for 1 more turn'):
                self.run_feedback(dict(trigger='message',session_id=sid,intent='hint',message='I need a hint.'),blocked,tmp)
            self.assertEqual(blocked.calls,[])
            answered=self.run_feedback(dict(trigger='message',session_id=sid,message='It transfers energy to the next part.'),
                                       FakeClient([turn(move='invite_elaboration_reasoning')]),tmp)
            self.assertFalse(answered['hint_request_pending'])
            self.assertEqual(answered['hint_turns_remaining'],0)
            again=self.run_feedback(dict(trigger='message',session_id=sid,intent='hint',message='I need a hint.'),
                                    FakeClient([turn(r=guidance(),move='provide_hints_guidance')]),tmp)
            self.assertTrue(again['hint_request_pending'])
            self.assertEqual(again['hint_turns_remaining'],2)

    def test_typed_hint_request_is_direct_help_without_automatic_edit_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            a=assessment(student_stuck=True)
            client=FakeClient([turn(a,guidance(),'provide_hints_guidance')])
            public=self.run_feedback(dict(trigger='message',session_id=sid,message='Please give me a hint.'),client,tmp)
            self.assertEqual(public['talk_move'],'provide_hints_guidance')
            self.assertFalse(public['edit_enabled'])
            self.assertNotIn('?',public['content'])
            self.assertEqual(len(client.calls),1)

    def test_three_unsuccessful_answers_precede_automatic_bounded_help(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            check=assessment(current_question_target='judge-current-transfer')
            self.run_feedback(dict(trigger='message',session_id=sid,message='It needs energy.'),
                              FakeClient([turn(check)]),tmp)
            state=F.SESSIONS[sid]['state']
            self.assertEqual(state['thinking_opportunity_count'],1)

            uncertain=assessment(talk_move='provide_hints_guidance',student_stuck=True,
                                 progress_status='stalled',current_question_target='predict-from-source',
                                 current_response_outcome='unsuccessful',outcome_evidence='I think the receiving end is the source.')
            premature=guidance('Reverse the connection so its direction follows the transfer source.',
                               guidance_requires_edit=True,next_step='revise')
            invitation=reply('Let’s inspect its source. What does the current arrow suggest is being transferred?',False)
            client=FakeClient([turn(uncertain,premature,'provide_hints_guidance'),invitation])
            public=self.run_feedback(dict(trigger='message',session_id=sid,message='I think the receiving end is the source.'),client,tmp)
            self.assertEqual(public['talk_move'],'invite_elaboration_reasoning')
            self.assertFalse(public['edit_enabled'])
            self.assertEqual(len(client.calls),2)
            policy=input_context(client.calls[-1])['thinking_policy']
            self.assertEqual(policy['opportunities_offered'],1)
            self.assertFalse(policy['hint_allowed'])
            self.assertFalse(policy['repair_instruction_allowed'])
            self.assertEqual(policy['unsuccessful_responses'],1)
            self.assertNotIn('Reverse the connection',public['content'])
            self.assertEqual(F.SESSIONS[sid]['state']['thinking_opportunity_count'],2)
            self.assertEqual(F.SESSIONS[sid]['state']['unsuccessful_response_count'],1)

            second=assessment(talk_move='invite_elaboration_reasoning',student_stuck=True,
                              progress_status='stalled',current_question_target='identify-transfer-source',
                              current_response_outcome='unsuccessful',outcome_evidence='I think the transfer has no source.')
            second_reply=reply('What does your arrow show about the source?',False)
            client=FakeClient([turn(second,second_reply,'invite_elaboration_reasoning')])
            continued=self.run_feedback(dict(trigger='message',session_id=sid,message='I think the transfer has no source.'),client,tmp)
            self.assertEqual(continued['talk_move'],'invite_elaboration_reasoning')
            self.assertFalse(continued['edit_enabled'])
            self.assertEqual(F.SESSIONS[sid]['state']['unsuccessful_response_count'],2)
            self.assertEqual(len(client.calls),1)

            help_assessment=assessment(talk_move='provide_hints_guidance',student_stuck=True,
                                       progress_status='stalled',current_question_target='use-transfer-principle',
                                       current_response_outcome='unsuccessful',
                                       outcome_evidence='I still cannot explain the source of the transfer.')
            help_reply=guidance('An arrow follows the transfer from its source. Reverse this connection to test that direction.',
                                guidance_requires_edit=True,next_step='revise')
            client=FakeClient([turn(help_assessment,help_reply,'provide_hints_guidance')])
            helped=self.run_feedback(dict(trigger='message',session_id=sid,message='I still cannot explain the source of the transfer.'),client,tmp)
            self.assertEqual(helped['talk_move'],'provide_hints_guidance')
            self.assertNotIn('?',helped['content'])
            self.assertTrue(helped['edit_enabled'])
            self.assertEqual(len(client.calls),1)
            self.assertEqual(F.SESSIONS[sid]['state']['unsuccessful_response_count'],3)

    def test_failed_early_hint_does_not_consume_thinking_opportunities(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            self.run_feedback(dict(trigger='message',session_id=sid,message='It needs energy.'),
                              FakeClient([turn(assessment(current_question_target='judge-transfer'))]),tmp)
            saved=deepcopy(F.SESSIONS[sid]['state'])
            premature=guidance('Reverse this connection.',guidance_requires_edit=True,next_step='revise')
            client=FakeClient([turn(assessment(student_stuck=True,talk_move='provide_hints_guidance'),premature,
                                    'provide_hints_guidance'),deepcopy(premature)])
            with self.assertRaises(F.FeedbackError):
                self.run_feedback(dict(trigger='message',session_id=sid,message='I think the receiving end is the source.'),client,tmp)
            self.assertEqual(F.SESSIONS[sid]['state'],saved)
            self.assertEqual(saved['thinking_opportunity_count'],1)

    def test_begin_revision_opens_editor_without_a_mastery_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            public=self.begin(tmp, sid)
            self.assertEqual(public['api_calls'], 1)
            self.assertEqual(public['talk_move'], 'propose_revision_plan')
            self.assertTrue(public['edit_enabled'])
            self.assertFalse(F.SESSIONS[sid]['state']['assessment']['ready_for_revision'])

    def test_fast_thinking_turns_advance_to_a_grounded_revision_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            checked=self.run_feedback(dict(trigger='message', session_id=sid, message='It needs energy.'), FakeClient([turn()]), tmp)
            support=turn(assessment(talk_move='prompt_reflection',
                cognitive_conflict='The stated source principle conflicts with the connection.',cognitive_conflict_evidence='The source determines the direction.',
                reflection_target='The learner explains direction using the transfer source.',
                reflection_evidence='The source determines the direction.',
                reflection_reference='The direction of the submitted connection.',reflection_reference_source='task_or_observable',
                reflection_need='Evaluate whether the drawn connection agrees with that source-based explanation.'),
                reply('Compare your connection with the transfer source. Which direction fits?', False), 'prompt_reflection')
            thinking=self.run_feedback(dict(trigger='message', session_id=sid, message='The source determines the direction.'), FakeClient([support]), tmp)
            reason='the arrow should follow the transfer from its source'
            a=assessment(ready_for_revision=True, readiness_evidence=reason, progress_status='ready')
            r=reply('Use that direction to revise this connection, then explain the change.', False,
                    revision_plan='Revise the connection using the transfer direction and explain your reason.', revision_plan_ids=['o3'], next_step='revise')
            ready=self.run_feedback(dict(trigger='message', session_id=sid, message='I see that '+reason+'.'),
                                    FakeClient([turn(a, r, 'propose_revision_plan')]), tmp)
            self.assertEqual([item['api_calls'] for item in (checked, thinking, ready)], [1, 1, 1])
            self.assertEqual(thinking['talk_move'], 'prompt_reflection')
            self.assertFalse(thinking['edit_enabled'])
            self.assertEqual(ready['talk_move'], 'propose_revision_plan')
            self.assertTrue(ready['edit_enabled'])

    def test_reason_chat_keeps_actual_changed_model_and_uses_previous_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            before=deepcopy(F.SESSIONS[sid]['state']['committed']['scene'])
            changed=self.pending_reason(tmp, sid)
            a=assessment(revision_reason_sufficient=True, revision_resolved=True, next_focus_kind='none', areas_for_improvement=[], ambiguities=[])
            client=FakeClient([turn(a, reply('You explained the revision. Any further questions?', False, visual_action='none', visual_delivery='none'), 'invite_dialogue')])
            public=self.run_feedback(dict(trigger='message', session_id=sid,
                                          message='I renamed the source because this makes the transfer clear.'), client, tmp)
            self.assertEqual(len(client.calls), 1)
            context=input_context(client.calls[0])
            self.assertIn('previous_submission', context)
            self.assertEqual(context['previous_submission']['scene']['objects'][0]['label'], before['objects'][0]['label'])
            self.assertNotIn('glyphs', context['previous_submission']['scene']['objects'][0])
            self.assertEqual(F.SESSIONS[sid]['state']['committed']['scene'], changed)
            self.assertFalse(public['awaiting_revision_reason'])
            self.assertFalse(public['edit_enabled'])
            self.assertEqual(public['drawing_version'], 2)

    def test_mismatched_combined_move_gets_one_authoritative_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            client=FakeClient([turn(r=reply('What familiar transfer helps you?', False), move='build_on_prior_knowledge'),
                               reply('Does this direction represent the transfer accurately?', False)])
            public=self.run_feedback(dict(trigger='message', session_id=sid, message='Energy reaches the food.'), client, tmp)
            self.assertEqual(len(client.calls), 2)
            self.assertIs(client.calls[1]['text_format'], F.TutorReply)
            self.assertIn('authoritative selected_talk_move=press_for_accuracy', input_context(client.calls[1])['rewrite_requirement'])
            self.assertEqual(public['talk_move'], 'press_for_accuracy')
            self.assertEqual(public['model'], 'test-fast')

    def test_invalid_fast_reply_gets_one_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            client=FakeClient([turn(r=reply('Why? How?', False)), reply('Does this direction match the source?', False)])
            public=self.run_feedback(dict(trigger='message', session_id=sid, message='It uses energy.'), client, tmp)
            self.assertEqual(len(client.calls), 2)
            self.assertEqual(public['api_calls'], 2)
            self.assertEqual(public['content'].count('?'), 1)

    def test_sparse_gap_and_redundant_metadata_can_be_repaired_without_another_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            a=assessment(areas_for_improvement=[],visual_intent='explain-mechanism',mechanism_paths=paths())
            r=reply('Watch the moving arrows. Does this route follow the transfer source?',False,visual_action='trace',mechanism_paths=paths(),
                    focus_id='o3',focus_ids=['o3','r1','r3','r7','o1'])
            r.check_observation=r.content;r.review=[]
            client=FakeClient([turn(a,r)])
            public=self.run_feedback(dict(trigger='message',session_id=sid,message='There are two different paths here.'),client,tmp)
            self.assertEqual(len(client.calls),1)
            self.assertEqual(public['talk_move'],'press_for_accuracy')
            self.assertEqual(public['review'],[row.model_dump() for row in a.criteria])
            self.assertEqual(public['focus_ids'],['o3','o1'])
            self.assertEqual(public['mechanism_paths'],[path.model_dump() for path in paths()])
            self.assertEqual(public['content'],r.content)

    def test_rewrite_retains_both_routing_and_validation_reasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            diagnosed=reply('This connection is incorrect. Where should you move it?',False,reveals_diagnosis=True,question_purpose='plan_revision')
            client=FakeClient([turn(r=diagnosed,move='build_on_prior_knowledge'),reply('Does this connection match the transfer source?',False)])
            public=self.run_feedback(dict(trigger='message',session_id=sid,message='There are two different paths here.'),client,tmp)
            requirement=input_context(client.calls[1])['rewrite_requirement']
            self.assertIn('authoritative selected_talk_move=press_for_accuracy',requirement)
            self.assertIn('without announcing its diagnosis',requirement)
            reports=[json.loads(path.read_text()) for path in Path(tmp).glob('feedback_turn_*/validation.json')]
            self.assertEqual(len(reports),1)
            self.assertEqual(reports[0]['initial_problem'],requirement)
            self.assertEqual(reports[0]['rewrite_problem'],'')
            self.assertEqual(public['talk_move'],'press_for_accuracy')

    def test_failed_fast_rewrite_leaves_progress_and_editor_state_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            saved=deepcopy(F.SESSIONS[sid]['state'])
            client=FakeClient([turn(r=reply('Why? How?', False)), reply('What? Why?', False)])
            with self.assertRaises(F.FeedbackError):
                self.run_feedback(dict(trigger='message', session_id=sid, message='It uses energy.'), client, tmp)
            self.assertEqual(len(client.calls), 2)
            self.assertEqual(F.SESSIONS[sid]['state'], saved)

    def test_invalid_private_criteria_fail_before_a_writer_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            saved=deepcopy(F.SESSIONS[sid]['state'])
            a=assessment()
            a.criteria=a.criteria[:1]
            client=FakeClient([turn(a)])
            with self.assertRaises(F.FeedbackError):
                self.run_feedback(dict(trigger='message', session_id=sid, message='It uses energy.'), client, tmp)
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(F.SESSIONS[sid]['state'], saved)

    def test_fast_turn_keeps_learning_goal_and_private_diagnostics_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=self.start(tmp)
            client=FakeClient([turn(assessment(learning_goal='An unrelated replacement goal.'))])
            public=self.run_feedback(dict(trigger='message', session_id=first['session_id'], message='It uses energy.'), client, tmp)
            self.assertEqual(public['learning_goal'], first['learning_goal'])
            self.assertEqual(public['criteria'], first['criteria'])
            self.assertNotIn('PRIVATE', json.dumps(public))
            self.assertIn('previous_assessment', input_context(client.calls[0]))

    def test_static_mechanism_reply_is_rewritten_to_matching_approved_animation(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            a=assessment(visual_intent='explain-mechanism', mechanism_paths=paths(), visual_focus_ids=['r1'], focus_id='r1')
            static=reply('Does this route show the transfer?', False, focus_id='r1', focus_ids=['r1'])
            animated=reply('Watch the moving arrows. Does this route carry the transfer to its destination?', False,
                           focus_id='r1', focus_ids=['r1'], visual_action='trace')
            client=FakeClient([turn(a, static), animated])
            public=self.run_feedback(dict(trigger='message', session_id=sid, message='How does the transfer travel?'), client, tmp)
            self.assertEqual(len(client.calls), 2)
            self.assertIn('approved mechanism animation', input_context(client.calls[1])['rewrite_requirement'])
            self.assertEqual(public['visual_action'], 'trace')
            self.assertEqual(public['visual_delivery'], 'automatic')
            self.assertEqual([s['relation_id'] for s in public['mechanism_paths'][0]['steps']], ['r1', 'r3', 'r7'])

    def test_matching_conditional_mechanism_animates_in_one_fast_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            a=assessment(visual_intent='explain-mechanism', mechanism_paths=paths(), visual_focus_ids=['r1'], focus_id='r1',
                         mechanism_requires_condition=True, mechanism_condition='When the process is running')
            r=reply('When the process is running, watch the moving arrows. Does the transfer follow the connection you described?', False,
                    focus_id='r1', focus_ids=['r1'], visual_action='trace')
            client=FakeClient([turn(a, r)])
            public=self.run_feedback(dict(trigger='message', session_id=sid, message='How does this process work?'), client, tmp)
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(public['visual_action'], 'trace')
            self.assertEqual(public['mechanism_condition'], a.mechanism_condition)
            self.assertEqual(F.SESSIONS[sid]['state']['committed']['scene'], F.validate_sketch(SCENE).model_dump())

    def test_inspection_turn_keeps_static_highlights_in_one_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            a=assessment(visual_intent='inspect-diagram', mechanism_paths=paths())
            client=FakeClient([turn(a, reply('Does this label name the correct stage?', False))])
            public=self.run_feedback(dict(trigger='message', session_id=sid, message='This is the label I chose.'), client, tmp)
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(public['visual_action'], 'highlight')
            self.assertEqual(public['mechanism_paths'], [])

    def test_fresh_issue_diagnosis_and_repair_question_are_rewritten_as_a_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            a=assessment(criterion='c2',focus_id='o2',talk_move='build_on_prior_knowledge')
            diagnosis=reply('This connection carries the transfer in the wrong direction. Where should you move it?',False,
                            focus_id='o2',focus_ids=['o2'],reveals_diagnosis=True,question_purpose='plan_revision')
            check=reply('Look at this connection. Does its direction match the source of the transfer?',False,focus_id='o2',focus_ids=['o2'])
            client=FakeClient([turn(a,diagnosis,'build_on_prior_knowledge'),check])
            public=self.run_feedback(dict(trigger='message',session_id=sid,message='yes'),client,tmp)
            self.assertEqual(len(client.calls),2)
            self.assertEqual(public['talk_move'],'press_for_accuracy')
            self.assertEqual(public['question_purpose'],'judge_current_diagram')
            self.assertFalse(public['reveals_diagnosis'])
            self.assertNotIn('wrong direction',public['content'])
            state=F.SESSIONS[sid]['state']
            self.assertEqual(state['accuracy_focus'],['c2','o2'])
            self.assertEqual(state['accuracy_started_at'],state['version'])
            self.assertEqual(state['thinking_started_at'],0)
            self.assertFalse(public['edit_enabled'])

    def test_invalid_press_rewrite_cannot_commit_a_new_issue_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id'];saved=deepcopy(F.SESSIONS[sid]['state'])
            diagnosis=reply('This connection is incorrect. Where should you move it?',False,reveals_diagnosis=True,question_purpose='plan_revision')
            client=FakeClient([turn(r=diagnosis),deepcopy(diagnosis)])
            with self.assertRaises(F.FeedbackError):
                self.run_feedback(dict(trigger='message',session_id=sid,message='yes'),client,tmp)
            self.assertEqual(len(client.calls),2)
            self.assertEqual(F.SESSIONS[sid]['state'],saved)

    def test_learner_diagnosis_after_current_check_can_be_briefly_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            checked=self.run_feedback(dict(trigger='message',session_id=sid,message='It needs energy.'),FakeClient([turn()]),tmp)
            self.assertEqual(checked['talk_move'],'press_for_accuracy')
            quote='The direction of the transfer does not match its source.'
            a=assessment(talk_move='build_on_prior_knowledge',learner_diagnosis_evidence=quote,
                         prior_knowledge_connection='Apply the familiar energy need to identifying a source.',
                         prior_knowledge_evidence='Food needs energy.')
            r=reply('Good catch, that direction does not match the transfer. In a familiar transfer, how do you identify its source?',False,
                    reveals_diagnosis=True,question_purpose='develop_reasoning')
            client=FakeClient([turn(a,r,'build_on_prior_knowledge')])
            public=self.run_feedback(dict(trigger='message',session_id=sid,message=quote),client,tmp)
            self.assertEqual(len(client.calls),1)
            self.assertEqual(public['talk_move'],'build_on_prior_knowledge')
            self.assertTrue(public['reveals_diagnosis'])
            self.assertFalse(public['edit_enabled'])

    def test_explicit_hint_can_explain_a_diagnosis_before_accuracy_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            r=guidance('This connection carries the transfer in the wrong direction. Follow its source toward the destination.',reveals_diagnosis=True)
            client=FakeClient([turn(r=r,move='provide_hints_guidance')])
            public=self.run_feedback(dict(trigger='message',session_id=sid,intent='hint',message='I need a hint.'),client,tmp)
            self.assertEqual(len(client.calls),1)
            self.assertEqual(public['talk_move'],'provide_hints_guidance')
            self.assertTrue(public['reveals_diagnosis'])
            self.assertNotIn('?',public['content'])
            self.assertFalse(public['edit_enabled'])

    def test_engaging_opening_requires_one_supportive_emoji(self):
        with tempfile.TemporaryDirectory() as tmp:
            warm=reply(acknowledgment='Nice work 😊 You correctly connected energy and food production.')
            client=FakeClient([assessment(), reply(), warm])
            public=self.run_feedback(self.data(), client, tmp, engaging_voice=True)
            self.assertEqual(len(client.calls), 3)
            self.assertIn('😊', public['content'])
            self.assertIn('supportive emoji', input_context(client.calls[2])['rewrite_requirement'])

    def test_teacher_style_spaces_emojis_after_two_plain_turns(self):
        state={'turns':[]}
        self.assertTrue(F.teacher_style(state, 'submission')['emoji_expected'])
        state['turns']=[{'content':'Nice work 😊 Why does it connect?'}]
        self.assertFalse(F.teacher_style(state, 'message')['emoji_expected'])
        state['turns'].append({'content':'That observation helps. What is the next step?'})
        self.assertFalse(F.teacher_style(state, 'message')['emoji_expected'])
        state['turns'].append({'content':'Use the transfer direction to choose a change.'})
        self.assertTrue(F.teacher_style(state, 'message')['emoji_expected'])

    def test_fast_style_schedule_can_rewrite_once_without_changing_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            # Add a second plain turn so the next turn expects occasional warmth.
            self.run_feedback(dict(trigger='message', session_id=sid, message='It needs energy.'), FakeClient([turn()]), tmp)
            a=assessment(talk_move='build_on_prior_knowledge',
                         prior_knowledge_connection='Connect the familiar energy need to the transfer source.',
                         prior_knowledge_evidence='Food needs energy.')
            client=FakeClient([turn(a, reply('In a familiar transfer, how do you identify its source?', False), 'build_on_prior_knowledge'),
                               reply('Nice observation 😊 In a familiar transfer, how do you identify its source?', False)])
            public=self.run_feedback(dict(trigger='message', session_id=sid, message='I can connect that idea.'), client, tmp, engaging_voice=True)
            self.assertEqual(len(client.calls), 2)
            self.assertEqual(public['talk_move'], 'build_on_prior_knowledge')
            self.assertIn('😊', public['content'])

    def test_performance_artifact_records_fast_path_without_timing_promises(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            public=self.run_feedback(dict(trigger='message', session_id=sid, message='It uses energy.'), FakeClient([turn()]), tmp)
            reports=[json.loads(path.read_text()) for path in Path(tmp).glob('feedback_turn_*/performance.json')]
            report=next(item for item in reports if item['path']=='fast-dialogue')
            self.assertEqual(len(report['calls']), 1)
            self.assertEqual(report['calls'][0]['stage'], 'dialogue')
            self.assertEqual(report['calls'][0]['model'], 'test-fast')
            self.assertGreater(report['calls'][0]['input_chars'], 0)
            self.assertGreaterEqual(report['calls'][0]['elapsed_seconds'], 0)
            self.assertEqual(report['elapsed_seconds'], public['elapsed_seconds'])


if __name__=='__main__':
    unittest.main()
