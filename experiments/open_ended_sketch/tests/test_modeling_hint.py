"""Concrete modeling guidance must agree with usable editor permission.

Local typed model stubs only. These checks do not draw on the learner's behalf.
"""
from copy import deepcopy
import tempfile
import unittest

from test_feedback import F, P, SCENE, FakeClient, assessment, reply, guidance
from test_fast_dialogue import input_context, turn


class ModelingHintTests(unittest.TestCase):
    ACTION = 'Draw one arrow from the source toward the receiver to represent this transfer.'
    TOOL_ACTION = ('Use ↗ Connect: set From = Written number 0, To = Written number −6, '
                   'and Direction = From → To; select Save connection.')

    def setUp(self):
        F.SESSIONS.clear()

    def data(self):
        return dict(trigger='submission', scene=deepcopy(SCENE), original_scene=deepcopy(SCENE),
                    explanation='Food needs energy.', task='Explain the represented transfers.',
                    goals=[], message='', edits=[])

    def start(self, directory):
        first = F.handle(self.data(), FakeClient([assessment(), reply()]), directory, 'offline-review')
        state = F.SESSIONS[first['session_id']]['state']
        state.update(version=3, progress_focus=['c3', 'o3'],
                     issue_check_focus=['c3', 'o3'], issue_check_started_at=1,
                     thinking_focus=['c3', 'o3'], thinking_started_at=2,
                     response_progress_focus=['c3', 'o3'], stage='thinking-dialogue',
                     assessment=assessment().model_dump())
        return first['session_id']

    def modeling_reply(self, **changes):
        fields = dict(guidance_requires_edit=True, next_step='revise',
                      new_conceptual_information=['An arrow from the source toward the receiver models this transfer.'])
        fields.update(changes)
        return guidance(self.ACTION, **fields)

    def options(self, fast):
        return dict(fast_dialogue_model='offline-fast') if fast else {}

    def values(self, fast, candidate):
        return [turn(assessment(), candidate, 'provide_hints_guidance')] if fast else [assessment(), candidate]

    def test_modeling_instruction_cannot_be_delivered_with_view_only_metadata(self):
        state, _, ids = F.prepare(None, self.data())
        state.update(intent='hint', _current_trigger='message', _current_message='I need a hint.')
        for candidate in (self.modeling_reply(guidance_requires_edit=False, next_step='explain'),
                          self.modeling_reply(guidance_requires_edit=False, next_step='explore')):
            with self.subTest(next_step=candidate.next_step):
                self.assertTrue(F.reply_problem(candidate, state, assessment(), ids, 'message', '',
                                                'provide_hints_guidance'))

    def test_exact_visible_modeling_instruction_has_a_valid_edit_contract(self):
        state, _, ids = F.prepare(None, self.data())
        state.update(intent='hint', _current_trigger='message', _current_message='I need a hint.')
        self.assertFalse(F.reply_problem(self.modeling_reply(), state, assessment(), ids,
                                         'message', '', 'provide_hints_guidance'))
        candidate = self.modeling_reply()
        candidate.guidance_instruction = 'Think about the direction of the transfer.'
        self.assertTrue(F.reply_problem(candidate, state, assessment(), ids,
                                        'message', '', 'provide_hints_guidance'))

    def test_full_and_fast_modeling_hint_open_editor_without_drawing_for_the_learner(self):
        for fast in (False, True):
            with self.subTest(fast=fast), tempfile.TemporaryDirectory() as directory:
                sid = self.start(directory)
                before = deepcopy(F.SESSIONS[sid]['state'])
                client = FakeClient(self.values(fast, self.modeling_reply()))
                public = F.handle(dict(trigger='message', session_id=sid, intent='hint', message='I need a hint.'),
                                  client, directory, 'offline-review', **self.options(fast))
                after = F.SESSIONS[sid]['state']
                self.assertEqual(public['talk_move'], 'provide_hints_guidance')
                self.assertTrue(public['edit_enabled'])
                self.assertEqual(public['next_step'], 'revise')
                self.assertEqual(public['guidance_instruction'], self.ACTION)
                self.assertEqual(after['committed'], before['committed'])
                self.assertEqual(after['original'], before['original'])
                self.assertEqual(after['drawing_version'], before['drawing_version'])
                self.assertFalse(after['assessment']['ready_for_revision'])
                self.assertEqual(public['revision_plan'], '')
                self.assertEqual(public['revision_plan_ids'], [])
                self.assertEqual(len(client.calls), 1 if fast else 2)

    def test_missing_editor_permission_is_rewritten_before_the_hint_is_delivered(self):
        for fast in (False, True):
            with self.subTest(fast=fast), tempfile.TemporaryDirectory() as directory:
                sid = self.start(directory)
                invalid = self.modeling_reply(guidance_requires_edit=False, next_step='explain')
                client = FakeClient(self.values(fast, invalid) + [self.modeling_reply()])
                public = F.handle(dict(trigger='message', session_id=sid, intent='hint', message='I need a hint.'),
                                  client, directory, 'offline-review', **self.options(fast))
                self.assertTrue(public['edit_enabled'])
                self.assertTrue(public['guidance_requires_edit'])
                self.assertEqual(len(client.calls), 2 if fast else 3)
                rewrite = input_context(client.calls[-1])
                self.assertTrue(rewrite['rewrite_requirement'])
                self.assertFalse(rewrite['previous_draft']['guidance_requires_edit'])

    def test_twice_invalid_modeling_hint_cannot_mutate_the_session(self):
        for fast in (False, True):
            with self.subTest(fast=fast), tempfile.TemporaryDirectory() as directory:
                sid = self.start(directory)
                before = deepcopy(F.SESSIONS[sid]['state'])
                invalid = self.modeling_reply(guidance_requires_edit=False, next_step='explain')
                client = FakeClient(self.values(fast, invalid) + [deepcopy(invalid)])
                with self.assertRaises(F.FeedbackError):
                    F.handle(dict(trigger='message', session_id=sid, intent='hint', message='I need a hint.'),
                             client, directory, 'offline-review', **self.options(fast))
                self.assertEqual(F.SESSIONS[sid]['state'], before)

    def test_description_and_imagined_arrow_keep_the_diagram_view_only(self):
        for content in ('An arrow from source to receiver represents the transfer.',
                        'Imagine drawing one arrow from the source toward the receiver.'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                sid = self.start(directory)
                client = FakeClient([assessment(), guidance(content)])
                public = F.handle(dict(trigger='message', session_id=sid, intent='hint', message='I need a hint.'),
                                  client, directory, 'offline-review')
                self.assertFalse(public['edit_enabled'])
                self.assertFalse(public['guidance_requires_edit'])
                self.assertEqual(public['next_step'], 'explain')

    def test_first_uncertainty_can_get_a_modeling_action_and_one_application_question(self):
        with tempfile.TemporaryDirectory() as directory:
            sid = self.start(directory)
            content = self.ACTION + ' Which transfer does this arrow represent?'
            candidate = reply(content, False, guidance_instruction=self.ACTION,
                              guidance_requires_edit=True, next_step='revise',
                              question_purpose='develop_reasoning',
                              new_conceptual_information=['The arrow models this one transfer.'])
            client = FakeClient([assessment(), candidate])
            public = F.handle(dict(trigger='message', session_id=sid, message="I don't know."),
                              client, directory, 'offline-review')
            self.assertEqual(public['talk_move'], 'provide_hints_guidance')
            self.assertTrue(public['edit_enabled'])
            self.assertEqual(public['content'].count('?'), 1)
            self.assertFalse(F.SESSIONS[sid]['state']['assessment']['ready_for_revision'])

    def test_full_and_fast_inputs_describe_the_actual_editor_even_while_locked(self):
        for fast in (False, True):
            with self.subTest(fast=fast), tempfile.TemporaryDirectory() as directory:
                sid = self.start(directory)
                client = FakeClient(self.values(fast, self.modeling_reply()))
                F.handle(dict(trigger='message', session_id=sid, intent='hint', message='I need a hint.'),
                         client, directory, 'offline-review', **self.options(fast))
                for call in client.calls:
                    context = input_context(call)
                    editor = context['editor_context']
                    self.assertFalse(editor['current_edit_enabled'])
                    self.assertFalse(editor['capabilities']['freehand_drawing'])
                    self.assertTrue(editor['capabilities']['object_connections'])
                    tools = {tool['action']: tool for tool in editor['tools']}
                    self.assertTrue(tools['connect']['available'], 'Tool support is distinct from the current lock.')
                    self.assertTrue(tools['connect']['requires_edit_permission'])
                    self.assertEqual(tools['connect']['endpoint_source'], 'committed.scene.objects')
                    self.assertIn('From', tools['connect']['fields'])
                    self.assertIn('To', tools['connect']['fields'])
                    self.assertIn('Direction', tools['connect']['fields'])
                    self.assertEqual(tools['connect']['save_label'], 'Save connection')
                    self.assertEqual(tools['add_text']['label'], '+ Text')
                    self.assertEqual(tools['add_object']['label'], '+ Object')
                    self.assertEqual(tools['submit_revision']['label'], 'Review changes')

    def test_editor_context_does_not_offer_a_connection_without_two_existing_endpoints(self):
        state = dict(committed=dict(scene=dict(objects=[dict(id='only-object')], relations=[])),
                     edit_enabled=True)
        editor = F.editor_context(state)
        tools = {tool['action']: tool for tool in editor['tools']}
        self.assertTrue(editor['current_edit_enabled'])
        self.assertFalse(tools['connect']['available'])
        self.assertFalse(tools['edit_connection']['available'])
        self.assertTrue(tools['add_text']['available'])
        self.assertFalse(editor['capabilities']['freehand_drawing'])

    def test_real_tool_commands_are_edits_while_inspection_and_explanatory_gerunds_are_not(self):
        for content in (self.TOOL_ACTION, 'Select ↗ Connect.', 'Choose + Text.', 'Use + Object.',
                        'Select Edit connection.', 'Select Save connection.',
                        'Try drawing one arrow from 0 to −6.'):
            with self.subTest(command=content):
                self.assertTrue(P.visible_edit_command(content))
        for content in ('Adding a negative number means moving left on the number line.',
                        'Moving left represents adding a negative number.',
                        'Drawing an arrow can represent a change.',
                        'Select Show to inspect the existing arrow.',
                        'Choose the source object to inspect its label.'):
            with self.subTest(observation=content):
                self.assertFalse(P.visible_edit_command(content))

    def test_explanation_of_adding_is_not_rejected_as_a_hidden_edit_instruction(self):
        sentence = 'Adding a negative number means moving left on the number line.'
        with tempfile.TemporaryDirectory() as directory:
            sid = self.start(directory)
            client = FakeClient([assessment(), guidance(sentence,
                                                       new_conceptual_information=[sentence])])
            public = F.handle(dict(trigger='message', session_id=sid, intent='hint', message='I need a hint.'),
                              client, directory, 'offline-review')
            self.assertFalse(public['edit_enabled'])
            self.assertFalse(public['guidance_requires_edit'])
            self.assertEqual(public['content'], sentence)
            self.assertEqual(len(client.calls), 2, 'An explanation must not trigger an edit-permission rewrite.')

    def test_actual_connect_tool_instruction_rejects_view_only_metadata(self):
        state, _, ids = F.prepare(None, self.data())
        state.update(intent='hint', _current_trigger='message', _current_message='I need a hint.')
        explanation = 'Adding a negative number means moving left on the number line.'
        candidate = reply(explanation + ' ' + self.TOOL_ACTION, False,
                          guidance_instruction=self.TOOL_ACTION,
                          guidance_requires_edit=False, next_step='explain',
                          new_conceptual_information=['The first card can be modeled by one arrow from 0 to −6.'])
        self.assertTrue(F.reply_problem(candidate, state, assessment(), ids,
                                        'message', '', 'provide_hints_guidance'))
        candidate.guidance_requires_edit = True
        candidate.next_step = 'revise'
        self.assertFalse(F.reply_problem(candidate, state, assessment(), ids,
                                         'message', '', 'provide_hints_guidance'))

    def test_full_and_fast_actual_connect_instruction_is_delivered_with_editor_access(self):
        for fast in (False, True):
            with self.subTest(fast=fast), tempfile.TemporaryDirectory() as directory:
                sid = self.start(directory)
                original = deepcopy(F.SESSIONS[sid]['state']['committed'])
                candidate = reply(self.TOOL_ACTION, False, guidance_instruction=self.TOOL_ACTION,
                                  guidance_requires_edit=True, next_step='revise',
                                  new_conceptual_information=['Represent this operation by one connection.'])
                client = FakeClient(self.values(fast, candidate))
                public = F.handle(dict(trigger='message', session_id=sid, intent='hint', message='I need a hint.'),
                                  client, directory, 'offline-review', **self.options(fast))
                self.assertEqual(public['content'], self.TOOL_ACTION)
                self.assertTrue(public['edit_enabled'])
                self.assertEqual(public['next_step'], 'revise')
                self.assertEqual(len(client.calls), 1 if fast else 2)
                self.assertEqual(F.SESSIONS[sid]['state']['committed'], original)


if __name__ == '__main__':
    unittest.main()
