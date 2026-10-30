"""Evidence-preserving lightweight Tutor requests; no model calls."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from learner_model import create_learner_model, record_evaluation
from tutor_context import build_tutor_context, editor_context


class TutorContextTests(unittest.TestCase):
    def state(self):
        scene = {'title': 'An example diagram',
                 'objects': [{'id': 'a', 'label': 'Start', 'verbatim_text': '0', 'kind': 'text',
                              'bbox': {'x': 0, 'y': 0, 'width': 20, 'height': 20}, 'members': [],
                              'ambiguity': 'No calibrated scale inferred.',
                              'glyph': ['HEAVY_STROKES'], 'evidence': 'HEAVY_PROVENANCE'},
                             {'id': 'b', 'label': 'End', 'verbatim_text': '−6', 'kind': 'text',
                              'bbox': {'x': 100, 'y': 0, 'width': 20, 'height': 20}, 'members': [],
                              'ambiguity': '', 'glyph': ['HEAVY_STROKES']}],
                 'relations': [{'id': 'r', 'source': 'a', 'target': 'b', 'direction': 'forward',
                                'points': [{'x': 10, 'y': 10}, {'x': 110, 'y': 10}],
                                'verbatim_text': 'first change', 'ambiguity': '',
                                'interpretation': 'HEAVY_PROVENANCE'}]}
        memory = create_learner_model('Represent one change.', [{'id': 'c1', 'label': 'Show a change.'}])
        memory = record_evaluation(memory, {'criteria': [], 'missing_parts': [
            {'id': 'm1', 'description': 'First issue.'}, {'id': 'm2', 'description': 'Chosen issue.'}]}, 1)
        return {'committed': {'scene': scene, 'explanation': 'Latest learner explanation.'},
                'learner_model': memory, 'current_issue_id': 'm2', 'stage': 'thinking-dialogue',
                'edit_enabled': False, 'hint_turns_remaining': 2, 'guidance_count': 1,
                'consecutive_difficulties': 1,
                'turns': [{'student': 'Learner ' + str(index), 'content': 'Tutor ' + str(index),
                           'talk_move': 'invite_elaboration_reasoning',
                           'submitted_snapshot': 'UNWANTED_OLD_SCENE'} for index in range(10)],
                'question_image': 'UNWANTED_IMAGE', 'assessment': 'UNWANTED_ASSESSMENT',
                'review': 'UNWANTED_REVIEW', 'accuracy_focus': 'UNWANTED_ROUTING'}

    def test_payload_omits_rendering_and_duplicate_state_but_preserves_geometry(self):
        state = self.state()
        context = build_tutor_context(state, 'Please help with this arrow.', 'message', 'dialogue')
        self.assertEqual(set(context), {'learner_model', 'current_diagram', 'latest_explanation',
                                       'recent_dialogue', 'student_message', 'selected_id', 'current_issue', 'interaction', 'editor_context'})
        packed = json.dumps(context)
        for marker in ('HEAVY_STROKES', 'HEAVY_PROVENANCE', 'UNWANTED_OLD_SCENE',
                       'UNWANTED_IMAGE', 'UNWANTED_ASSESSMENT', 'UNWANTED_REVIEW', 'UNWANTED_ROUTING'):
            self.assertNotIn(marker, packed)
        self.assertEqual(context['current_diagram']['relations'][0]['points'],
                         state['committed']['scene']['relations'][0]['points'])
        self.assertEqual(context['current_diagram']['objects'][0]['ambiguity'], 'No calibrated scale inferred.')
        self.assertEqual(context['current_diagram']['objects'][0]['id'], 'a')

    def test_short_context_has_six_recent_pairs_and_character_limits_preserve_current_message(self):
        state = self.state()
        state['turns'][-1]['student'] = 's' * 1000
        state['turns'][-1]['content'] = 't' * 1000
        state['committed']['explanation'] = 'e' * 3000
        message = 'm' * 4000
        context = build_tutor_context(state, message, 'message', 'hint')
        self.assertEqual(len(context['recent_dialogue']), 6)
        self.assertEqual(context['recent_dialogue'][0]['student'], 'Learner 4')
        self.assertEqual(context['recent_dialogue'][0]['talk_moves'], ['invite_elaboration_reasoning'])
        self.assertEqual(len(context['recent_dialogue'][-1]['student']), 700)
        self.assertEqual(len(context['recent_dialogue'][-1]['tutor']), 700)
        self.assertEqual(len(context['latest_explanation']), 2000)
        self.assertEqual(context['student_message'], message)
        with self.assertRaises(ValueError):
            build_tutor_context(state, message + 'x', 'message', 'dialogue')

    def test_current_issue_selects_id_then_first_and_empty_issues_are_none(self):
        state = self.state()
        self.assertEqual(build_tutor_context(state, '', 'submission', 'dialogue')['current_issue']['id'], 'm2')
        state['current_issue_id'] = 'missing'
        self.assertEqual(build_tutor_context(state, '', 'submission', 'dialogue')['current_issue']['id'], 'm1')
        state['learner_model']['evaluation']['result']['missing_parts'] = []
        self.assertIsNone(build_tutor_context(state, '', 'submission', 'dialogue')['current_issue'])

    def test_supported_editor_controls_remain_available_while_permission_is_locked(self):
        state = self.state()
        context = editor_context(state)
        tools = {item['action']: item for item in context['tools']}
        self.assertFalse(context['current_edit_enabled'])
        self.assertFalse(context['capabilities']['freehand_drawing'])
        self.assertTrue(tools['connect']['available'])
        self.assertTrue(tools['connect']['requires_edit_permission'])
        self.assertEqual(tools['connect']['endpoint_source'], 'current_diagram.objects')
        self.assertEqual(tools['connect']['save_label'], 'Save connection')
        state['committed']['scene']['objects'] = state['committed']['scene']['objects'][:1]
        self.assertFalse({item['action']: item for item in editor_context(state)['tools']}['connect']['available'])

    def test_context_is_independent_and_prefers_explicit_recent_dialogue(self):
        state = self.state()
        state['recent_dialogue'] = [{'student': 'Current learner words.', 'tutor': 'Current tutor reply.',
                                     'talk_moves': ['revoice', 'ask_for_clarification']}]
        before = deepcopy(state)
        context = build_tutor_context(state, 'Clarify this.', 'message', 'dialogue')
        self.assertEqual(context['recent_dialogue'], state['recent_dialogue'])
        context['current_diagram']['objects'][0]['bbox']['x'] = 999
        context['learner_model']['task']['text'] = 'Mutated copy'
        context['current_issue']['description'] = 'Mutated issue'
        self.assertEqual(state, before)


if __name__ == '__main__':
    unittest.main()
