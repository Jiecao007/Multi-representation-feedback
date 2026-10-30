"""Live move-entry regressions with local typed Tutor responses only.

These verify evidence provenance, restored support ordering, and the single-call
Tutor contract. They do not call an external model or replay a learner trial.
"""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'app'))
import feedback as F
from agent_api import AgentCalls
from agent_types import MoveEvidence
from learner_model import record_evaluation
from move_selection import eligible_support_moves, preferred_support_moves, validate_move_selection
from tutor_agent import TutorAgent
from tutor_context import build_tutor_context
from test_three_agent_runtime import FakeClient, SCENE, context as call_context, evaluation, tutor


PRIOR_QUOTE = 'The arrowhead marks where the transfer ends.'
REFLECTION_QUOTE = 'This arrow is meant to show a change of +12.'
REVOICE_QUOTE = 'The two routes meet there'


def prior_evidence(**changes):
    value = dict(prior_knowledge_mode='established',
                 prior_knowledge_connection='Apply the arrowhead convention to this transfer.',
                 prior_knowledge_evidence=PRIOR_QUOTE)
    value.update(changes)
    return value


def reflection_evidence(**changes):
    value = dict(reflection_target='The expressed +12 interpretation.',
                 reflection_evidence=REFLECTION_QUOTE,
                 reflection_reference='The current arrow direction and its number-line endpoint.',
                 reflection_reference_source='task_or_observable',
                 reflection_need='Judge whether the drawn arrow expresses that intended change.')
    value.update(changes)
    return value


def meaning_evidence(**changes):
    value = dict(revoice_need='Check the shared interpretation of the route claim.',
                 revoice_evidence=REVOICE_QUOTE,
                 clarification_need='Identify which arrow the student calls this arrow.')
    value.update(changes)
    return value


