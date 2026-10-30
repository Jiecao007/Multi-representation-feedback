"""Generic move progression, edit permissions, and text–visual grounding.

All evaluator/writer calls use typed local stubs; no paid or network calls.
"""
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import json
import re
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE/'app'))
from legacy_support import feedback as F
from legacy_support import feedback_policy as P
SCENE=json.loads((HERE/'results/20260922T035929331824Z/pic1.scene.json').read_text())


def rows():
    return [dict(criterion='c'+str(i),status='developing',strength='Visible components.',gap='Relationships need explanation.') for i in (1,2,3)]


def assessment(**changes):
    data=dict(criteria=rows(),changed_criteria=['c3'],strengths=[dict(claim='PRIVATE DIAGNOSIS',evidence='Private summary')],
        ambiguities=[],areas_for_improvement=[dict(claim='PRIVATE ERROR',evidence='Visible relationship')],
        criterion='c3',student_idea='Food needs energy.',response_highlight_ids=['o3'],next_focus_kind='gap',
        focus_id='o3',talk_move='press_for_accuracy',ready_for_revision=False,inquiry_target='Check the relationship.',
        avoid_telling=['PRIVATE TARGET ANSWER'],learning_goal='Explain the relationships represented by the diagram.')
    data.update(changes)
    return F.Assessment(**data)


def reply(content='Why does your diagram link these ideas?',ack=True,**changes):
    pieces=re.split(r'(?<=[.!])\s+',content.strip()) if content.strip().endswith('?') else []
    question=pieces[-1] if pieces else ''
    observation=' '.join(pieces[:-1])
    data=dict(acknowledgment='Nice work, your diagram successfully connects energy and food production.' if ack else '',
        acknowledgment_ids=['o3'] if ack else [],content=content,review=rows(),focus_id='o3',focus_ids=['o3'],
        evidence_quote='',evidence_source='original',next_step='explain',visual_action='highlight',visual_delivery='on-request',
        check_observation=observation,check_question=question,question_purpose='judge_current_diagram' if question else 'none')
    data.update(changes)
    return F.TutorReply(**data)


def guidance(content='Use the transfer source to choose the direction of this connection.',**changes):
    return reply(content,False,guidance_instruction=content,**changes)


def paths():
    # A connected route from a non-circuit task, without source-specific routing.
    return [F.MechanismPath(label='Transfer route',steps=[F.TraceStep(relation_id=id_,direction='forward') for id_ in ('r1','r3','r7')])]


class FakeClient:
    def __init__(self,sequence):self.sequence=iter(sequence);self.calls=[];self.responses=self
    def parse(self,**kwargs):
        self.calls.append(kwargs);result=next(self.sequence)
        if isinstance(result,Exception):raise result
        return SimpleNamespace(status='completed',output_parsed=result,
            model_dump=lambda **kw:dict(status='completed',model='test-stub',output=result.model_dump()))


