"""Live three-agent contract checks using typed local model stubs.

These exercise the new runtime, not the archived feedback-policy implementation.
No external model, simulated learner, or original research output is used.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'app'))
import feedback as F
from agent_types import EvaluationResult, TutorTurn

SCENE = json.loads((HERE / 'results/20260922T035929331824Z/pic1.scene.json').read_text())


def evaluation(**changes):
    value = dict(
        learning_goal='Explain the source and receiver in the represented transfer.',
        criteria=[dict(criterion='c1', status='developing', level='developing',
                       evidence='The components are visible; the transfer still needs explanation.')],
        strengths=[dict(description='The diagram includes a relevant component.',
                        evidence='A relevant component is drawn.', focus_ids=['o3'])],
        missing_parts=[dict(id='m1', criterion='c1', description='Explain the represented transfer.',
                            evidence='The initial explanation does not describe that relationship.', focus_ids=['o3'])],
        uncertainties=[], revision_outcome='not_reviewed', revision_evidence='',
    )
    value.update(changes)
    return EvaluationResult(**value)


def tutor(opening=False, **changes):
    value = dict(
        content='Which part shows the energy source?' if opening else 'How does the source connect to the receiver?',
        acknowledgment='Your drawing includes the energy source.' if opening else '',
        talk_moves=['recognize_strengths'] if opening else ['invite_elaboration_reasoning'],
        issue_id='m1', stage='recognition' if opening else 'thinking-dialogue',
        focus_ids=['o3'], acknowledgment_ids=['o3'] if opening else [],
        visual_action='highlight', visual_delivery='automatic',
        mechanism_paths=[], mechanism_condition='', edit_instruction='',
        next_step='explain', question_target='Explain the transfer.',
        progress='other', memory_updates=[],
    )
    value.update(changes)
    return TutorTurn(**value)


class FakeClient:
    def __init__(self, values):
        self.values = iter(values)
        self.calls = []
        self.responses = self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(status='completed', output_parsed=value, usage=None,
                               model_dump=lambda **kw: dict(status='completed', output=value.model_dump()))


def contract_types(client):
    return [EvaluationResult if issubclass(call['text_format'], EvaluationResult) else TutorTurn
            for call in client.calls]


def context(call):
    for item in call.get('input', []):
        for part in item.get('content', []):
            if part.get('type') != 'input_text':
                continue
            try:
                return json.loads(part['text'])
            except (KeyError, TypeError, ValueError):
                pass
    raise AssertionError('The agent call must include a structured JSON context.')


class ThreeAgentRuntimeTests(unittest.TestCase):
    def setUp(self):
        F.SESSIONS.clear()

    def data(self, **changes):
        value = dict(trigger='submission', scene=deepcopy(SCENE), original_scene=deepcopy(SCENE),
                     explanation='Food needs energy.', task='Explain the represented transfer.',
                     goals=['Explain source and receiver.'], source_id='local-contract-fixture',
                     message='', edits=[])
        value.update(changes)
        return value

    def handle(self, data, client, directory, **changes):
        return F.handle(data, client, directory, 'evaluation-model',
                        dialogue_model='fallback-tutor', fast_dialogue_model='fast-tutor', **changes)

    def start(self, directory, checked=False, **changes):
        client = FakeClient([evaluation(), tutor(opening=True)])
        public = self.handle(self.data(), client, directory, **changes)
        if checked:
            self.handle(dict(trigger='message', session_id=public['session_id'],
                             message='Yes, that is the source.'),
                        FakeClient([tutor(content='What transfer does the current arrow show?',
                                          talk_moves=['press_for_accuracy'], stage='inquiry')]), directory)
        return public, client

    def state(self, sid):
        return F.SESSIONS[sid]['state']

    def formal(self, sid):
        return deepcopy(self.state(sid)['learner_model']['evaluation'])

    def test_initial_submission_runs_evaluation_then_fast_tutor(self):
        with tempfile.TemporaryDirectory() as directory:
            public, client = self.start(directory)
            self.assertEqual(len(client.calls), 2)
            self.assertEqual(contract_types(client), [EvaluationResult, TutorTurn])
            self.assertEqual([call['model'] for call in client.calls], ['evaluation-model', 'fast-tutor'])
            self.assertEqual(public['talk_move'], 'recognize_strengths')
            self.assertEqual(public['content'].count('?'), 1)
            self.assertTrue(self.formal(public['session_id'])['result']['missing_parts'])

    def test_initial_evaluation_can_see_student_original_and_task_figure_while_tutor_is_text_only(self):
        student_image = 'data:image/png;base64,c3R1ZGVudA=='
        task_image = 'data:image/png;base64,dGFzaw=='
        with tempfile.TemporaryDirectory() as directory:
            _, client = self.start(directory, student_image=student_image, question_image=task_image)
            evaluation_parts = [part for item in client.calls[0]['input'] for part in item.get('content', [])]
            images = [part['image_url'] for part in evaluation_parts if part['type'] == 'input_image']
            self.assertEqual(set(images), {student_image, task_image})
            tutor_parts = [part for item in client.calls[1]['input'] for part in item.get('content', [])]
            self.assertTrue(all(part['type'] == 'input_text' for part in tutor_parts))

    def test_ordinary_messages_are_one_tutor_call_and_preserve_formal_evaluation(self):
        for message in ('It points toward the receiver.', "I don't know.",
                        'Please directly tell me.', 'I have changed my explanation of the whole task.',
                        'Move A2 to the common path.', 'Draw an arrow from 6 to 2.',
                        'I moved A2 and drew the missing arrow.'):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                first, _ = self.start(directory, checked=True)
                sid = first['session_id']
                formal = self.formal(sid)
                submitted = deepcopy(self.state(sid)['committed'])
                candidate = tutor()
                if 'tell me' in message:
                    candidate = tutor(content='Which end of the visible arrow has its arrowhead?',
                                      progress='uncertain')
                client = FakeClient([candidate])
                public = self.handle(dict(trigger='message', session_id=sid, message=message), client, directory)
                self.assertEqual(len(client.calls), 1)
                self.assertTrue(issubclass(client.calls[0]['text_format'], TutorTurn))
                self.assertEqual(client.calls[0]['model'], 'fast-tutor')
                self.assertEqual(self.formal(sid), formal)
                self.assertEqual(self.state(sid)['committed'], submitted)
                self.assertEqual(public['drawing_version'], 1)
                self.assertFalse(public['evaluation_updated'])
                self.assertFalse(context(client.calls[0])['interaction']['diagram_changed'])
                self.assertNotIn('assessment', TutorTurn.model_fields)

    def test_message_does_not_fall_back_to_evaluation_when_old_figure_cache_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory, checked=True, question_image='data:image/png;base64,dGVzdA==')
            sid = first['session_id']
            self.state(sid)['task_figure_context'] = ''
            client = FakeClient([tutor()])
            self.handle(dict(trigger='message', session_id=sid, message='I understand the connection.'), client, directory)
            self.assertEqual(len(client.calls), 1)
            self.assertTrue(issubclass(client.calls[0]['text_format'], TutorTurn))
            self.assertTrue(all(part['type'] != 'input_image' for item in client.calls[0]['input']
                                for part in item.get('content', [])))

    def test_figure_only_task_givens_are_retained_for_text_only_tutor(self):
        summary = 'The task figure requires three moves: minus six, plus twelve, then minus four.'
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient([evaluation(task_summary=summary), tutor(opening=True)])
            first = self.handle(self.data(task=''), client, directory,
                                question_image='data:image/png;base64,dGFzaw==')
            sid = first['session_id']
            self.assertEqual(self.formal(sid)['result']['task_summary'], summary)
            ordinary = FakeClient([tutor(content='What should the first drawn move represent?',
                                         talk_moves=['press_for_accuracy'], stage='inquiry')])
            self.handle(dict(trigger='message', session_id=sid, message='What should the first move show?'), ordinary, directory)
            self.assertEqual(len(ordinary.calls), 1)
            self.assertIn(summary, json.dumps(context(ordinary.calls[0])))

    def test_legacy_session_migrates_without_reassessment_or_invented_ability_level(self):
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory)
            sid = first['session_id']
            state = self.state(sid)
            state.pop('runtime_version')
            state.pop('learner_model')
            state['assessment'] = dict(
                learning_goal='Explain the transfer.', criterion='c1',
                criteria=[dict(criterion='c1', status='developing', strength='Visible source.', gap='Explain the transfer.')],
                strengths=[dict(claim='Visible source.', evidence='The source appears in the drawing.')],
                areas_for_improvement=[dict(claim='Explain the transfer.', evidence='The relationship is not explained.')],
                ambiguities=[], revision_outcome='not_reviewed')
            state['task_figure_context'] = 'The task figure identifies a source and receiver.'
            client = FakeClient([tutor(content='What transfer does this current arrow show?',
                                       talk_moves=['press_for_accuracy'], stage='inquiry', issue_id='legacy_gap_1')])
            self.handle(dict(trigger='message', session_id=sid, message='I want to discuss that arrow.'), client, directory)
            self.assertEqual(len(client.calls), 1)
            formal = self.formal(sid)
            self.assertEqual(formal['source'], 'legacy_assessment')
            self.assertNotIn('level', formal['result']['criteria'][0])
            self.assertIn('source and receiver', json.dumps(context(client.calls[0])))

    def test_real_diagram_submission_re_evaluates_without_transformation(self):
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory)
            sid = first['session_id']
            F.begin_revision(dict(session_id=sid))
            changed = deepcopy(SCENE)
            changed['objects'][0]['label'] = 'Updated submitted label'
            client = FakeClient([evaluation(revision_outcome='unsuccessful', revision_evidence='The submitted label changed; the transfer issue remains.'), tutor()])
            public = self.handle(dict(trigger='workspace-complete', session_id=sid, scene=changed,
                                      explanation='The label names this component.', edits=[]), client, directory)
            self.assertEqual(contract_types(client), [EvaluationResult, TutorTurn])
            self.assertEqual(public['drawing_version'], 2)
            self.assertEqual(self.state(sid)['committed']['scene']['objects'][0]['label'], 'Updated submitted label')
            self.assertEqual(self.formal(sid)['drawing_version'], 2)

    def test_current_review_flags_distinguish_a_new_evaluation_from_historical_success(self):
        with tempfile.TemporaryDirectory() as directory:
            first, initial = self.start(directory)
            sid = first['session_id']
            initial_flags = context(initial.calls[1])['interaction']
            self.assertTrue(initial_flags['evaluation_updated'])
            self.assertFalse(initial_flags['diagram_changed'])
            self.assertTrue(first['evaluation_updated'])

            changed = deepcopy(SCENE)
            changed['objects'][0]['label'] = 'Updated submitted label'
            F.begin_revision(dict(session_id=sid))
            review = FakeClient([evaluation(missing_parts=[dict(id='m2', criterion='c1', description='Explain transfer quantity.',
                               evidence='The quantity still needs explanation.', focus_ids=['o3'])],
                               revision_outcome='successful', revision_evidence='The submitted direction is corrected.'),
                                 tutor(issue_id='m2', acknowledgment='Nice revision! The direction is now correct.')])
            public = self.handle(dict(trigger='workspace-complete', session_id=sid, scene=changed,
                                      explanation='The label names this component.', edits=[]), review, directory)
            flags = context(review.calls[1])['interaction']
            self.assertTrue(flags['evaluation_updated'])
            self.assertTrue(flags['diagram_changed'])
            self.assertTrue(public['evaluation_updated'])
            formal = self.formal(sid)
            self.assertEqual(formal['result']['revision_outcome'], 'successful')

            cases = [dict(trigger='message', session_id=sid, message='I understand that label.'),
                     dict(trigger='workspace-complete', session_id=sid, scene=deepcopy(changed),
                          explanation='The label names this component.', edits=[]),
                     dict(trigger='workspace-complete', session_id=sid, scene=deepcopy(changed),
                          explanation='A different explanation, with the same submitted drawing.', edits=[])]
            for data in cases:
                with self.subTest(trigger=data['trigger'], explanation=data.get('explanation')):
                    if data['trigger'] == 'workspace-complete':
                        F.begin_revision(dict(session_id=sid))
                    client = FakeClient([tutor(issue_id='m2')])
                    result = self.handle(data, client, directory)
                    self.assertEqual(len(client.calls), 1)
                    current = context(client.calls[0])
                    self.assertFalse(current['interaction']['evaluation_updated'])
                    self.assertFalse(current['interaction']['diagram_changed'])
                    self.assertFalse(result['evaluation_updated'])
                    self.assertEqual(current['learner_model']['evaluation']['result']['revision_outcome'], 'successful')
                    self.assertEqual(self.formal(sid), formal)

    def test_revision_evaluation_receives_the_issue_actually_addressed_by_tutor_support(self):
        with tempfile.TemporaryDirectory() as directory:
            first_part = dict(id='m1', criterion='c1', description='Explain the source.',
                              evidence='The source needs explanation.', focus_ids=['o3'])
            second_part = dict(id='m2', criterion='c1', description='Represent the receiving end.',
                               evidence='The receiving-end relation needs development.', focus_ids=['o3'])
            first = self.handle(self.data(), FakeClient([evaluation(missing_parts=[second_part, first_part]), tutor(opening=True, issue_id='m2')]), directory)
            sid = first['session_id']
            instruction = 'Draw one arrow toward the receiver to represent this transfer.'
            support = tutor(content=instruction, talk_moves=['provide_hints_guidance'], issue_id='m2',
                            edit_instruction=instruction, next_step='revise', question_target='Represent the receiving end.')
            self.handle(dict(trigger='message', session_id=sid, intent='hint', message='I need a hint.'),
                        FakeClient([support]), directory)
            self.assertEqual(self.state(sid)['current_issue_id'], 'm2')
            self.assertEqual(self.state(sid)['turns'][-1]['issue_id'], 'm2')
            self.assertTrue(self.state(sid)['edit_enabled'])

            changed = deepcopy(SCENE)
            changed['objects'][0]['label'] = 'Updated receiving-end label'
            review = FakeClient([evaluation(missing_parts=[first_part], revision_outcome='successful', revision_evidence='The receiving-end representation changed.'),
                                 tutor(acknowledgment='Nice revision! The receiving end is represented.')])
            self.handle(dict(trigger='workspace-complete', session_id=sid, scene=changed,
                             explanation='The endpoint represents the receiver.', edits=[]), review, directory)
            assessment_context = context(review.calls[0])
            self.assertEqual(assessment_context['addressed_issue'], second_part)
            self.assertEqual([part['id'] for part in assessment_context['prior_evaluation']['missing_parts']], ['m2', 'm1'])
            self.assertTrue(assessment_context['support_history'])
            self.assertEqual(assessment_context['support_history'][-1]['issue_id'], 'm2')
            self.assertEqual(assessment_context['support_history'][-1]['instruction'], instruction)

    def test_unchanged_diagram_and_explanation_only_submission_do_not_evaluate(self):
        for explanation in ('Food needs energy.', 'A new explanation without a changed diagram.'):
            with self.subTest(explanation=explanation), tempfile.TemporaryDirectory() as directory:
                first, _ = self.start(directory, checked=True)
                sid = first['session_id']
                formal = self.formal(sid)
                F.begin_revision(dict(session_id=sid))
                client = FakeClient([tutor()])
                self.handle(dict(trigger='workspace-complete', session_id=sid, scene=deepcopy(SCENE),
                                 explanation=explanation, edits=[]), client, directory)
                self.assertEqual(len(client.calls), 1)
                self.assertTrue(issubclass(client.calls[0]['text_format'], TutorTurn))
                self.assertEqual(self.formal(sid), formal)

    def test_selected_part_reaches_tutor_only_when_it_exists_in_submitted_work(self):
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory, checked=True)
            sid = first['session_id']
            for selected, expected in (('o3', 'o3'), ('private-draft-only', ''), ([], '')):
                client = FakeClient([tutor(content='At which end of this part can you see the arrowhead?',
                                           progress='uncertain')])
                self.handle(dict(trigger='message', session_id=sid, message='Explain this part.',
                                 selected_id=selected), client, directory)
                self.assertEqual(context(client.calls[0])['selected_id'], expected)

    def test_unsubmitted_client_draft_cannot_enter_tutor_context(self):
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory, checked=True)
            sid = first['session_id']
            original = deepcopy(self.state(sid)['committed'])
            draft = deepcopy(SCENE)
            draft['objects'][0]['label'] = 'PRIVATE_UNSUBMITTED_LABEL'
            client = FakeClient([tutor(content='At which end of this connection can you see the arrowhead?',
                                           progress='uncertain')])
            self.handle(dict(trigger='message', session_id=sid, message='Explain this connection.',
                             scene=draft, task='PRIVATE_REPLACEMENT_TASK', explanation='PRIVATE_EXPLANATION'), client, directory)
            serialized = json.dumps(context(client.calls[0]))
            for secret in ('PRIVATE_UNSUBMITTED_LABEL', 'PRIVATE_REPLACEMENT_TASK', 'PRIVATE_EXPLANATION'):
                self.assertNotIn(secret, serialized)
            self.assertEqual(self.state(sid)['committed'], original)

    def test_no_significant_update_does_not_change_learner_memory_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory, checked=True)
            sid = first['session_id']
            memory = deepcopy(self.state(sid)['learner_model'])
            for message in ('Okay.', 'I am looking at the line.', 'Yes.'):
                self.handle(dict(trigger='message', session_id=sid, message=message), FakeClient([tutor()]), directory)
                self.assertEqual(self.state(sid)['learner_model'], memory)

    def test_short_term_context_stays_bounded_without_expanding_long_term_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory, checked=True)
            sid = first['session_id']
            memory = deepcopy(self.state(sid)['learner_model'])
            last = None
            for index in range(14):
                last = FakeClient([tutor()])
                self.handle(dict(trigger='message', session_id=sid, message='I am considering step ' + str(index)), last, directory)
            self.assertLessEqual(len(context(last.calls[0])['recent_dialogue']), 6)
            self.assertLessEqual(len(self.state(sid)['turns']), 12)
            self.assertEqual(self.state(sid)['learner_model'], memory)

    def test_significant_grounded_tutor_update_does_not_overwrite_formal_assessment(self):
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory, checked=True)
            sid = first['session_id']
            before = deepcopy(self.state(sid)['learner_model'])
            message = 'The arrow points toward the receiver.'
            patch = dict(kind='understanding', summary='The learner explains the receiving-end convention.', evidence=message)
            self.handle(dict(trigger='message', session_id=sid, message=message),
                        FakeClient([tutor(memory_updates=[patch])]), directory)
            after = self.state(sid)['learner_model']
            self.assertGreater(after['revision'], before['revision'])
            self.assertEqual(after['evaluation'], before['evaluation'])
            self.assertTrue(any(row['evidence'] == message for row in after['observations']))

    def test_modeling_guidance_opens_editing_but_does_not_draw_for_the_learner(self):
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory)
            sid = first['session_id']
            before = deepcopy(self.state(sid)['committed'])
            formal = self.formal(sid)
            instruction = 'Draw one arrow toward the receiver to represent this transfer.'
            candidate = tutor(content=instruction, talk_moves=['provide_hints_guidance'],
                              edit_instruction=instruction, next_step='revise', question_target='')
            client = FakeClient([candidate])
            public = self.handle(dict(trigger='message', session_id=sid, intent='hint', message='I need a hint.'), client, directory)
            self.assertEqual(len(client.calls), 1)
            self.assertTrue(public['edit_enabled'])
            self.assertEqual(public['guidance_instruction'], instruction)
            self.assertEqual(self.state(sid)['committed'], before)
            self.assertEqual(public['drawing_version'], 1)
            self.assertEqual(self.formal(sid), formal)
            self.assertFalse(public['evaluation_updated'])

            draft = deepcopy(before['scene'])
            draft['objects'][0]['bbox']['x'] += 20
            dialogue = FakeClient([tutor()])
            reported = self.handle(dict(trigger='message', session_id=sid,
                                        message='I moved the source on the canvas.', scene=draft,
                                        edits=[dict(kind='move', id=draft['objects'][0]['id'])]), dialogue, directory)
            self.assertEqual(contract_types(dialogue), [TutorTurn])
            self.assertEqual(self.state(sid)['committed'], before)
            self.assertEqual(reported['drawing_version'], 1)
            self.assertEqual(self.formal(sid), formal)
            self.assertFalse(reported['evaluation_updated'])

            review = FakeClient([evaluation(revision_outcome='unsuccessful',
                                           revision_evidence='The source moved; the transfer still needs explanation.'), tutor()])
            submitted = self.handle(dict(trigger='workspace-complete', session_id=sid, scene=draft,
                                         explanation=before['explanation'], edits=[]), review, directory)
            self.assertEqual(contract_types(review), [EvaluationResult, TutorTurn])
            self.assertEqual(self.state(sid)['committed']['scene'], draft)
            self.assertEqual(submitted['drawing_version'], 2)
            self.assertEqual(self.formal(sid)['drawing_version'], 2)
            self.assertTrue(submitted['evaluation_updated'])

    def test_begin_and_end_revision_preserve_memory_and_dialogue_without_model_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            first, client = self.start(directory)
            sid = first['session_id']
            before = deepcopy(self.state(sid))
            opened = F.begin_revision(dict(session_id=sid))
            self.assertTrue(opened['edit_enabled'])
            self.assertEqual(self.state(sid)['learner_model'], before['learner_model'])
            self.assertEqual(self.state(sid)['turns'], before['turns'])
            self.assertEqual(self.state(sid)['version'], before['version'])
            closed = F.end_revision(dict(session_id=sid))
            self.assertFalse(closed['edit_enabled'])
            self.assertEqual(self.state(sid), before)
            self.assertEqual(len(client.calls), 2)

    def test_busy_revision_permission_request_cannot_mutate_state(self):
        with tempfile.TemporaryDirectory() as directory:
            first, client = self.start(directory)
            sid = first['session_id']
            entry = F.SESSIONS[sid]
            before = deepcopy(entry['state'])
            entry['lock'].acquire()
            try:
                with self.assertRaises(F.FeedbackError):
                    F.begin_revision(dict(session_id=sid))
                self.assertEqual(entry['state'], before)
                self.assertEqual(len(client.calls), 2)
            finally:
                entry['lock'].release()

    def test_invalid_mechanical_reply_does_not_trigger_a_second_model_call_or_commit_state(self):
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory, checked=True)
            sid = first['session_id']
            before = deepcopy(self.state(sid))
            client = FakeClient([tutor(content='The arrowhead identifies the receiving end.',
                                       talk_moves=['provide_hints_guidance'],
                                       edit_instruction='Draw one arrow toward the receiver.')])
            with self.assertRaises(F.FeedbackError):
                self.handle(dict(trigger='message', session_id=sid, message='I need help.'), client, directory)
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(self.state(sid), before)

    def test_failed_model_response_does_not_change_session_or_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory)
            sid = first['session_id']
            before = deepcopy(self.state(sid))
            client = FakeClient([RuntimeError('local stub failure')])
            with self.assertRaises((F.FeedbackError, RuntimeError)):
                self.handle(dict(trigger='message', session_id=sid, message='Explain this part.'), client, directory)
            self.assertEqual(self.state(sid), before)

    def test_revoice_and_clarification_can_be_returned_as_an_ordered_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory)
            sid = first['session_id']
            candidate = tutor(content='You mean the two routes meet there. Which arrow are you referring to?',
                              talk_moves=['revoice', 'ask_for_clarification'], stage='inquiry',
                              move_evidence=dict(revoice_need='Check the route interpretation.',
                                                 revoice_evidence='The two routes meet there',
                                                 clarification_need='Identify which arrow this arrow refers to.'))
            public = self.handle(dict(trigger='message', session_id=sid,
                                      message='The two routes meet there, so this arrow includes both.'),
                                 FakeClient([candidate]), directory)
            self.assertEqual(public['talk_moves'], ['revoice', 'ask_for_clarification'])
            self.assertEqual(public['talk_move'], 'revoice')

    def test_hint_button_interval_blocks_without_a_model_call_and_preserves_input_state(self):
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory)
            sid = first['session_id']
            hint = tutor(content='The arrowhead identifies the receiving end.', talk_moves=['provide_hints_guidance'], question_target='')
            self.handle(dict(trigger='message', session_id=sid, intent='hint', message='I need a hint.'), FakeClient([hint]), directory)
            before = deepcopy(self.state(sid))
            client = FakeClient([])
            with self.assertRaises(F.FeedbackError):
                self.handle(dict(trigger='message', session_id=sid, intent='hint', message='I need another hint.'), client, directory)
            self.assertEqual(client.calls, [])
            self.assertEqual(self.state(sid), before)

    def test_tutor_receives_editor_tools_and_recent_dialogue_without_full_assessment_output(self):
        with tempfile.TemporaryDirectory() as directory:
            first, _ = self.start(directory, checked=True)
            sid = first['session_id']
            client = FakeClient([tutor(content='Which visible mark distinguishes one end of this connection?',
                                       progress='uncertain')])
            self.handle(dict(trigger='message', session_id=sid, message='Please show me how to represent this.'), client, directory)
            ctx = context(client.calls[0])
            self.assertIn('editor_context', ctx)
            self.assertNotIn('previous_assessment', ctx)
            self.assertNotIn('assessment', ctx)
            self.assertNotIn('assessment', TutorTurn.model_fields)
            self.assertTrue(any(tool['action'] == 'connect' for tool in ctx['editor_context']['tools']))


if __name__ == '__main__':
    unittest.main()
