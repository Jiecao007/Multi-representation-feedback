"""Recorded delivery failures from the 2026-10-28 P1–P4 batch.

All 16 original inputs and parsed Tutor outputs live in a self-contained fixture.
Historical replay distinguishes lossless metadata recovery from genuinely missing
content/evidence. Future-contract tests use explicitly constructed local stubs;
they are not new model responses or a rerun of the learner experiment.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from pydantic import ValidationError

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'app'))

import feedback as F
from agent_api import AgentCalls
from agent_types import TutorTurn
from feedback_process import VERSION, validate_process_turn
from interaction_contract import canonical_tutor, validate_tutor
from move_selection import canonical_move_evidence, readiness_sources, validate_move_selection
from tutor_agent import TutorAgent, process_tutor_type
from test_three_agent_runtime import FakeClient, context as call_context
from test_tutor_visual_grounding import initial_data


FIXTURE = json.loads((Path(__file__).parent / 'fixtures/recorded_delivery_20261028/failures.json').read_text())
CASES = {case['id']: case for case in FIXTURE['cases']}
MECHANICAL_IDS = {
    'feedback_turn_79c679d1645341cfbc71a2b63a7c10b2',  # Outer quotation marks.
    'feedback_turn_277c787d1fbc4f07b59ec5aab45bec36',  # Existing learner lines joined.
    'feedback_turn_180b10b0e722479ab31d86da873d4fbc',
    'feedback_turn_65528d6343b64320aba21780c2a94174',
    'feedback_turn_799755086bcf4372be06dbc7789d03e3',
    'feedback_turn_a3ab688aba034095b8adf7a362e22d6b',
    'feedback_turn_d390967d84984a06848ef018ba60f318',  # Five narrated exact quotes.
    'feedback_turn_06bbda716e95412eae3664759a685c0c',  # Praise already in content.
}
PRAISE_IN_CONTENT = 'feedback_turn_06bbda716e95412eae3664759a685c0c'
PRAISE_MISSING = 'feedback_turn_e412d7c00dbc4a939e1f258e43c9841c'


def recorded_context(case):
    context = deepcopy(case['context'])
    for key in ('current_diagram', 'learner_model', 'editor_context'):
        context[key] = deepcopy(FIXTURE['shared'][context[key]['shared_ref']])
    return context


def spoken(turn):
    return ' '.join(value.strip() for value in (turn.acknowledgment, turn.content) if value.strip())


def reconstructed_state(context, sid='recorded-delivery'):
    """Recover session fields visible to the recorded Tutor, without new inference.

    The projected submitted diagram contains all IDs and connectivity required
    here. A message never revalidates or submits this drawing as a new revision.
    """
    state, _, _ = F.prepare(None, initial_data())
    memory = deepcopy(state['learner_model'])
    memory.update(deepcopy(context['learner_model']))
    interaction = context['interaction']
    state.update(
        id=sid, learner_model=memory, task=memory['task']['text'],
        criteria=deepcopy(memory['task']['criteria']),
        goals_configured=interaction['goals_configured'],
        source_id=memory['task']['source_id'],
        committed=dict(scene=deepcopy(context['current_diagram']),
                       explanation=context['latest_explanation'], edits=[]),
        drawing_version=memory['drawing_version'], stage=interaction['stage'],
        current_issue_id=interaction['active_issue_id'],
        edit_enabled=interaction['edit_enabled'],
        hint_turns_remaining=interaction['hint_turns_remaining'],
        hint_request_pending=bool(interaction['hint_turns_remaining']),
        consecutive_difficulties=interaction['consecutive_difficulties'],
        guidance_count=interaction['guidance_count'],
        recent_dialogue=deepcopy(context['recent_dialogue']),
        turns=[dict(student=row['student'], content=row['tutor'],
                    talk_moves=row.get('talk_moves', [])) for row in context['recent_dialogue']],
        workflow=dict(version=VERSION, active_issue=deepcopy(context['current_issue']),
                      check_issued=not interaction['check_required'],
                      review_clarification_pending=interaction['review_clarification_required'],
                      closing_invited=interaction['closing_invited'], finished=False,
                      review_outcome=interaction['review_outcome'],
                      review_evidence=interaction['review_evidence']),
    )
    return state


def normalize_and_check(raw, context, state=None):
    state = reconstructed_state(context) if state is None else state
    turn = canonical_move_evidence(raw, context)
    turn = canonical_tutor(turn, state, process=context['interaction'])
    problem = (validate_tutor(turn, state)
               or validate_move_selection(turn, context)
               or validate_process_turn(turn, state, context))
    return turn, problem


class RecordedDeliveryFailuresTests(unittest.TestCase):
    def setUp(self):
        F.SESSIONS.clear()

    def test_all_recorded_failures_distinguish_lossless_recovery_from_missing_evidence(self):
        self.assertEqual(len(CASES), 16)
        recovered, rejected = [], []
        for key, case in CASES.items():
            with self.subTest(recorded_run=key):
                context = recorded_context(case)
                before = deepcopy(context)
                raw = TutorTurn.model_validate(deepcopy(case['raw_tutor']))
                raw_before = raw.model_dump()
                result, problem = normalize_and_check(raw, context)
                self.assertEqual(spoken(result), spoken(raw))
                self.assertEqual(raw.model_dump(), raw_before)
                self.assertEqual(context, before)
                if key in MECHANICAL_IDS:
                    self.assertEqual(problem, '')
                    recovered.append(key)
                else:
                    self.assertTrue(problem)
                    self.assertEqual(problem, case['historical_error'])
                    rejected.append(key)
        self.assertEqual(len(recovered), 8)
        self.assertEqual(len(rejected), 8)

    def test_existing_review_praise_moves_fields_without_changing_visible_reply(self):
        case = CASES[PRAISE_IN_CONTENT]
        context = recorded_context(case)
        raw = TutorTurn.model_validate(case['raw_tutor'])
        result, problem = normalize_and_check(raw, context)
        self.assertEqual(problem, '')
        self.assertEqual(result.acknowledgment, 'Nice work completing your number-line model!')
        self.assertEqual(result.content, 'What would you like to discuss?')
        self.assertEqual(spoken(result), spoken(raw))

    def test_genuinely_missing_review_praise_is_not_invented(self):
        case = CASES[PRAISE_MISSING]
        raw = TutorTurn.model_validate(case['raw_tutor'])
        result, problem = normalize_and_check(raw, recorded_context(case))
        self.assertEqual(result.acknowledgment, '')
        self.assertEqual(result.content, raw.content)
        self.assertEqual(problem, case['historical_error'])

    def test_new_contract_selects_actual_learner_source_in_one_tutor_call(self):
        # These are constructed future-contract stubs, not repairs claimed as
        # having been present in the historical model outputs.
        for key, case in CASES.items():
            if case['raw_tutor']['talk_moves'] != ['propose_revision_plan']:
                continue
            with self.subTest(recorded_context=key), tempfile.TemporaryDirectory() as directory:
                context = recorded_context(case)
                state = reconstructed_state(context, sid='stub-' + key)
                before = deepcopy(state)
                source_id = next(name for name, text in readiness_sources(context).items()
                                 if text == context['student_message'])
                value = deepcopy(case['raw_tutor'])
                value['move_evidence'].update(readiness_source_id=source_id, readiness_evidence='')
                client = FakeClient([TutorTurn.model_validate(value)])
                F.SESSIONS[state['id']] = dict(lock=threading.Lock(), state=state)
                public = F.handle(dict(trigger='message', session_id=state['id'],
                                       message=context['student_message']),
                                  client, directory, 'local-evaluation', fast_dialogue_model='local-fast-tutor')
                self.assertEqual(len(client.calls), 1)
                self.assertEqual(public['agents_called'], ['tutor'])
                self.assertFalse(public['evaluation_updated'])
                self.assertEqual(public['drawing_version'], before['drawing_version'])
                self.assertEqual(F.SESSIONS[state['id']]['state']['committed'], before['committed'])
                self.assertEqual(F.SESSIONS[state['id']]['state']['learner_model']['evaluation'],
                                 before['learner_model']['evaluation'])
                self.assertEqual(public['content'], spoken(TutorTurn.model_validate(value)))
                actual = call_context(client.calls[0])
                self.assertIn(source_id, actual['revision_readiness_sources'])
                self.assertEqual(readiness_sources(actual)[source_id], context['student_message'])

    def test_unknown_source_id_is_rejected_by_dynamic_schema_and_runtime(self):
        case = CASES['feedback_turn_180b10b0e722479ab31d86da873d4fbc']
        context = recorded_context(case)
        value = deepcopy(case['raw_tutor'])
        value['move_evidence'].update(readiness_source_id='teacher-message', readiness_evidence='')
        with self.assertRaises(ValidationError):
            process_tutor_type(context).model_validate(value)
        candidate = TutorTurn.model_validate(value)
        self.assertTrue(validate_move_selection(candidate, context))
        poisoned = deepcopy(context)
        poisoned['revision_readiness_sources'] = ['teacher-message']
        self.assertNotIn('teacher-message', readiness_sources(poisoned))
        with self.assertRaises(ValidationError):
            process_tutor_type(poisoned).model_validate(value)

    def test_task_teacher_agreement_and_uncertainty_cannot_supply_readiness(self):
        base = recorded_context(CASES['feedback_turn_180b10b0e722479ab31d86da873d4fbc'])
        for message in ('Yes.', "I don't know.", 'Maybe.'):
            with self.subTest(message=message):
                context = deepcopy(base)
                context.update(student_message=message, latest_explanation='', recent_dialogue=[
                    dict(student='Okay.', tutor='The sum is 2.', talk_moves=['provide_hints_guidance'])])
                context['learner_model']['observations'] = []
                context['learner_model']['task']['text'] = 'The sum is 2.'
                self.assertEqual(readiness_sources(context), {})
                value = deepcopy(CASES['feedback_turn_180b10b0e722479ab31d86da873d4fbc']['raw_tutor'])
                value['move_evidence'].update(readiness_source_id='', readiness_evidence='The sum is 2.')
                result, problem = normalize_and_check(TutorTurn.model_validate(value), context)
                self.assertTrue(problem)
                self.assertEqual(result.move_evidence.readiness_evidence, 'The sum is 2.')

    def test_new_successful_review_contract_requires_praise_and_delivers_one_call(self):
        for key in (PRAISE_IN_CONTENT, PRAISE_MISSING):
            case = CASES[key]
            context = recorded_context(case)
            value = deepcopy(case['raw_tutor'])
            with self.subTest(recorded_context=key), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValidationError):
                    process_tutor_type(context).model_validate(value)
                # A new, explicitly constructed compliant stub. The historical
                # e412... response is still missing praise and remains rejected.
                value['acknowledgment'] = 'Nice revision: your submitted path now shows the three card moves!'
                if key == PRAISE_IN_CONTENT:
                    value['content'] = 'What would you like to discuss?'
                contract = process_tutor_type(context)
                valid = contract.model_validate(value)
                client = FakeClient([valid])
                calls = AgentCalls(client, directory)
                reply = TutorAgent(calls, 'local-fast-tutor').respond(context)
                result, problem = normalize_and_check(reply, context)
                self.assertEqual(problem, '')
                self.assertEqual(len(client.calls), 1)
                self.assertEqual([row['stage'] for row in calls.records], ['tutor'])
                self.assertEqual(result.acknowledgment, value['acknowledgment'])

    def test_grounded_readiness_cannot_override_wrong_issue_or_phase(self):
        case = CASES['feedback_turn_180b10b0e722479ab31d86da873d4fbc']
        context = recorded_context(case)
        source_id = next(name for name, text in readiness_sources(context).items()
                         if text == context['student_message'])
        value = deepcopy(case['raw_tutor'])
        value['move_evidence'].update(readiness_source_id=source_id, readiness_evidence='')
        for change in ('issue', 'phase'):
            with self.subTest(change=change):
                candidate = TutorTurn.model_validate(value)
                ctx = deepcopy(context)
                if change == 'issue':
                    candidate.issue_id = 'unrelated-gap'
                else:
                    ctx['interaction'].update(process_phase='check', expected_stage='inquiry',
                                              allowed_moves=['press_for_accuracy'], allowed_stages=['inquiry'])
                _, problem = normalize_and_check(candidate, ctx)
                self.assertTrue(problem)

    def test_actual_handle_recovers_seven_recorded_readiness_replies_once(self):
        for key in sorted(MECHANICAL_IDS - {PRAISE_IN_CONTENT}):
            case = CASES[key]
            with self.subTest(recorded_run=key), tempfile.TemporaryDirectory() as directory:
                context = recorded_context(case)
                state = reconstructed_state(context, sid='original-' + key)
                before = deepcopy(state)
                raw = TutorTurn.model_validate(deepcopy(case['raw_tutor']))
                original = raw.model_dump()
                client = FakeClient([raw])
                F.SESSIONS[state['id']] = dict(lock=threading.Lock(), state=state)
                public = F.handle(dict(trigger='message', session_id=state['id'],
                                       message=context['student_message']),
                                  client, directory, 'local-evaluation', fast_dialogue_model='local-fast-tutor')
                self.assertEqual(len(client.calls), 1)
                self.assertEqual(public['agents_called'], ['tutor'])
                self.assertEqual(public['content'], spoken(raw))
                self.assertEqual(raw.model_dump(), original)
                self.assertFalse(public['evaluation_updated'])
                after = F.SESSIONS[state['id']]['state']
                self.assertEqual(after['drawing_version'], before['drawing_version'])
                self.assertEqual(after['committed'], before['committed'])
                self.assertEqual(after['learner_model']['evaluation'], before['learner_model']['evaluation'])
                folder = next(Path(directory).glob('feedback_turn_*'))
                correction = json.loads((folder / 'canonicalization.json').read_text())
                self.assertIn('move_evidence', [row['field'] for row in correction['changes']])
                self.assertFalse((folder / 'validation.json').exists())

    def test_long_source_reference_does_not_relax_legacy_quote_limit(self):
        case = CASES['feedback_turn_180b10b0e722479ab31d86da873d4fbc']
        context = recorded_context(case)
        long_source = ('I start at zero and draw a leftward arrow to minus six, then move '
                       'twelve units right to six, and finally move four units left to two.')
        self.assertGreater(len(long_source.split()), 25)
        context.update(student_message=long_source, latest_explanation='', recent_dialogue=[])
        context['learner_model']['observations'] = []
        self.assertEqual(readiness_sources(context), {'student_message': long_source})
        value = deepcopy(case['raw_tutor'])
        value['move_evidence'].update(readiness_source_id='student_message', readiness_evidence='')
        process_tutor_type(context).model_validate(value)
        self.assertEqual(validate_move_selection(TutorTurn.model_validate(value), context), '')
        value['move_evidence'].update(readiness_source_id='', readiness_evidence=long_source)
        canonical = canonical_move_evidence(TutorTurn.model_validate(value), context)
        self.assertTrue(validate_move_selection(canonical, context))
        self.assertEqual(canonical.move_evidence.readiness_evidence, long_source)

    def test_explicit_source_id_does_not_fall_back_to_legacy_quote(self):
        case = CASES['feedback_turn_180b10b0e722479ab31d86da873d4fbc']
        context = recorded_context(case)
        for source_id in ('unknown-source', 'student_message'):
            with self.subTest(source_id=source_id):
                value = deepcopy(case['raw_tutor'])
                value['move_evidence'].update(readiness_source_id=source_id,
                                              readiness_evidence=context['student_message'])
                candidate = canonical_move_evidence(TutorTurn.model_validate(value), context)
                self.assertTrue(validate_move_selection(candidate, context))
                self.assertEqual(candidate.move_evidence.readiness_source_id, source_id)
                self.assertEqual(candidate.move_evidence.readiness_evidence, context['student_message'])

    def test_praise_relocation_requires_a_new_successful_review(self):
        case = CASES[PRAISE_IN_CONTENT]
        base = recorded_context(case)
        raw = TutorTurn.model_validate(case['raw_tutor'])
        for updates in (dict(new_review=False), dict(review_outcome='unsuccessful')):
            with self.subTest(updates=updates):
                context = deepcopy(base)
                context['interaction'].update(updates)
                result = canonical_tutor(raw, reconstructed_state(context), process=context['interaction'])
                self.assertEqual(result.acknowledgment, '')
                self.assertEqual(result.content, raw.content)
        neutral = raw.model_copy(update={'content': 'Your path has three arrows. What would you like to discuss?'})
        result = canonical_tutor(neutral, reconstructed_state(base), process=base['interaction'])
        self.assertEqual(result.acknowledgment, '')
        self.assertEqual(result.content, neutral.content)


if __name__ == '__main__':
    unittest.main()