class FeedbackTests(unittest.TestCase):
    def setUp(self):F.SESSIONS.clear()
    def data(self,**changes):
        data=dict(trigger='submission',scene=deepcopy(SCENE),original_scene=deepcopy(SCENE),
                  explanation='Food needs energy.',task='',goals=[],message='',edits=[])
        data.update(changes);return data
    def start(self,tmp):return F.handle(self.data(),FakeClient([assessment(),reply()]),tmp,'test')
    def begin(self,tmp,sid):
        return F.handle(dict(trigger='message',session_id=sid,intent='begin_revision',message='Begin a revision.'),
            FakeClient([assessment(),reply('Revise this connection, then explain your change.',False,
                revision_plan='Revise this connection using the transfer direction and explain your change.',revision_plan_ids=['o3'],next_step='revise')]),tmp,'test')
    def thinking_state(self):
        state,_,_=F.prepare(None,self.data())
        state.update(accuracy_focus=['c3','o3'],accuracy_started_at=2,thinking_focus=['c3','o3'],thinking_started_at=3,version=4,progress_focus=['c3','o3'],thinking_opportunity_count=2,
                     response_progress_focus=['c3','o3'],unsuccessful_response_count=0,_current_trigger='message')
        return state
    def changed(self):
        scene=deepcopy(SCENE);scene['objects'][0]['label']='Student revision'
        return F.validate_sketch(scene).model_dump()

    def test_edit_lock_and_committed_snapshot_boundary(self):
        state,_,_=F.prepare(None,self.data());self.assertFalse(state['edit_enabled'])
        changed=self.changed();changed['objects'][0]['label']='UNSUBMITTED'
        data=dict(trigger='message',scene=changed,explanation='UNSUBMITTED',message='I will change it.')
        nxt,ctx,_=F.prepare(state,data)
        self.assertEqual(nxt['committed'],state['committed']);self.assertNotIn('UNSUBMITTED',json.dumps(ctx))
        with self.assertRaises(F.FeedbackError):F.prepare(state,{**data,'trigger':'workspace-complete','edits':[]})
        state['edit_enabled']=True
        reviewed,_,_=F.prepare(state,{**data,'trigger':'workspace-complete','edits':[]})
        self.assertEqual(reviewed['committed']['scene'],changed);self.assertEqual(reviewed['original'],state['original'])
        self.assertEqual(reviewed['drawing_version'],2)
        with self.assertRaises(F.FeedbackError):F.prepare(state,{'trigger':'drag'})

    def test_system_revision_requires_current_issue_reasoning_after_support(self):
        state,_,_=F.prepare(None,self.data())
        ready=assessment(ready_for_revision=True,readiness_evidence='Here is my reason.',progress_status='ready')
        self.assertEqual(F.select_move(ready,state,'submission'),'recognize_strengths')
        self.assertEqual(F.select_move(ready,state,'message','Here is my reason.'),'press_for_accuracy')
        state['accuracy_focus']=['c3','o3']
        self.assertEqual(F.select_move(ready,state,'message','Here is my reason.'),'invite_elaboration_reasoning')
        state.update(thinking_focus=['c3','o3'],thinking_started_at=2,version=3)
        self.assertEqual(F.select_move(ready,state,'message','Here is my reason.'),'propose_revision_plan')
        self.assertNotEqual(F.select_move(ready,state,'message','yes'),'propose_revision_plan')
        ready.focus_id='o1'
        self.assertEqual(F.select_move(ready,state,'message','Here is my reason.'),'press_for_accuracy')

    def test_support_moves_follow_grounded_learning_needs_before_revision(self):
        state=self.thinking_state()
        message='Food needs energy.'
        cases=[('build_on_prior_knowledge',dict(prior_knowledge_connection='Connect the energy need to its source.',prior_knowledge_evidence=message)),
               ('prompt_reflection',dict(cognitive_conflict='The explanation conflicts with the arrow direction.',cognitive_conflict_evidence=message,
                    reflection_target='The learner explains why food needs energy.',reflection_evidence=message,
                    reflection_reference='The direction of the submitted transfer arrow.',
                    reflection_reference_source='task_or_observable',
                    reflection_need='Evaluate whether the represented transfer supports the stated energy need.')),
               ('invite_elaboration_reasoning',dict(reasoning_gap='Explain the represented relationship.')),
               ('provide_hints_guidance',{})]
        for move,changes in cases:
            state['thinking_opportunity_count']=3 if move=='provide_hints_guidance' else 2
            state['unsuccessful_response_count']=3 if move=='provide_hints_guidance' else 0
            self.assertEqual(F.select_move(assessment(talk_move=move,**changes),state,'message',message),move)
        state['thinking_opportunity_count']=2
        state['unsuccessful_response_count']=0
        self.assertEqual(F.select_move(assessment(goal_unclear=True),state,'message'),'clarify_goals')
        self.assertEqual(F.select_move(assessment(next_focus_kind='clarification'),state,'message'),'invite_elaboration_reasoning')

    def test_old_reason_and_other_issue_cannot_supply_readiness(self):
        state=self.thinking_state();state['turns']=[dict(student='The source supplies energy.',version=2)]
        a=assessment(ready_for_revision=True,readiness_evidence='The source supplies energy.',progress_status='ready')
        self.assertEqual(F.select_move(a,state,'message','I agree.'),'invite_elaboration_reasoning')
        state['turns'].append(dict(student='The source supplies energy.',version=4));state['version']=5
        self.assertEqual(F.select_move(a,state,'message','I want to try it.'),'propose_revision_plan')
        a.focus_id='o1'
        self.assertEqual(F.select_move(a,state,'message','The source supplies energy.'),'press_for_accuracy')

    def test_ready_solution_does_not_require_another_comparison_why(self):
        state=self.thinking_state();reason='the direction should follow the transfer from its source'
        a=assessment(ready_for_revision=True,readiness_evidence=reason,progress_status='ready')
        self.assertEqual(F.select_move(a,state,'message','I choose this route because '+reason+'.'),'propose_revision_plan')

    def test_three_unsuccessful_responses_escalate_without_forcing_mastery(self):
        state=self.thinking_state()
        self.assertEqual(F.select_move(assessment(progress_status='stalled',talk_move='prompt_reflection'),state,'message','I think the receiving end is the source.'),'invite_elaboration_reasoning')
        state['thinking_opportunity_count']=3
        self.assertIn(F.select_move(assessment(),state,'message','Maybe?'),P.THINKING_MOVES)
        state['unsuccessful_response_count']=3
        self.assertEqual(F.select_move(assessment(),state,'message','Maybe?'),'provide_hints_guidance')
        self.assertFalse(state['edit_enabled'])

    def test_repeated_question_target_alone_does_not_trigger_guidance(self):
        state=self.thinking_state();state['last_question_target']='Which part receives the transfer?'
        a=assessment(current_question_target='Which part receives the transfer?',talk_move='prompt_reflection')
        self.assertIn(F.select_move(a,state,'message','I think the receiving end is the source.'),P.THINKING_MOVES)

    def test_grounded_ready_solution_wins_over_stall_counter(self):
        state=self.thinking_state();state['issue_turn_count']=4;state['last_question_target']='Explain the same direction again.'
        reason='the source determines the direction of this transfer'
        a=assessment(ready_for_revision=True,readiness_evidence=reason,progress_status='ready',current_question_target=state['last_question_target'])
        self.assertEqual(F.select_move(a,state,'message','I see that '+reason+'.'),'propose_revision_plan')

    def test_three_failed_responses_not_tutor_opportunities_trigger_an_automatic_hint(self):
        message='I think the receiving end is the source.'
        state=self.thinking_state();state.update(thinking_opportunity_count=12,issue_turn_count=12)
        a=assessment(student_stuck=True,talk_move='provide_hints_guidance',
                     current_response_outcome='unsuccessful',outcome_evidence=message)
        for prior in (0,1,2):
            with self.subTest(prior_unsuccessful_responses=prior):
                state['unsuccessful_response_count']=prior
                move=F.select_move(a,state,'message',message)
                self.assertEqual(P.thinking_policy(a,state,message,'provide_hints_guidance')['hint_allowed'],prior==2)
                if prior==2:self.assertEqual(move,'provide_hints_guidance')
                else:self.assertIn(move,P.THINKING_MOVES)
        state['unsuccessful_response_count']=0
        self.assertIn(F.select_move(assessment(student_stuck=True,progress_status='stalled'),state,'message',message),P.THINKING_MOVES)

    def test_completed_reasoning_moves_forward_without_a_budget_filling_hint(self):
        state=self.thinking_state();state['thinking_opportunity_count']=3
        a=assessment(next_focus_kind='none',areas_for_improvement=[],ambiguities=[],progress_status='ready')
        self.assertEqual(F.select_move(a,state,'message','I understand this relationship now.'),'invite_dialogue')

    def test_recognition_revoice_direct_statements_and_repeated_targets_do_not_spend_thinking_budget(self):
        state,_,_=F.prepare(None,self.data());a=assessment(current_question_target='Check the transfer direction.')
        question=reply('Does this direction match its source?',False)
        F.update_progress(state,a,'recognize_strengths',question)
        F.update_progress(state,a,'ask_for_clarification',question)
        self.assertEqual(state['thinking_opportunity_count'],0)
        F.update_progress(state,a,'press_for_accuracy',question)
        self.assertEqual(state['thinking_opportunity_count'],1)
        F.update_progress(state,a,'prompt_reflection',question)
        self.assertEqual(state['thinking_opportunity_count'],1)
        a.current_question_target='Use a familiar transfer.'
        F.update_progress(state,a,'build_on_prior_knowledge',reply('Your description names a transfer source.',False))
        self.assertEqual(state['thinking_opportunity_count'],1)
        a.current_question_target='Explain a familiar transfer.'
        F.update_progress(state,a,'build_on_prior_knowledge',reply('Compare a familiar transfer with this drawing.',False))
        self.assertEqual(state['thinking_opportunity_count'],2)
        F.update_progress(state,a,'provide_hints_guidance',guidance())
        self.assertEqual(state['thinking_opportunity_count'],2)
        a.focus_id='o1';a.current_question_target='Inspect another connection.'
        F.update_progress(state,a,'press_for_accuracy',question)
        self.assertEqual(state['thinking_opportunity_count'],1);self.assertEqual(state['progress_focus'],['c3','o1'])

    def test_new_issue_at_the_same_focus_gets_a_fresh_check_and_thinking_budget(self):
        state=self.thinking_state();state.update(thinking_opportunity_count=3,hint_count=2,last_question_target='The prior issue.')
        a=assessment(progress_status='new',current_question_target='Check a different property.',student_stuck=True)
        self.assertEqual(F.select_move(a,state,'message','I have another uncertainty.'),'press_for_accuracy')
        policy=P.thinking_policy(a,state,'I have another uncertainty.','provide_hints_guidance')
        self.assertEqual(policy['opportunities_offered'],0);self.assertFalse(policy['hint_allowed'])
        F.update_progress(state,a,'press_for_accuracy',reply('Does this different property meet the goal?',False))
        self.assertEqual(state['thinking_opportunity_count'],1);self.assertEqual(state['hint_count'],0)

    def test_new_issue_pending_reason_and_clarification_retire_prior_issue_anchors(self):
        state=self.thinking_state();state.update(thinking_opportunity_count=3,awaiting_revision_reason=True)
        a=assessment(progress_status='new',student_stuck=True,next_focus_kind='clarification')
        self.assertEqual(F.select_move(a,state,'message','I am unsure of the change.'),'invite_elaboration_reasoning')
        self.assertFalse(P.thinking_policy(a,state,'I am unsure of the change.','provide_hints_guidance')['hint_allowed'])
        state['awaiting_revision_reason']=False
        F.update_progress(state,a,'ask_for_clarification',reply('Do you mean the direction or the connection?',False))
        self.assertEqual(state['thinking_opportunity_count'],0)
        self.assertEqual(state['accuracy_focus'],[]);self.assertEqual(state['accuracy_started_at'],0)
        self.assertEqual(state['thinking_focus'],[]);self.assertEqual(state['thinking_started_at'],0)
        a.progress_status='ready';a.ready_for_revision=True;a.readiness_evidence='The source determines the direction.'
        self.assertFalse(P.ready_evidence(a,state,a.readiness_evidence))
        self.assertFalse(P.diagnosis_policy(a,state,a.readiness_evidence,'provide_hints_guidance')['current_issue_checked'])

    def test_explicit_typed_hint_request_matches_the_button_without_generic_help_bypass(self):
        state=self.thinking_state();state.update(intent='dialogue',thinking_opportunity_count=0)
        a=assessment(progress_status='new',student_stuck=True)
        for message in ('I need a hint.', 'Can you give me a hint?', 'Please provide me some guidance.',
                        'I would like guidance.', 'Oh! Give me another hint.', 'Hint, please.', 'Help me.'):
            with self.subTest(message=message):
                self.assertTrue(P.hint_requested(state,message))
                self.assertEqual(F.select_move(a,state,'message',message),'provide_hints_guidance')
                self.assertTrue(P.thinking_policy(a,state,message,'provide_hints_guidance')['repair_instruction_allowed'])
                self.assertTrue(P.diagnosis_policy(a,state,message,'provide_hints_guidance')['allowed'])
        for message in ("I don't need a hint.", 'Please do not give me a hint.', 'I do not want guidance.',
                        'You told me to get a hint.', 'I needed a hint earlier.', 'Do I need a hint?',
                        'The words "I need a hint" appear on the button.', '“Give me a hint”',
                        'I do not know.', 'What is the first step?'):
            with self.subTest(message=message):
                self.assertFalse(P.hint_requested(state,message))
                self.assertEqual(F.select_move(a,state,'message',message),'press_for_accuracy')
                self.assertFalse(P.thinking_policy(a,state,message,'provide_hints_guidance')['hint_allowed'])
        state['intent']='hint';self.assertTrue(P.hint_requested(state,''))

    def test_repeated_question_does_not_rotate_moves_without_a_grounded_connection(self):
        state=self.thinking_state();state['thinking_opportunity_count']=1
        state['last_question_target']='Explain the same connection.'
        state['turns']=[dict(talk_move='invite_elaboration_reasoning',student='I am unsure.',version=3)]
        a=assessment(talk_move='invite_elaboration_reasoning',current_question_target=state['last_question_target'])
        self.assertEqual(F.select_move(a,state,'message','I think the receiving end is the source.'),'invite_elaboration_reasoning')
        state['thinking_opportunity_count']=2
        self.assertEqual(F.select_move(a,state,'message','I think the receiving end is the source.'),'invite_elaboration_reasoning')
        state['unsuccessful_response_count']=3
        self.assertEqual(F.select_move(a,state,'message','I think the receiving end is the source.'),'provide_hints_guidance')

    def test_shared_hint_gate_controls_new_diagnoses_and_repair_locations(self):
        state=self.thinking_state();state['thinking_opportunity_count']=1
        message='I think the receiving end is the source.'
        a=assessment(student_stuck=True,solution_target_ids=['o1'],current_response_outcome='unsuccessful',outcome_evidence=message)
        state['unsuccessful_response_count']=1
        policy=P.thinking_policy(a,state,message,'provide_hints_guidance')
        self.assertEqual({key:policy[key] for key in ('opportunities_offered','hint_allowed','repair_instruction_allowed')},
                         dict(opportunities_offered=1,hint_allowed=False,repair_instruction_allowed=False))
        self.assertEqual(policy['unsuccessful_responses'],2)
        self.assertFalse(P.diagnosis_policy(a,state,message,'provide_hints_guidance')['allowed'])
        ids={o['id'] for o in SCENE['objects']}|{r['id'] for r in SCENE['relations']}
        self.assertNotIn('o1',F.planned_visual(a,state,'message',message,ids,'provide_hints_guidance')['allowed_ids'])
        state['thinking_opportunity_count']=2
        state['unsuccessful_response_count']=2
        self.assertTrue(P.thinking_policy(a,state,message,'provide_hints_guidance')['repair_instruction_allowed'])
        self.assertTrue(P.diagnosis_policy(a,state,message,'provide_hints_guidance')['allowed'])
        self.assertIn('o1',F.planned_visual(a,state,'message',message,ids,'provide_hints_guidance')['allowed_ids'])
        state['thinking_opportunity_count']=0;state['unsuccessful_response_count']=0;state['intent']='hint'
        self.assertTrue(P.thinking_policy(a,state,'I need a hint.','provide_hints_guidance')['hint_allowed'])
        self.assertTrue(P.thinking_policy(a,state,'I need a hint.','provide_hints_guidance')['repair_instruction_allowed'])

    def test_failed_turn_and_retry_do_not_create_extra_unsuccessful_responses(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            F.handle(dict(trigger='message',session_id=sid,message='I am checking the connection.'),
                     FakeClient([assessment(current_response_outcome='unsuccessful',outcome_evidence='I am checking the connection.'),
                                 reply('Does the direction match the source?',False)]),tmp,'test')
            self.assertEqual(F.SESSIONS[sid]['state']['thinking_opportunity_count'],1)
            self.assertEqual(F.SESSIONS[sid]['state']['unsuccessful_response_count'],1)
            F.handle(dict(trigger='message',session_id=sid,message='I think the receiving end is the source.'),
                     FakeClient([assessment(student_stuck=True,talk_move='provide_hints_guidance',current_response_outcome='unsuccessful',outcome_evidence='I think the receiving end is the source.'),
                                 reply('Which familiar transfer might help you compare these components?',False)]),tmp,'test')
            before=deepcopy(F.SESSIONS[sid]['state']);self.assertEqual(before['thinking_opportunity_count'],2)
            self.assertEqual(before['unsuccessful_response_count'],2)
            with self.assertRaises(RuntimeError):
                F.handle(dict(trigger='message',session_id=sid,message='I am stuck again.'),FakeClient([RuntimeError('Local stub failure')]),tmp,'test')
            self.assertEqual(F.SESSIONS[sid]['state'],before)
            result=F.handle(dict(trigger='message',session_id=sid,message='I am stuck again.'),
                            FakeClient([assessment(student_stuck=True,current_response_outcome='unsuccessful',outcome_evidence='I am stuck again.'),
                                        guidance('Trace the connection from its source toward its destination.')]),tmp,'test')
            self.assertEqual(result['talk_move'],'provide_hints_guidance');self.assertFalse(result['edit_enabled'])
            self.assertEqual(F.SESSIONS[sid]['state']['thinking_opportunity_count'],2)
            self.assertEqual(F.SESSIONS[sid]['state']['unsuccessful_response_count'],3)

    def test_hint_button_gives_instruction_without_questions_or_edit_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id'];instruction='Follow the connection from its source and use that direction for your next change.'
            result=F.handle(dict(trigger='message',session_id=sid,intent='hint',message='I need a hint.'),FakeClient([assessment(),guidance(instruction)]),tmp,'test')
            self.assertEqual(result['talk_move'],'provide_hints_guidance');self.assertEqual(result['guidance_instruction'],instruction)
            self.assertNotIn('?',result['content']);self.assertFalse(result['edit_enabled'])

    def test_hint_button_rewrites_question_only_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id'];client=FakeClient([assessment(),reply('Which way do you think it goes?',False),guidance()])
            result=F.handle(dict(trigger='message',session_id=sid,intent='hint',message='I need a hint.'),client,tmp,'test')
            self.assertEqual(len(client.calls),3);self.assertNotIn('?',result['content']);self.assertEqual(result['talk_move'],'provide_hints_guidance')

    def test_revision_contract_defaults_remain_conceptual_and_non_editing(self):
        self.assertEqual(assessment().revision_change_kind,'conceptual')
        self.assertFalse(guidance().guidance_requires_edit)
        with self.assertRaises(ValueError):assessment(revision_change_kind='unknown')

    def test_only_actionable_edit_guidance_can_request_revision_permission(self):
        state,_,ids=F.prepare(None,self.data());state['intent']='hint';a=assessment()
        action='Move this connection endpoint onto the object named in its label.'
        valid=guidance(action,guidance_requires_edit=True,next_step='revise')
        self.assertFalse(F.reply_problem(valid,state,a,ids,'message','','provide_hints_guidance'))
        for candidate,move in ((guidance(action,guidance_requires_edit=True,next_step='explain'),'provide_hints_guidance'),
                               (reply(action,False,guidance_requires_edit=True,guidance_instruction='',next_step='revise'),'provide_hints_guidance'),
                               (guidance(action,next_step='revise'),'provide_hints_guidance'),
                               (valid,'prompt_reflection'),
                               (guidance('Think about the relationship.',guidance_requires_edit=True,next_step='revise'),'provide_hints_guidance'),
                               (guidance('Explain why you would move the endpoint.',guidance_requires_edit=True,next_step='revise'),'provide_hints_guidance')):
            with self.subTest(move=move,flag=candidate.guidance_requires_edit,instruction=candidate.guidance_instruction,next_step=candidate.next_step):
                self.assertTrue(F.reply_problem(candidate,state,a,ids,'message','',move))

    def test_edit_guidance_opens_editor_without_inventing_mastery_or_a_revision_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id'];action='Move this connection endpoint onto the object named in its label.'
            result=F.handle(dict(trigger='message',session_id=sid,intent='hint',message='I need a hint.'),
                FakeClient([assessment(),guidance(action,guidance_requires_edit=True,next_step='revise')]),tmp,'test')
            self.assertEqual(result['talk_move'],'provide_hints_guidance');self.assertTrue(result['edit_enabled'])
            self.assertTrue(result['guidance_requires_edit']);self.assertEqual(result['guidance_instruction'],action)
            self.assertFalse(F.SESSIONS[sid]['state']['assessment']['ready_for_revision'])
            self.assertEqual(result['revision_plan'],'');self.assertNotIn('?',result['content'])

    def test_regular_hint_stays_in_view_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            result=F.handle(dict(trigger='message',session_id=sid,intent='hint',message='I need a hint.'),
                FakeClient([assessment(),guidance('Compare each label with the object it names.',next_step='explore')]),tmp,'test')
            self.assertFalse(result['guidance_requires_edit']);self.assertFalse(result['edit_enabled'])
            self.assertEqual(result['talk_move'],'provide_hints_guidance')

    def test_rejected_edit_guidance_cannot_unlock_or_change_session_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id'];before=deepcopy(F.SESSIONS[sid]['state'])
            invalid=reply('Think about the connection.',False,guidance_requires_edit=True,next_step='revise')
            client=FakeClient([assessment(),invalid,deepcopy(invalid)])
            with self.assertRaises(F.FeedbackError):
                F.handle(dict(trigger='message',session_id=sid,intent='hint',message='I need a hint.'),client,tmp,'test')
            self.assertEqual(len(client.calls),3);self.assertEqual(F.SESSIONS[sid]['state'],before)

    def test_begin_revision_bypasses_readiness_and_opens_editor(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=self.start(tmp);self.assertFalse(first['edit_enabled'])
            result=self.begin(tmp,first['session_id'])
            self.assertEqual(result['talk_move'],'propose_revision_plan');self.assertTrue(result['edit_enabled']);self.assertTrue(result['revision_plan'])

    def test_natural_revision_request_also_moves_forward(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            result=F.handle(dict(trigger='message',session_id=sid,message='Tell me how to fix my diagram.'),
                FakeClient([assessment(learner_requested_revision=True),reply('Reverse this connection, then explain how it fits your idea.',False,
                    revision_plan='Reverse this connection and explain your reason.',revision_plan_ids=['o3'],next_step='revise')]),tmp,'test')
            self.assertEqual(result['talk_move'],'propose_revision_plan');self.assertTrue(result['edit_enabled'])

    def test_common_natural_revision_requests_do_not_need_a_readiness_flag(self):
        state,_,_=F.prepare(None,self.data())
        for message in ('Tell me how to fix my diagram.','I want to revise my model.','Help me edit this.','帮我修改'):
            with self.subTest(message=message):
                self.assertEqual(F.select_move(assessment(),state,'message',message),'propose_revision_plan')

    def test_revision_flag_cannot_override_a_denial_past_report_or_reasoning_question(self):
        state,_,_=F.prepare(None,self.data());a=assessment(learner_requested_revision=True)
        for message in ("I don't want to edit my diagram.",'You told me to change the diagram.',
                        'I changed the connection earlier.','Why should I change that connection?',
                        'Do I need to revise it?',"You said 'I want to revise my model'.",'You said "Oh! Let me edit".',
                        'I added the detail already.','No, I do not need to delete it.','Why should I add another mark?',
                        'I want to change my explanation.','我不想修改','我已经修改了'):
            with self.subTest(message=message):
                self.assertFalse(P.revision_requested(a,state,message))
                self.assertNotEqual(F.select_move(a,state,'message',message),'propose_revision_plan')
        for message in ('Could you help me edit my diagram?','How can I revise this connection?',
                        'Can I change this part?','I understand now. Let me revise it.',
                        'no,let me add more','oh! not, let me change it','no, i need to delete it'):
            with self.subTest(message=message):self.assertTrue(P.revision_requested(a,state,message))

    def test_edit_permission_requires_a_visible_diagram_operation_not_move_metadata(self):
        for move in ('propose_revision_plan','provide_hints_guidance'):
            for text in ('Why should you move this endpoint?','Explain why you would move the endpoint.',
                         'Change your explanation.','Draw on prior knowledge.',
                         'Use the source to explain why you should revise this connection.',
                         'Use your observation to reconsider your answer.'):
                with self.subTest(move=move,text=text):
                    r=reply(text,False,next_step='revise',revision_plan='Move the endpoint.',revision_plan_ids=['o3'],
                            guidance_requires_edit=move=='provide_hints_guidance',guidance_instruction=text)
                    self.assertFalse(P.reply_requires_edit(r,move))
        for text in ('Move this endpoint onto the source.','Try changing this connection, then explain your reason.',
                     'Reverse the connection to show the direction you explained.',
                     'Use that direction to revise this connection, then explain the change.'):
            with self.subTest(text=text):
                r=reply(text,False,next_step='revise',revision_plan=text,revision_plan_ids=['o3'])
                self.assertTrue(P.reply_requires_edit(r,'propose_revision_plan'))
                r.guidance_requires_edit=True;r.guidance_instruction=text
                self.assertTrue(P.reply_requires_edit(r,'provide_hints_guidance'))
        hidden=guidance('Explain your thinking.',guidance_requires_edit=True,next_step='revise')
        hidden.guidance_instruction='Move this endpoint.'
        self.assertFalse(P.reply_requires_edit(hidden,'provide_hints_guidance'))

    def test_reasoning_only_feedforward_does_not_open_editing_from_its_hidden_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id']
            F.handle(dict(trigger='message',session_id=sid,message='I am checking the source.'),
                     FakeClient([assessment(),reply('Does this direction match the source?',False)]),tmp,'test')
            F.handle(dict(trigger='message',session_id=sid,message='I am comparing the relationship.'),
                     FakeClient([assessment(talk_move='prompt_reflection'),reply('How does this connection represent its source?',False)]),tmp,'test')
            reason='the source determines the transfer direction'
            result=F.handle(dict(trigger='message',session_id=sid,message='I understand that '+reason+'.'),
                FakeClient([assessment(ready_for_revision=True,readiness_evidence=reason,progress_status='ready'),
                    reply('Why does this connection need to begin at its source?',False,next_step='explain',
                          revision_plan='Move the connection endpoint onto its source.',revision_plan_ids=['o3'])]),tmp,'test')
            self.assertEqual(result['talk_move'],'propose_revision_plan');self.assertFalse(result['edit_enabled'])

    def test_repeated_begin_request_guides_the_existing_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id'];first=self.begin(tmp,sid)
            second=F.handle(dict(trigger='message',session_id=sid,intent='begin_revision',message='Begin a revision.'),
                FakeClient([assessment(),guidance('Revise this connection using the proposed direction, then explain your reason.',guidance_requires_edit=True,next_step='revise')]),tmp,'test')
            self.assertEqual(second['talk_move'],'provide_hints_guidance');self.assertTrue(second['edit_enabled'])
            self.assertEqual(second['revision_plan'],first['revision_plan'])

    def test_locked_workspace_review_fails_before_evaluator_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id'];saved=deepcopy(F.SESSIONS[sid]['state']);client=FakeClient([])
            with self.assertRaises(F.FeedbackError):F.handle(dict(trigger='workspace-complete',session_id=sid,scene=SCENE,explanation='',edits=[]),client,tmp,'test')
            self.assertEqual(client.calls,[]);self.assertEqual(F.SESSIONS[sid]['state'],saved)

    def test_missing_reason_commits_actual_model_then_accepts_reason_in_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id'];self.begin(tmp,sid);changed=self.changed()
            a=assessment(areas_for_improvement=[],ambiguities=[],revision_resolved=True,next_focus_kind='none',revision_reason_sufficient=True)
            reviewed=F.handle(dict(trigger='workspace-complete',session_id=sid,scene=changed,explanation='',edits=[],revision_reason=''),
                FakeClient([a,reply('Why does this change better represent the transfer?',acknowledgment='You revised the label.',acknowledgment_ids=['o1'])]),tmp,'test')
            self.assertEqual(reviewed['talk_move'],'invite_elaboration_reasoning');self.assertTrue(reviewed['awaiting_revision_reason']);self.assertFalse(reviewed['edit_enabled'])
            self.assertEqual(F.SESSIONS[sid]['state']['committed']['scene'],changed);self.assertEqual(reviewed['drawing_version'],2)
            finished=F.handle(dict(trigger='message',session_id=sid,message='I changed the label because it should name the source of this transfer.'),
                FakeClient([a,reply('You explained the change. Any further questions?',False,visual_action='none',visual_delivery='none')]),tmp,'test')
            self.assertFalse(finished['awaiting_revision_reason']);self.assertFalse(finished['edit_enabled']);self.assertEqual(finished['talk_move'],'invite_dialogue')
            self.assertEqual(F.SESSIONS[sid]['state']['committed']['scene'],changed);self.assertEqual(finished['drawing_version'],2)

    def operational_fixture(self,tmp,student='The connection should begin at the source of the transfer.'):
        sid=self.start(tmp)['session_id']
        F.handle(dict(trigger='message',session_id=sid,message=student),
            FakeClient([assessment(),reply('Does this endpoint match the source you identified?',False)]),tmp,'test')
        F.begin_revision({'session_id':sid})
        changed=deepcopy(F.SESSIONS[sid]['state']['committed']['scene'])
        changed['relations'][0]['points'][0]['x']+=5
        return sid,changed

    def test_correct_operational_fix_reuses_prior_understanding_without_another_question(self):
        with tempfile.TemporaryDirectory() as tmp:
            quote='The connection should begin at the source of the transfer.'
            sid,changed=self.operational_fixture(tmp,quote)
            a=assessment(revision_change_kind='operational',revision_understanding_evidence=quote,revision_resolved=True,
                         revision_reason_sufficient=False,next_focus_kind='none',areas_for_improvement=[],ambiguities=[])
            r=reply('This placement now matches the relationship you explained.',acknowledgment='Nice correction, you adjusted the endpoint.',
                    acknowledgment_ids=['r1'],focus_id='',focus_ids=[],next_step='explore',visual_action='none',visual_delivery='none')
            result=F.handle(dict(trigger='workspace-complete',session_id=sid,scene=changed,explanation='Food needs energy.',edits=[],revision_reason=''),
                            FakeClient([a,r]),tmp,'test')
            self.assertFalse(result['awaiting_revision_reason']);self.assertFalse(result['edit_enabled'])
            self.assertEqual(result['talk_move'],'invite_dialogue');self.assertNotIn('?',result['content'])
            self.assertEqual(F.SESSIONS[sid]['state']['committed']['scene'],changed)
            self.assertFalse(F.SESSIONS[sid]['state']['assessment']['revision_reason_sufficient'])

    def test_completed_operational_fix_rewrites_a_redundant_why_to_brief_affirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            quote='The connection should begin at the source of the transfer.'
            sid,changed=self.operational_fixture(tmp,quote)
            a=assessment(revision_change_kind='operational',revision_understanding_evidence=quote,revision_resolved=True,
                         next_focus_kind='none',areas_for_improvement=[],ambiguities=[])
            fields=dict(acknowledgment='Nice correction, you adjusted the endpoint.',acknowledgment_ids=['r1'],
                        focus_id='',focus_ids=[],next_step='explore',visual_action='none',visual_delivery='none')
            client=FakeClient([a,reply('Why did you move that endpoint?',**fields),reply('',**fields)])
            result=F.handle(dict(trigger='workspace-complete',session_id=sid,scene=changed,explanation='Food needs energy.',edits=[]),
                            client,tmp,'test')
            self.assertEqual(len(client.calls),3);self.assertEqual(result['talk_move'],'invite_dialogue')
            self.assertEqual(result['content'],fields['acknowledgment']);self.assertNotIn('?',result['content'])
            self.assertFalse(result['awaiting_revision_reason']);self.assertFalse(result['edit_enabled'])

    def test_operational_label_needs_specific_prior_learner_understanding(self):
        quote='The connection should begin at the source of the transfer.'
        long_quote=' '.join(['A meaningful learner explanation']*8)
        cases=[('label-only',quote,''),('vague','yes','yes'),('tutor-only','I am still looking.',quote),('task-only','I am still looking.',quote),
               ('ungrounded',quote,'The source should be placed elsewhere.'),('too-long',long_quote,long_quote)]
        for name,student,evidence in cases:
            with self.subTest(case=name),tempfile.TemporaryDirectory() as tmp:
                sid,changed=self.operational_fixture(tmp,student)
                if name=='tutor-only':F.SESSIONS[sid]['state']['turns'][-1]['content']=quote
                if name=='task-only':F.SESSIONS[sid]['state']['task']=quote
                a=assessment(revision_change_kind='operational',revision_understanding_evidence=evidence,revision_resolved=True,
                             next_focus_kind='none',areas_for_improvement=[],ambiguities=[])
                r=reply('How does this change represent the relationship you intend?',acknowledgment='You adjusted the endpoint.',acknowledgment_ids=['r1'])
                result=F.handle(dict(trigger='workspace-complete',session_id=sid,scene=changed,explanation='Food needs energy.',edits=[]),
                                FakeClient([a,r]),tmp,'test')
                self.assertTrue(result['awaiting_revision_reason']);self.assertEqual(result['talk_move'],'invite_elaboration_reasoning')
                self.assertEqual(F.SESSIONS[sid]['state']['committed']['scene'],changed)

    def test_operational_fix_can_reuse_the_submitted_student_explanation(self):
        with tempfile.TemporaryDirectory() as tmp:
            quote='The connection should begin at the source of the transfer.'
            first=F.handle(self.data(explanation=quote),FakeClient([assessment(),reply()]),tmp,'test');sid=first['session_id']
            F.begin_revision({'session_id':sid});changed=deepcopy(F.SESSIONS[sid]['state']['committed']['scene'])
            changed['relations'][0]['points'][0]['x']+=5
            a=assessment(revision_change_kind='operational',revision_understanding_evidence=quote,revision_resolved=True,
                         next_focus_kind='none',areas_for_improvement=[],ambiguities=[])
            result=F.handle(dict(trigger='workspace-complete',session_id=sid,scene=changed,explanation=quote,edits=[]),
                FakeClient([a,reply('This placement now matches your explanation.',acknowledgment='Nice correction, you adjusted the endpoint.',
                                   acknowledgment_ids=['r1'],focus_id='',focus_ids=[],next_step='explore',visual_action='none',visual_delivery='none')]),tmp,'test')
            self.assertFalse(result['awaiting_revision_reason']);self.assertNotIn('?',result['content'])

    def test_operational_exemption_does_not_hide_same_issue_errors_or_ambiguity(self):
        for problem in ('gap','ambiguity'):
            with self.subTest(problem=problem),tempfile.TemporaryDirectory() as tmp:
                quote='The connection should begin at the source of the transfer.'
                sid,changed=self.operational_fixture(tmp,quote)
                a=assessment(revision_change_kind='operational',revision_understanding_evidence=quote,revision_resolved=False,
                             next_focus_kind='clarification' if problem=='ambiguity' else 'gap',
                             areas_for_improvement=[] if problem=='ambiguity' else assessment().areas_for_improvement,
                             ambiguities=[dict(claim='The intended source is unclear.',evidence='Endpoint placement.')] if problem=='ambiguity' else [])
                result=F.handle(dict(trigger='workspace-complete',session_id=sid,scene=changed,explanation='Food needs energy.',edits=[]),
                    FakeClient([a,reply('How does this endpoint represent the source you intend?',
                                       acknowledgment='You adjusted the endpoint.',acknowledgment_ids=['r1'])]),tmp,'test')
                self.assertTrue(result['awaiting_revision_reason']);self.assertEqual(result['talk_move'],'invite_elaboration_reasoning')

    def test_correct_operational_fix_can_advance_to_an_independent_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            quote='The connection should begin at the source of the transfer.'
            sid,changed=self.operational_fixture(tmp,quote)
            a=assessment(criterion='c1',focus_id='o2',revision_change_kind='operational',revision_understanding_evidence=quote,revision_resolved=True)
            r=reply('Does this separate connection represent its source?',acknowledgment='You adjusted the endpoint.',acknowledgment_ids=['r1'],focus_id='o2',focus_ids=['o2'])
            result=F.handle(dict(trigger='workspace-complete',session_id=sid,scene=changed,explanation='Food needs energy.',edits=[]),FakeClient([a,r]),tmp,'test')
            self.assertFalse(result['awaiting_revision_reason']);self.assertFalse(result['edit_enabled'])
            self.assertEqual(result['talk_move'],'press_for_accuracy');self.assertEqual(result['focus_id'],'o2')

    def test_no_actual_submission_delta_cannot_waive_an_existing_reason_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            quote='The connection should begin at the source of the transfer.'
            sid,_=self.operational_fixture(tmp,quote);state=F.SESSIONS[sid]['state']
            state['awaiting_revision_reason']=True;state['previous_submission']=deepcopy(state['committed'])
            unchanged=deepcopy(state['committed'])
            a=assessment(revision_change_kind='operational',revision_understanding_evidence=quote,revision_resolved=True,
                         next_focus_kind='none',areas_for_improvement=[],ambiguities=[])
            result=F.handle(dict(trigger='workspace-complete',session_id=sid,scene=unchanged['scene'],explanation=unchanged['explanation'],edits=[]),
                FakeClient([a,reply('How does your intended change represent the relationship?',acknowledgment='You submitted the same diagram.',acknowledgment_ids=['o3'])]),tmp,'test')
            self.assertTrue(result['awaiting_revision_reason']);self.assertEqual(result['talk_move'],'invite_elaboration_reasoning')
            self.assertEqual(F.SESSIONS[sid]['state']['committed'],unchanged)

    def test_conceptual_fix_can_use_grounded_history_when_understanding_is_sufficient(self):
        with tempfile.TemporaryDirectory() as tmp:
            quote='The connection should begin at the source of the transfer.'
            sid,changed=self.operational_fixture(tmp,quote)
            a=assessment(revision_change_kind='conceptual',revision_understanding_evidence=quote,revision_reason_sufficient=True,
                         revision_resolved=True,next_focus_kind='none',areas_for_improvement=[],ambiguities=[])
            result=F.handle(dict(trigger='workspace-complete',session_id=sid,scene=changed,explanation='Food needs energy.',edits=[]),
                FakeClient([a,reply('This change now matches the relationship you explained.',acknowledgment='Nice correction, you adjusted the endpoint.',
                                   acknowledgment_ids=['r1'],focus_id='',focus_ids=[],next_step='explore',visual_action='none',visual_delivery='none')]),tmp,'test')
            self.assertFalse(result['awaiting_revision_reason']);self.assertFalse(result['edit_enabled'])
            self.assertNotIn('?',result['content'])

    def test_conceptual_understanding_still_needs_evaluator_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            quote='The connection should begin at the source of the transfer.'
            sid,changed=self.operational_fixture(tmp,quote)
            a=assessment(revision_change_kind='conceptual',revision_understanding_evidence=quote,revision_reason_sufficient=False,
                         revision_resolved=True,next_focus_kind='none',areas_for_improvement=[],ambiguities=[])
            result=F.handle(dict(trigger='workspace-complete',session_id=sid,scene=changed,explanation='Food needs energy.',edits=[]),
                FakeClient([a,reply('How does this change represent the source you intend?',acknowledgment='You adjusted the endpoint.',acknowledgment_ids=['r1'])]),tmp,'test')
            self.assertTrue(result['awaiting_revision_reason']);self.assertEqual(result['talk_move'],'invite_elaboration_reasoning')

    def test_inadequate_reason_keeps_review_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id'];self.begin(tmp,sid)
            result=F.handle(dict(trigger='workspace-complete',session_id=sid,scene=self.changed(),explanation='',edits=[],revision_reason='because it is right'),
                FakeClient([assessment(revision_reason_sufficient=False),reply('How does this change represent your idea?',acknowledgment='You revised the label.',acknowledgment_ids=['o1'])]),tmp,'test')
            self.assertTrue(result['awaiting_revision_reason']);self.assertEqual(result['talk_move'],'invite_elaboration_reasoning')

    def test_hint_while_reason_is_pending_provides_guidance(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id'];self.begin(tmp,sid)
            F.handle(dict(trigger='workspace-complete',session_id=sid,scene=self.changed(),explanation='',edits=[]),
                FakeClient([assessment(),reply('How does this change represent your idea?',acknowledgment='You revised the label.',acknowledgment_ids=['o1'])]),tmp,'test')
            result=F.handle(dict(trigger='message',session_id=sid,intent='hint',message='I need a hint.'),
                FakeClient([assessment(),guidance('Explain what the new label represents and how it improves the transfer shown.')]),tmp,'test')
            self.assertEqual(result['talk_move'],'provide_hints_guidance');self.assertNotIn('?',result['content']);self.assertTrue(result['awaiting_revision_reason'])

    def test_learner_can_exit_with_a_reason_still_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id'];self.begin(tmp,sid);changed=self.changed()
            F.handle(dict(trigger='workspace-complete',session_id=sid,scene=changed,explanation='',edits=[]),
                FakeClient([assessment(),reply('Why does this change better represent the transfer?',acknowledgment='You revised the label.',acknowledgment_ids=['o1'])]),tmp,'test')
            result=F.handle(dict(trigger='message',session_id=sid,message='I want to finish now.'),
                FakeClient([assessment(closing_requested=True),reply('You can finish here and return to your drawing later.',False,
                    focus_id='',focus_ids=[],visual_action='none',visual_delivery='none')]),tmp,'test')
            self.assertEqual(result['stage'],'complete');self.assertNotIn('?',result['content'])
            self.assertFalse(result['edit_enabled']);self.assertFalse(result['awaiting_revision_reason'])
            state=F.SESSIONS[sid]['state'];self.assertEqual(state['committed']['scene'],changed)
            self.assertFalse(state['assessment']['revision_reason_sufficient'])

    def test_review_context_compares_with_the_previous_submission(self):
        state,_,_=F.prepare(None,self.data());original=deepcopy(state['original']);state['edit_enabled']=True
        first=self.changed()
        state,_,_=F.prepare(state,dict(trigger='workspace-complete',scene=first,explanation='',edits=[]))
        second=deepcopy(first);second['objects'][0]['label']='Second revision'
        state['edit_enabled']=True
        updated,context,_=F.prepare(state,dict(trigger='workspace-complete',scene=second,explanation='',edits=[]))
        self.assertEqual(context['previous_submission']['scene'],first);self.assertEqual(updated['original'],original)
        self.assertEqual(updated['committed']['scene'],second)

    def test_unchanged_resubmission_retains_the_actual_pre_revision_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id'];self.begin(tmp,sid)
            before=deepcopy(F.SESSIONS[sid]['state']['committed']);changed=self.changed()
            F.handle(dict(trigger='workspace-complete',session_id=sid,scene=changed,explanation='',edits=[]),
                FakeClient([assessment(),reply('Why does this change better represent the transfer?',acknowledgment='You revised the label.',acknowledgment_ids=['o1'])]),tmp,'test')
            client=FakeClient([assessment(revision_resolved=True,revision_reason_sufficient=True,next_focus_kind='none',areas_for_improvement=[],ambiguities=[]),
                reply('Do you have any further questions?',acknowledgment='You explained the revised label.',acknowledgment_ids=['o1'])])
            F.begin_revision({'session_id':sid})
            result=F.handle(dict(trigger='workspace-complete',session_id=sid,scene=changed,explanation='',edits=[],
                revision_reason='The label identifies the source of this transfer.'),client,tmp,'test')
            context=json.loads(client.calls[0]['input'][0]['content'][0]['text'])
            self.assertEqual(context['previous_submission'],before)
            self.assertEqual(context['committed']['scene'],changed)
            self.assertFalse(result['awaiting_revision_reason']);self.assertFalse(result['edit_enabled'])
            self.assertEqual(result['talk_move'],'invite_dialogue')

    def test_legacy_explanation_revision_also_requires_permission_and_reason(self):
        state,_,_=F.prepare(None,self.data())
        with self.assertRaises(F.FeedbackError):F.prepare(state,dict(trigger='revision',explanation='A revised explanation.'))
        state['edit_enabled']=True
        updated,context,_=F.prepare(state,dict(trigger='revision',explanation='A revised explanation.'))
        self.assertTrue(updated['awaiting_revision_reason']);self.assertEqual(context['previous_submission'],state['committed'])
        self.assertEqual(updated['committed']['scene'],state['committed']['scene'])

    def test_sufficient_reason_at_review_closes_revision_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id'];self.begin(tmp,sid)
            result=F.handle(dict(trigger='workspace-complete',session_id=sid,scene=self.changed(),explanation='',edits=[],revision_reason='I renamed the source so this transfer is clear.'),
                FakeClient([assessment(revision_reason_sufficient=True,revision_resolved=True,next_focus_kind='none',areas_for_improvement=[],ambiguities=[]),
                    reply('Do you have any further questions?',acknowledgment='You revised the label.',acknowledgment_ids=['o1'])]),tmp,'test')
            self.assertEqual(result['talk_move'],'invite_dialogue');self.assertFalse(result['awaiting_revision_reason']);self.assertFalse(result['edit_enabled']);self.assertEqual(result['revision_plan'],'')

    def test_independent_issue_after_review_starts_a_new_thinking_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id'];self.begin(tmp,sid)
            next_issue=assessment(criterion='c1',focus_id='o2',revision_reason_sufficient=True)
            reviewed=F.handle(dict(trigger='workspace-complete',session_id=sid,scene=self.changed(),explanation='',edits=[],revision_reason='The new label identifies the transfer source.'),
                FakeClient([next_issue,reply('Does this separate connection represent its source accurately?',acknowledgment='You revised the source label.',acknowledgment_ids=['o1'],focus_id='o2',focus_ids=['o2'])]),tmp,'test')
            self.assertEqual(reviewed['talk_move'],'press_for_accuracy');self.assertFalse(reviewed['edit_enabled']);self.assertEqual(reviewed['revision_plan'],'')
            self.assertEqual(F.SESSIONS[sid]['state']['thinking_started_at'],0)
            reason='the source determines the transfer direction'
            next_issue.ready_for_revision=True;next_issue.readiness_evidence=reason;next_issue.talk_move='build_on_prior_knowledge'
            next_issue.prior_knowledge_connection='Connect the familiar energy need to the newly selected relationship.'
            next_issue.prior_knowledge_evidence='Food needs energy.'
            thinking=F.handle(dict(trigger='message',session_id=sid,message='The earlier reason was that '+reason+'.'),
                FakeClient([next_issue,reply('What familiar idea helps explain this separate connection?',False,focus_id='o2',focus_ids=['o2'])]),tmp,'test')
            self.assertEqual(thinking['talk_move'],'build_on_prior_knowledge');self.assertFalse(thinking['edit_enabled'])

    def test_system_progression_then_revision_and_closure(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=self.start(tmp);sid=first['session_id'];self.assertEqual(first['talk_move'],'recognize_strengths');self.assertEqual(first['next_focus_kind'],'extension')
            checked=F.handle(dict(trigger='message',session_id=sid,message='It needs energy to grow.'),FakeClient([assessment(),reply('Does this connection represent that transfer accurately?',False)]),tmp,'test')
            self.assertEqual(checked['talk_move'],'press_for_accuracy')
            thinking=F.handle(dict(trigger='message',session_id=sid,message='The direction depends on the source.'),FakeClient([assessment(talk_move='prompt_reflection',
                cognitive_conflict='The stated source principle conflicts with the shown direction.',cognitive_conflict_evidence='The direction depends on the source.',
                reflection_target='The learner says the source determines transfer direction.',
                reflection_evidence='The direction depends on the source.',
                reflection_reference='The direction of the submitted connection.',reflection_reference_source='task_or_observable',
                reflection_need='Evaluate whether the drawn direction agrees with the source-based explanation.'),
                reply('How does your drawing compare with that direction?',False)]),tmp,'test')
            self.assertEqual(thinking['talk_move'],'prompt_reflection');self.assertFalse(thinking['edit_enabled'])
            reason='the arrow should follow the energy transfer'
            proposed=F.handle(dict(trigger='message',session_id=sid,message='I see that '+reason+'.'),
                FakeClient([assessment(ready_for_revision=True,readiness_evidence=reason,progress_status='ready'),reply('Try changing this connection using your reasoning.',False,
                    revision_plan='Revise this connection using the direction you explained.',revision_plan_ids=['o3'],next_step='revise')]),tmp,'test')
            self.assertEqual(proposed['talk_move'],'propose_revision_plan');self.assertTrue(proposed['edit_enabled'])
            end=F.handle(dict(trigger='message',session_id=sid,message='I am done.'),FakeClient([assessment(closing_requested=True,next_focus_kind='none',areas_for_improvement=[],focus_id=''),
                reply('You can finish here.',False,focus_id='',focus_ids=[],visual_action='none',visual_delivery='none')]),tmp,'test')
            self.assertEqual(end['stage'],'complete');self.assertNotIn('?',end['content']);self.assertNotIn('PRIVATE',json.dumps(end))

    def test_failed_turn_cannot_change_permissions_or_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid=self.start(tmp)['session_id'];saved=deepcopy(F.SESSIONS[sid]['state'])
            with self.assertRaises(RuntimeError):F.handle(dict(trigger='message',session_id=sid,intent='begin_revision',message='Begin a revision.'),FakeClient([assessment(),RuntimeError('Writer failed')]),tmp,'test')
            self.assertEqual(F.SESSIONS[sid]['state'],saved)

    def test_supported_opening_affirms_success_and_uses_same_feature(self):
        state,_,ids=F.prepare(None,self.data());a=assessment()
        self.assertFalse(F.reply_problem(reply(),state,a,ids,'submission','','recognize_strengths'))
        self.assertIn('recognized feature',F.reply_problem(reply(focus_id='o1',focus_ids=['o1']),state,a,ids,'submission','','recognize_strengths'))
        self.assertIn('First acknowledge',F.reply_problem(reply(ack=False),state,a,ids,'submission','','recognize_strengths'))
        neutral=reply(acknowledgment='You connected energy and food production.')
        self.assertIn('Explicitly affirm',F.reply_problem(neutral,state,a,ids,'submission','','recognize_strengths'))
        a.recognized_strength_supported=False;self.assertFalse(F.reply_problem(neutral,state,a,ids,'submission','','recognize_strengths'))

    def test_private_grounding_and_unsubmitted_draft_do_not_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=self.start(tmp);sid=first['session_id'];old=deepcopy(F.SESSIONS[sid]['state']);draft=self.changed();draft['objects'][0]['label']='PRIVATE DRAFT'
            client=FakeClient([assessment(),reply('How does this connection match your explanation?',False)])
            public=F.handle(dict(trigger='message',session_id=sid,message='Here is my reason.',scene=draft,explanation='PRIVATE DRAFT'),client,tmp,'test',dialogue_model='test-dialogue')
            self.assertEqual(client.calls[-1]['model'],'test-dialogue');self.assertNotIn('PRIVATE DRAFT',json.dumps([c['input'] for c in client.calls]))
            self.assertEqual(F.SESSIONS[sid]['state']['committed'],old['committed']);self.assertEqual(public['review_version'],first['review_version'])

    def test_single_validation_rewrite_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            client=FakeClient([assessment(),reply('No question.'),reply()]);public=F.handle(self.data(),client,tmp,'test');self.assertEqual(len(client.calls),3)
            saved=deepcopy(F.SESSIONS[public['session_id']]['state'])
            with self.assertRaises(F.FeedbackError):F.handle(dict(trigger='message',session_id=public['session_id'],message='Help.'),
                FakeClient([assessment(),reply('Why? How?',False),reply('What? Why?',False)]),tmp,'test')
            self.assertEqual(F.SESSIONS[public['session_id']]['state'],saved)

    def test_optional_explanation_and_frozen_private_question_figure(self):
        a=assessment();a.criteria[-1].status='not-requested';a.criteria[-1].gap=''
        self.assertFalse(F.valid_review(a.criteria,[dict(id='c'+str(i)) for i in (1,2,3)]));a.criteria[-1].gap='Explain more.'
        self.assertTrue(F.valid_review(a.criteria,[dict(id='c'+str(i)) for i in (1,2,3)]))
        state,_,_=F.prepare(None,self.data(goals=['Design constraints','Relationships']));self.assertTrue(state['goals_configured']);self.assertEqual(len(state['criteria']),2)
        with tempfile.TemporaryDirectory() as tmp:
            figure='data:image/png;base64,dGVzdA==';client=FakeClient([assessment(),reply()]);public=F.handle(self.data(),client,tmp,'test',question_image=figure)
            self.assertNotIn(figure,json.dumps(public));self.assertEqual([p['image_url'] for p in client.calls[0]['input'][0]['content'] if p['type']=='input_image'],[figure])
            F.handle(dict(trigger='message',session_id=public['session_id'],message='Let me explain.'),FakeClient([assessment(),reply(ack=False)]),tmp,'test',question_image='replacement')
            self.assertEqual(F.SESSIONS[public['session_id']]['state']['question_image'],figure)

    def test_brevity_grounded_quotes_and_private_only_referents(self):
        for text in ('Why? How?','word '*56,'Good. One. Two. Why?'):self.assertTrue(F.short_turn_problem(text))
        self.assertTrue(F.short_turn_problem('Nice catch 😊 Why?','Good work 😊 Why?'));self.assertFalse(F.short_turn_problem('Try one small change.'))
        state,_,ids=F.prepare(None,self.data());state['review']=rows();state['review'][0]['strength']='Earlier supported evidence.'
        cleaned=F.normalize_reply(reply(evidence_quote='Invented quotation'),state,assessment(),ids)
        self.assertEqual(cleaned['review'][0]['strength'],'Earlier supported evidence.');self.assertEqual(cleaned['evidence_quote'],'')
        r=reply(visual_action='none',visual_delivery='none');public=F.normalize_reply(r,state,assessment(),ids)
        self.assertEqual(public['focus_ids'],[]);self.assertEqual(public['acknowledgment_ids'],[]);self.assertEqual(public['focus_id'],'');self.assertTrue(r.acknowledgment_ids)

    def test_diagram_turn_defaults_to_static_automatic_highlight(self):
        with tempfile.TemporaryDirectory() as tmp:
            client=FakeClient([assessment(),reply(visual_action='none',visual_delivery='none')]);result=F.handle(self.data(),client,tmp,'test')
            self.assertEqual(result['visual_action'],'highlight');self.assertEqual(result['visual_delivery'],'automatic');self.assertEqual(result['focus_ids'],['o3']);self.assertEqual(result['mechanism_paths'],[]);self.assertEqual(len(client.calls),2)

    def test_conceptual_turn_can_omit_visual_feedback(self):
        state,_,ids=F.prepare(None,self.data());a=assessment(visual_intent='conceptual');plan=F.planned_visual(a,state,'message','What is energy?',ids,'build_on_prior_knowledge')
        self.assertFalse(plan['prefer_automatic']);r=F.coordinate_reply(reply('Use a familiar example of a transfer.',False,visual_action='none',visual_delivery='none'),plan)
        self.assertEqual(r.visual_delivery,'none')

    def test_trace_needs_mechanism_intent_and_matching_writer_action(self):
        state,_,ids=F.prepare(None,self.data());a=assessment(visual_intent='explain-mechanism',mechanism_paths=paths(),visual_focus_ids=['r1'])
        plan=F.planned_visual(a,state,'message','How does the transfer travel?',ids,'invite_elaboration_reasoning')
        static=F.coordinate_reply(reply('Look at this connection. Where does it start?',False,focus_id='r1',focus_ids=['r1']),plan)
        self.assertEqual(static.visual_action,'highlight');self.assertEqual(static.mechanism_paths,[])
        animated=F.coordinate_reply(reply('Watch the moving arrows. How does the transfer reach the final stage?',False,focus_id='r1',focus_ids=['r1'],visual_action='trace'),plan)
        self.assertEqual(animated.visual_action,'trace');self.assertEqual(len(animated.mechanism_paths),1)
        self.assertFalse(F.reply_problem(animated,state,a,ids,'message','','invite_elaboration_reasoning'))

    def test_inspection_downgrades_an_unneeded_animation(self):
        state,_,ids=F.prepare(None,self.data());a=assessment(visual_intent='inspect-diagram',mechanism_paths=paths())
        plan=F.planned_visual(a,state,'message','Which label belongs here?',ids,'press_for_accuracy');self.assertEqual(plan['mechanism_paths'],[])
        r=F.coordinate_reply(reply('Does this label name the correct stage?',False,visual_action='trace',mechanism_paths=paths()),plan)
        self.assertEqual(r.visual_action,'highlight');self.assertEqual(r.mechanism_paths,[])

    def test_generic_mechanism_requires_existing_continuous_geometry(self):
        route=paths();self.assertFalse(F.mechanism_problem(route,'',SCENE))
        wrong=deepcopy(route);wrong[0].steps[1].relation_id='missing';self.assertIn('never invent',F.mechanism_problem(wrong,'',SCENE))
        wrong=deepcopy(route);wrong[0].steps[1].direction='backward';self.assertIn('actual endpoint',F.mechanism_problem(wrong,'',SCENE))
        wrong=deepcopy(route);wrong[0].steps[1]=deepcopy(wrong[0].steps[0]);self.assertIn('once per path',F.mechanism_problem(wrong,'',SCENE))
        wrong=[F.MechanismPath(label='Unresolved route',steps=[F.TraceStep(relation_id='r6',direction='forward')])]
        self.assertIn('unresolved endpoints',F.mechanism_problem(wrong,'',SCENE))

    def test_conditional_mechanism_needs_its_generic_condition(self):
        state,_,ids=F.prepare(None,self.data());a=assessment(visual_intent='explain-mechanism',mechanism_paths=paths(),mechanism_requires_condition=True)
        plan=F.planned_visual(a,state,'message','How does the process run?',ids,'invite_elaboration_reasoning');self.assertEqual(plan['mechanism_paths'],[])
        a.mechanism_condition='When the process is running';plan=F.planned_visual(a,state,'message','How does the process run?',ids,'invite_elaboration_reasoning')
        self.assertEqual(len(plan['mechanism_paths']),1);self.assertEqual(plan['mechanism_condition'],'When the process is running')

    def test_text_cannot_promise_an_unshown_animation(self):
        state,_,ids=F.prepare(None,self.data());r=reply("Let's trace one route. Does it pass through this part?",False,visual_action='none',visual_delivery='none')
        self.assertIn('promise an animation',F.reply_problem(r,state,assessment(),ids,'message','','invite_elaboration_reasoning'))

    def test_repair_highlights_require_grounding_or_revision_authorization(self):
        state,_,ids=F.prepare(None,self.data());a=assessment(solution_target_ids=['o1']);state['_current_message']='I do not know where to place it.'
        r=reply('Which part do you identify as the transfer source?',False,focus_id='o1',focus_ids=['o1']);self.assertIn('protected repair',F.reply_problem(r,state,a,ids,'message','','build_on_prior_knowledge'))
        state['_current_message']='I think the source should be this part.';a.learner_identifications=[F.Evidence(claim='o1',evidence='the source should be this part')]
        self.assertFalse(F.reply_problem(r,state,a,ids,'message','','build_on_prior_knowledge'))
        a.learner_identifications=[];state['intent']='begin_revision';planned=reply('Revise the connection at this source.',False,focus_id='o1',focus_ids=['o1'],revision_plan='Revise the source connection and explain your reason.',revision_plan_ids=['o1'],next_step='revise')
        self.assertFalse(F.reply_problem(planned,state,a,ids,'message','','propose_revision_plan'))

    def test_plan_targets_exist_and_guidance_contains_an_instruction(self):
        state,_,ids=F.prepare(None,self.data());a=assessment()
        self.assertTrue(F.reply_problem(reply(ack=False),state,a,ids,'message','','propose_revision_plan'))
        bad=reply('Try one change.',False,revision_plan='Try one change.',revision_plan_ids=['deleted']);self.assertTrue(F.reply_problem(bad,state,a,ids,'message','','propose_revision_plan'))
        self.assertTrue(F.reply_problem(reply('What happens here?',False),state,a,ids,'message','','provide_hints_guidance'))
        state['intent']='hint'
        self.assertFalse(F.reply_problem(guidance(),state,a,ids,'message','','provide_hints_guidance'))

    def test_fresh_gap_requires_press_before_support_stall_or_readiness(self):
        state=self.thinking_state()
        state.update(accuracy_focus=['c1','o1'],progress_focus=['c1','o1'],issue_turn_count=8)
        for a in (assessment(student_stuck=True,talk_move='provide_hints_guidance'),
                  assessment(progress_status='stalled'),
                  assessment(talk_move='build_on_prior_knowledge'),
                  assessment(ready_for_revision=True,readiness_evidence='the direction follows its source',progress_status='ready')):
            with self.subTest(move=a.talk_move,progress=a.progress_status):
                self.assertEqual(F.select_move(a,state,'message','I see that the direction follows its source.'),'press_for_accuracy')

    def test_explicit_hint_and_revision_requests_are_fresh_gap_exceptions(self):
        state,_,_=F.prepare(None,self.data())
        state['intent']='hint'
        self.assertEqual(F.select_move(assessment(),state,'message','I need a hint.'),'provide_hints_guidance')
        state['intent']='begin_revision'
        self.assertEqual(F.select_move(assessment(),state,'message','Begin a revision.'),'propose_revision_plan')

    def test_first_accuracy_check_resets_same_key_recognition_and_clarification_counts(self):
        state,_,_=F.prepare(None,self.data());a=assessment(current_question_target='Does this direction match its source?')
        F.update_progress(state,a,'recognize_strengths')
        state['version']+=1
        F.update_progress(state,a,'ask_for_clarification')
        self.assertEqual(state['progress_focus'],['c3','o3'])
        self.assertEqual(state['issue_turn_count'],2)
        self.assertEqual(state['accuracy_focus'],[])
        state.update(hint_count=2,text_hint_focus=['c3','o3'])
        state['version']+=1
        F.update_progress(state,a,'press_for_accuracy')
        self.assertEqual(state['issue_turn_count'],1)
        self.assertEqual(state['hint_count'],0)
        self.assertEqual(state['text_hint_focus'],[])
        self.assertEqual(state['accuracy_focus'],['c3','o3'])
        self.assertEqual(state['accuracy_started_at'],state['version'])
        state['version']+=1
        F.update_progress(state,a,'prompt_reflection')
        self.assertEqual(state['issue_turn_count'],2)

    def test_validated_criterion_gap_routes_press_when_error_list_is_sparse(self):
        state,_,_=F.prepare(None,self.data())
        a=assessment(areas_for_improvement=[],next_focus_kind='gap',talk_move='build_on_prior_knowledge')
        self.assertEqual(F.select_move(a,state,'message','There are two paths.'),'press_for_accuracy')
        a.criteria[-1].status='established';a.criteria[-1].gap=''
        self.assertEqual(F.select_move(a,state,'message','There are two paths.'),'invite_elaboration_reasoning')

    def test_canonical_reply_repairs_duplicate_question_metadata_and_empty_review(self):
        state,_,ids=F.prepare(None,self.data());a=assessment()
        r=reply('Look at this connection. Does its direction match the transfer source?',False)
        r.check_observation=r.content;r.review=[]
        canonical=F.canonical_reply(r,a)
        self.assertEqual(canonical.content,r.content)
        self.assertEqual(canonical.check_observation,'Look at this connection.')
        self.assertEqual(canonical.review,a.criteria)
        self.assertFalse(F.reply_problem(canonical,state,a,ids,'message','','press_for_accuracy'))

    def test_canonical_metadata_repair_preserves_diagnostic_prose_for_rejection(self):
        state,_,ids=F.prepare(None,self.data());a=assessment()
        r=reply('The transfer bypasses this component, so it misses part of the transfer. Does it meet the goal?',False,reveals_diagnosis=False)
        r.check_observation=r.content
        canonical=F.canonical_reply(r,a)
        self.assertEqual(canonical.content,r.content)
        self.assertIn('so it misses',canonical.check_observation)
        self.assertTrue(F.reply_problem(canonical,state,a,ids,'message','','press_for_accuracy'))

    def test_question_metadata_repair_requires_an_identical_full_paragraph(self):
        a=assessment();r=reply('Look at this connection. Does it match the task?',False)
        r.check_observation=r.content;r.content='An extra conclusion. '+r.content
        canonical=F.canonical_reply(r,a)
        self.assertEqual(canonical.check_observation,r.check_observation)

    def test_trace_focus_dedup_preserves_all_mechanism_steps(self):
        a=assessment(visual_intent='explain-mechanism',mechanism_paths=paths())
        r=reply('Watch the moving arrows. Does the transfer follow this route?',False,visual_action='trace',mechanism_paths=paths(),
                focus_id='o3',focus_ids=['o3','r1','r3','r7','o1'])
        canonical=F.canonical_reply(r,a)
        self.assertEqual(canonical.focus_ids,['o3','o1'])
        self.assertEqual(canonical.mechanism_paths,r.mechanism_paths)
        self.assertEqual(canonical.content,r.content)

    def test_path_only_trace_focus_overflow_retains_one_visual_anchor(self):
        state,_,ids=F.prepare(None,self.data())
        routes=paths()+[F.MechanismPath(label='Second transfer route',steps=[
            F.TraceStep(relation_id=id_,direction='forward') for id_ in ('r2','r3','r8','r9')])]
        a=assessment(visual_intent='explain-mechanism',mechanism_paths=routes,focus_id='r1',visual_focus_ids=['r1'])
        r=reply('Watch the moving arrows. Does the transfer follow the routes you drew?',False,visual_action='trace',visual_delivery='automatic',
                mechanism_paths=routes,focus_id='',focus_ids=['r1','r3','r7','r2','r8','r9'])
        canonical=F.canonical_reply(r,a)
        self.assertEqual(canonical.focus_ids,['r1'])
        self.assertEqual(canonical.mechanism_paths,routes)
        self.assertFalse(F.reply_problem(canonical,state,a,ids,'message','','press_for_accuracy'))

    def test_canonical_trace_does_not_hide_non_path_focus_overflow(self):
        state,_,ids=F.prepare(None,self.data());a=assessment(visual_intent='explain-mechanism',mechanism_paths=paths())
        r=reply('Watch the moving arrows. Does the transfer follow this route?',False,visual_action='trace',mechanism_paths=paths(),
                focus_id='o3',focus_ids=['o1','o2','o3','o4','o5'])
        canonical=F.canonical_reply(r,a)
        self.assertEqual(len(canonical.focus_ids),5)
        self.assertTrue(F.reply_problem(canonical,state,a,ids,'message','','press_for_accuracy'))

    def test_support_can_acknowledge_current_learner_words_without_diagram_ids(self):
        state,_,ids=F.prepare(None,self.data());quote='There are two different paths here'
        state['_current_message']=quote
        r=reply('How can that observation help you compare the two routes?',acknowledgment='You noticed the two different paths.',acknowledgment_ids=[],
                evidence_quote=quote,evidence_source='dialogue')
        self.assertFalse(F.reply_problem(r,state,assessment(),ids,'message','','build_on_prior_knowledge'))
        self.assertEqual(F.normalize_reply(r,state,assessment(),ids)['evidence_quote'],quote)
        for invalid_quote in ('An invented statement','word '*13):
            with self.subTest(quote=invalid_quote):
                r.evidence_quote=invalid_quote
                self.assertTrue(F.reply_problem(r,state,assessment(),ids,'message','','build_on_prior_knowledge'))

    def test_press_checks_the_current_diagram_with_neutral_visual_orientation(self):
        state,_,ids=F.prepare(None,self.data())
        r=reply('Look at the highlighted connection. Does its direction match the source of the transfer?',False)
        self.assertFalse(F.reply_problem(r,state,assessment(),ids,'message','','press_for_accuracy'))
        self.assertEqual(r.content,' '.join((r.check_observation,r.check_question)))
        self.assertEqual(r.question_purpose,'judge_current_diagram')
        self.assertFalse(r.reveals_diagnosis)

    def test_current_mechanism_animation_remains_usable_for_an_accuracy_check(self):
        state,_,ids=F.prepare(None,self.data())
        a=assessment(visual_intent='explain-mechanism',mechanism_paths=paths(),visual_focus_ids=['r1'],focus_id='r1')
        plan=F.planned_visual(a,state,'message','How does this transfer travel?',ids,'press_for_accuracy')
        r=F.coordinate_reply(reply('Watch the moving arrows. Does the transfer follow the direction drawn in your model?',False,
                                   focus_id='r1',focus_ids=['r1'],visual_action='trace'),plan)
        self.assertEqual(r.visual_action,'trace')
        self.assertTrue(r.mechanism_paths)
        self.assertFalse(F.reply_problem(r,state,a,ids,'message','','press_for_accuracy'))

    def test_review_resets_accuracy_timestamp_and_keeps_dialogue_versions(self):
        state=self.thinking_state();state['edit_enabled']=True
        state['turns']=[dict(student='The direction follows its source.',content='Does this connection show the transfer?',
                            trigger='message',talk_move='press_for_accuracy',version=2)]
        updated,context,_=F.prepare(state,dict(trigger='workspace-complete',scene=self.changed(),explanation='',edits=[],revision_reason='I renamed the source.'))
        self.assertEqual(updated['accuracy_started_at'],0)
        self.assertEqual(updated['accuracy_focus'],[])
        self.assertEqual(context['accuracy_started_at'],0)
        self.assertEqual(context['dialogue'][0]['version'],2)

    def test_press_rejects_a_diagnosis_followed_by_a_repair_question(self):
        state,_,ids=F.prepare(None,self.data())
        r=reply('This connection sends the transfer in the wrong direction. Where should you move it?',False,
                question_purpose='plan_revision',reveals_diagnosis=True)
        self.assertTrue(F.reply_problem(r,state,assessment(),ids,'message','','press_for_accuracy'))

    def test_press_rejects_repair_wording_even_when_labeled_as_a_current_check(self):
        state,_,ids=F.prepare(None,self.data())
        for question in ('Where would you move this connection?',
                         'What position would this object need to be in?',
                         'What would its position need to be relative to the two paths?',
                         'How could you change this connection?'):
            with self.subTest(question=question):
                r=reply(question,False,question_purpose='judge_current_diagram',reveals_diagnosis=False)
                self.assertTrue(F.reply_problem(r,state,assessment(),ids,'message','','press_for_accuracy'))

    def test_press_rejects_an_extra_conclusion_outside_check_fields(self):
        state,_,ids=F.prepare(None,self.data())
        r=reply('Does this direction match the source?',False)
        r.content='This connection is incorrect. '+r.content
        self.assertTrue(F.reply_problem(r,state,assessment(),ids,'message','','press_for_accuracy'))

    def test_press_rejects_a_verdict_disguised_as_a_neutral_observation(self):
        state,_,ids=F.prepare(None,self.data())
        for observation in ('This placement is incorrect.',
                            'The transfer bypasses this component, so it misses part of the transfer.'):
            with self.subTest(observation=observation):
                r=reply(observation+' Does it match the task?',False,reveals_diagnosis=False)
                self.assertTrue(F.reply_problem(r,state,assessment(),ids,'message','','press_for_accuracy'))

    def test_press_rejects_diagnosis_in_a_separate_acknowledgment(self):
        state,_,ids=F.prepare(None,self.data())
        r=reply('Does this direction match the source of the transfer?',acknowledgment='This connection is incorrect.',
                acknowledgment_ids=['o3'],reveals_diagnosis=False)
        self.assertTrue(F.reply_problem(r,state,assessment(),ids,'message','','press_for_accuracy'))

    def test_revision_press_acknowledgment_cannot_announce_a_verdict(self):
        state,_,ids=F.prepare(None,self.data())
        r=reply('Does the revised connection match the transfer source?',acknowledgment='Your revised connection is incorrect.',
                acknowledgment_ids=['o3'],reveals_diagnosis=False)
        self.assertTrue(F.reply_problem(r,state,assessment(),ids,'workspace-complete','','press_for_accuracy'))

    def test_press_rejects_a_diagnostic_premise_inside_its_question(self):
        state,_,ids=F.prepare(None,self.data())
        for question in ('Since this connection sends the transfer the wrong way, does it meet the goal?',
                         'Because this component misses part of the transfer, does it meet the goal?',
                         'Given that this object represents only one part, does it represent the whole?'):
            with self.subTest(question=question):
                r=reply(question,False,reveals_diagnosis=False)
                self.assertTrue(F.reply_problem(r,state,assessment(),ids,'message','','press_for_accuracy'))

    def test_press_rejects_a_hidden_statement_inside_check_question(self):
        state,_,ids=F.prepare(None,self.data())
        content='This component misses part of the transfer. Does it meet the goal?'
        r=reply(content,False,check_observation='',check_question=content,reveals_diagnosis=False)
        self.assertTrue(F.reply_problem(r,state,assessment(),ids,'message','','press_for_accuracy'))

    def test_press_accepts_a_hypothetical_mechanism_question(self):
        state,_,ids=F.prepare(None,self.data())
        a=assessment(visual_intent='explain-mechanism',mechanism_paths=paths(),visual_focus_ids=['r1'],focus_id='r1',
                     mechanism_requires_condition=True,mechanism_condition='If the process is running')
        plan=F.planned_visual(a,state,'message','How does this process work?',ids,'press_for_accuracy')
        r=F.coordinate_reply(reply('If the process is running, do the moving arrows follow the route you drew?',False,
                                  focus_id='r1',focus_ids=['r1'],visual_action='trace'),plan)
        self.assertFalse(F.reply_problem(r,state,a,ids,'message','','press_for_accuracy'))

    def test_revision_press_accepts_a_neutral_change_acknowledgment(self):
        state,_,ids=F.prepare(None,self.data())
        r=reply('Does the revised connection match the transfer source?',acknowledgment='You revised this connection.',acknowledgment_ids=['o3'])
        self.assertFalse(F.reply_problem(r,state,assessment(),ids,'workspace-complete','','press_for_accuracy'))

    def test_press_cannot_reveal_a_diagnosis_even_if_a_learner_quote_exists(self):
        state=self.thinking_state();state['_current_message']='The transfer is going in the opposite direction.'
        a=assessment(learner_diagnosis_evidence=state['_current_message'])
        ids={o['id'] for o in SCENE['objects']}|{r['id'] for r in SCENE['relations']}
        r=reply('Does this connection send the transfer in the wrong direction?',False,reveals_diagnosis=True)
        self.assertTrue(F.reply_problem(r,state,a,ids,'message','','press_for_accuracy'))

    def test_diagnosis_confirmation_needs_exact_current_issue_learner_evidence(self):
        state=self.thinking_state();state['_current_message']='The transfer is going in the opposite direction.'
        ids={o['id'] for o in SCENE['objects']}|{r['id'] for r in SCENE['relations']}
        a=assessment(learner_diagnosis_evidence=state['_current_message'])
        r=reply('Good catch, the direction does not match that transfer. How does the source help you explain this direction?',False,
                reveals_diagnosis=True,question_purpose='develop_reasoning')
        self.assertFalse(F.reply_problem(r,state,a,ids,'message','','build_on_prior_knowledge'))
        state['accuracy_focus']=['c1','o1']
        self.assertTrue(F.reply_problem(r,state,a,ids,'message','','build_on_prior_knowledge'))

    def test_old_invented_trivial_or_long_diagnosis_quotes_do_not_authorize_a_verdict(self):
        state=self.thinking_state();ids={o['id'] for o in SCENE['objects']}|{r['id'] for r in SCENE['relations']}
        r=reply('The direction does not match the transfer. Use its source to guide your next decision.',False,reveals_diagnosis=True)
        cases=[('yes','yes',[]),('no','no',[]),('both','both',[]),
               ('An invented learner conclusion.','I am unsure.',[]),
               ('The transfer goes in the opposite direction.','I agree.',[dict(student='The transfer goes in the opposite direction.',version=1)]),
               ('word '*26,'word '*26,[])]
        for quote,message,turns in cases:
            with self.subTest(quote=quote):
                state['_current_message']=message;state['turns']=turns
                a=assessment(learner_diagnosis_evidence=quote)
                self.assertTrue(F.reply_problem(r,state,a,ids,'message','','build_on_prior_knowledge'))

    def test_explicit_hint_allows_direct_diagnosis_without_an_accuracy_answer(self):
        state,_,ids=F.prepare(None,self.data());state['intent']='hint';state['_current_message']='I need a hint.'
        r=guidance('This connection sends the transfer in the wrong direction. Follow its source toward the destination.',reveals_diagnosis=True)
        self.assertFalse(F.reply_problem(r,state,assessment(),ids,'message','','provide_hints_guidance'))

    def test_three_unsuccessful_responses_authorize_focused_help_without_a_fresh_accuracy_quiz(self):
        state=self.thinking_state();state['_current_message']='I think the receiving end is the source.'
        state['unsuccessful_response_count']=3
        ids={o['id'] for o in SCENE['objects']}|{r['id'] for r in SCENE['relations']}
        r=guidance('The direction does not match this transfer. Follow its source toward the destination.',reveals_diagnosis=True)
        self.assertFalse(F.reply_problem(r,state,assessment(student_stuck=True),ids,'message','','provide_hints_guidance'))
        state['accuracy_focus']=['c1','o1']
        self.assertFalse(F.reply_problem(r,state,assessment(student_stuck=True),ids,'message','','provide_hints_guidance'))


if __name__=='__main__':unittest.main()