class TutorMoveSelectionTests(unittest.TestCase):
    def setUp(self):
        F.SESSIONS.clear()

    def data(self, **changes):
        value = dict(trigger='submission', scene=deepcopy(SCENE), original_scene=deepcopy(SCENE),
                     explanation='', task='Explain the source and receiver in the transfer.',
                     goals=['Explain source and receiver.'], source_id='move-contract-fixture',
                     message='', edits=[])
        value.update(changes)
        return value

    def context(self, message='', recent=(), explanation='', task=None, **interaction):
        changes = dict(explanation=explanation)
        if task is not None:
            changes['task'] = task
        state, _, _ = F.prepare(None, self.data(**changes))
        state['learner_model'] = record_evaluation(state['learner_model'], evaluation(), 1)
        state['stage'] = 'thinking-dialogue'
        state.pop('workflow', None)
        state['current_issue_id'] = 'm1'
        state['turns'] = list(recent)
        result = build_tutor_context(state, message, 'message', 'dialogue')
        result['interaction'].update(interaction)
        return result

    def initial_check(self, sid, directory):
        F.handle(dict(trigger='message', session_id=sid, message='Yes, that is the source.'),
                 FakeClient([tutor(content='What transfer does the current arrow show?',
                                   talk_moves=['press_for_accuracy'], stage='inquiry')]),
                 directory, 'evaluation-model', fast_dialogue_model='fast-tutor')

    def candidate(self, move, evidence=None, **changes):
        value = dict(talk_moves=[move], move_evidence=MoveEvidence(**(evidence or {})))
        value.update(changes)
        return tutor(**value)

    def test_established_prior_knowledge_requires_substantive_actual_learner_words(self):
        ctx = self.context(message=PRIOR_QUOTE)
        candidate = self.candidate('build_on_prior_knowledge', prior_evidence())
        self.assertEqual(validate_move_selection(candidate, ctx), '')
        self.assertEqual(preferred_support_moves(candidate.move_evidence, ctx), ['build_on_prior_knowledge'])
        for quote in ('Yes.', "I don't know.", 'Maybe.'):
            with self.subTest(quote=quote):
                ctx = self.context(message=quote)
                invalid = self.candidate('build_on_prior_knowledge', prior_evidence(prior_knowledge_evidence=quote))
                self.assertTrue(validate_move_selection(invalid, ctx))

    def test_teacher_or_task_information_is_not_established_student_knowledge(self):
        candidate = self.candidate('build_on_prior_knowledge', prior_evidence())
        for ctx in (
            self.context(message='I can see the arrow.', recent=[dict(student='I am looking.', content=PRIOR_QUOTE)]),
            self.context(message='I can see the arrow.', task=PRIOR_QUOTE),
        ):
            with self.subTest(context=ctx):
                self.assertTrue(validate_move_selection(candidate, ctx))

    def test_established_knowledge_can_use_recent_student_text_or_submitted_explanation(self):
        candidate = self.candidate('build_on_prior_knowledge', prior_evidence())
        for ctx in (
            self.context(message='Here is the next transfer.', recent=[dict(student=PRIOR_QUOTE, content='Which transfer?')]),
            self.context(message='Here is the next transfer.', explanation=PRIOR_QUOTE),
        ):
            with self.subTest(context=ctx):
                self.assertEqual(validate_move_selection(candidate, ctx), '')

    def test_quote_outside_the_actual_bounded_tutor_input_is_not_available_evidence(self):
        ctx = self.context(message='Here is the next transfer.', recent=[
            dict(student=('Earlier unrelated words. ' * 40) + PRIOR_QUOTE, content='Which transfer?')])
        self.assertNotIn(PRIOR_QUOTE, ctx['recent_dialogue'][0]['student'])
        candidate = self.candidate('build_on_prior_knowledge', prior_evidence())
        self.assertTrue(validate_move_selection(candidate, ctx))

    def test_activated_prior_knowledge_uses_context_anchor_without_claiming_mastery(self):
        ctx = self.context(message='Which idea is relevant here?')
        evidence = prior_evidence(prior_knowledge_mode='activate',
                                  prior_knowledge_evidence='',
                                  prior_knowledge_activation_evidence='source and receiver')
        candidate = self.candidate('build_on_prior_knowledge', evidence)
        self.assertEqual(validate_move_selection(candidate, ctx), '')
        self.assertEqual(candidate.move_evidence.prior_knowledge_evidence, '')
        forged = self.candidate('build_on_prior_knowledge', dict(evidence, prior_knowledge_activation_evidence='current at a junction'))
        self.assertTrue(validate_move_selection(forged, ctx))
        conflated = self.candidate('build_on_prior_knowledge', dict(evidence, prior_knowledge_evidence='source and receiver'))
        self.assertTrue(validate_move_selection(conflated, ctx))

    def test_long_term_prior_knowledge_uses_only_accepted_observation_evidence(self):
        candidate = self.candidate('build_on_prior_knowledge', prior_evidence())
        ctx = self.context(message='Here is the next transfer.')
        for observation, valid in (
            (dict(source='tutor_observation', evidence=PRIOR_QUOTE), True),
            (dict(source='evaluation', evidence=PRIOR_QUOTE), False),
            (dict(source='tutor_observation', summary=PRIOR_QUOTE, evidence='A separate student claim.'), False),
        ):
            with self.subTest(observation=observation):
                ctx['learner_model']['observations'] = [observation]
                self.assertEqual(validate_move_selection(candidate, ctx) == '', valid)

    def test_activated_prior_knowledge_can_use_task_figure_givens_or_verbatim_marks(self):
        ctx = self.context(message='Which idea is relevant here?')
        ctx['learner_model']['evaluation']['result']['task_summary'] = 'The task figure asks about current at a junction.'
        ctx['current_diagram']['objects'][0]['verbatim_text'] = 'junction current'
        for quote in ('current at a junction', 'junction current'):
            with self.subTest(anchor=quote):
                candidate = self.candidate('build_on_prior_knowledge', prior_evidence(
                    prior_knowledge_mode='activate', prior_knowledge_evidence='',
                    prior_knowledge_activation_evidence=quote))
                self.assertEqual(validate_move_selection(candidate, ctx), '')

    def test_prior_activation_cannot_borrow_an_ungrounded_tutor_utterance(self):
        ctx = self.context(message='Which idea is relevant here?', recent=[
            dict(student='I can see two lines.', content='Recall current at a junction.')])
        candidate = self.candidate('build_on_prior_knowledge', prior_evidence(
            prior_knowledge_mode='activate', prior_knowledge_evidence='',
            prior_knowledge_activation_evidence='current at a junction'))
        self.assertTrue(validate_move_selection(candidate, ctx))

    def test_reflection_requires_existing_explanation_reference_and_unfinished_judgment(self):
        ctx = self.context(message=REFLECTION_QUOTE)
        candidate = self.candidate('prompt_reflection', reflection_evidence())
        self.assertEqual(validate_move_selection(candidate, ctx), '')
        # Reflection is eligible without a cognitive-conflict flag or an asserted error.
        self.assertNotIn('cognitive_conflict', candidate.model_dump())
        self.assertEqual(preferred_support_moves(candidate.move_evidence, ctx), ['prompt_reflection'])
        for field, value in (
            ('reflection_target', ''), ('reflection_evidence', ''),
            ('reflection_reference', ''), ('reflection_reference_source', 'none'),
            ('reflection_need', ''),
        ):
            with self.subTest(missing_field=field):
                invalid = self.candidate('prompt_reflection', reflection_evidence(**{field: value}))
                self.assertTrue(validate_move_selection(invalid, ctx))

    def test_reflection_cannot_treat_teacher_explanation_or_bare_agreement_as_student_explanation(self):
        ctx = self.context(message='Yes.', recent=[dict(student='I am looking.', content=REFLECTION_QUOTE)])
        for quote in (REFLECTION_QUOTE, 'Yes.'):
            with self.subTest(quote=quote):
                candidate = self.candidate('prompt_reflection', reflection_evidence(reflection_evidence=quote))
                self.assertTrue(validate_move_selection(candidate, ctx))

    def test_missing_first_explanation_uses_default_reasoning(self):
        ctx = self.context(message='I have drawn an arrow.')
        candidate = self.candidate('invite_elaboration_reasoning',
                                   dict(reasoning_gap='Explain what the arrow represents.'))
        self.assertEqual(preferred_support_moves(candidate.move_evidence, ctx), ['invite_elaboration_reasoning'])
        self.assertEqual(validate_move_selection(candidate, ctx), '')

    def test_meaning_then_reflection_then_prior_then_reasoning_is_restored(self):
        ctx = self.context(message=REVOICE_QUOTE + ', so this arrow includes both.',
                           recent=[dict(student=REFLECTION_QUOTE, content='What is uncertain?'),
                                   dict(student=PRIOR_QUOTE, content='Which transfer?')])
        all_evidence = dict(prior_evidence(), **reflection_evidence(), **meaning_evidence())
        evidence = MoveEvidence(**all_evidence)
        self.assertEqual(preferred_support_moves(evidence, ctx), ['revoice', 'ask_for_clarification'])
        self.assertIn('revoice', eligible_support_moves(evidence, ctx))
        reflection = self.candidate('prompt_reflection', all_evidence)
        self.assertTrue(validate_move_selection(reflection, ctx))
        no_meaning = MoveEvidence(**dict(prior_evidence(), **reflection_evidence()))
        self.assertEqual(preferred_support_moves(no_meaning, ctx), ['prompt_reflection'])
        prior = self.candidate('build_on_prior_knowledge', no_meaning.model_dump())
        self.assertTrue(validate_move_selection(prior, ctx))
        self.assertEqual(preferred_support_moves(MoveEvidence(**prior_evidence()), ctx), ['build_on_prior_knowledge'])
        self.assertEqual(preferred_support_moves(MoveEvidence(), ctx), ['invite_elaboration_reasoning'])

    def test_revoice_and_clarification_are_separate_and_combinable_with_specific_needs(self):
        ctx = self.context(message=REVOICE_QUOTE + ', so this arrow includes both.')
        for moves, evidence in (
            (['revoice'], meaning_evidence(clarification_need='')),
            (['ask_for_clarification'], dict(clarification_need='Identify this arrow.')),
            (['revoice', 'ask_for_clarification'], meaning_evidence()),
        ):
            with self.subTest(moves=moves):
                candidate = self.candidate(moves[0], evidence, talk_moves=moves)
                self.assertEqual(validate_move_selection(candidate, ctx), '')
        for moves, evidence in (
            (['revoice'], meaning_evidence(revoice_evidence='Both currents flow through A₂.', clarification_need='')),
            (['ask_for_clarification'], {}),
        ):
            with self.subTest(invalid_moves=moves):
                candidate = self.candidate(moves[0], evidence, talk_moves=moves)
                self.assertTrue(validate_move_selection(candidate, ctx))

    def test_evidence_limits_are_checked_before_using_a_special_move(self):
        for field, text in (
            ('prior_knowledge_evidence', ' '.join(['arrow'] * 26)),
            ('prior_knowledge_connection', ' '.join(['connect'] * 36)),
        ):
            with self.subTest(field=field):
                ctx = self.context(message=PRIOR_QUOTE + ' ' + text)
                candidate = self.candidate('build_on_prior_knowledge', prior_evidence(**{field: text}))
                self.assertTrue(validate_move_selection(candidate, ctx))

    def test_direct_chat_help_cannot_bypass_guidance_gate(self):
        ctx = self.context(message='Please directly tell me.', recent=[dict(student=REFLECTION_QUOTE, content='Which mark?')])
        candidate = self.candidate('provide_hints_guidance', reflection_evidence(),
                                   content='The arrowhead marks the receiving end of the transfer.', question_target='')
        self.assertTrue(validate_move_selection(candidate, ctx))

    def test_sufficient_reasoning_plan_needs_actual_student_evidence_unless_revision_requested(self):
        instruction = 'Reverse the arrow so its tip points toward the receiver.'
        ctx = self.context(message='The receiver is at the arrow tail, so the direction is reversed.')
        candidate = self.candidate('propose_revision_plan',
                                   dict(readiness_evidence='the direction is reversed'),
                                   content=instruction, edit_instruction=instruction, next_step='revise')
        self.assertEqual(validate_move_selection(candidate, ctx), '')
        candidate.move_evidence.readiness_evidence = ''
        self.assertTrue(validate_move_selection(candidate, ctx))
        requested = self.context(message='I want to revise the arrow.')
        self.assertEqual(validate_move_selection(candidate, requested), '')

    def test_valid_reflection_is_one_tutor_call_without_formal_evaluation_or_memory_change(self):
        with tempfile.TemporaryDirectory() as directory:
            first = F.handle(self.data(), FakeClient([evaluation(), tutor(opening=True)]),
                             directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
            sid = first['session_id']
            self.initial_check(sid, directory)
            before = deepcopy(F.SESSIONS[sid]['state']['learner_model'])
            candidate = self.candidate('prompt_reflection', reflection_evidence(),
                                       content='What evidence in your arrow helps you judge whether it shows the +12 change you described?')
            client = FakeClient([candidate])
            public = F.handle(dict(trigger='message', session_id=sid, message=REFLECTION_QUOTE),
                              client, directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
            self.assertEqual(public['talk_moves'], ['prompt_reflection'])
            self.assertEqual(public['agents_called'], ['tutor'])
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(F.SESSIONS[sid]['state']['learner_model'], before)
            self.assertEqual(call_context(client.calls[0])['student_message'], REFLECTION_QUOTE)

    def test_inviting_a_plan_then_providing_one_keeps_edit_permission_and_calls_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            first = F.handle(self.data(), FakeClient([evaluation(), tutor(opening=True)]),
                             directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
            sid = first['session_id']
            self.initial_check(sid, directory)
            formal = deepcopy(F.SESSIONS[sid]['state']['learner_model']['evaluation'])
            invite = self.candidate('propose_revision_plan',
                                    dict(plan_mode='invite', readiness_evidence='should point toward the receiver'),
                                    content='What change would make the arrow show that direction?',
                                    stage='revision-planning', next_step='explain')
            client = FakeClient([invite])
            public = F.handle(dict(trigger='message', session_id=sid,
                                   message='The arrowhead should point toward the receiver.'),
                              client, directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
            self.assertFalse(public['edit_enabled'])
            self.assertEqual(public['next_step'], 'explain')
            self.assertEqual(public['agents_called'], ['tutor'])
            self.assertEqual(len(client.calls), 1)
            instruction = 'Reverse the arrow so its tip points toward the receiver.'
            provide = self.candidate('propose_revision_plan',
                                     dict(plan_mode='provide', readiness_evidence='I would reverse the arrow'),
                                     content=instruction, stage='revision-planning',
                                     edit_instruction=instruction, next_step='revise')
            client = FakeClient([provide])
            public = F.handle(dict(trigger='message', session_id=sid, message='I would reverse the arrow.'),
                              client, directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
            self.assertTrue(public['edit_enabled'])
            self.assertEqual(public['next_step'], 'revise')
            self.assertEqual(public['agents_called'], ['tutor'])
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(F.SESSIONS[sid]['state']['learner_model']['evaluation'], formal)

    def test_ineligible_move_is_not_relabelled_or_committed_or_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            first = F.handle(self.data(), FakeClient([evaluation(), tutor(opening=True)]),
                             directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
            sid = first['session_id']
            self.initial_check(sid, directory)
            before = deepcopy(F.SESSIONS[sid]['state'])
            candidate = self.candidate('prompt_reflection', reflection_evidence(), content='Does that explanation fit your arrow?')
            client = FakeClient([candidate])
            with self.assertRaises(F.FeedbackError):
                F.handle(dict(trigger='message', session_id=sid, message='Yes.'), client, directory,
                         'evaluation-model', fast_dialogue_model='fast-tutor')
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(F.SESSIONS[sid]['state'], before)
            self.assertEqual(candidate.talk_moves, ['prompt_reflection'])

    def test_actual_support_call_contains_live_definitions_and_restored_examples_in_one_request(self):
        ctx = self.context(message=PRIOR_QUOTE)
        client = FakeClient([self.candidate('build_on_prior_knowledge', prior_evidence())])
        with tempfile.TemporaryDirectory() as directory:
            TutorAgent(AgentCalls(client, directory), 'fast-tutor').respond(ctx)
        self.assertEqual(len(client.calls), 1)
        instructions = client.calls[0]['instructions']
        for marker in ('build_on_prior_knowledge', 'prompt_reflection', 'Established knowledge',
                       'Activate relevant knowledge', 'Reflection with a supported explanation',
                       'Revoice + clarification'):
            self.assertIn(marker, instructions)
        self.assertEqual(client.calls[0]['model'], 'fast-tutor')

    def test_actual_phase_calls_include_relevant_examples_without_loading_every_phase(self):
        cases = (
            (dict(expected_stage='recognition'), 'Great job connecting A₁', 'Established knowledge'),
            (dict(expected_stage='inquiry'), 'With the switch closed', 'Reflection without conflict'),
            (dict(expected_stage='thinking-dialogue', intent='hint'), 'Strict eligibility', 'Established knowledge'),
            (dict(expected_stage='thinking-dialogue', evaluation_updated=True, diagram_changed=True),
             'Nice revision!', None),
        )
        for interaction, included, excluded in cases:
            with self.subTest(interaction=interaction), tempfile.TemporaryDirectory() as directory:
                ctx = self.context(message='Here is the current diagram.')
                ctx['interaction'].update(interaction)
                for key in ('allowed_moves', 'allowed_stages', 'active_issue_id'):
                    ctx['interaction'].pop(key, None)
                client = FakeClient([tutor()])
                TutorAgent(AgentCalls(client, directory), 'fast-tutor').respond(ctx)
                self.assertEqual(len(client.calls), 1)
                instructions = client.calls[0]['instructions']
                self.assertIn(included, instructions)
                if excluded:
                    self.assertNotIn(excluded, instructions)

    def start_support(self, directory, difficulties=0):
        first = F.handle(self.data(), FakeClient([evaluation(), tutor(opening=True)]),
                         directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
        sid = first['session_id']
        self.initial_check(sid, directory)
        state = F.SESSIONS[sid]['state']
        state['consecutive_difficulties'] = difficulties
        return sid

    def test_hint_button_requires_guidance_without_retry_or_partial_state_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            sid = self.start_support(directory)
            before = deepcopy(F.SESSIONS[sid]['state'])
            client = FakeClient([self.candidate('invite_elaboration_reasoning',
                                                content='Why does the arrow point that way?')])
            with self.assertRaises(F.FeedbackError):
                F.handle(dict(trigger='message', session_id=sid, intent='hint', message='I need a hint.'),
                         client, directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(F.SESSIONS[sid]['state'], before)

    def test_third_current_difficulty_requires_guidance_and_counts_once_when_delivered(self):
        with tempfile.TemporaryDirectory() as directory:
            sid = self.start_support(directory, difficulties=2)
            before = deepcopy(F.SESSIONS[sid]['state'])
            data = dict(trigger='message', session_id=sid, message='The arrow still ends at the source.')
            client = FakeClient([self.candidate('invite_elaboration_reasoning',
                                                content='Which end receives the transfer?', progress='difficulty')])
            with self.assertRaises(F.FeedbackError):
                F.handle(data, client, directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(F.SESSIONS[sid]['state'], before)
            client = FakeClient([self.candidate('provide_hints_guidance',
                                                content='The arrowhead marks the receiving end of a transfer.',
                                                progress='difficulty')])
            public = F.handle(data, client, directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
            self.assertEqual(public['talk_moves'], ['provide_hints_guidance'])
            self.assertEqual(public['agents_called'], ['tutor'])
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(F.SESSIONS[sid]['state']['consecutive_difficulties'], 3)
            self.assertEqual(F.SESSIONS[sid]['state']['guidance_count'], 1)
            self.assertEqual(F.SESSIONS[sid]['state']['learner_model']['evaluation'], before['learner_model']['evaluation'])

    def test_success_after_two_difficulties_allows_advance_and_resets_streak(self):
        with tempfile.TemporaryDirectory() as directory:
            sid = self.start_support(directory, difficulties=2)
            formal = deepcopy(F.SESSIONS[sid]['state']['learner_model']['evaluation'])
            client = FakeClient([self.candidate('invite_elaboration_reasoning',
                                                content='How does the arrow connect the source to the receiver?',
                                                progress='progress')])
            public = F.handle(dict(trigger='message', session_id=sid,
                                   message='The arrowhead is at the receiver, so that end receives the transfer.'),
                              client, directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
            self.assertEqual(public['talk_moves'], ['invite_elaboration_reasoning'])
            self.assertEqual(public['agents_called'], ['tutor'])
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(F.SESSIONS[sid]['state']['consecutive_difficulties'], 0)
            self.assertEqual(F.SESSIONS[sid]['state']['learner_model']['evaluation'], formal)

    def test_ui_status_after_two_difficulties_does_not_add_a_third_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            sid = self.start_support(directory, difficulties=2)
            client = FakeClient([self.candidate('invite_dialogue',
                                                content='What would you like help with on the current diagram?',
                                                progress='other', stage='thinking-dialogue')])
            public = F.handle(dict(trigger='message', session_id=sid, message='I have saved the diagram.'),
                              client, directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
            self.assertEqual(public['talk_moves'], ['invite_dialogue'])
            self.assertEqual(public['agents_called'], ['tutor'])
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(F.SESSIONS[sid]['state']['consecutive_difficulties'], 2)

    def test_finishing_and_requested_revision_remain_available_at_difficulty_threshold(self):
        instruction = 'Reverse the arrow so its tip points toward the receiver.'
        cases = (
            ('I am finished.', self.candidate('invite_dialogue', content='Thanks for working through your diagram!',
                                              progress='difficulty', stage='complete', question_target='')),
            ('I want to revise the arrow.', self.candidate('propose_revision_plan', content=instruction,
                                                           edit_instruction=instruction, next_step='revise',
                                                           progress='difficulty', stage='revision-planning')),
        )
        for message, candidate in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                sid = self.start_support(directory, difficulties=2)
                client = FakeClient([candidate])
                public = F.handle(dict(trigger='message', session_id=sid, message=message), client,
                                  directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
                self.assertEqual(public['agents_called'], ['tutor'])
                self.assertEqual(len(client.calls), 1)
                self.assertEqual(public['stage'], candidate.stage)
                self.assertEqual(public['edit_enabled'], candidate.stage == 'revision-planning')


if __name__ == '__main__':
    unittest.main()
