"""Sparse learning memory, source ownership, and compatibility without model calls."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from learner_model import (
    create_learner_model, record_evaluation, record_observations, record_representation,
    migrate_learner_model, project_learner_model, MAX_OBSERVATIONS,
)


class LearnerModelTests(unittest.TestCase):
    def memory(self):
        return create_learner_model('Represent the change on a number line.', [{'id': 'c1', 'label': 'Show the change.'}], 'drawing-a')

    def evaluation(self):
        return {'learning_goal': 'Show the first change with an arrow.',
                'task_summary': 'Represent a change of minus six on the supplied number line.',
                'criteria': [{'criterion': 'c1', 'status': 'developing', 'level': 'developing',
                              'evidence': 'The scale is present, but no change arrow is submitted.'}],
                'strengths': [{'description': 'The drawing includes zero.', 'evidence': 'Visible 0 label.', 'focus_ids': ['zero']}],
                'missing_parts': [{'id': 'm1', 'criterion': 'c1', 'description': 'Represent the change.',
                                   'evidence': 'No operation arrow.', 'focus_ids': ['zero']}],
                'uncertainties': [], 'revision_outcome': 'not_reviewed', 'revision_evidence': ''}

    def update(self, **changes):
        value = {'kind': 'understanding', 'summary': 'The learner identifies the first arrow endpoint.',
                 'evidence': 'The first arrow ends at minus six.'}
        value.update(changes)
        return value

    def test_empty_or_unsupported_turn_does_not_change_memory_revision(self):
        memory = self.memory()
        for updates in ([], None, [self.update(evidence='Invented learner evidence.')],
                        [self.update(evidence='yes')], [self.update(evidence='I do not know.')],
                        [self.update(kind=['understanding'])]):
            with self.subTest(updates=updates):
                current, accepted = record_observations(memory, updates, ['yes', 'I do not know.'], 1)
                self.assertEqual(current, memory)
                self.assertEqual(accepted, [])
        self.assertIsNone(memory['evaluation'])
        self.assertEqual(memory['revision'], 0)

    def test_formal_evaluation_is_updated_by_submission_version_without_aliasing(self):
        before = self.memory()
        result = self.evaluation()
        after = record_evaluation(before, result, 1)
        self.assertEqual(before, self.memory())
        self.assertEqual(after['evaluation']['source'], 'evaluation')
        self.assertEqual(after['evaluation']['result']['criteria'][0]['level'], 'developing')
        self.assertEqual(project_learner_model(after)['evaluation']['result']['task_summary'],
                         'Represent a change of minus six on the supplied number line.')
        self.assertEqual(after['revision'], 1)
        result['criteria'][0]['level'] = 'demonstrated'
        self.assertEqual(after['evaluation']['result']['criteria'][0]['level'], 'developing')
        unchanged = record_evaluation(after, self.evaluation(), 1)
        self.assertEqual(unchanged, after)
        newer = record_evaluation(after, self.evaluation(), 2)
        self.assertEqual(newer['revision'], 2)
        with self.assertRaises(ValueError):
            record_evaluation(newer, self.evaluation(), 1)

    def test_tutor_observation_cannot_patch_formal_level_task_or_source(self):
        memory = record_evaluation(self.memory(), self.evaluation(), 1)
        for extra in ({'evaluation': {'criteria': []}}, {'level': 'demonstrated'},
                      {'task': 'Different task'}, {'source': 'evaluation'}):
            with self.subTest(extra=extra):
                updated, accepted = record_observations(memory, [self.update(**extra)],
                    ['The first arrow ends at minus six.'], 1)
                self.assertEqual(updated, memory)
                self.assertEqual(accepted, [])
        updated, accepted = record_observations(memory, [self.update()],
                                               ['The first arrow ends at minus six.'], 1)
        self.assertEqual(updated['evaluation'], memory['evaluation'])
        self.assertEqual(accepted[0]['source'], 'tutor_observation')
        self.assertEqual(updated['revision'], memory['revision'] + 1)

    def test_grounded_significant_observations_are_deduplicated_and_current_version_only(self):
        memory = self.memory()
        source = ['The first arrow ends at minus six.']
        after, accepted = record_observations(memory, [self.update(), self.update()], source, 1)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(after['observations']), 1)
        repeated, accepted = record_observations(after, [self.update()], source, 1)
        self.assertEqual(repeated, after)
        self.assertEqual(accepted, [])
        for version in (2, 3):
            ignored, accepted = record_observations(after, [self.update()], source, version)
            self.assertEqual(ignored, after)
            self.assertEqual(accepted, [])

    def test_important_difficulty_is_retained_as_observation_not_ability_downgrade(self):
        memory = record_evaluation(self.memory(), self.evaluation(), 1)
        update = self.update(kind='difficulty', summary='The learner needs help choosing the first arrow endpoints.',
                             evidence='I do not know.')
        after, accepted = record_observations(memory, [update], ['I do not know.'], 1)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(after['evaluation'], memory['evaluation'])
        self.assertEqual(after['observations'][0]['kind'], 'difficulty')

    def test_history_is_bounded_and_projection_has_no_cached_transcript_or_routing(self):
        memory = self.memory()
        for index in range(MAX_OBSERVATIONS + 4):
            quote = 'I can describe relation ' + str(index)
            memory, _ = record_observations(memory, [self.update(summary='New relation ' + str(index), evidence=quote)], [quote], 1)
        memory['dialogue'] = ['UNWANTED FULL CHAT']
        memory['evaluation'] = {'source': 'evaluation', 'drawing_version': 1,
                                'result': {**self.evaluation(), 'cached_assessment': 'UNWANTED FIELDS'}}
        view = project_learner_model(memory)
        self.assertEqual(len(memory['observations']), MAX_OBSERVATIONS)
        self.assertEqual(len(view['observations']), 6)
        self.assertNotIn('dialogue', view)
        self.assertNotIn('cached_assessment', view['evaluation']['result'])
        view['task']['text'] = 'Changed projection'
        self.assertNotEqual(view['task'], memory['task'])

    def test_legacy_import_preserves_provenance_and_does_not_invent_levels(self):
        state = {'task': 'Old task.', 'criteria': [{'id': 'c1', 'label': 'Old criterion.'}],
                 'task_figure_context': 'Given a number line; show a change of minus six.',
                 'drawing_version': 2, 'source_id': 'old-drawing',
                 'assessment': {'learning_goal': 'Old task goal.',
                                'criteria': [{'criterion': 'c1', 'status': 'developing',
                                              'strength': 'Visible zero.', 'gap': 'Missing arrow.'}],
                                'strengths': [{'claim': 'Zero shown.', 'evidence': 'Visible zero.'}],
                                'areas_for_improvement': [{'claim': 'Arrow missing.', 'evidence': 'No arrow.'}],
                                'ambiguities': [], 'criterion': 'c1', 'student_stuck': True},
                 'turns': [{'student': 'Do not bulk-import every turn.'}]}
        old = deepcopy(state)
        memory = migrate_learner_model(state)
        self.assertEqual(state, old)
        self.assertEqual(memory['evaluation']['source'], 'legacy_assessment')
        self.assertEqual(memory['drawing_version'], 2)
        criterion = memory['evaluation']['result']['criteria'][0]
        self.assertEqual(criterion['status'], 'developing')
        self.assertNotIn('level', criterion)
        self.assertEqual(memory['evaluation']['result']['task_summary'], state['task_figure_context'])
        self.assertNotIn('student_stuck', memory['evaluation']['result'])
        self.assertEqual(memory['observations'], [])
        state['learner_model'] = memory
        self.assertEqual(migrate_learner_model(state), memory)
        self.assertEqual(memory['revision'], 1)

    def test_invalid_versions_and_oversized_evidence_do_not_enter_memory(self):
        for value in (0, -1, True, '1'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                create_learner_model('', [], drawing_version=value)
        long_quote = ' '.join('part' + str(index) for index in range(26))
        memory = self.memory()
        current, accepted = record_observations(memory, [self.update(evidence=long_quote)], [long_quote], 1)
        self.assertEqual(current, memory)
        self.assertEqual(accepted, [])

    def test_representation_summary_is_compact_and_preserves_source_uncertainty(self):
        memory = self.memory()
        scene = {'objects': [{'id': 'zero', 'glyph': ['LARGE_RENDER_DATA'],
                              'ambiguity': 'The tick-label association is uncertain.'},
                             {'id': 'six', 'ambiguity': 'The tick-label association is uncertain.'}],
                 'relations': [{'id': 'arrow', 'points': ['LARGE_COORDINATE_DATA'],
                                'ambiguity': 'The arrow endpoint is uncertain.'}]}
        before = deepcopy(scene)
        after = record_representation(memory, scene, 'drawing-a', 1)
        self.assertEqual(scene, before)
        self.assertEqual(memory, self.memory())
        self.assertEqual(after['representation'], {
            'source_id': 'drawing-a', 'drawing_version': 1, 'object_count': 2, 'relation_count': 1,
            'uncertainties': ['The tick-label association is uncertain.', 'The arrow endpoint is uncertain.'],
        })
        self.assertEqual(after['revision'], 1)
        view = project_learner_model(after)
        self.assertEqual(view['representation'], after['representation'])
        self.assertNotIn('LARGE_RENDER_DATA', str(view))
        self.assertNotIn('LARGE_COORDINATE_DATA', str(view))

    def test_empty_stale_or_unchanged_representation_does_not_rewrite_memory(self):
        scene = {'objects': [{'id': 'zero', 'ambiguity': ''}], 'relations': []}
        memory = record_representation(self.memory(), scene, 'drawing-a', 2)
        for replacement, version in ((None, 2), ({}, 2), ({'objects': [], 'relations': []}, 2),
                                     (scene, 1), (scene, 2)):
            with self.subTest(replacement=replacement, version=version):
                self.assertEqual(record_representation(memory, replacement, 'drawing-a', version), memory)
        with self.assertRaises(ValueError):
            record_representation(memory, scene, 'drawing-a', 0)

    def test_native_edit_changes_representation_version_without_rewriting_formal_evaluation(self):
        memory = record_evaluation(self.memory(), self.evaluation(), 1)
        updated = record_representation(memory,
            {'objects': [{'id': 'zero', 'ambiguity': ''}],
             'relations': [{'id': 'new-arrow', 'ambiguity': ''}]}, 'drawing-a', 2)
        self.assertEqual(updated['drawing_version'], 2)
        self.assertEqual(updated['representation']['relation_count'], 1)
        self.assertEqual(updated['evaluation'], memory['evaluation'])
        self.assertEqual(updated['evaluation']['drawing_version'], 1)
        self.assertEqual(updated['revision'], memory['revision'] + 1)
        self.assertEqual(record_evaluation(updated, self.evaluation(), 2)['evaluation']['drawing_version'], 2)


if __name__ == '__main__':
    unittest.main()
