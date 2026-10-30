"""Replay the three exported Math case validation failures without model calls.

These regressions use the saved structured responses and their actual routing
contexts, rather than asking a model to reproduce the same wording again.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest


HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'app'))
from legacy_support import feedback as F
from legacy_support import feedback_policy as P
from legacy_support.reply_format import canonical_reply
from legacy_support.visual_feedback import visual_policy
from test_feedback import FakeClient


PARAPHRASE_RUNS = (
    'feedback_turn_3191cc74a0e245ff8eba48a278b8d85f',
    'feedback_turn_6b25fbc387fd40dc984c8db8b4a578cb',
)
RELATION_RUN = 'feedback_turn_0f2a44064ebc4b41b215418680f37502'


def output(path):
    response = json.loads(path.read_text())
    value = next(part['text'] for item in response['output']
                 for part in item.get('content', [])
                 if part.get('type') == 'output_text')
    return json.loads(value)


def historical(run, draft='tutor_rewrite.response.json'):
    folder = HERE / 'app' / 'runs' / run
    context = json.loads((folder / 'tutor_rewrite.input.json').read_text())
    state = deepcopy(context)
    state.update(context['routing_state'])
    # A completed explanation can update state before the writer runs; the
    # routing-state copy in this historical input predates that update.
    state['awaiting_revision_reason'] = context['awaiting_revision_reason']
    state['_current_message'] = context['message']
    state['_teacher_style'] = context['teacher_style']
    state['turns'] = [dict(row, content=row['tutor'])
                      for row in context['dialogue']]
    assessment = F.Assessment(**context['private_assessment'])
    value = output(folder / draft)
    reply = F.TutorReply(**value.get('reply', value))
    reply = canonical_reply(reply, assessment)
    scene = state['committed']['scene']
    ids = {row['id'] for kind in ('objects', 'relations') for row in scene[kind]}
    return state, assessment, reply, ids, context['selected_talk_move']


class HistoricalFeedbackFailures(unittest.TestCase):
    def check_reply(self, state, assessment, reply, ids, move):
        return F.reply_problem(reply, state, assessment, ids, 'message',
                               state['turns'][-1]['content'], move)

    def test_learner_grounded_paraphrases_are_not_new_repair_instructions(self):
        for run in PARAPHRASE_RUNS:
            for draft in ('dialogue.response.json', 'tutor_rewrite.response.json'):
                with self.subTest(run=run, draft=draft):
                    state, assessment, reply, ids, move = historical(run, draft)
                    self.assertFalse(state['edit_enabled'])
                    self.assertTrue(state['awaiting_revision_reason'])
                    self.assertTrue(any(row['trigger'] == 'workspace-complete'
                                        for row in state['turns']))
                    gate = P.thinking_policy(assessment, state,
                                             state['_current_message'], move)
                    self.assertFalse(gate['hint_allowed'])
                    self.assertFalse(gate['repair_instruction_allowed'])
                    self.assertEqual(self.check_reply(state, assessment, reply,
                                                      ids, move), '')
                    self.assertFalse(P.reply_requires_edit(reply, move))
                    self.assertFalse(P.revision_requested(
                        assessment, state, state['_current_message']))
                    self.assertFalse(state['edit_enabled'])

    def test_a_paraphrase_does_not_authorize_an_additional_solution_step(self):
        state, assessment, reply, ids, move = historical(PARAPHRASE_RUNS[0])
        reply.content = (
            'You’ve got the starting point and direction: begin at −6 and move '
            '12 units right. Then draw the final arrow to 2. '
            'What number does that movement land on?')
        self.assertIn('Do not supply a diagram repair instruction',
                      self.check_reply(state, assessment, reply, ids, move))
        self.assertFalse(state['edit_enabled'])

    def test_paraphrase_exception_requires_a_genuine_current_learner_quote(self):
        state, assessment, reply, ids, move = historical(PARAPHRASE_RUNS[0])
        for changes in (
                {'evidence_quote': ''},
                {'evidence_quote': 'begin at -5? then move 12 to the right'},
                {'evidence_source': 'original'}):
            with self.subTest(changes=changes):
                candidate = reply.model_copy(update=changes)
                self.assertFalse(P.learner_action_echo(candidate, state))
                self.assertIn('Do not supply a diagram repair instruction',
                              self.check_reply(state, assessment, candidate,
                                               ids, move))
                self.assertFalse(P.reply_requires_edit(candidate, move))

    def test_paraphrase_exception_cannot_add_or_reinterpret_action_arguments(self):
        state, assessment, reply, ids, move = historical(PARAPHRASE_RUNS[0])
        proposals = (
            'begin at −6 and move 10 units right',
            'begin at −6 and move 12 units left',
            'begin at −6 and move 12 units right to 6',
            'move from 12 to −6 right',
            'begin at −6 and move 12 units right, then move from 12 to −6',
        )
        for proposal in proposals:
            with self.subTest(proposal=proposal):
                candidate = reply.model_copy(update={
                    'content': 'You’ve got the starting point and direction: '
                    + proposal + '. What number does that movement land on?'})
                self.assertFalse(P.learner_action_echo(candidate, state))
                self.assertIn('Do not supply a diagram repair instruction',
                              self.check_reply(state, assessment, candidate,
                                               ids, move))
                self.assertFalse(P.reply_requires_edit(candidate, move))

    def test_generic_relation_echo_preserves_source_target_and_action_count(self):
        state, _, reply, _, move = historical(PARAPHRASE_RUNS[0])
        state['_current_message'] = 'I would connect node1 to node2.'
        reply.evidence_quote = 'connect node1 to node2'
        reply.content = ('You’ve proposed: connect node1 to node2. '
                         'What would that connection represent?')
        self.assertTrue(P.learner_action_echo(reply, state))
        self.assertFalse(P.reply_requires_edit(reply, move))
        for proposal in (
                'connect node1 to node3',
                'connect node2 to node1',
                'connect node1 to node2 and connect node1 to node2'):
            with self.subTest(proposal=proposal):
                reply.content = ('You’ve proposed: ' + proposal
                                 + '. What would that connection represent?')
                self.assertFalse(P.learner_action_echo(reply, state))
                self.assertFalse(P.reply_requires_edit(reply, move))
        self.assertFalse(state['edit_enabled'])

    def test_purpose_adjunct_cannot_hide_an_additional_directive(self):
        state, assessment, reply, ids, move = historical(PARAPHRASE_RUNS[0])
        adjuncts = (
            'for the +12 card, draw the arrow',
            'because you should move 12 units right again',
            'so draw the arrow',
        )
        for adjunct in adjuncts:
            with self.subTest(adjunct=adjunct):
                candidate = reply.model_copy(update={
                    'content': 'You’d start at −6 and move 12 units right '
                    + adjunct + '. What does that movement represent?'})
                self.assertFalse(P.learner_action_echo(candidate, state))
                self.assertIn('Do not supply a diagram repair instruction',
                              self.check_reply(state, assessment, candidate,
                                               ids, move))

    def test_rewritten_accuracy_check_can_show_the_current_submitted_relation(self):
        state, assessment, reply, ids, move = historical(RELATION_RUN)
        self.assertEqual(move, 'press_for_accuracy')
        self.assertIn(assessment.focus_id,
                      {row['id'] for row in state['committed']['scene']['relations']})
        self.assertIn(assessment.focus_id, assessment.solution_target_ids)
        policy = visual_policy(assessment, state, 'message',
                               state['_current_message'], ids, move)
        self.assertIn(assessment.focus_id, policy['allowed_ids'])
        self.assertFalse(policy['solution_cue_allowed'])
        self.assertEqual(self.check_reply(state, assessment, reply, ids, move), '')
        self.assertFalse(P.reply_requires_edit(reply, move))
        self.assertFalse(state['edit_enabled'])

    def test_showing_the_current_relation_does_not_expose_a_future_target(self):
        state, assessment, reply, ids, move = historical(RELATION_RUN)
        scene = state['committed']['scene']
        future = next(row['id'] for row in scene['relations']
                      if row['id'] != assessment.focus_id)
        assessment.solution_target_ids.append(future)
        policy = visual_policy(assessment, state, 'message',
                               state['_current_message'], ids, move)
        self.assertIn(assessment.focus_id, policy['allowed_ids'])
        self.assertNotIn(future, policy['allowed_ids'])
        reply.focus_ids.append(future)
        self.assertIn('protected repair location',
                      self.check_reply(state, assessment, reply, ids, move))
        self.assertFalse(state['edit_enabled'])

    def test_saved_model_outputs_complete_the_real_handler_without_editing(self):
        for run in (*PARAPHRASE_RUNS, RELATION_RUN):
            with self.subTest(run=run), tempfile.TemporaryDirectory() as tmp:
                folder = HERE / 'app' / 'runs' / run
                context = json.loads((folder / 'tutor_rewrite.input.json').read_text())
                state, _, _, _, _ = historical(run)
                initial = json.loads((HERE / 'app' / 'runs' / PARAPHRASE_RUNS[0]
                                      / 'tutor_rewrite.input.json').read_text())['previous_submission']
                state.update(id='historical_replay_' + run, source_id='offline-case',
                             original=deepcopy(initial),
                             assessment=context['previous_assessment'],
                             revision_plan_ids=[], drawing_version=3 if run == RELATION_RUN else 2,
                             question_image=None)
                state['awaiting_revision_reason'] = context['routing_state']['awaiting_revision_reason']
                state['version'] -= 1
                before = deepcopy(state['committed'])
                original_before = deepcopy(state['original'])
                drawing_version = state['drawing_version']
                sequence = [F.FastDialogueTurn(**output(folder / 'dialogue.response.json'))]
                if run == RELATION_RUN:
                    sequence.append(F.TutorReply(**output(folder / 'tutor_rewrite.response.json')))
                client = FakeClient(sequence)
                F.SESSIONS[state['id']] = {'state': state, 'lock': threading.Lock()}
                try:
                    public = F.handle(
                        dict(trigger='message', session_id=state['id'], intent='dialogue',
                             message=context['message']), client, tmp, 'offline-review',
                        fast_dialogue_model='offline-fast')
                    self.assertFalse(public['edit_enabled'])
                    self.assertEqual(public['next_step'], 'explain')
                    self.assertEqual(F.SESSIONS[state['id']]['state']['committed'], before)
                    self.assertEqual(F.SESSIONS[state['id']]['state']['original'], original_before)
                    self.assertEqual(state['original'], original_before)
                    self.assertEqual(state['committed'], before)
                    self.assertEqual(public['drawing_version'], drawing_version)
                    self.assertEqual(public['api_calls'], len(sequence))
                    self.assertEqual(public['version'], context['routing_state']['version'])
                finally:
                    F.SESSIONS.pop(state['id'], None)


if __name__ == '__main__':
    unittest.main()
