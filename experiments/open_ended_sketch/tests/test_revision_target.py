"""Bounded review targets survive dialogue and never require whole-task success."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from revision_target import (VERSION, consume_reviewed_revision_target,
    record_delivered_revision_target, revision_target_context)


def state():
    return dict(version=3, drawing_version=1, current_issue_id='complete_model', review_version=1,
        workflow=dict(active_issue=dict(id='complete_model')),
        committed=dict(scene=dict(objects=[dict(id='a', label='A')], relations=[])), turns=[])


def turn(instruction='', move='propose_revision_plan'):
    return SimpleNamespace(edit_instruction=instruction, talk_moves=[move])


class RevisionTargetTests(unittest.TestCase):
    def test_instruction_scope_survives_dialogue_and_deduplicates(self):
        value = state()
        record_delivered_revision_target(value, turn('Draw one arrow from A to B.'))
        value['version'] += 1
        record_delivered_revision_target(value, turn('', 'invite_elaboration_reasoning'))
        record_delivered_revision_target(value, turn('Draw one arrow from A to B.'))
        target = revision_target_context(value, 'diagram_revision')
        self.assertEqual(target['scope_source'], 'delivered_tutor_instructions')
        self.assertEqual(len(target['instructions']), 1)
        self.assertEqual(target['instructions'][0]['delivery_version'], 3)
        self.assertEqual(target['instructions'][0]['instruction'], 'Draw one arrow from A to B.')

    def test_multiple_local_instructions_in_one_submission_are_kept(self):
        value = state()
        record_delivered_revision_target(value, turn('Draw the first arrow.'))
        value['version'] += 1
        record_delivered_revision_target(value, turn('Add the second arrow.', 'provide_hints_guidance'))
        self.assertEqual(len(revision_target_context(value, 'diagram_revision')['instructions']), 2)

    def test_invitation_is_not_a_provided_edit(self):
        value = state()
        record_delivered_revision_target(value, turn())
        target = revision_target_context(value, 'diagram_revision')
        self.assertEqual(target['scope_source'], 'submitted_delta')
        self.assertEqual(target['instructions'], [])

    def test_changed_submission_target_is_consumed_before_next_instruction(self):
        value = state()
        record_delivered_revision_target(value, turn('Draw the first arrow.'))
        value['drawing_version'] = 2
        consume_reviewed_revision_target(value)
        record_delivered_revision_target(value, turn('Add the next arrow.'))
        target = revision_target_context(value, 'diagram_revision')
        self.assertEqual([row['instruction'] for row in target['instructions']], ['Add the next arrow.'])
        self.assertEqual(target['base_drawing_version'], 2)

    def test_consumption_does_not_resurrect_legacy_instructions(self):
        value = state()
        value['turns'] = [dict(version=2, issue_id='complete_model', talk_move='propose_revision_plan',
                               content='Draw the first arrow.')]
        self.assertEqual(len(revision_target_context(value, 'diagram_revision')['instructions']), 1)
        consume_reviewed_revision_target(value)
        self.assertEqual(revision_target_context(value, 'diagram_revision')['instructions'], [])

    def test_legacy_recovery_excludes_invitations_old_reviews_other_issues_and_concepts(self):
        value = state()
        value['turns'] = [
            dict(version=0, issue_id='complete_model', talk_move='propose_revision_plan', content='Draw an old arrow.'),
            dict(version=2, issue_id='other_issue', talk_move='propose_revision_plan', content='Draw another issue.'),
            dict(version=3, issue_id='complete_model', talk_move='propose_revision_plan', content='How will you show all the moves?'),
            dict(version=4, issue_id='complete_model', talk_move='provide_hints_guidance', content='From 6, move four steps left.'),
            dict(version=5, issue_id='complete_model', talk_move='propose_revision_plan', content='Draw one arrow from A to B.'),
        ]
        target = revision_target_context(value, 'diagram_revision')
        self.assertEqual([row['instruction'] for row in target['instructions']], ['Draw one arrow from A to B.'])
        self.assertEqual(target['instructions'][0]['source'], 'delivered_legacy_turn')

    def test_legacy_target_is_preserved_on_first_new_ordinary_turn(self):
        value = state()
        value['turns'] = [dict(version=2, issue_id='complete_model', talk_move='propose_revision_plan',
                               content='Draw the first arrow.')]
        record_delivered_revision_target(value, turn('', 'invite_elaboration_reasoning'))
        self.assertEqual(value['workflow']['revision_target_protocol'], VERSION)
        self.assertEqual(len(revision_target_context(value, 'diagram_revision')['instructions']), 1)

    def test_new_issue_cannot_inherit_previous_issue_target(self):
        value = state()
        record_delivered_revision_target(value, turn('Draw the first arrow.'))
        value['workflow']['active_issue'] = dict(id='other_issue')
        self.assertEqual(revision_target_context(value, 'diagram_revision')['instructions'], [])

    def test_learner_reason_and_mechanical_delta_are_fallback_not_whole_issue(self):
        value = state()
        value['revision_reason'] = 'I corrected the A label.'
        value['previous_submission'] = deepcopy(value['committed'])
        value['committed']['scene']['objects'][0]['label'] = 'B'
        target = revision_target_context(value, 'diagram_revision')
        self.assertEqual(target['scope_source'], 'learner_revision_intent')
        self.assertEqual(target['learner_revision_reason'], 'I corrected the A label.')
        self.assertEqual(target['submitted_delta']['objects']['changed'], [dict(id='a', fields=['label'])])
        self.assertNotIn('description', target)

    def test_explicit_learner_request_is_stored_with_provenance(self):
        value = state()
        record_delivered_revision_target(value, turn(), dict(intent='begin_revision', message='I want to correct the arrow.'))
        target = revision_target_context(value, 'diagram_revision')
        self.assertEqual(target['scope_source'], 'learner_revision_intent')
        self.assertEqual(target['learner_requests'][0]['text'], 'I want to correct the arrow.')

    def test_context_is_read_only_and_initial_has_no_revision(self):
        value = state()
        before = deepcopy(value)
        self.assertIsNone(revision_target_context(value, 'initial'))
        revision_target_context(value, 'diagram_revision')
        self.assertEqual(value, before)

    def test_protocol_store_is_not_limited_by_twelve_turn_history(self):
        value = state()
        record_delivered_revision_target(value, turn('Draw the first arrow.'))
        value['turns'] = [dict(version=number, content='A later question.', issue_id='complete_model',
            talk_move='invite_elaboration_reasoning') for number in range(20, 32)]
        self.assertEqual(len(revision_target_context(value, 'diagram_revision')['instructions']), 1)

    def test_legacy_base_version_distinguishes_current_dialogue_from_submission(self):
        value = state()
        value['drawing_version'] = 3
        value['previous_submission'] = deepcopy(value['committed'])
        value['turns'] = [dict(version=2, issue_id='complete_model', talk_move='propose_revision_plan',
                               content='Draw the current arrow.')]
        # A legacy session can already contain an older previous_submission;
        # recording a newly delivered ordinary turn must keep current version 3.
        record_delivered_revision_target(value, turn('', 'invite_elaboration_reasoning'))
        self.assertEqual(value['workflow']['pending_revision_target']['base_drawing_version'], 3)
        value['drawing_version'] = 4
        self.assertEqual(revision_target_context(value, 'diagram_revision')['base_drawing_version'], 3)

    def test_legacy_review_reply_can_supply_the_next_local_target(self):
        value = state()
        value.update(version=6, drawing_version=2, review_version=5)
        value['previous_submission'] = deepcopy(value['committed'])
        value['turns'] = [
            dict(version=4, issue_id='complete_model', talk_move='propose_revision_plan',
                 content='Draw the already reviewed arrow.'),
            dict(version=5, issue_id='complete_model', talk_move='propose_revision_plan',
                 content='Nice work on the first arrow! Draw the next arrow.'),
            dict(version=6, issue_id='complete_model', talk_move='invite_elaboration_reasoning',
                 content='What does that arrow show?'),
        ]
        record_delivered_revision_target(value, turn('', 'invite_elaboration_reasoning'))
        pending = value['workflow']['pending_revision_target']
        self.assertEqual([row['instruction'] for row in pending['instructions']], ['Draw the next arrow.'])
        self.assertEqual(pending['instructions'][0]['delivery_version'], 5)
        self.assertEqual(pending['base_drawing_version'], 2)
        value['drawing_version'] = 3
        target = revision_target_context(value, 'diagram_revision')
        self.assertEqual(target['base_drawing_version'], 2)
        self.assertEqual(target['submitted_drawing_version'], 3)

    def test_delta_covers_additions_removals_and_null_field_removal(self):
        value = state()
        value['previous_submission'] = dict(scene=dict(
            objects=[dict(id='a', label='A', ambiguity=None)],
            relations=[dict(id='old', source='a', target='b')]))
        value['committed']['scene']['relations'] = [dict(id='new', source='a', target='c')]
        result = revision_target_context(value, 'diagram_revision')['submitted_delta']
        self.assertEqual(result['objects']['changed'], [dict(id='a', fields=['ambiguity'])])
        self.assertEqual(result['relations']['removed_ids'], ['old'])
        self.assertEqual(result['relations']['added_ids'], ['new'])


if __name__ == '__main__':
    unittest.main()
