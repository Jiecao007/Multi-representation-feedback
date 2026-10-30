"""Current PH_007 uncertainty routing, with local typed model responses only.

These assert the process contract and single-call runtime behavior. They do not
claim that a model-generated question has been evaluated with real learners.
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
from tutor_context import build_tutor_context
from feedback_process import GUIDANCE_POLICY_VERSION, ensure_process, frustration_evidence
from test_three_agent_runtime import FakeClient, context
from test_three_agent_process_recovery import assessment, reply, submission, ISSUE


SCAFFOLD_QUESTION = 'From the right junction, which wire leads toward the switch?'
SECOND_QUESTION = 'Which wire touches both the right junction and the switch?'
GUIDANCE = 'A₂ needs a shared path before the branches split or after they rejoin.'


def support(**changes):
    values = dict(content=SCAFFOLD_QUESTION, talk_moves=['invite_elaboration_reasoning'],
                  stage='thinking-dialogue', focus_ids=['right_junction', 'wire_right_supply', 'switch'],
                  question_target='Trace a wire from the right junction toward the switch.',
                  progress='uncertain')
    values.update(changes)
    return reply(**values)


class UncertaintyScaffoldingTests(unittest.TestCase):
    def setUp(self):
        F.SESSIONS.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def handle(self, data, candidates):
        client = FakeClient(candidates)
        public = F.handle(data, client, self.directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
        return public, client

    def start(self, checked=True):
        first, _ = self.handle(submission(), [assessment(), reply(opening=True)])
        sid = first['session_id']
        if checked:
            self.message(sid, 'Yes, A₁ measures L₁ current.', reply())
        return sid

    def state(self, sid):
        return F.SESSIONS[sid]['state']

    def message(self, sid, text, candidate, **changes):
        data = dict(trigger='message', session_id=sid, message=text)
        data.update(changes)
        return self.handle(data, [candidate])

    def reject(self, sid, text, candidate, **changes):
        before = deepcopy(self.state(sid))
        client = FakeClient([candidate])
        data = dict(trigger='message', session_id=sid, message=text)
        data.update(changes)
        with self.assertRaises(F.FeedbackError):
            F.handle(data, client, self.directory, 'evaluation-model', fast_dialogue_model='fast-tutor')
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(self.state(sid), before)
        return client

    def assert_question_support(self, public, client, sid, before):
        self.assertEqual(public['agents_called'], ['tutor'])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]['model'], 'fast-tutor')
        interaction = context(client.calls[0])['interaction']
        self.assertTrue(interaction['uncertainty_expressed'])
        self.assertEqual(interaction['support_question_scaffold'], 'high')
        self.assertFalse(interaction['help_requested'])
        self.assertNotIn('provide_hints_guidance', interaction['allowed_moves'])
        self.assertNotIn('propose_revision_plan', interaction['allowed_moves'])
        self.assertEqual(interaction['active_issue_id'], ISSUE)
        schema = client.calls[0]['text_format'].model_json_schema()['properties']
        self.assertNotIn('provide_hints_guidance', schema['talk_moves']['items']['enum'])
        self.assertNotIn('propose_revision_plan', schema['talk_moves']['items']['enum'])
        self.assertEqual(schema['stage']['const'], 'thinking-dialogue')
        self.assertEqual(public['stage'], 'thinking-dialogue')
        self.assertEqual(public['content'].count('?'), 1)
        self.assertFalse(public['edit_enabled'])
        self.assertEqual(public['guidance_instruction'], '')
        self.assertEqual(public['next_step'], 'explain')
        self.assertEqual(public['drawing_version'], 1)
        self.assertEqual(self.state(sid)['current_issue_id'], ISSUE)
        self.assertEqual(self.state(sid)['committed'], before['committed'])
        self.assertEqual(self.state(sid)['learner_model'], before['learner_model'])

    def test_recorded_ph007_unknown_gets_one_scaffolded_question_without_evaluation(self):
        sid = self.start()
        self.message(sid, 'I think only L₂’s branch current.',
                     support(content='How does that compare with the total-current requirement?', progress='progress'))
        self.message(sid, 'So I need to move A₂.',
                     support(content='Which path could carry current from both branches?', progress='progress'))
        before = deepcopy(self.state(sid))
        public, client = self.message(sid, "I don't know.", support())
        self.assert_question_support(public, client, sid, before)
        self.assertEqual(public['content'], SCAFFOLD_QUESTION)
        self.assertEqual(self.state(sid)['consecutive_difficulties'], 0)
        self.assertEqual(self.state(sid)['guidance_count'], 0)

    def test_uncertainty_variants_do_not_mean_explicit_help(self):
        for text in ("I don't know.", 'I don’t understand.', 'I am not sure.',
                     "I'm confused.", 'I am stuck.', '我不确定', '我还是不会'):
            with self.subTest(text=text):
                F.SESSIONS.clear()
                sid = self.start()
                before = deepcopy(self.state(sid))
                public, client = self.message(sid, text, support())
                self.assert_question_support(public, client, sid, before)

    def test_uncertainty_after_highlight_enters_support_and_consumes_check_only_on_delivery(self):
        sid = self.start(checked=False)
        self.assertFalse(self.state(sid)['workflow']['check_issued'])
        self.reject(sid, "I don't know.",
                    support(content=GUIDANCE, talk_moves=['provide_hints_guidance'], question_target=''))
        self.assertFalse(self.state(sid)['workflow']['check_issued'])
        public, client = self.message(sid, "I don't know.", support())
        self.assertEqual(context(client.calls[0])['interaction']['process_phase'], 'support')
        self.assertEqual(public['stage'], 'thinking-dialogue')
        self.assertTrue(self.state(sid)['workflow']['check_issued'])
        following, following_client = self.message(sid, 'It leads toward the switch.', support(progress='progress'))
        self.assertEqual(context(following_client.calls[0])['interaction']['process_phase'], 'support')
        self.assertEqual(following['stage'], 'thinking-dialogue')

    def test_first_two_incorrect_answers_get_questions_and_third_gets_guidance(self):
        sid = self.start()
        formal = deepcopy(self.state(sid)['learner_model']['evaluation'])
        for count, question in enumerate((SCAFFOLD_QUESTION, SECOND_QUESTION), 1):
            before = deepcopy(self.state(sid))
            public, client = self.message(sid, 'I am not sure, but A₂ reads both branch currents.',
                                         support(content=question, progress='difficulty'))
            self.assert_question_support(public, client, sid, before)
            self.assertEqual(self.state(sid)['consecutive_difficulties'], count)
        self.reject(sid, 'A₂ reads both branch currents.', support(progress='difficulty'))
        public, client = self.message(sid, 'A₂ reads both branch currents.',
                                     support(content=GUIDANCE, talk_moves=['provide_hints_guidance'],
                                             question_target='', progress='difficulty'))
        self.assertEqual(public['talk_moves'], ['provide_hints_guidance'])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(public['agents_called'], ['tutor'])
        self.assertEqual(self.state(sid)['consecutive_difficulties'], 3)
        self.assertEqual(self.state(sid)['guidance_count'], 1)
        self.assertEqual(self.state(sid)['learner_model']['evaluation'], formal)

    def test_tentative_progress_resets_difficulties_before_the_next_uncertainty(self):
        sid = self.start()
        for text in ('I am not sure, but A₂ reads both branch currents.',
                     'I am not sure, but both currents pass through A₂.'):
            self.message(sid, text, support(progress='difficulty'))
        self.assertEqual(self.state(sid)['consecutive_difficulties'], 2)
        public, client = self.message(sid, 'I am not sure, but L₁ current bypasses A₂.',
                                     support(content='How does that compare with measuring total current?', progress='progress'))
        self.assertEqual(public['talk_moves'], ['invite_elaboration_reasoning'])
        self.assertEqual(self.state(sid)['consecutive_difficulties'], 0)
        before = deepcopy(self.state(sid))
        public, client = self.message(sid, 'I am not sure what comes next.', support())
        self.assert_question_support(public, client, sid, before)
        self.assertEqual(self.state(sid)['consecutive_difficulties'], 0)

    def test_guidance_is_not_an_unconditional_option_in_other_process_phases(self):
        sid = self.start()
        original = deepcopy(self.state(sid))
        for phase in ('support', 'editing', 'revision', 'dialogue'):
            with self.subTest(phase=phase):
                state = deepcopy(original)
                text = 'I can see the wire.'
                if phase == 'editing':
                    state['edit_enabled'] = True
                elif phase == 'revision':
                    text = 'I want to revise A₂.'
                elif phase == 'dialogue':
                    state['workflow'].update(active_issue=None, closing_invited=True)
                    formal = state['learner_model']['evaluation']['result']
                    formal['missing_parts'] = []
                    for criterion in formal['criteria']:
                        criterion.update(status='established', level='demonstrated')
                interaction = build_tutor_context(state, text, 'message', 'dialogue')['interaction']
                self.assertEqual(interaction['process_phase'], phase)
                self.assertNotIn('provide_hints_guidance', interaction['allowed_moves'])

    def test_uncertainty_cannot_deliver_a_statement_or_unlock_edits(self):
        sid = self.start()
        for candidate in (
            support(content='Consider the wire touching the right junction.'),
            support(content=GUIDANCE, talk_moves=['provide_hints_guidance'], question_target=''),
            support(content='Move A₂ to the upper shared wire.', talk_moves=['propose_revision_plan'],
                    stage='revision-planning', edit_instruction='Move A₂ to the upper shared wire.', next_step='revise'),
        ):
            with self.subTest(move=candidate.talk_moves):
                self.reject(sid, 'I am not sure.', candidate)

    def test_uncertainty_does_not_allow_an_unreviewed_issue_switch(self):
        sid = self.start()
        self.reject(sid, "I don't know.", support(issue_id='invented_issue'))

    def test_meaning_then_reflection_then_prior_knowledge_priority_is_retained(self):
        student_quote = 'A₂ measures only L₂ current.'
        established_quote = 'An ammeter measures the current passing through it.'
        cases = (
            ('ask_for_clarification', dict(clarification_need='Identify the wire the student means.'),
             'Which wire do you mean by that one?'),
            ('prompt_reflection', dict(reflection_target='The claimed A₂ reading.',
                                      reflection_evidence=student_quote,
                                      reflection_reference='The requirement to measure total current.',
                                      reflection_reference_source='task_or_observable',
                                      reflection_need='Compare the reading with the required total current.'),
             'Does that reading include the current from both bulbs?'),
            ('build_on_prior_knowledge', dict(prior_knowledge_mode='established',
                                             prior_knowledge_connection='Connect meter reading to a traced current path.',
                                             prior_knowledge_evidence=established_quote),
             'If you follow L₁’s wire, does its current pass through A₂?'),
        )
        for move, evidence, question in cases:
            with self.subTest(move=move):
                F.SESSIONS.clear()
                sid = self.start()
                self.message(sid, student_quote, support(progress='progress'))
                self.message(sid, established_quote, support(progress='progress'))
                public, client = self.message(sid, 'I am not sure.',
                                             support(content=question, talk_moves=[move], move_evidence=evidence))
                self.assertEqual(public['talk_moves'], [move])
                self.assertTrue(context(client.calls[0])['interaction']['uncertainty_expressed'])
                self.assertEqual(public['stage'], 'thinking-dialogue')
                if move == 'prompt_reflection':
                    both = dict(evidence, clarification_need='Identify the wire the student means.')
                    self.reject(sid, 'I am not sure.', support(content=question, talk_moves=[move], move_evidence=both))

    def test_uncertainty_during_formally_uncertain_review_keeps_meaning_priority(self):
        sid = self.start()
        F.begin_revision(dict(session_id=sid))
        changed = deepcopy(self.state(sid)['committed']['scene'])
        changed['objects'][0]['label'] += ' revised'
        candidate = support(content='Which two wires do you intend A₂ to connect?',
                            talk_moves=['ask_for_clarification'],
                            move_evidence=dict(clarification_need='Identify the intended revised A₂ connections.'))
        public, client = self.handle(dict(trigger='workspace-complete', session_id=sid, scene=changed,
                                          explanation='', edits=[], message="I don't know."),
                                     [assessment(revision_outcome='uncertain', revision_evidence='The intended A₂ connections are unclear.'), candidate])
        interaction = context(client.calls[1])['interaction']
        self.assertEqual(interaction['process_phase'], 'review-clarification')
        self.assertTrue(interaction['review_clarification_required'])
        self.assertTrue(interaction['uncertainty_expressed'])
        self.assertEqual(set(interaction['allowed_moves']), {'revoice', 'ask_for_clarification'})
        self.assertEqual(public['talk_moves'], ['ask_for_clarification'])
        self.assertEqual(self.state(sid)['current_issue_id'], ISSUE)
        self.assertEqual(public['agents_called'], ['evaluation', 'tutor'])

    def test_only_button_hint_or_clear_frustration_keep_immediate_guidance(self):
        cases = (
            ('I need a hint.', 'hint'),
            ('This is frustrating.', 'dialogue'),
        )
        for text, intent in cases:
            with self.subTest(text=text, intent=intent):
                F.SESSIONS.clear()
                sid = self.start()
                public, client = self.message(sid, text,
                                             support(content=GUIDANCE, talk_moves=['provide_hints_guidance'], question_target=''),
                                             intent=intent)
                interaction = context(client.calls[0])['interaction']
                self.assertTrue(interaction['help_requested'])
                self.assertEqual(public['talk_moves'], ['provide_hints_guidance'])
                self.assertEqual(len(client.calls), 1)
                self.assertEqual(public['hint_turns_remaining'], 2 if intent == 'hint' else 0)

    def test_chat_help_requests_get_high_scaffold_questions_not_guidance(self):
        for text in ('I need a hint.', "I don't know, please directly tell me.",
                     'Please help me understand.', 'Could you show me a smaller example?',
                     'Can you explain that connection?', 'Can you give me an example?',
                     'Can I get a hint?', 'How do I find where this move ends?'):
            with self.subTest(text=text):
                F.SESSIONS.clear()
                sid = self.start()
                self.reject(sid, text, support(content=GUIDANCE,
                            talk_moves=['provide_hints_guidance'], question_target=''))
                public, client = self.message(sid, text, support())
                interaction = context(client.calls[0])['interaction']
                self.assertTrue(interaction['support_requested'])
                self.assertFalse(interaction['help_requested'])
                self.assertEqual(interaction['support_question_scaffold'], 'high')
                self.assertNotIn('provide_hints_guidance', interaction['allowed_moves'])
                self.assertEqual(public['talk_moves'], ['invite_elaboration_reasoning'])
                self.assertEqual(self.state(sid)['consecutive_difficulties'], 0)

    def test_recorded_chat_requests_do_not_authorize_guidance(self):
        recorded = (
            'I’m not sure how to use +12 to find where I’d land from −6. Could you show me a smaller example?',
            'I’m not sure how the +12 card changes the position from −6. Can you give me a hint about its direction?',
            'The three moves end at 2, but I’m not sure why that makes 2 their sum. Can you explain that link?',
            'I know the next move starts at −6. Could you show me what +12 means on the line? The last replies didn’t come through.',
        )
        for text in recorded:
            with self.subTest(text=text):
                F.SESSIONS.clear()
                sid = self.start()
                public, client = self.message(sid, text, support())
                interaction = context(client.calls[0])['interaction']
                self.assertTrue(interaction['support_requested'])
                self.assertFalse(interaction['frustration_expressed'])
                self.assertFalse(interaction['hint_button_requested'])
                self.assertNotIn('provide_hints_guidance', interaction['allowed_moves'])
                self.assertEqual(interaction['support_question_scaffold'], 'high')

    def test_repeated_uncertainty_does_not_become_three_incorrect_answers(self):
        sid = self.start()
        for _ in range(4):
            self.message(sid, "I still don't know.", support())
            self.assertEqual(self.state(sid)['consecutive_difficulties'], 0)
        self.reject(sid, "I still don't know.", support(progress='difficulty'))
        self.reject(sid, "I still don't know.",
                    support(content=GUIDANCE, talk_moves=['provide_hints_guidance'],
                            question_target='', progress='uncertain'))

    def test_uncertainty_after_two_incorrect_answers_does_not_trigger_guidance(self):
        sid = self.start()
        self.state(sid)['consecutive_difficulties'] = 2
        self.reject(sid, 'I am not sure.',
                    support(content=GUIDANCE, talk_moves=['provide_hints_guidance'], question_target=''))
        public, client = self.message(sid, 'I am not sure.', support())
        self.assertEqual(self.state(sid)['consecutive_difficulties'], 2)
        self.assertEqual(public['talk_moves'], ['invite_elaboration_reasoning'])

    def test_clear_current_frustration_has_exact_evidence_but_does_not_persist(self):
        sid = self.start()
        text = 'This is really frustrating. Please help me.'
        public, client = self.message(sid, text,
                    support(content=GUIDANCE, talk_moves=['provide_hints_guidance'], question_target=''))
        interaction = context(client.calls[0])['interaction']
        self.assertTrue(interaction['frustration_expressed'])
        self.assertEqual(interaction['frustration_evidence'], 'This is really frustrating')
        self.assertIn(interaction['frustration_evidence'], text)
        self.reject(sid, 'Could you show me another example?',
                    support(content=GUIDANCE, talk_moves=['provide_hints_guidance'], question_target=''))
        self.message(sid, 'Could you show me another example?', support())

    def test_negated_quoted_or_reported_frustration_is_not_current_frustration(self):
        for text in ('I am not frustrated.', 'I do not feel frustrated.',
                     "It's not that I'm frustrated.", "I'm not saying I'm frustrated.",
                     'My friend said I am frustrated.', 'If I am frustrated, should I stop?',
                     'The example says “This is frustrating.”',
                     'I am confused.', 'This is too hard.',
                     'The last replies did not come through.'):
            with self.subTest(text=text):
                self.assertEqual(frustration_evidence(text), '')

    def test_old_counter_migration_preserves_workflow_and_historical_state(self):
        sid = self.start()
        old = deepcopy(self.state(sid))
        old.pop('guidance_policy_version')
        old['consecutive_difficulties'] = 2
        old['workflow'].update(review_clarification_pending=True, closing_invited=True)
        before = deepcopy(old)
        prepared, _, _ = F.prepare(old, dict(trigger='message', intent='dialogue',
                                             message='Could you show me a smaller example?'))
        self.assertEqual(old, before)
        self.assertEqual(prepared['workflow'], before['workflow'])
        self.assertEqual(prepared['consecutive_difficulties'], 0)
        self.assertEqual(prepared['guidance_policy_version'], GUIDANCE_POLICY_VERSION)
        self.assertEqual(prepared['guidance_counter_migration']['prior_count'], 2)
        prepared['consecutive_difficulties'] = 1
        ensure_process(prepared)
        self.assertEqual(prepared['consecutive_difficulties'], 1)

    def test_open_editor_does_not_turn_a_help_question_into_guidance_or_a_plan(self):
        sid = self.start()
        F.begin_revision(dict(session_id=sid))
        text = 'I am not sure how to draw it. Could you show me an example?'
        self.reject(sid, text, support(content=GUIDANCE,
                    talk_moves=['provide_hints_guidance'], question_target=''))
        self.reject(sid, text, support(content='Draw the connection on the common path.',
                    talk_moves=['propose_revision_plan'], stage='revision-planning',
                    edit_instruction='Draw the connection on the common path.', next_step='revise'))
        public, client = self.message(sid, text, support())
        self.assertEqual(context(client.calls[0])['interaction']['allowed_stages'], ['thinking-dialogue'])
        self.assertEqual(public['guidance_instruction'], '')

    def test_mixed_revision_request_and_uncertainty_still_gets_a_question(self):
        sid = self.start()
        text = 'I want to revise A₂, but I do not know which wire to use. Please show me.'
        self.reject(sid, text, support(content='Move A₂ to the common path.',
                    talk_moves=['propose_revision_plan'], stage='revision-planning',
                    edit_instruction='Move A₂ to the common path.', next_step='revise'))
        public, client = self.message(sid, text, support())
        interaction = context(client.calls[0])['interaction']
        self.assertTrue(interaction['revision_requested'])
        self.assertEqual(interaction['allowed_stages'], ['thinking-dialogue'])
        self.assertNotIn('propose_revision_plan', interaction['allowed_moves'])
        self.assertFalse(public['edit_enabled'])

    def test_chat_help_during_uncertain_review_keeps_meaning_priority(self):
        sid = self.start()
        self.state(sid)['workflow']['review_clarification_pending'] = True
        candidate = support(content='Which wire do you mean by that path?',
                            talk_moves=['ask_for_clarification'],
                            move_evidence=dict(clarification_need='Identify the intended revised path.'))
        public, client = self.message(sid, 'Could you explain that?', candidate)
        interaction = context(client.calls[0])['interaction']
        self.assertEqual(interaction['process_phase'], 'review-clarification')
        self.assertEqual(set(interaction['allowed_moves']), {'revoice', 'ask_for_clarification'})
        self.assertEqual(public['talk_moves'], ['ask_for_clarification'])

    def test_request_only_or_affect_only_is_not_an_incorrect_answer_but_mixed_attempt_can_be(self):
        for text, intent in (('I need a hint.', 'hint'),
                             ('Can you give me an example?', 'dialogue'),
                             ('Can I get a hint?', 'dialogue'),
                             ('How do I find where this move ends?', 'dialogue'),
                             ('I am frustrated.', 'dialogue')):
            with self.subTest(text=text):
                F.SESSIONS.clear()
                sid = self.start()
                self.reject(sid, text, support(content=GUIDANCE,
                            talk_moves=['provide_hints_guidance'], question_target='', progress='difficulty'),
                            intent=intent)
                self.assertEqual(self.state(sid)['consecutive_difficulties'], 0)
        sid = self.start()
        self.message(sid, 'I think A₂ reads both branch currents. Can you show me an example?',
                     support(progress='difficulty'))
        self.assertEqual(self.state(sid)['consecutive_difficulties'], 1)

    def test_explicit_revision_request_still_receives_a_plan_without_evaluation(self):
        sid = self.start()
        instruction = 'Move A₂ onto the wire from the right junction toward the switch.'
        public, client = self.message(sid, 'I want to revise A₂.',
                                     support(content=instruction, talk_moves=['propose_revision_plan'],
                                             stage='revision-planning', edit_instruction=instruction, next_step='revise'))
        self.assertTrue(context(client.calls[0])['interaction']['revision_requested'])
        self.assertEqual(public['talk_moves'], ['propose_revision_plan'])
        self.assertTrue(public['edit_enabled'])
        self.assertEqual(public['agents_called'], ['tutor'])
        self.assertEqual(len(client.calls), 1)


if __name__ == '__main__':
    unittest.main()
