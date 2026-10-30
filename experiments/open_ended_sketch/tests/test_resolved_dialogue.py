"""A reply after resolved review must not restart a compulsory reasoning loop.

Includes the actual failing learner/teacher wording. All calls are typed local
stubs; no API, browser, or network is used.
"""
from copy import deepcopy
import tempfile
import unittest

from test_feedback import F, P, FakeClient, SCENE, assessment, reply, rows


LEARNER_SUMMARY = 'The moves end at 2, so the sum is 2.'
ACTUAL_FOLLOW_UP = 'Exactly—the moves end at 2, so the sum is 2. Any questions about your completed model? 🙂'


def resolved_assessment(**changes):
    established = [dict(row, status='established', gap='') for row in rows()]
    values = dict(criteria=established, changed_criteria=['c1', 'c2', 'c3'],
                  areas_for_improvement=[], ambiguities=[], next_focus_kind='none',
                  revision_resolved=True, revision_reason_sufficient=True,
                  progress_status='ready', talk_move='invite_dialogue',
                  current_response_outcome='successful', outcome_evidence=LEARNER_SUMMARY,
                  visual_intent='none')
    values.update(changes)
    return assessment(**values)


class ResolvedDialogueTests(unittest.TestCase):
    def setUp(self):
        F.SESSIONS.clear()

    def data(self):
        return dict(trigger='submission', scene=deepcopy(SCENE),
                    original_scene=deepcopy(SCENE), explanation='Food needs energy.',
                    task='Explain the represented transfers.', goals=[], message='', edits=[])

    def start(self, directory):
        return F.handle(self.data(), FakeClient([assessment(), reply()]), directory, 'offline-stub')

    def completed_review(self, directory):
        first = self.start(directory)
        sid = first['session_id']
        F.begin_revision({'session_id': sid})
        changed = deepcopy(SCENE)
        changed['objects'][0]['label'] = 'Completed representation'
        reviewed = F.handle(
            dict(trigger='workspace-complete', session_id=sid, scene=changed,
                 explanation='Food needs energy.', edits=[],
                 revision_reason='I completed the representation to match my explanation.'),
            FakeClient([
                resolved_assessment(current_response_outcome='not_applicable', outcome_evidence=''),
                reply('Any remaining questions about your completed model?',
                      acknowledgment='Your updated model matches your explanation.',
                      acknowledgment_ids=['o1'], visual_action='none', visual_delivery='none'),
            ]), directory, 'offline-stub',
        )
        self.assertEqual(reviewed['talk_move'], 'invite_dialogue')
        state = F.SESSIONS[sid]['state']
        self.assertFalse(state['awaiting_revision_reason'])
        self.assertEqual(state['thinking_started_at'], 0)
        self.assertEqual(state['turns'][-1]['talk_move'], 'invite_dialogue')
        return sid

    def next_state(self, directory, message=LEARNER_SUMMARY):
        sid = self.completed_review(directory)
        state, _, _ = F.prepare(F.SESSIONS[sid]['state'],
                                dict(trigger='message', message=message))
        return state

    def test_completed_review_followup_stays_in_dialogue_without_thinking_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.next_state(directory)
            self.assertEqual(state['thinking_started_at'], 0)
            self.assertEqual(P.select_move(resolved_assessment(), state,
                                           'message', LEARNER_SUMMARY), 'invite_dialogue')

    def test_initial_recognition_and_first_exploration_are_not_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            state, _, _ = F.prepare(None, self.data())
            self.assertEqual(P.select_move(resolved_assessment(), state,
                                           'submission'), 'recognize_strengths')
            first = self.start(directory)
            state, _, _ = F.prepare(F.SESSIONS[first['session_id']]['state'],
                                    dict(trigger='message', message=LEARNER_SUMMARY))
            self.assertEqual(state['turns'][-1]['talk_move'], 'recognize_strengths')
            self.assertIn(P.select_move(resolved_assessment(), state,
                                       'message', LEARNER_SUMMARY), P.THINKING_MOVES)

    def test_a_still_pending_revision_reason_is_not_silently_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.next_state(directory)
            state['awaiting_revision_reason'] = True
            current = resolved_assessment(revision_reason_sufficient=False)
            self.assertEqual(P.select_move(current, state, 'message', LEARNER_SUMMARY),
                             'invite_elaboration_reasoning')

    def test_a_new_gap_or_ambiguity_still_receives_its_check(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.next_state(directory)
            self.assertEqual(P.select_move(assessment(progress_status='new'), state,
                                           'message', LEARNER_SUMMARY), 'press_for_accuracy')
            unclear = resolved_assessment(next_focus_kind='clarification',
                ambiguities=[dict(claim='Meaning unclear.', evidence='The learner asks about another mark.')])
            self.assertEqual(P.select_move(unclear, state, 'message', LEARNER_SUMMARY),
                             'ask_for_clarification')

    def test_goal_uncertainty_and_requested_help_keep_their_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.next_state(directory)
            self.assertEqual(P.select_move(resolved_assessment(goal_unclear=True), state,
                                           'message', LEARNER_SUMMARY), 'clarify_goals')
            self.assertEqual(P.select_move(resolved_assessment(), state,
                                           'message', 'I need a hint.'), 'provide_hints_guidance')

    def test_actual_optional_invitation_or_statement_passes_first_fast_call(self):
        for content in (ACTUAL_FOLLOW_UP, 'Exactly—the moves end at 2, so the sum is 2. 🙂'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                sid = self.completed_review(directory)
                before = deepcopy(F.SESSIONS[sid]['state']['committed'])
                candidate = F.FastDialogueTurn(
                    assessment=resolved_assessment(), selected_talk_move='invite_dialogue',
                    reply=reply(content, False, visual_action='none', visual_delivery='none'),
                )
                client = FakeClient([candidate])
                public = F.handle(dict(trigger='message', session_id=sid, message=LEARNER_SUMMARY),
                                  client, directory, 'offline-stub', fast_dialogue_model='offline-fast')
                self.assertEqual(public['talk_move'], 'invite_dialogue')
                self.assertEqual(public['api_calls'], 1, 'No routing rewrite should be needed.')
                self.assertEqual(len(client.calls), 1)
                self.assertEqual(public['follow_up'], content)
                self.assertFalse(public['awaiting_revision_reason'])
                self.assertFalse(public['edit_enabled'])
                self.assertEqual(F.SESSIONS[sid]['state']['committed'], before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
