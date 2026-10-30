"""Visible edit instructions survive ordinary punctuation and friendly emoji.

Regression strings come from failed tutor turns. All integration calls use
typed local stubs; no model API, browser, or network is involved.
"""
from copy import deepcopy
import tempfile
from types import SimpleNamespace
import unittest

from test_feedback import F, P, FakeClient, SCENE, assessment, reply


ACTUAL_PLANS = (
    (
        'Arrows are a clear way to show the moves in order. 🙂 Add arrows to your '
        'number line to represent each card’s move, then submit it for review.',
        'Add arrows to your number line to represent each card’s move, then submit it for review.',
    ),
    (
        'Nice, you’ve got a clear first step! 🙂 Add the movement you described '
        'for the −6 card to the number line, then submit it for review.',
        'Add the movement you described for the −6 card to the number line, then submit it for review.',
    ),
    (
        'You’ve got a clear first movement in mind! 🙂 Draw the move you described '
        'from zero for the −6 card, then submit it for review.',
        'Draw the move you described from zero for the −6 card, then submit it for review.',
    ),
)


class EditCommandDecorationTests(unittest.TestCase):
    def setUp(self):
        F.SESSIONS.clear()

    def echo(self, content, quote='move 6 right'):
        value = SimpleNamespace(
            evidence_quote=quote, evidence_source='dialogue',
            question_purpose='develop_reasoning', next_step='explore',
            guidance_requires_edit=False, revision_plan='', content=content,
        )
        return P.learner_action_echo(value, {'_current_message': 'I would ' + quote + '.'})

    def test_actual_failed_plans_are_visible_edit_commands(self):
        for content, _ in ACTUAL_PLANS:
            with self.subTest(content=content):
                self.assertTrue(P.visible_edit_command(content))

    def test_decorated_imperatives_and_use_to_commands(self):
        for content in (
            'Good reasoning! Add an arrow.',
            '🙂 Add an arrow.',
            'Good reasoning. 🙂 Add an arrow.',
            'Good work! 🙂 Please add an arrow.',
            'Good work! ❤️ Add an arrow.',
            'Ready? Add an arrow.',
            '🙂 Use your starting value to move the endpoint.',
        ):
            with self.subTest(content=content):
                self.assertTrue(P.visible_edit_command(content))

    def test_non_commands_and_mental_targets_remain_non_edits(self):
        for content in (
            '🙂 Your arrow shows a movement.',
            'You could add an arrow later.',
            'Perhaps add an arrow later.',
            'Consider adding an arrow.',
            'How would moving an arrow help?',
            '🙂 Revise your explanation.',
            'Good work! 🙂 Add an explanation.',
            'Good work! 🙂 Could you explain the movement?',
            'You said “Add an arrow.”',
        ):
            with self.subTest(content=content):
                self.assertFalse(P.visible_edit_command(content))

    def test_grounded_descriptive_echo_accepts_leading_decoration(self):
        for content in (
            "You're proposing: move 6 right.",
            "🙂 You're proposing: move 6 right.",
            "❤️ You're proposing: move 6 right.",
        ):
            with self.subTest(content=content):
                self.assertTrue(self.echo(content))

    def test_emoji_cannot_hide_an_extra_command_inside_an_echo(self):
        for content in (
            "You're proposing: move 6 right. 🙂 Add an arrow.",
            "You're proposing: move 6 right! 🙂 Add an arrow.",
            "You're proposing: move 6 right. 🙂 Use the label to move the endpoint.",
            "You're proposing: move 6 right, because 🙂 add an arrow.",
        ):
            with self.subTest(content=content):
                self.assertFalse(self.echo(content))

    def test_decoration_does_not_make_a_new_argument_or_imperative_an_echo(self):
        for content in (
            "🙂 You're proposing: move 12 right.",
            "🙂 You're proposing: move 6 left.",
            '🙂 Move 6 right.',
            'Good work! 🙂 Move 6 right.',
        ):
            with self.subTest(content=content):
                self.assertFalse(self.echo(content))

    def test_decorated_plan_unlocks_on_first_writer_reply_without_rewrite(self):
        message = 'Each arrow should show the change represented by one card.'
        for content, plan in ACTUAL_PLANS:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                data = dict(trigger='submission', scene=deepcopy(SCENE),
                            original_scene=deepcopy(SCENE), explanation='Food needs energy.',
                            task='Explain the represented transfers.', goals=[], message='', edits=[])
                first = F.handle(data, FakeClient([assessment(), reply()]), directory, 'offline-stub')
                state = F.SESSIONS[first['session_id']]['state']
                state.update(accuracy_focus=['c3', 'o3'], accuracy_started_at=1,
                             progress_focus=['c3', 'o3'], thinking_focus=['c3', 'o3'],
                             thinking_started_at=1)
                client = FakeClient([
                    assessment(progress_status='ready', ready_for_revision=True,
                               readiness_evidence=message, talk_move='propose_revision_plan'),
                    reply(content, False, revision_plan=plan,
                          revision_plan_ids=['o3'], next_step='revise'),
                ])
                result = F.handle(dict(trigger='message', session_id=first['session_id'],
                                       message=message), client, directory, 'offline-stub')
                self.assertEqual(result['talk_move'], 'propose_revision_plan')
                self.assertTrue(result['edit_enabled'])
                self.assertEqual(result['revision_plan'], plan)
                self.assertEqual(result['api_calls'], 2, 'Evaluator + first writer only; no corrective retry.')
                self.assertEqual(len(client.calls), 2)
                self.assertEqual(result['follow_up'], content)


if __name__ == '__main__':
    unittest.main(verbosity=2)
