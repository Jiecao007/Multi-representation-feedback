"""Reflection and prior-knowledge entry preserve the existing feedback flow.

Typed local stubs only; no browser, network, or paid model calls.
"""
from copy import deepcopy
import tempfile
import unittest

from test_feedback import F, P, SCENE, FakeClient, assessment, reply
from test_fast_dialogue import turn, input_context


LEARNER_IDEA = 'The arrow shows energy moving from its source.'
TASK = 'Explain the represented transfers.'
TUTOR_ONLY = 'Only the tutor described a hidden destination.'


def reflection_assessment(**changes):
    """Explicitly complete a reflection candidate, without altering shared fixtures."""
    fields = dict(
        talk_move='prompt_reflection',
        reflection_target='The learner explains transfer direction using its source.',
        reflection_evidence=LEARNER_IDEA,
        reflection_reference='The direction of the currently submitted transfer arrow.',
        reflection_reference_source='task_or_observable',
        reflection_need='Evaluate whether the drawn direction supports the expressed explanation.',
    )
    fields.update(changes)
    return assessment(**fields)


class MoveEntryConditionsTests(unittest.TestCase):
    def setUp(self):
        F.SESSIONS.clear()

    def data(self):
        return dict(trigger='submission', scene=deepcopy(SCENE), original_scene=deepcopy(SCENE),
                    explanation='Food needs energy.', task=TASK, goals=[], message='', edits=[])

    def state(self):
        state, _, _ = F.prepare(None, self.data())
        state.update(version=4, stage='thinking-dialogue', progress_focus=['c3', 'o3'],
                     accuracy_focus=['c3', 'o3'], accuracy_started_at=1,
                     issue_check_focus=['c3', 'o3'], issue_check_started_at=1,
                     thinking_focus=['c3', 'o3'], thinking_started_at=2,
                     response_progress_focus=['c3', 'o3'],
                     _current_trigger='message', _current_message=LEARNER_IDEA)
        state['turns'] = [dict(student=LEARNER_IDEA, content=TUTOR_ONLY, version=3,
                               trigger='message', talk_move='invite_elaboration_reasoning')]
        return state

    def selected(self, candidate, state=None, message=LEARNER_IDEA):
        return P.select_move(candidate, state or self.state(), 'message', message)

    def start_checked_session(self, directory):
        first = F.handle(self.data(), FakeClient([assessment(), reply()]), directory, 'offline-review')
        sid = first['session_id']
        F.handle(dict(trigger='message', session_id=sid, message='I am inspecting this transfer.'),
                 FakeClient([turn()]), directory, 'offline-review', fast_dialogue_model='offline-fast')
        return sid

    def test_complete_reflection_without_conflict_precedes_a_valid_prior_connection(self):
        candidate = reflection_assessment(prior_knowledge_connection='Apply the learner\'s source idea.',
                                           prior_knowledge_evidence=LEARNER_IDEA)
        self.assertEqual(candidate.cognitive_conflict, '')
        self.assertEqual(candidate.cognitive_conflict_evidence, '')
        self.assertEqual(self.selected(candidate), 'prompt_reflection')

    def test_conflict_alone_falls_back_to_valid_prior_then_default_reasoning(self):
        candidate = assessment(cognitive_conflict='The explanation conflicts with the drawn direction.',
                               cognitive_conflict_evidence=LEARNER_IDEA)
        self.assertEqual(self.selected(candidate), 'invite_elaboration_reasoning')
        candidate.prior_knowledge_connection = 'Apply the learner\'s known source idea.'
        candidate.prior_knowledge_evidence = LEARNER_IDEA
        self.assertEqual(self.selected(candidate), 'build_on_prior_knowledge')

    def test_reflection_requires_every_new_evidence_field(self):
        for field, empty in (('reflection_target', ''), ('reflection_evidence', ''),
                             ('reflection_reference', ''), ('reflection_reference_source', 'none'),
                             ('reflection_need', '')):
            with self.subTest(field=field):
                candidate = reflection_assessment(**{field: empty})
                self.assertEqual(self.selected(candidate), 'invite_elaboration_reasoning')
        for field in ('reflection_target', 'reflection_reference', 'reflection_need'):
            with self.subTest(overlong=field):
                candidate = reflection_assessment(**{field: ' '.join('detail' for _ in range(36))})
                self.assertEqual(self.selected(candidate), 'invite_elaboration_reasoning')

    def test_reflection_quote_must_be_actual_student_text_not_task_or_tutor_text(self):
        for quote in (TASK, TUTOR_ONLY, 'An invented learner explanation.', LEARNER_IDEA.upper()):
            with self.subTest(quote=quote):
                self.assertEqual(self.selected(reflection_assessment(reflection_evidence=quote)),
                                 'invite_elaboration_reasoning')
        state = self.state()
        long_quote = ' '.join('concept' + str(i) for i in range(26))
        state['_current_message'] = long_quote
        self.assertEqual(self.selected(reflection_assessment(reflection_evidence=long_quote), state, long_quote),
                         'invite_elaboration_reasoning')

    def test_reflection_may_use_a_submitted_explanation_or_prior_learner_words(self):
        self.assertEqual(self.selected(reflection_assessment(reflection_evidence='Food needs energy.')),
                         'prompt_reflection')
        self.assertEqual(self.selected(reflection_assessment(), message='I can compare them now.'),
                         'prompt_reflection')

    def test_acknowledgment_or_bare_uncertainty_does_not_establish_prior_or_reflection(self):
        for quote in ('yes', 'okay', 'I don\'t know.', 'I do not remember.', 'I am unsure.', 'I agree.'):
            with self.subTest(quote=quote):
                state = self.state()
                state['_current_message'] = quote
                for candidate in (
                    reflection_assessment(reflection_evidence=quote),
                    assessment(prior_knowledge_connection='Connect a relevant earlier idea.',
                               prior_knowledge_evidence=quote),
                    assessment(prior_knowledge_mode='activate', prior_knowledge_connection='Recall a relevant idea.',
                               prior_knowledge_activation_evidence=quote),
                ):
                    self.assertFalse(P.reflection_eligible(candidate, state, quote))
                    self.assertFalse(P.prior_knowledge_eligible(candidate, state, quote))
                    expected = 'provide_hints_guidance' if P.learner_uncertainty(candidate, state, quote) else 'invite_elaboration_reasoning'
                    self.assertEqual(self.selected(candidate, state, quote), expected)

    def test_established_prior_requires_learner_evidence_and_never_auto_activates(self):
        candidate = assessment(prior_knowledge_connection='Use a familiar transfer idea.',
                               prior_knowledge_activation_evidence=TASK)
        self.assertEqual(candidate.prior_knowledge_mode, 'established')
        self.assertEqual(self.selected(candidate), 'invite_elaboration_reasoning')
        for quote in (TASK, TUTOR_ONLY, 'Invented prior knowledge.'):
            with self.subTest(quote=quote):
                candidate.prior_knowledge_evidence = quote
                self.assertEqual(self.selected(candidate), 'invite_elaboration_reasoning')
        candidate.prior_knowledge_evidence = 'Food needs energy.'
        self.assertEqual(self.selected(candidate), 'build_on_prior_knowledge')

    def test_explicit_activation_uses_real_context_without_claiming_demonstrated_knowledge(self):
        state = self.state()
        state['task_figure_context'] = 'The task figure names the source and receiver.'
        state['goals_configured'] = True
        state['criteria'][2]['label'] = 'Explain the transfer direction.'
        state['committed']['scene']['objects'][0]['verbatim_text'] = 'SOURCE LABEL'
        anchors = (TASK, state['task_figure_context'], state['criteria'][2]['label'],
                   'SOURCE LABEL', 'Food needs energy.', LEARNER_IDEA)
        for anchor in anchors:
            with self.subTest(anchor=anchor):
                candidate = assessment(prior_knowledge_mode='activate',
                    prior_knowledge_connection='Invite recall of a source-and-transfer concept for the current diagram.',
                    prior_knowledge_evidence='', prior_knowledge_activation_evidence=anchor)
                self.assertEqual(self.selected(candidate, state), 'build_on_prior_knowledge')
                self.assertEqual(candidate.prior_knowledge_evidence, '',
                                 'Context grounding does not manufacture evidence of learner mastery.')

    def test_activation_rejects_missing_invented_tutor_or_overlong_anchors(self):
        for anchor in ('', 'A nonexistent task concept.', TUTOR_ONLY):
            with self.subTest(anchor=anchor):
                candidate = assessment(prior_knowledge_mode='activate',
                    prior_knowledge_connection='Recall a relevant transfer idea.',
                    prior_knowledge_activation_evidence=anchor)
                self.assertEqual(self.selected(candidate), 'invite_elaboration_reasoning')
        state = self.state()
        anchor = ' '.join('taskword' + str(i) for i in range(26))
        state['task'] = anchor
        candidate = assessment(prior_knowledge_mode='activate',
            prior_knowledge_connection='Recall the task concept.', prior_knowledge_activation_evidence=anchor)
        self.assertEqual(self.selected(candidate, state), 'invite_elaboration_reasoning')
        candidate.prior_knowledge_activation_evidence = TASK
        candidate.prior_knowledge_connection = ''
        self.assertEqual(self.selected(candidate), 'invite_elaboration_reasoning')

    def test_unconfigured_default_lens_is_not_an_activation_anchor(self):
        state = self.state()
        self.assertFalse(state['goals_configured'])
        candidate = assessment(prior_knowledge_mode='activate', prior_knowledge_connection='Recall a structural idea.',
                               prior_knowledge_activation_evidence=state['criteria'][1]['label'])
        self.assertEqual(self.selected(candidate, state), 'invite_elaboration_reasoning')

    def test_new_candidates_do_not_bypass_existing_flow_or_permission_gates(self):
        candidate = reflection_assessment(prior_knowledge_connection='Apply a known source idea.',
                                           prior_knowledge_evidence=LEARNER_IDEA)
        state = self.state()
        self.assertEqual(P.select_move(candidate, state, 'submission', LEARNER_IDEA), 'recognize_strengths')
        unchecked, _, _ = F.prepare(None, self.data())
        self.assertEqual(self.selected(candidate, unchecked), 'press_for_accuracy')
        for intent, message, expected in (('hint', 'I need a hint.', 'provide_hints_guidance'),
                                          ('begin_revision', 'Begin a revision.', 'propose_revision_plan')):
            with self.subTest(intent=intent):
                state = self.state()
                state['intent'] = intent
                self.assertEqual(self.selected(candidate, state, message), expected)
        state = self.state()
        state['unsuccessful_response_count'] = 3
        self.assertEqual(self.selected(candidate, state), 'provide_hints_guidance')
        frustration = 'This is frustrating; I keep getting nowhere.'
        state = self.state()
        state['_current_message'] = frustration
        self.assertEqual(self.selected(reflection_assessment(frustration_evidence=frustration), state, frustration),
                         'provide_hints_guidance')
        state = self.state()
        state['awaiting_revision_reason'] = True
        self.assertEqual(self.selected(candidate, state), 'invite_elaboration_reasoning')
        self.assertEqual(self.selected(reflection_assessment(goal_unclear=True)), 'clarify_goals')
        self.assertEqual(self.selected(reflection_assessment(closing_requested=True)), 'invite_dialogue')
        ready = reflection_assessment(ready_for_revision=True, readiness_evidence=LEARNER_IDEA,
                                      progress_status='ready')
        self.assertEqual(self.selected(ready), 'propose_revision_plan')
        self.assertFalse(P.thinking_policy(candidate, self.state(), LEARNER_IDEA, 'prompt_reflection')['hint_allowed'])
        self.assertFalse(P.thinking_policy(candidate, self.state(), LEARNER_IDEA, 'prompt_reflection')['repair_instruction_allowed'])

    def test_legacy_assessment_defaults_and_unknown_mode_or_source_are_rejected(self):
        legacy = assessment().model_dump()
        for field in ('prior_knowledge_mode', 'prior_knowledge_activation_evidence', 'reflection_target',
                      'reflection_evidence', 'reflection_reference', 'reflection_reference_source', 'reflection_need'):
            legacy.pop(field)
        restored = F.Assessment.model_validate(legacy)
        self.assertEqual(restored.prior_knowledge_mode, 'established')
        self.assertEqual(restored.prior_knowledge_activation_evidence, '')
        self.assertEqual(restored.reflection_reference_source, 'none')
        self.assertEqual(self.selected(restored), 'invite_elaboration_reasoning')
        for changes in ({'prior_knowledge_mode': 'guess'}, {'reflection_reference_source': 'private_answer'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                assessment(**changes)

    def test_full_and_fast_accept_complete_non_conflict_reflection_without_extra_calls(self):
        for fast in (False, True):
            with self.subTest(fast=fast), tempfile.TemporaryDirectory() as directory:
                sid = self.start_checked_session(directory)
                candidate = reflection_assessment()
                response = reply('How does the drawn direction fit your explanation?', False,
                                 question_purpose='develop_reasoning')
                outputs = [turn(candidate, response, 'prompt_reflection')] if fast else [candidate, response]
                client = FakeClient(outputs)
                options = {'fast_dialogue_model': 'offline-fast'} if fast else {}
                public = F.handle(dict(trigger='message', session_id=sid, message=LEARNER_IDEA),
                                  client, directory, 'offline-review', **options)
                self.assertEqual(public['talk_move'], 'prompt_reflection')
                self.assertEqual(len(client.calls), 1 if fast else 2)
                self.assertFalse(public['edit_enabled'])
                self.assertEqual(public['new_conceptual_information'], [])

    def test_fast_activation_preserves_context_anchor_and_no_assumed_learner_quote(self):
        with tempfile.TemporaryDirectory() as directory:
            sid = self.start_checked_session(directory)
            candidate = assessment(prior_knowledge_mode='activate',
                prior_knowledge_connection='Recall how an arrow represents a transfer.',
                prior_knowledge_activation_evidence=TASK)
            response = reply('What do you remember about using an arrow to represent a transfer?', False,
                             question_purpose='develop_reasoning')
            client = FakeClient([turn(candidate, response, 'build_on_prior_knowledge')])
            public = F.handle(dict(trigger='message', session_id=sid, message='I am considering the arrow.'),
                              client, directory, 'offline-review', fast_dialogue_model='offline-fast')
            self.assertEqual(public['talk_move'], 'build_on_prior_knowledge')
            self.assertEqual(len(client.calls), 1)
            self.assertFalse(public['edit_enabled'])
            saved = F.SESSIONS[sid]['state']['assessment']
            self.assertEqual(saved['prior_knowledge_mode'], 'activate')
            self.assertEqual(saved['prior_knowledge_evidence'], '')
            self.assertEqual(saved['prior_knowledge_activation_evidence'], TASK)

    def test_new_reflection_fields_reach_fast_cache_and_rewrite_context(self):
        with tempfile.TemporaryDirectory() as directory:
            sid = self.start_checked_session(directory)
            candidate = reflection_assessment()
            response = reply('How does the current direction fit your explanation?', False,
                             question_purpose='develop_reasoning')
            F.handle(dict(trigger='message', session_id=sid, message=LEARNER_IDEA),
                     FakeClient([turn(candidate, response, 'prompt_reflection')]), directory, 'offline-review',
                     fast_dialogue_model='offline-fast')
            invalid = reply('Why? How?', False)
            client = FakeClient([turn(candidate, invalid, 'prompt_reflection'), response])
            public = F.handle(dict(trigger='message', session_id=sid, message='I can compare them now.'),
                              client, directory, 'offline-review', fast_dialogue_model='offline-fast')
            self.assertEqual(public['talk_move'], 'prompt_reflection')
            self.assertEqual(len(client.calls), 2)
            cached = input_context(client.calls[0])['previous_assessment']
            rewritten = input_context(client.calls[1])['private_assessment']
            for field in ('reflection_target', 'reflection_evidence', 'reflection_reference',
                          'reflection_reference_source', 'reflection_need'):
                self.assertEqual(cached[field], getattr(candidate, field))
                self.assertEqual(rewritten[field], getattr(candidate, field))

    def test_conflict_only_fast_choice_gets_one_authoritative_reasoning_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            sid = self.start_checked_session(directory)
            candidate = assessment(talk_move='prompt_reflection',
                cognitive_conflict='The stated source and drawn direction differ.',
                cognitive_conflict_evidence=LEARNER_IDEA)
            response = reply('How does this connection represent the transfer?', False,
                             question_purpose='develop_reasoning')
            client = FakeClient([turn(candidate, response, 'prompt_reflection'), response])
            public = F.handle(dict(trigger='message', session_id=sid, message=LEARNER_IDEA),
                              client, directory, 'offline-review', fast_dialogue_model='offline-fast')
            self.assertEqual(public['talk_move'], 'invite_elaboration_reasoning')
            self.assertEqual(len(client.calls), 2)
            self.assertIn('authoritative selected_talk_move=invite_elaboration_reasoning',
                          input_context(client.calls[1])['rewrite_requirement'])
            self.assertFalse(public['edit_enabled'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
