"""Evidence-based support selection and shortened review loops.

All calls use typed local stubs. No browser, network, or paid model calls.
"""
from copy import deepcopy
import tempfile
import unittest

from test_feedback import F, P, SCENE, FakeClient, assessment, reply


class SupportRoutingTests(unittest.TestCase):
    def setUp(self):
        F.SESSIONS.clear()

    def data(self, **changes):
        value=dict(trigger='submission',scene=deepcopy(SCENE),original_scene=deepcopy(SCENE),
                   explanation='Food needs energy.',task='Explain the represented transfers.',
                   goals=[],message='',edits=[])
        value.update(changes)
        return value

    def state(self):
        state,_,_=F.prepare(None,self.data())
        state.update(version=4,progress_focus=['c3','o3'],accuracy_focus=['c3','o3'],accuracy_started_at=1,
                     issue_check_focus=['c3','o3'],issue_check_started_at=1,
                     thinking_focus=['c3','o3'],thinking_started_at=2,
                     response_progress_focus=['c3','o3'],stage='thinking-dialogue',
                     _current_trigger='message',_current_message='I am considering the transfer.')
        return state

    def reviewed_state(self):
        state=self.state()
        state['previous_submission']=deepcopy(state['committed'])
        state['committed']['scene']['objects'][0]['label']='Revised source label'
        state['assessment']=assessment().model_dump()
        state['_current_trigger']='workspace-complete'
        state['awaiting_revision_reason']=False
        return state

    def test_support_uses_the_actual_obstacle_instead_of_requested_move_or_rotation(self):
        state=self.state()
        message='Food needs energy.'
        prior=assessment(talk_move='prompt_reflection',
            prior_knowledge_connection='Connect the familiar need for energy to the represented transfer.',
            prior_knowledge_evidence=message)
        self.assertEqual(P.select_move(prior,state,'message',message),'build_on_prior_knowledge')
        conflict=assessment(talk_move='build_on_prior_knowledge',
            prior_knowledge_connection=prior.prior_knowledge_connection,prior_knowledge_evidence=message,
            cognitive_conflict='The learner describes needing energy but claims that no source is needed.',
            cognitive_conflict_evidence=message)
        self.assertEqual(P.select_move(conflict,state,'message',message),'build_on_prior_knowledge',
                         'A conflict label alone does not establish an evaluative task.')
        conflict.reflection_target='The learner explains the need for energy.'
        conflict.reflection_evidence=message
        conflict.reflection_reference='The submitted relationship between source and receiver.'
        conflict.reflection_reference_source='task_or_observable'
        conflict.reflection_need='Evaluate whether the represented relationship supports that explanation.'
        self.assertEqual(P.select_move(conflict,state,'message',message),'prompt_reflection')
        incomplete=assessment(talk_move='build_on_prior_knowledge',reasoning_gap='Explain why this arrow represents the transfer.')
        self.assertEqual(P.select_move(incomplete,state,'message',message),'invite_elaboration_reasoning')
        state['last_question_target']='Explain the same connection.'
        state['turns']=[dict(student=message,content='What does the connection represent?',version=3,
                             trigger='message',talk_move='invite_elaboration_reasoning')]
        incomplete.current_question_target=state['last_question_target']
        self.assertEqual(P.select_move(incomplete,state,'message',message),'invite_elaboration_reasoning')

    def test_support_conditions_need_short_exact_learner_evidence(self):
        state=self.state()
        state['turns']=[dict(student='The source supplies energy.',content='The tutor says it transfers food.',version=3,
                             trigger='message',talk_move='invite_elaboration_reasoning')]
        for quote in ('','Invented learner knowledge.','The tutor says it transfers food.',
                      ' '.join('word'+str(i) for i in range(26))):
            with self.subTest(quote=quote):
                a=assessment(prior_knowledge_connection='Connect to a known source.',prior_knowledge_evidence=quote,
                             cognitive_conflict='Conflicting source interpretation.',cognitive_conflict_evidence=quote)
                self.assertEqual(P.select_move(a,state,'message','I am thinking.'),'invite_elaboration_reasoning')
        prior=assessment(prior_knowledge_connection='Connect to the familiar source.',
                         prior_knowledge_evidence='The source supplies energy.')
        self.assertEqual(P.select_move(prior,state,'message','I am thinking.'),'build_on_prior_knowledge')
        prior.prior_knowledge_evidence='Food needs energy.'
        self.assertEqual(P.select_move(prior,state,'message','I am thinking.'),'build_on_prior_knowledge')

    def test_initial_error_check_still_precedes_support_with_grounded_prior_knowledge(self):
        state,_,_=F.prepare(None,self.data())
        a=assessment(progress_status='new',prior_knowledge_connection='Link energy needs and sources.',
                     prior_knowledge_evidence='Food needs energy.',issue_priority_reason='The transfer is central to the task.')
        self.assertEqual(P.select_move(a,state,'submission'),'recognize_strengths')
        self.assertEqual(P.select_move(a,state,'message','Food needs energy.'),'press_for_accuracy')

    def test_one_clarification_check_then_support_for_the_same_issue(self):
        state,_,_=F.prepare(None,self.data())
        a=assessment(next_focus_kind='clarification',areas_for_improvement=[],
                     ambiguities=[dict(claim='The mark has two plausible meanings.',evidence='Unlabeled connection.')])
        self.assertEqual(P.select_move(a,state,'message','It shows the connection.'),'ask_for_clarification')
        P.update_progress(state,a,'ask_for_clarification',reply('Do you mean that this mark shows a connection?',False))
        state['version']+=1
        a.reasoning_gap='The meaning was named but its role still needs explanation.'
        self.assertEqual(P.select_move(a,state,'message','It connects the source to the food.'),'invite_elaboration_reasoning')

    def test_success_resets_the_failure_streak_and_next_failure_starts_at_one(self):
        state=self.state()
        state['unsuccessful_response_count']=2
        message='The source supplies energy.'
        success=assessment(current_response_outcome='successful',outcome_evidence=message)
        P.record_response_progress(success,state,message)
        self.assertEqual(state['unsuccessful_response_count'],0)
        state['version']+=1
        failure=assessment(current_response_outcome='unsuccessful',outcome_evidence='I do not know.')
        P.record_response_progress(failure,state,'I do not know.')
        self.assertEqual(state['unsuccessful_response_count'],1)
        self.assertFalse(P.guidance_progress(failure,state,'I do not know.')['automatic_guidance_due'])

    def test_explicit_review_outcomes_need_actual_delta_and_evidence(self):
        state=self.reviewed_state()
        a=assessment(revision_outcome='successful',revision_outcome_evidence='The new source label identifies the transfer origin.')
        policy=P.revision_review_policy(a,state,'workspace-complete')
        self.assertTrue(policy['active']);self.assertTrue(policy['praise_required'])
        self.assertTrue(policy['bypass_initial_check'])
        ids={o['id'] for o in SCENE['objects']}|{r['id'] for r in SCENE['relations']}
        neutral=reply('How does this relationship support your explanation?',
                      acknowledgment='You changed the source label.',acknowledgment_ids=['o1'])
        self.assertTrue(F.reply_problem(neutral,state,a,ids,'workspace-complete','','invite_elaboration_reasoning'))
        neutral.acknowledgment='Nice work, your corrected label now identifies the source.'
        self.assertFalse(F.reply_problem(neutral,state,a,ids,'workspace-complete','','invite_elaboration_reasoning'))
        a.revision_outcome_evidence=''
        self.assertFalse(P.revision_review_policy(a,state,'workspace-complete')['active'])
        a.revision_outcome_evidence='The source label was corrected.'
        state['committed']=deepcopy(state['previous_submission'])
        self.assertFalse(P.revision_review_policy(a,state,'workspace-complete')['active'])

    def test_successful_review_praises_and_enters_next_issue_support_without_a_new_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=F.handle(self.data(),FakeClient([assessment(),reply()]),tmp,'offline-stub')
            sid=first['session_id'];F.begin_revision({'session_id':sid})
            changed=deepcopy(SCENE);changed['objects'][0]['label']='Corrected source'
            next_issue=assessment(criterion='c1',focus_id='o2',progress_status='new',revision_outcome='successful',
                revision_outcome_evidence='The new source label fixes the previously discussed issue.',
                prior_knowledge_connection='Connect the familiar need for energy to the next relationship.',
                prior_knowledge_evidence='Food needs energy.',
                reasoning_gap='Explain the next represented relationship.',
                issue_priority_reason='This relationship is the remaining prerequisite for the task.')
            recognized=reply('How does this relationship connect to the need for energy?',
                acknowledgment='Nice work, your revised label correctly identifies the source.',acknowledgment_ids=['o1'],
                focus_id='o2',focus_ids=['o2'])
            public=F.handle(dict(trigger='workspace-complete',session_id=sid,scene=changed,explanation='Food needs energy.',edits=[]),
                            FakeClient([next_issue,recognized]),tmp,'offline-stub')
            self.assertEqual(public['talk_move'],'build_on_prior_knowledge')
            self.assertFalse(public['awaiting_revision_reason'])
            self.assertFalse(public['edit_enabled'])
            state=F.SESSIONS[sid]['state']
            self.assertEqual(state['review_support_focus'],['c1','o2'])
            next_issue.progress_status='developing';next_issue.revision_outcome='not_reviewed'
            follow=F.handle(dict(trigger='message',session_id=sid,message='It carries the energy.'),
                          FakeClient([next_issue,reply('How does this connection support your explanation?',False,focus_id='o2',focus_ids=['o2'])]),
                          tmp,'offline-stub')
            self.assertEqual(follow['talk_move'],'build_on_prior_knowledge')

    def test_unsuccessful_review_cannot_diagnose_a_different_issue_or_commit_it(self):
        bad=assessment(criterion='c1',focus_id='o2',revision_outcome='unsuccessful',
            revision_outcome_evidence='The revised source label does not resolve the disputed transfer.',
            cognitive_conflict='The revised source and represented transfer conflict.',
            cognitive_conflict_evidence='Food needs energy.')
        state=self.reviewed_state()
        policy=P.revision_review_policy(bad,state,'workspace-complete')
        self.assertFalse(policy['active']);self.assertTrue(policy['invalid_reason'])
        self.assertFalse(P.diagnosis_policy(bad,state,'','prompt_reflection')['allowed'])
        with tempfile.TemporaryDirectory() as tmp:
            first=F.handle(self.data(),FakeClient([assessment(),reply()]),tmp,'offline-stub')
            sid=first['session_id'];F.begin_revision({'session_id':sid})
            before=deepcopy(F.SESSIONS[sid]['state'])
            changed=deepcopy(SCENE);changed['objects'][0]['label']='Attempted source correction'
            client=FakeClient([bad])
            with self.assertRaisesRegex(F.FeedbackError,'issue under revision'):
                F.handle(dict(trigger='workspace-complete',session_id=sid,scene=changed,
                              explanation='Food needs energy.',edits=[]),client,tmp,'offline-stub')
            self.assertEqual(len(client.calls),1,'Reject the wrong issue before requesting tutor prose.')
            self.assertEqual(F.SESSIONS[sid]['state'],before)

    def test_unchanged_review_cannot_reuse_the_previous_revision_delta(self):
        state=self.reviewed_state()
        state.update(edit_enabled=True,awaiting_revision_reason=True)
        self.assertNotEqual(state['previous_submission'],state['committed'])
        unchanged,_,_=F.prepare(state,dict(trigger='workspace-complete',scene=deepcopy(state['committed']['scene']),
            explanation=state['committed']['explanation'],edits=[]))
        self.assertFalse(unchanged['_review_changed'])
        # A pending reason preserves the older before/after pair for context,
        # but that pair does not establish another actual change this turn.
        self.assertNotEqual(unchanged['previous_submission'],unchanged['committed'])
        a=assessment(revision_outcome='successful',revision_outcome_evidence='The source was corrected in the earlier review.')
        policy=P.revision_review_policy(a,unchanged,'workspace-complete')
        self.assertFalse(policy['active']);self.assertFalse(policy['praise_required'])
        self.assertFalse(policy['bypass_initial_check'])

    def test_failed_review_requires_diagnosis_but_does_not_unlock_a_repair(self):
        state=self.reviewed_state();ids={o['id'] for o in SCENE['objects']}|{r['id'] for r in SCENE['relations']}
        a=assessment(revision_outcome='unsuccessful',revision_outcome_evidence='The renamed source leaves the disputed transfer direction unchanged.',
            cognitive_conflict='The stated energy need and the transfer direction conflict.',cognitive_conflict_evidence='Food needs energy.',
            reflection_target='The learner explains that food needs energy.',reflection_evidence='Food needs energy.',
            reflection_reference='The unchanged direction of the submitted transfer.',
            reflection_reference_source='task_or_observable',
            reflection_need='Evaluate whether the revised representation supports the expressed energy explanation.')
        self.assertEqual(P.select_move(a,state,'workspace-complete'),'prompt_reflection')
        policy=P.revision_review_policy(a,state,'workspace-complete')
        self.assertTrue(policy['diagnosis_required']);self.assertFalse(policy['praise_required'])
        self.assertTrue(P.diagnosis_policy(a,state,'','prompt_reflection')['allowed'])
        self.assertFalse(P.thinking_policy(a,state,'','prompt_reflection')['repair_instruction_allowed'])
        direct=reply('The transfer direction is still unresolved. How does that direction fit your energy explanation?',
                     acknowledgment='You changed the source label.',acknowledgment_ids=['o1'],reveals_diagnosis=True)
        self.assertFalse(F.reply_problem(direct,state,a,ids,'workspace-complete','','prompt_reflection'))
        direct.reveals_diagnosis=False
        self.assertTrue(F.reply_problem(direct,state,a,ids,'workspace-complete','','prompt_reflection'))
        direct.reveals_diagnosis=True;direct.content='Reverse this connection. Why does that work?'
        self.assertTrue(F.reply_problem(direct,state,a,ids,'workspace-complete','','prompt_reflection'))

    def test_uncertain_review_goes_to_support_without_false_praise_or_diagnosis(self):
        state=self.reviewed_state()
        a=assessment(revision_outcome='uncertain',revision_outcome_evidence='The new mark is visible but its intended relationship is unclear.',
                     next_focus_kind='clarification',areas_for_improvement=[],
                     ambiguities=[dict(claim='The revised mark is still ambiguous.',evidence='Its endpoint is unresolved.')],
                     reasoning_gap='Explain the intention behind the revised mark.')
        policy=P.revision_review_policy(a,state,'workspace-complete')
        self.assertTrue(policy['active']);self.assertFalse(policy['praise_required']);self.assertFalse(policy['diagnosis_required'])
        self.assertEqual(P.select_move(a,state,'workspace-complete'),'invite_elaboration_reasoning')


if __name__=='__main__':
    unittest.main(verbosity=2)
