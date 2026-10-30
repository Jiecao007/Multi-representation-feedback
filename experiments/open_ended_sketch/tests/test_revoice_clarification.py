"""Distinct and combined dialogue moves preserve the current learning workflow.

All tutoring calls use typed local stubs. No network, browser, or model calls.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from test_feedback import F, P, SCENE, FakeClient, assessment, reply, guidance
from test_fast_dialogue import input_context, turn


LEARNER_IDEA = 'Both arrows carry energy to that part.'
TUTOR_ONLY = 'The tutor alone mentioned another destination.'
COMBINED = ['revoice', 'ask_for_clarification']


def dialogue_assessment(kind='combined', **changes):
    fields = dict(talk_move='revoice' if kind != 'clarify' else 'ask_for_clarification',
                  talk_moves=COMBINED if kind == 'combined' else
                             ['ask_for_clarification' if kind == 'clarify' else 'revoice'],
                  revoice_need='Check the uptake of the learner\'s account of the two arrows.'
                               if kind != 'clarify' else '',
                  revoice_evidence=LEARNER_IDEA if kind != 'clarify' else '',
                  clarification_need='Identify the particular part referred to by that part.'
                                     if kind != 'revoice' else '')
    fields.update(changes)
    return assessment(**fields)


def dialogue_reply(kind='combined', **changes):
    content = {
        'revoice': 'You mean both arrows carry energy to one part. Have I understood your idea?',
        'clarify': 'Which part do you mean by that part?',
        'combined': 'You mean both arrows carry energy to one part. Which part do you mean?',
    }[kind]
    return reply(content, False, question_purpose='clarify_meaning', **changes)


class RevoiceClarificationTests(unittest.TestCase):
    def setUp(self):
        F.SESSIONS.clear()

    def data(self):
        return dict(trigger='submission', scene=deepcopy(SCENE), original_scene=deepcopy(SCENE),
                    explanation='Food needs energy.', task='Explain the represented transfers.',
                    goals=[], message='', edits=[])

    def state(self, **changes):
        state, _, _ = F.prepare(None, self.data())
        state.update(version=4, stage='thinking-dialogue', progress_focus=['c3', 'o3'],
                     accuracy_focus=['c3', 'o3'], accuracy_started_at=1,
                     issue_check_focus=['c3', 'o3'], issue_check_started_at=1,
                     thinking_focus=['c3', 'o3'], thinking_started_at=2,
                     response_progress_focus=['c3', 'o3'], unsuccessful_response_count=1,
                     _current_trigger='message', _current_message=LEARNER_IDEA)
        state['turns'] = [dict(student=LEARNER_IDEA, content=TUTOR_ONLY, version=3,
                               trigger='message', talk_move='invite_elaboration_reasoning')]
        state.update(changes)
        return state

    def checked_session(self, directory):
        first = F.handle(self.data(), FakeClient([assessment(), reply()]), directory, 'offline-review')
        sid = first['session_id']
        F.handle(dict(trigger='message', session_id=sid, message='I am inspecting this transfer.'),
                 FakeClient([turn()]), directory, 'offline-review', fast_dialogue_model='offline-fast')
        return sid

    def test_move_inventory_has_eleven_canonical_ids_and_no_combined_id(self):
        self.assertEqual(len(P.MOVES), 11)
        self.assertIn('revoice', P.MOVES)
        self.assertIn('ask_for_clarification', P.MOVES)
        self.assertNotIn('revoice_or_clarify', P.MOVES)

    def test_standalone_and_combined_moves_follow_their_actual_needs(self):
        for kind, expected in (('revoice', ['revoice']), ('clarify', ['ask_for_clarification']),
                               ('combined', COMBINED)):
            with self.subTest(kind=kind):
                candidate = dialogue_assessment(kind)
                self.assertEqual(P.select_move(candidate, self.state(), 'message', LEARNER_IDEA), expected[0])
                self.assertEqual(P.select_moves(candidate, self.state(), 'message', LEARNER_IDEA), expected)

    def test_revoice_requires_a_real_substantive_learner_quote(self):
        for quote in ('', TUTOR_ONLY, 'Invented learner words.', 'I do not know.', 'okay',
                      ' '.join('word' + str(i) for i in range(26))):
            with self.subTest(quote=quote):
                candidate = dialogue_assessment('revoice', revoice_evidence=quote)
                self.assertEqual(P.select_move(candidate, self.state(), 'message', LEARNER_IDEA),
                                 'invite_elaboration_reasoning')
        candidate = dialogue_assessment('combined', revoice_evidence=TUTOR_ONLY)
        self.assertEqual(P.select_moves(candidate, self.state(), 'message', LEARNER_IDEA),
                         ['ask_for_clarification'])

    def test_support_needs_are_required_and_do_not_infer_a_missing_revoice(self):
        candidate = dialogue_assessment('combined', revoice_need='', clarification_need='')
        self.assertEqual(P.select_move(candidate, self.state(), 'message', LEARNER_IDEA),
                         'invite_elaboration_reasoning')
        for field, kind in (('revoice_need', 'revoice'), ('clarification_need', 'clarify')):
            with self.subTest(field=field):
                candidate = dialogue_assessment(kind, **{field: ' '.join('need' for _ in range(36))})
                self.assertEqual(P.select_move(candidate, self.state(), 'message', LEARNER_IDEA),
                                 'invite_elaboration_reasoning')

    def test_initial_ambiguity_defaults_to_clarification_without_inventing_a_revoice(self):
        state, _, _ = F.prepare(None, self.data())
        candidate = assessment(next_focus_kind='clarification', areas_for_improvement=[],
            ambiguities=[dict(claim='The referenced part is unclear.', evidence='The learner says that part.')])
        self.assertEqual(P.select_move(candidate, state, 'message', LEARNER_IDEA), 'ask_for_clarification')
        P.update_progress(state, candidate, 'ask_for_clarification', dialogue_reply('clarify'))
        self.assertEqual(state['issue_check_focus'], ['c3', 'o3'])
        self.assertEqual(state['issue_check_started_at'], state['version'])

    def test_each_support_dialogue_move_preserves_completed_check_and_thinking_markers(self):
        for kind in ('revoice', 'clarify', 'combined'):
            with self.subTest(kind=kind):
                state = self.state()
                candidate = dialogue_assessment(kind)
                expected = P.select_moves(candidate, state, 'message', LEARNER_IDEA)
                markers = {key: deepcopy(state[key]) for key in (
                    'issue_check_focus', 'issue_check_started_at', 'accuracy_focus', 'accuracy_started_at',
                    'thinking_focus', 'thinking_started_at', 'response_progress_focus',
                    'unsuccessful_response_count')}
                P.update_progress(state, candidate, expected[0], dialogue_reply(kind))
                for key, value in markers.items():
                    self.assertEqual(state[key], value, f'{kind} reset {key}')

    def test_review_support_entry_and_outcome_survive_targeted_dialogue_moves(self):
        for kind in ('revoice', 'clarify', 'combined'):
            with self.subTest(kind=kind):
                state = self.state(review_support_focus=['c3', 'o3'], review_outcome='unsuccessful')
                candidate = dialogue_assessment(kind)
                move = P.select_move(candidate, state, 'message', LEARNER_IDEA)
                P.update_progress(state, candidate, move, dialogue_reply(kind))
                self.assertEqual(state['review_support_focus'], ['c3', 'o3'])
                self.assertEqual(state['review_outcome'], 'unsuccessful')
                self.assertEqual(state['issue_check_started_at'], 1)
                self.assertEqual(state['thinking_started_at'], 2)

    def test_dialogue_candidates_do_not_override_existing_help_closure_or_revision_priorities(self):
        candidate = dialogue_assessment()
        cases = (
            (dict(intent='hint'), LEARNER_IDEA, candidate, 'provide_hints_guidance'),
            ({}, 'I need a hint.', candidate, 'provide_hints_guidance'),
            (dict(unsuccessful_response_count=3), LEARNER_IDEA, candidate, 'provide_hints_guidance'),
            ({}, LEARNER_IDEA, dialogue_assessment(closing_requested=True), 'invite_dialogue'),
            (dict(intent='begin_revision'), LEARNER_IDEA, candidate, 'propose_revision_plan'),
            (dict(awaiting_revision_reason=True), LEARNER_IDEA, candidate, 'invite_elaboration_reasoning'),
            (dict(awaiting_revision_reason=True), 'I need a hint.', candidate, 'provide_hints_guidance'),
        )
        for changes, message, value, expected in cases:
            with self.subTest(changes=changes, expected=expected):
                self.assertEqual(P.select_moves(value, self.state(**changes), 'message', message), [expected])
        frustration = 'This is frustrating; I keep getting nowhere.'
        candidate = dialogue_assessment(frustration_evidence=frustration)
        self.assertEqual(P.select_move(candidate, self.state(_current_message=frustration), 'message', frustration),
                         'provide_hints_guidance')

    def test_revoice_and_clarification_do_not_authorize_editing_or_extra_information(self):
        state = self.state()
        ids = {row['id'] for kind in ('objects', 'relations') for row in SCENE[kind]}
        for kind in ('revoice', 'clarify', 'combined'):
            with self.subTest(kind=kind):
                candidate = dialogue_assessment(kind)
                move = P.select_move(candidate, state, 'message', LEARNER_IDEA)
                self.assertFalse(P.thinking_policy(candidate, state, LEARNER_IDEA, move)['repair_instruction_allowed'])
                self.assertEqual(P.disclosure_policy(candidate, state, LEARNER_IDEA, move)['max_new_conceptual_steps'], 0)
                self.assertFalse(F.reply_problem(dialogue_reply(kind), state, candidate, ids, 'message', '', move))
                leaking = dialogue_reply(kind, new_conceptual_information=['An unstated solution.'])
                self.assertTrue(F.reply_problem(leaking, state, candidate, ids, 'message', '', move))
                editing = dialogue_reply(kind, next_step='revise')
                self.assertTrue(F.reply_problem(editing, state, candidate, ids, 'message', '', move))

    def test_combined_response_requires_only_one_question_and_rejects_two(self):
        candidate = dialogue_assessment()
        ids = {row['id'] for kind in ('objects', 'relations') for row in SCENE[kind]}
        self.assertFalse(F.reply_problem(dialogue_reply(), self.state(), candidate, ids, 'message', '', 'revoice'))
        two = reply('Do you mean both arrows? Which part receives the energy?', False,
                    question_purpose='clarify_meaning')
        self.assertTrue(F.reply_problem(two, self.state(), candidate, ids, 'message', '', 'revoice'))

    def test_schema_preserves_order_and_rejects_unsupported_plural_combinations(self):
        for moves in (['ask_for_clarification', 'revoice'], ['revoice', 'revoice'],
                      ['revoice', 'prompt_reflection'], ['revoice', 'ask_for_clarification', 'press_for_accuracy']):
            with self.subTest(moves=moves), self.assertRaises(ValueError):
                dialogue_assessment(talk_moves=moves)
        with self.assertRaises(ValueError):
            dialogue_assessment(talk_move='ask_for_clarification', talk_moves=COMBINED)
        single = assessment(talk_move='revoice', revoice_need='Check the interpretation.', revoice_evidence=LEARNER_IDEA)
        self.assertEqual(single.talk_moves, ['revoice'])

    def test_legacy_input_is_normalized_without_mutating_the_input_or_archive(self):
        legacy = assessment().model_dump()
        legacy['talk_move'] = 'revoice_or_clarify'
        legacy.pop('talk_moves', None)
        for field in ('revoice_need', 'revoice_evidence', 'clarification_need'):
            legacy.pop(field, None)
        before = deepcopy(legacy)
        restored = F.Assessment.model_validate(legacy)
        self.assertEqual(restored.talk_move, 'ask_for_clarification')
        self.assertEqual(restored.talk_moves, ['ask_for_clarification'])
        self.assertEqual(restored.revoice_need, '')
        self.assertEqual(restored.clarification_need, '')
        self.assertEqual(legacy, before)
        raw = dict(assessment=legacy, selected_talk_move='revoice_or_clarify', reply=dialogue_reply('clarify').model_dump())
        before = deepcopy(raw)
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'historical-response.json'
            archive.write_text(json.dumps(raw))
            original_bytes = archive.read_bytes()
            restored_turn = F.FastDialogueTurn.model_validate(json.loads(archive.read_text()))
            self.assertEqual(restored_turn.selected_talk_move, 'ask_for_clarification')
            self.assertEqual(restored_turn.selected_talk_moves, ['ask_for_clarification'])
            self.assertEqual(archive.read_bytes(), original_bytes)
        self.assertEqual(raw, before)

    def test_full_and_fast_combined_move_is_saved_publicly_and_keeps_support_stage(self):
        for fast in (False, True):
            with self.subTest(fast=fast), tempfile.TemporaryDirectory() as directory:
                sid = self.checked_session(directory)
                before = deepcopy(F.SESSIONS[sid]['state'])
                candidate = dialogue_assessment()
                response = dialogue_reply()
                outputs = [F.FastDialogueTurn(assessment=candidate, selected_talk_move='revoice',
                           selected_talk_moves=COMBINED, reply=response)] if fast else [candidate, response]
                client = FakeClient(outputs)
                public = F.handle(dict(trigger='message', session_id=sid, message=LEARNER_IDEA), client,
                                  directory, 'offline-review', **({'fast_dialogue_model': 'offline-fast'} if fast else {}))
                self.assertEqual(len(client.calls), 1 if fast else 2)
                self.assertEqual(public['talk_move'], 'revoice')
                self.assertEqual(public['talk_moves'], COMBINED)
                self.assertEqual(public['stage'], 'thinking-dialogue')
                self.assertFalse(public['edit_enabled'])
                self.assertEqual(public['new_conceptual_information'], [])
                state = F.SESSIONS[sid]['state']
                self.assertEqual(state['issue_check_started_at'], before['issue_check_started_at'])
                self.assertEqual(state['assessment']['talk_moves'], COMBINED)
                self.assertEqual(state['turns'][-1]['talk_moves'], COMBINED)
                stored = [json.loads(path.read_text()) for path in Path(directory).glob('feedback_turn_*/public_reply.json')]
                self.assertTrue(any(row.get('talk_moves') == COMBINED for row in stored))
                private = [json.loads(path.read_text()) for path in Path(directory).glob('feedback_turn_*/session.json')]
                self.assertTrue(any(row['turns'][-1].get('talk_moves') == COMBINED for row in private))

    def test_fast_plural_mismatch_gets_one_authoritative_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            sid = self.checked_session(directory)
            candidate = dialogue_assessment()
            incomplete = F.FastDialogueTurn(assessment=candidate, selected_talk_move='revoice',
                                           selected_talk_moves=['revoice'], reply=dialogue_reply())
            client = FakeClient([incomplete, dialogue_reply()])
            public = F.handle(dict(trigger='message', session_id=sid, message=LEARNER_IDEA), client,
                              directory, 'offline-review', fast_dialogue_model='offline-fast')
            self.assertEqual(len(client.calls), 2)
            context = input_context(client.calls[1])
            self.assertEqual(context['selected_talk_move'], 'revoice')
            self.assertEqual(context['selected_talk_moves'], COMBINED)
            self.assertIn('selected_talk_moves', context['rewrite_requirement'])
            self.assertEqual(public['talk_moves'], COMBINED)

    def test_plural_moves_and_private_needs_reach_cached_fast_and_rewrite_context(self):
        with tempfile.TemporaryDirectory() as directory:
            sid = self.checked_session(directory)
            candidate = dialogue_assessment()
            first = F.FastDialogueTurn(assessment=candidate, selected_talk_move='revoice',
                                      selected_talk_moves=COMBINED, reply=dialogue_reply())
            F.handle(dict(trigger='message', session_id=sid, message=LEARNER_IDEA), FakeClient([first]),
                     directory, 'offline-review', fast_dialogue_model='offline-fast')
            invalid = reply('Do you mean both arrows? Which part?', False, question_purpose='clarify_meaning')
            client = FakeClient([F.FastDialogueTurn(assessment=candidate, selected_talk_move='revoice',
                                selected_talk_moves=COMBINED, reply=invalid), dialogue_reply()])
            public = F.handle(dict(trigger='message', session_id=sid, message='I mean the same part.'), client,
                              directory, 'offline-review', fast_dialogue_model='offline-fast')
            self.assertEqual(len(client.calls), 2)
            cached = input_context(client.calls[0])['previous_assessment']
            rewritten = input_context(client.calls[1])['private_assessment']
            for field in ('talk_moves', 'revoice_need', 'revoice_evidence', 'clarification_need'):
                self.assertEqual(cached[field], getattr(candidate, field))
                self.assertEqual(rewritten[field], getattr(candidate, field))
            self.assertEqual(public['talk_moves'], COMBINED)


if __name__ == '__main__':
    unittest.main(verbosity=2)
