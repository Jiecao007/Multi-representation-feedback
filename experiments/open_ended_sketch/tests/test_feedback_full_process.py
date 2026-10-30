"""The complete feedback graph, exercised through the live runtime.

Every model response is a local typed stub. These tests check which responses
the runtime accepts, state transitions, submitted-diagram review and call counts;
they do not establish live-model teaching quality.
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
from agent_types import EvaluationResult, TutorTurn
from case_resume import prepare_resume
from test_three_agent_runtime import FakeClient, SCENE, context


M1 = dict(id='m1', criterion='c1', description='Show the transfer direction.',
          evidence='The represented direction still needs explanation.', focus_ids=['o3'])
M2 = dict(id='m2', criterion='c1', description='Explain the transfer quantity.',
          evidence='The quantity relationship remains unexplained.', focus_ids=['o3'])
READY = 'The arrow should point toward the receiver because the transfer ends there.'
INSTRUCTION = 'Draw one arrow pointing toward the receiver.'


def assessment(parts=None, outcome='not_reviewed', **changes):
    parts = deepcopy([M1, M2] if parts is None else parts)
    value = dict(
        learning_goal='Represent the direction and quantity of the transfer.',
        task_summary='Show the transfer direction and explain its quantity.',
        criteria=[dict(criterion='c1', status='developing' if parts else 'established',
                       level='developing' if parts else 'demonstrated',
                       evidence='The direction and quantity need explanation.' if parts
                       else 'The submitted direction and quantity are supported.')],
        strengths=[dict(description='The source is represented.',
                        evidence='The source component is visible.', focus_ids=['o3'])],
        missing_parts=parts, uncertainties=[], revision_outcome=outcome,
        revision_evidence='' if outcome == 'not_reviewed' else 'The submitted change was compared with the addressed issue.',
    )
    value.update(changes)
    return EvaluationResult(**value)


def turn(move='invite_elaboration_reasoning', issue='m1', **changes):
    value = dict(
        content='How does this connection represent the transfer?', acknowledgment='',
        talk_moves=[move], issue_id=issue, stage='thinking-dialogue',
        focus_ids=['o3'], acknowledgment_ids=[], visual_action='highlight',
        visual_delivery='automatic', next_step='explain',
        question_target='Explain the represented transfer relationship.',
        progress='other',
    )
    value.update(changes)
    return TutorTurn(**value)


def opening(issue='m1'):
    return turn('recognize_strengths', issue,
                acknowledgment='Nice work showing the source clearly!',
                content='Is this the source you intended?', stage='recognition',
                acknowledgment_ids=['o3'])


def check(issue='m1'):
    return turn('press_for_accuracy', issue, content='What transfer does your current arrow show?',
                stage='inquiry', question_target='Judge the current transfer direction.')


def guidance(issue='m1', **changes):
    value = dict(content='An arrowhead shows where the transfer ends.',
                 question_target='', stage='thinking-dialogue')
    value.update(changes)
    return turn('provide_hints_guidance', issue, **value)


class FullFeedbackProcessTests(unittest.TestCase):
    def setUp(self):
        F.SESSIONS.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def data(self, **changes):
        value = dict(trigger='submission', scene=deepcopy(SCENE), original_scene=deepcopy(SCENE),
                     explanation='', task='Show the transfer direction and explain its quantity.',
                     goals=['Explain transfer direction and quantity.'], source_id='full-process-fixture',
                     message='', edits=[])
        value.update(changes)
        return value

    def call(self, data, values):
        client = FakeClient(values)
        result = F.handle(data, client, self.directory, 'local-evaluation',
                          fast_dialogue_model='local-fast-tutor')
        return result, client

    def start(self, parts=None):
        result, client = self.call(self.data(), [assessment(parts), opening()])
        self.assertEqual(result['agents_called'], ['evaluation', 'tutor'])
        self.assertEqual(len(client.calls), 2)
        return result['session_id']

    def state(self, sid):
        return F.SESSIONS[sid]['state']

    def message(self, sid, text, candidate, **changes):
        data = dict(trigger='message', session_id=sid, message=text)
        data.update(changes)
        result, client = self.call(data, [candidate])
        self.assertEqual(result['agents_called'], ['tutor'])
        self.assertEqual(len(client.calls), 1)
        return result, client

    def checked(self, parts=None):
        sid = self.start(parts)
        result, client = self.message(sid, 'Yes, that is the source.', check())
        self.assertEqual(result['stage'], 'inquiry')
        self.assertEqual(context(client.calls[0])['interaction']['expected_stage'], 'inquiry')
        contract = client.calls[0]['text_format']
        self.assertTrue(issubclass(contract, TutorTurn))
        schema = contract.model_json_schema()['properties']
        self.assertEqual(schema['issue_id']['const'], 'm1')
        self.assertEqual(schema['stage']['const'], 'inquiry')
        self.assertIn('press_for_accuracy', schema['talk_moves']['items']['enum'])
        self.assertNotIn('invite_elaboration_reasoning', schema['talk_moves']['items']['enum'])
        return sid

    def revise(self, sid, result, response, explanation='The submitted arrow shows the transfer.'):
        F.begin_revision(dict(session_id=sid))
        changed = deepcopy(self.state(sid)['committed']['scene'])
        changed['objects'][0]['label'] += ' revised'
        return self.call(dict(trigger='workspace-complete', session_id=sid,
                              scene=changed, explanation=explanation, edits=[]), [result, response])

    def reject(self, sid, message, candidate, **changes):
        before = deepcopy(self.state(sid))
        client = FakeClient([candidate])
        data = dict(trigger='message', session_id=sid, message=message)
        data.update(changes)
        with self.assertRaises((F.FeedbackError, ValueError)):
            F.handle(data, client, self.directory, 'local-evaluation', fast_dialogue_model='local-fast-tutor')
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(self.state(sid), before)
        records = list(self.directory.glob('feedback_turn_*/validation.json'))
        self.assertTrue(records)
        record = json.loads(max(records, key=lambda path: path.stat().st_mtime).read_text())
        self.assertTrue(record['problem'])
        self.assertFalse(record['automatic_rewrite'])

    def test_normal_path_checks_current_diagram_before_support_without_more_evaluation(self):
        sid = self.checked()
        before = deepcopy(self.state(sid)['learner_model'])
        result, client = self.message(sid, 'It points toward the receiver.', turn(progress='progress'))
        self.assertEqual(context(client.calls[0])['interaction']['expected_stage'], 'thinking-dialogue')
        self.assertEqual(result['stage'], 'thinking-dialogue')
        self.assertEqual(self.state(sid)['current_issue_id'], 'm1')
        self.assertEqual(self.state(sid)['learner_model'], before)

    def test_rejects_the_recorded_post_highlight_skip(self):
        sid = self.start()
        self.reject(sid, 'Yes, that is the source.', turn())

    def test_readiness_quote_alone_cannot_skip_initial_check_for_a_plan(self):
        sid = self.start()
        self.reject(sid, READY, turn('propose_revision_plan', content=INSTRUCTION,
                                    stage='revision-planning', edit_instruction=INSTRUCTION,
                                    next_step='revise', move_evidence=dict(readiness_evidence=READY)))

    def test_goal_clarification_does_not_consume_the_current_diagram_check(self):
        sid = self.start()
        result, client = self.message(sid, 'What is the goal of this task?',
                                      turn('clarify_goals', stage='inquiry',
                                           content='The goal is to show the transfer direction and explain its quantity.'))
        self.assertTrue(context(client.calls[0])['interaction']['goal_clarification_requested'])
        self.assertEqual(result['stage'], 'inquiry')
        result, client = self.message(sid, 'I understand the goal now.', check())
        self.assertTrue(context(client.calls[0])['interaction']['check_required'])
        result, client = self.message(sid, 'The arrow points to the receiver.', turn())
        self.assertFalse(context(client.calls[0])['interaction']['check_required'])

    def test_statement_only_press_cannot_consume_the_initial_check(self):
        sid = self.start()
        self.reject(sid, 'Yes, that is the source.',
                    turn('press_for_accuracy', content='Let us inspect the current arrow.', stage='inquiry'))
        result, client = self.message(sid, 'Yes, that is the source.', check())
        self.assertTrue(context(client.calls[0])['interaction']['check_required'])
        self.assertEqual(result['stage'], 'inquiry')

    def test_third_difficulty_guidance_is_expressible_during_the_initial_check(self):
        sid = self.start()
        self.state(sid)['consecutive_difficulties'] = 2
        result, client = self.message(sid, 'The arrow still points toward the source.', guidance(progress='difficulty'))
        interaction = context(client.calls[0])['interaction']
        self.assertTrue(interaction['check_required'])
        self.assertIn('provide_hints_guidance', interaction['allowed_moves'])
        self.assertEqual(result['stage'], 'thinking-dialogue')
        self.assertEqual(self.state(sid)['consecutive_difficulties'], 3)
        result, client = self.message(sid, 'It should end at the receiver.', turn(progress='progress'))
        self.assertEqual(context(client.calls[0])['interaction']['expected_stage'], 'thinking-dialogue')

    def test_rejects_spontaneous_issue_switch_before_review(self):
        sid = self.checked()
        self.reject(sid, 'It points toward the receiver.', turn(issue='m2'))

    def test_rejects_unrequested_completion_while_an_issue_remains(self):
        sid = self.checked()
        self.reject(sid, 'I think so.', turn('invite_dialogue', content='Thanks for completing your model.',
                                           stage='complete', question_target=''))

    def test_support_meaning_pair_keeps_issue_and_does_not_restart_initial_check(self):
        sid = self.checked()
        candidate = turn('revoice', content='You mean the routes meet there. Which arrow do you mean?',
                         talk_moves=['revoice', 'ask_for_clarification'],
                         move_evidence=dict(revoice_need='Check the route interpretation.',
                                            revoice_evidence='The two routes meet there',
                                            clarification_need='Identify the arrow called this arrow.'))
        result, _ = self.message(sid, 'The two routes meet there, so this arrow includes both.', candidate)
        self.assertEqual(result['stage'], 'thinking-dialogue')
        result, client = self.message(sid, 'I mean this arrow toward the receiver.', turn())
        self.assertEqual(context(client.calls[0])['interaction']['expected_stage'], 'thinking-dialogue')
        self.assertEqual(self.state(sid)['current_issue_id'], 'm1')

    def test_unsuccessful_review_keeps_addressed_issue_when_new_gaps_are_reordered(self):
        sid = self.checked()
        result, client = self.revise(sid, assessment([M2, M1], 'unsuccessful'),
                                    turn(acknowledgment='The direction still needs correction.'))
        self.assertEqual(context(client.calls[0])['addressed_issue']['id'], 'm1')
        self.assertEqual(context(client.calls[1])['current_issue']['id'], 'm1')
        self.assertEqual(self.state(sid)['current_issue_id'], 'm1')
        self.assertEqual(result['stage'], 'thinking-dialogue')
        self.assertEqual(result['agents_called'], ['evaluation', 'tutor'])
        self.assertEqual([p['id'] for p in self.state(sid)['learner_model']['evaluation']['result']['missing_parts']], ['m2', 'm1'])

    def test_unsuccessful_review_keeps_anchor_even_when_new_formal_gap_list_omits_it(self):
        sid = self.checked()
        result, client = self.revise(sid, assessment([M2], 'unsuccessful'),
                                    turn(acknowledgment='The addressed direction remains unresolved.'))
        self.assertEqual(context(client.calls[1])['current_issue']['id'], 'm1')
        self.assertEqual(self.state(sid)['current_issue_id'], 'm1')
        self.assertEqual([p['id'] for p in self.state(sid)['learner_model']['evaluation']['result']['missing_parts']], ['m2'])
        self.assertEqual(result['stage'], 'thinking-dialogue')

    def test_uncertain_review_clarifies_within_support_and_keeps_omitted_anchor(self):
        sid = self.checked()
        clarification = turn('ask_for_clarification', content='Which transfer does this revised arrow represent?',
                             move_evidence=dict(clarification_need='Identify the revised arrow’s intended transfer.'))
        result, client = self.revise(sid, assessment([M2], 'uncertain'), clarification)
        self.assertEqual(result['stage'], 'thinking-dialogue')
        self.assertEqual(context(client.calls[1])['current_issue']['id'], 'm1')
        self.assertEqual(self.state(sid)['current_issue_id'], 'm1')
        result, client = self.message(sid, 'It represents the transfer to the receiver.', turn())
        self.assertEqual(context(client.calls[0])['interaction']['expected_stage'], 'thinking-dialogue')
        self.assertEqual(result['stage'], 'thinking-dialogue')

    def test_uncertain_review_cannot_skip_clarification_or_restart_press(self):
        for invalid in (turn(), check()):
            with self.subTest(move=invalid.talk_moves):
                F.SESSIONS.clear()
                sid = self.checked()
                before = deepcopy(self.state(sid))
                F.begin_revision(dict(session_id=sid))
                opened = deepcopy(self.state(sid))
                changed = deepcopy(SCENE)
                changed['objects'][0]['label'] = 'Uncertain revision'
                client = FakeClient([assessment([M2], 'uncertain'), invalid])
                with self.assertRaises((F.FeedbackError, ValueError)):
                    F.handle(dict(trigger='workspace-complete', session_id=sid, scene=changed,
                                  explanation='', edits=[]), client, self.directory,
                             'local-evaluation', fast_dialogue_model='local-fast-tutor')
                self.assertEqual(self.state(sid), opened)
                self.assertEqual(len(client.calls), 2)
                self.assertEqual(before['learner_model'], opened['learner_model'])

    def test_frustration_during_uncertain_review_preserves_the_pending_meaning_check(self):
        sid = self.checked()
        F.begin_revision(dict(session_id=sid))
        changed = deepcopy(SCENE)
        changed['objects'][0]['label'] = 'Uncertain changed endpoint'
        result, client = self.call(dict(trigger='workspace-complete', session_id=sid,
                                       scene=changed, explanation='', edits=[], message='This is frustrating.'),
                                   [assessment([M2], 'uncertain'), guidance()])
        self.assertEqual(result['talk_move'], 'provide_hints_guidance')
        self.assertEqual(self.state(sid)['current_issue_id'], 'm1')
        clarification = turn('ask_for_clarification', content='Which transfer does the revised arrow represent?',
                             move_evidence=dict(clarification_need='Identify the intended revised transfer.'))
        result, client = self.message(sid, 'I can look at the revised arrow now.', clarification)
        self.assertTrue(context(client.calls[0])['interaction']['review_clarification_required'])
        self.assertEqual(result['stage'], 'thinking-dialogue')

    def test_successful_review_praises_and_enters_next_issue_support_directly(self):
        sid = self.checked()
        response = turn(issue='m2', acknowledgment='Nice revision! The direction now matches the transfer.',
                        content='How does the quantity fit your model?')
        result, client = self.revise(sid, assessment([M2], 'successful'), response)
        self.assertEqual(result['stage'], 'thinking-dialogue')
        self.assertEqual(self.state(sid)['current_issue_id'], 'm2')
        self.assertEqual(context(client.calls[1])['interaction']['expected_stage'], 'thinking-dialogue')
        result, client = self.message(sid, 'The quantity describes how much is transferred.', turn(issue='m2'))
        self.assertEqual(context(client.calls[0])['interaction']['expected_stage'], 'thinking-dialogue')
        self.assertEqual(result['stage'], 'thinking-dialogue')

    def test_successful_review_cannot_start_a_new_highlight_or_accuracy_quiz(self):
        for invalid in (opening('m2'), check('m2')):
            with self.subTest(move=invalid.talk_moves):
                F.SESSIONS.clear()
                sid = self.checked()
                F.begin_revision(dict(session_id=sid))
                before = deepcopy(self.state(sid))
                changed = deepcopy(SCENE)
                changed['objects'][0]['label'] = 'Successful direction revision'
                client = FakeClient([assessment([M2], 'successful'), invalid])
                with self.assertRaises((F.FeedbackError, ValueError)):
                    F.handle(dict(trigger='workspace-complete', session_id=sid, scene=changed,
                                  explanation='', edits=[]), client, self.directory,
                             'local-evaluation', fast_dialogue_model='local-fast-tutor')
                self.assertEqual(self.state(sid), before)
                self.assertEqual(len(client.calls), 2)

    def test_successful_review_must_recognize_the_actual_correction(self):
        sid = self.checked()
        F.begin_revision(dict(session_id=sid))
        before = deepcopy(self.state(sid))
        changed = deepcopy(SCENE)
        changed['objects'][0]['label'] = 'Corrected transfer direction'
        client = FakeClient([assessment([M2], 'successful'), turn(issue='m2')])
        with self.assertRaises(F.FeedbackError):
            F.handle(dict(trigger='workspace-complete', session_id=sid, scene=changed,
                          explanation=READY, edits=[]), client, self.directory,
                     'local-evaluation', fast_dialogue_model='local-fast-tutor')
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(self.state(sid), before)

    def test_invalid_revision_assessment_is_rejected_before_tutor_or_state_commit(self):
        invalid = [assessment([M1, M2], 'not_reviewed'),
                   assessment([M2], 'successful', revision_evidence=''),
                   assessment([M2], 'unsuccessful', revision_evidence=''),
                   assessment([M1, M2], 'successful', addressed_issue_status='resolved')]
        for result in invalid:
            with self.subTest(outcome=result.revision_outcome, evidence=result.revision_evidence,
                              gaps=[part.id for part in result.missing_parts]):
                F.SESSIONS.clear()
                sid = self.checked()
                F.begin_revision(dict(session_id=sid))
                before = deepcopy(self.state(sid))
                changed = deepcopy(SCENE)
                changed['objects'][0]['label'] = 'Changed submitted work'
                client = FakeClient([result])
                with self.assertRaises(F.FeedbackError):
                    F.handle(dict(trigger='workspace-complete', session_id=sid, scene=changed,
                                  explanation='', edits=[]), client, self.directory,
                             'local-evaluation', fast_dialogue_model='local-fast-tutor')
                self.assertEqual(len(client.calls), 1)
                self.assertIs(client.calls[0]['text_format'], EvaluationResult)
                self.assertEqual(self.state(sid), before)

    def test_initial_evaluation_cannot_claim_a_reviewed_correction(self):
        client = FakeClient([assessment([M2], 'successful')])
        with self.assertRaises(F.FeedbackError):
            F.handle(self.data(), client, self.directory, 'local-evaluation', fast_dialogue_model='local-fast-tutor')
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(F.SESSIONS, {})

    def test_all_resolved_invites_dialogue_then_no_further_questions_finishes(self):
        sid = self.checked()
        closing = turn('invite_dialogue', issue='', acknowledgment='Nice revision! Your model now meets the task.',
                       content='What else would you like to ask?', stage='dialogue', question_target='')
        result, client = self.revise(sid, assessment([], 'successful'), closing)
        self.assertEqual(result['stage'], 'dialogue')
        self.assertEqual(self.state(sid)['current_issue_id'], '')
        self.assertEqual(result['content'].count('?'), 1)
        result, client = self.message(sid, 'No, thanks.',
                                      turn('invite_dialogue', issue='', content='Thanks for working through your diagram!',
                                           stage='complete', question_target=''))
        self.assertEqual(result['stage'], 'complete')
        self.assertFalse(result['edit_enabled'])
        self.assertNotIn('?', result['content'])

    def test_initially_complete_work_still_gets_highlight_before_the_closing_invitation(self):
        first, _ = self.call(self.data(), [assessment([]), opening(issue='')])
        sid = first['session_id']
        self.assertEqual(first['stage'], 'recognition')
        result, _ = self.message(sid, 'Yes, that is what I intended.',
                                  turn('invite_dialogue', issue='', content='What else would you like to ask?',
                                       stage='dialogue', question_target=''))
        self.assertEqual(result['stage'], 'dialogue')
        result, _ = self.message(sid, 'No further questions.',
                                  turn('invite_dialogue', issue='', content='Thanks for explaining your model!',
                                       stage='complete', question_target=''))
        self.assertEqual(result['stage'], 'complete')

    def test_empty_gap_list_does_not_close_unestablished_requested_criteria(self):
        sid = self.checked()
        unresolved = assessment([], 'successful', criteria=[dict(criterion='c1', status='developing',
                                 level='developing', evidence='A requested quantity relationship remains unresolved.')])
        F.begin_revision(dict(session_id=sid))
        before = deepcopy(self.state(sid))
        changed = deepcopy(SCENE)
        changed['objects'][0]['label'] = 'Changed work'
        client = FakeClient([unresolved, turn('invite_dialogue', issue='', content='Any other questions?',
                                            stage='dialogue', question_target='')])
        with self.assertRaises((F.FeedbackError, ValueError)):
            F.handle(dict(trigger='workspace-complete', session_id=sid, scene=changed, explanation='', edits=[]),
                     client, self.directory, 'local-evaluation', fast_dialogue_model='local-fast-tutor')
        self.assertEqual(self.state(sid), before)

    def test_learner_can_explicitly_exit_before_resolution_but_quoted_or_negated_exit_cannot_close(self):
        sid = self.checked()
        for text in ("I don't want to stop.", 'My friend said "I want to stop now".',
                     'What happens if someone says "I am finished"?'):
            with self.subTest(message=text):
                self.reject(sid, text, turn('invite_dialogue', content='Thanks for working on your diagram!',
                                           stage='complete', question_target=''))
        result, _ = self.message(sid, 'I want to stop now.',
                                  turn('invite_dialogue', content='Thanks for working on your diagram!',
                                       stage='complete', question_target=''))
        self.assertEqual(result['stage'], 'complete')
        self.assertTrue(self.state(sid)['learner_model']['evaluation']['result']['missing_parts'])

    def test_explicit_revision_can_resume_a_finished_session(self):
        sid = self.checked()
        self.message(sid, 'I want to stop now.',
                     turn('invite_dialogue', content='Thanks for working on your diagram!',
                          stage='complete', question_target=''))
        self.assertTrue(self.state(sid)['workflow']['finished'])
        result, client = self.message(sid, 'I want to revise the arrow.',
                                      turn('propose_revision_plan', content=INSTRUCTION,
                                           edit_instruction=INSTRUCTION, next_step='revise',
                                           stage='revision-planning'))
        self.assertTrue(context(client.calls[0])['interaction']['revision_requested'])
        self.assertFalse(self.state(sid)['workflow']['finished'])
        self.assertTrue(result['edit_enabled'])
        self.assertEqual(self.state(sid)['current_issue_id'], 'm1')

    def test_hint_interval_counts_delivered_dialogue_and_does_not_block_frustration_help(self):
        sid = self.checked()
        result, _ = self.message(sid, 'I need a hint.', guidance(), intent='hint')
        self.assertEqual(result['hint_turns_remaining'], 2)
        before = deepcopy(self.state(sid))
        client = FakeClient([])
        with self.assertRaises(F.FeedbackError):
            F.handle(dict(trigger='message', session_id=sid, intent='hint', message='I need another hint.'),
                     client, self.directory, 'local-evaluation', fast_dialogue_model='local-fast-tutor')
        self.assertEqual(client.calls, [])
        self.assertEqual(self.state(sid), before)
        result, _ = self.message(sid, 'This is frustrating. I still do not understand.', guidance())
        self.assertEqual(result['hint_turns_remaining'], 1)
        result, _ = self.message(sid, 'I see that the arrowhead shows the destination.', turn(progress='progress'))
        self.assertEqual(result['hint_turns_remaining'], 0)
        result, _ = self.message(sid, 'I need another hint.', guidance(), intent='hint')
        self.assertEqual(result['hint_turns_remaining'], 2)

    def test_incorrect_answers_get_support_before_third_same_issue_guidance(self):
        sid = self.start()
        result, _ = self.message(sid, 'I am not sure, but the tail shows the destination.',
                                 turn(content='Which end of the arrow has its arrowhead?', progress='difficulty'))
        self.assertEqual(result['talk_move'], 'invite_elaboration_reasoning')
        result, _ = self.message(sid, 'The tail marks the receiving end.',
                                 turn(content='At which component does the arrowhead appear?', progress='difficulty'))
        self.assertEqual(self.state(sid)['consecutive_difficulties'], 2)
        self.reject(sid, 'The tail marks the receiving end.', turn(progress='difficulty'))
        result, _ = self.message(sid, 'The tail marks the receiving end.', guidance(progress='difficulty'))
        self.assertEqual(self.state(sid)['consecutive_difficulties'], 3)
        result, _ = self.message(sid, 'It ends at the receiver.', turn(progress='progress'))
        self.assertEqual(self.state(sid)['consecutive_difficulties'], 0)

    def test_ready_plan_invitation_then_provided_edit_and_actual_revision(self):
        sid = self.checked()
        invited = turn('propose_revision_plan', content='How will you change the arrow to show that transfer?',
                       stage='revision-planning',
                       move_evidence=dict(plan_mode='invite', readiness_evidence=READY))
        result, _ = self.message(sid, READY, invited)
        self.assertFalse(result['edit_enabled'])
        self.assertEqual(result['next_step'], 'explain')
        provided = turn('propose_revision_plan', content=INSTRUCTION, stage='revision-planning',
                        edit_instruction=INSTRUCTION, next_step='revise',
                        move_evidence=dict(readiness_evidence='I will point it toward the receiver.'))
        result, _ = self.message(sid, 'I will point it toward the receiver.', provided)
        self.assertTrue(result['edit_enabled'])
        self.assertEqual(result['next_step'], 'revise')
        self.assertEqual(self.state(sid)['drawing_version'], 1)
        result, client = self.revise(sid, assessment([M2], 'successful'),
                                    turn(issue='m2', acknowledgment='Nice revision! The direction now fits.'))
        self.assertEqual(result['drawing_version'], 2)
        self.assertEqual(result['agents_called'], ['evaluation', 'tutor'])

    def test_begin_revision_is_available_before_initial_check_and_has_no_model_call(self):
        sid = self.start()
        before = deepcopy(self.state(sid))
        opened = F.begin_revision(dict(session_id=sid))
        self.assertTrue(opened['edit_enabled'])
        self.assertEqual(self.state(sid)['learner_model'], before['learner_model'])
        self.assertEqual(self.state(sid)['turns'], before['turns'])
        self.assertEqual(self.state(sid)['drawing_version'], before['drawing_version'])
        F.end_revision(dict(session_id=sid))
        self.assertEqual(self.state(sid), before)
        result, client = self.message(sid, 'Yes, that is the source.', check())
        self.assertTrue(context(client.calls[0])['interaction']['check_required'])

    def test_concept_help_during_open_revision_keeps_editing_and_uses_one_tutor(self):
        sid = self.start()
        F.begin_revision(dict(session_id=sid))
        before = deepcopy(self.state(sid))
        result, client = self.message(sid, 'Please explain what the arrowhead means.',
                                      turn(content='At which end can you see the arrowhead?', progress='uncertain'))
        self.assertEqual(result['talk_move'], 'invite_elaboration_reasoning')
        self.assertEqual(result['stage'], 'thinking-dialogue')
        self.assertEqual(result['guidance_instruction'], '')
        self.assertTrue(result['edit_enabled'])
        self.assertEqual(self.state(sid)['committed'], before['committed'])
        self.assertEqual(self.state(sid)['learner_model'], before['learner_model'])
        self.assertFalse(result['evaluation_updated'])

    def test_ordinary_dialogue_during_open_revision_is_not_forced_into_a_new_plan(self):
        sid = self.start()
        F.begin_revision(dict(session_id=sid))
        before = deepcopy(self.state(sid))
        result, client = self.message(sid, 'The arrowhead is at the receiver.', turn())
        interaction = context(client.calls[0])['interaction']
        self.assertEqual(interaction['process_phase'], 'editing')
        self.assertIn('invite_elaboration_reasoning', interaction['allowed_moves'])
        self.assertEqual(result['talk_move'], 'invite_elaboration_reasoning')
        self.assertEqual(result['stage'], 'thinking-dialogue')
        self.assertTrue(result['edit_enabled'])
        self.assertEqual(self.state(sid)['committed'], before['committed'])
        self.assertEqual(self.state(sid)['learner_model'], before['learner_model'])
        self.assertFalse(result['evaluation_updated'])

    def test_explicit_revision_request_can_invite_a_plan_without_inventing_an_edit(self):
        sid = self.start()
        invitation = turn('propose_revision_plan', content='How will you change the arrow?',
                          stage='revision-planning', move_evidence=dict(plan_mode='invite'))
        result, client = self.message(sid, 'I want to revise the arrow.', invitation)
        self.assertTrue(context(client.calls[0])['interaction']['revision_requested'])
        self.assertEqual(result['stage'], 'revision-planning')
        self.assertEqual(result['guidance_instruction'], '')
        self.assertFalse(result['edit_enabled'])

    def test_unchanged_and_explanation_only_submissions_do_not_evaluate_or_resolve_issue(self):
        sid = self.checked()
        formal = deepcopy(self.state(sid)['learner_model']['evaluation'])
        for explanation in ('', 'I can now describe the transfer direction.'):
            with self.subTest(explanation=explanation):
                F.begin_revision(dict(session_id=sid))
                result, client = self.call(dict(trigger='workspace-complete', session_id=sid,
                                                scene=deepcopy(SCENE), explanation=explanation, edits=[]), [turn()])
                self.assertEqual(len(client.calls), 1)
                self.assertEqual(result['agents_called'], ['tutor'])
                self.assertFalse(result['evaluation_updated'])
                self.assertEqual(self.state(sid)['learner_model']['evaluation'], formal)
                self.assertEqual(self.state(sid)['current_issue_id'], 'm1')

    def test_saved_session_restores_current_process_without_a_new_evaluation(self):
        sid = self.checked()
        state = deepcopy(self.state(sid))
        result = state['turns'][-1]
        case = dict(feedback_session=sid, feedback_turns=[dict(version=state['version'], drawing_version=1)],
                    committed_work=state['committed'], current_draft=state['committed'],
                    original_model=state['original']['scene'], source=dict(id='full-process-fixture'))
        path = self.directory / 'saved.exploration.json'
        path.write_text(json.dumps(case))
        restored, backend = prepare_resume(path, self.directory,
            lambda source: dict(record=dict(id=source), scene=deepcopy(SCENE)))
        self.assertEqual(backend['current_issue_id'], 'm1')
        self.assertEqual(backend['learner_model'], state['learner_model'])
        self.assertEqual(backend.get('workflow'), state.get('workflow'))
        F.SESSIONS[sid]['state'] = backend
        public, client = self.message(sid, 'The arrow ends at the receiver.', turn())
        self.assertEqual(context(client.calls[0])['interaction']['expected_stage'], 'thinking-dialogue')
        self.assertEqual(public['agents_called'], ['tutor'])

    def test_pre_controller_session_migrates_check_history_without_new_evaluation(self):
        sid = self.checked()
        state = self.state(sid)
        state.pop('workflow', None)
        state['runtime_version'] = 'three-agent-v1'
        formal = deepcopy(state['learner_model']['evaluation'])
        result, client = self.message(sid, 'It transfers toward the receiver.', turn())
        self.assertEqual(result['agents_called'], ['tutor'])
        self.assertEqual(context(client.calls[0])['interaction']['expected_stage'], 'thinking-dialogue')
        self.assertEqual(self.state(sid)['learner_model']['evaluation'], formal)


if __name__ == '__main__':
    unittest.main()
