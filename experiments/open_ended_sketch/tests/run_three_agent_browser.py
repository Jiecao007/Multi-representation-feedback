"""Serve the actual application with typed local agent stubs for browser QA."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE / 'app'))
from agent_types import EvaluationResult, TutorTurn


def input_context(kwargs):
    for item in kwargs.get('input', []):
        for part in item.get('content', []):
            if part.get('type') == 'input_text':
                try:
                    return json.loads(part['text'])
                except (ValueError, KeyError):
                    pass
    return {}


def scenes(value):
    if isinstance(value, dict):
        if isinstance(value.get('objects'), list) and isinstance(value.get('relations'), list):
            yield value
        for child in value.values():
            yield from scenes(child)
    elif isinstance(value, list):
        for child in value:
            yield from scenes(child)


class LocalAgents:
    def __init__(self):
        self.responses = self
        self.calls = []
        self.tutor_count = 0
        self.evaluation_count = 0
        self.last_scene = None

    def parse(self, **kwargs):
        contract = kwargs['text_format']
        family = 'TutorTurn' if issubclass(contract, TutorTurn) else contract.__name__
        self.calls.append(dict(contract=contract.__name__, contract_family=family,
                               model=kwargs['model'], input_context=input_context(kwargs)))
        if contract is EvaluationResult:
            self.evaluation_count += 1
            candidates = list(scenes(input_context(kwargs)))
            self.last_scene = max(candidates, key=lambda item: len(item['relations'])) if candidates else None
            revised = self.evaluation_count > 1
            focus = [self.last_scene['relations'][0]['id']] if revised and self.last_scene and self.last_scene['relations'] else ['label_zero']
            value = EvaluationResult(
                learning_goal='Represent the first card as an arrow on the number line.',
                criteria=[dict(criterion='c1', status='established' if revised else 'developing',
                               level='demonstrated' if revised else 'developing',
                               evidence='The first arrow is now drawn.' if revised else 'The number line is drawn without an operation arrow.')],
                strengths=[dict(description='The first card is represented.' if revised else 'Zero is represented.',
                                evidence='The submitted first arrow is visible.' if revised else 'The zero label is visible.', focus_ids=focus)],
                missing_parts=[] if revised else [dict(id='m1', criterion='c1', description='Represent the first card with an arrow.',
                                                      evidence='No operation arrow is present.', focus_ids=['label_zero', 'label_minus6'])],
                uncertainties=[], revision_outcome='successful' if revised else 'not_reviewed',
                revision_evidence='The learner added an arrow for the first card.' if revised else '')
        elif issubclass(contract, TutorTurn):
            self.tutor_count += 1
            turn = self.tutor_count
            value = dict(content='How does zero help you locate the first move?', acknowledgment='',
                         talk_moves=['invite_elaboration_reasoning'], issue_id='m1', stage='thinking-dialogue',
                         focus_ids=['label_zero'], acknowledgment_ids=[], visual_action='highlight', visual_delivery='automatic',
                         mechanism_paths=[], mechanism_condition='', edit_instruction='', next_step='explain',
                         question_target='Represent the first card.', progress='other', memory_updates=[])
            if turn == 1:
                value.update(content='Can you identify zero on your number line?', acknowledgment='Your number line includes zero.',
                             acknowledgment_ids=['label_zero'], talk_moves=['recognize_strengths'], stage='recognition')
            elif turn == 2:
                value.update(content='Which marks on your line show the first card’s change?',
                             talk_moves=['press_for_accuracy'], stage='inquiry')
            elif turn == 3:
                instruction = 'Use ↗ Connect to draw one arrow from 0 to −6, pointing left, to represent the first card.'
                value.update(content=instruction, talk_moves=['provide_hints_guidance'], focus_ids=['label_zero', 'label_minus6'],
                             edit_instruction=instruction, next_step='revise', question_target='')
            elif turn == 4:
                arrow = self.last_scene['relations'][0]['id']
                value.update(content='Do you have any further questions?', acknowledgment='Your new arrow correctly represents the first card.',
                             acknowledgment_ids=[arrow], focus_ids=[arrow], talk_moves=['invite_dialogue'], issue_id='', stage='dialogue',
                             question_target='')
            value = TutorTurn(**value)
        else:
            raise AssertionError('The browser fixture must not invoke another agent contract: ' + contract.__name__)
        return SimpleNamespace(status='completed', output_parsed=value, usage=None,
                               model_dump=lambda **kw: dict(status='completed', output=value.model_dump()))


def main():
    output = ROOT / 'outputs/three_agent_refactor_20261027/browser_qa'
    output.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('three_agent_browser_server', HERE / 'app/server.py')
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    agents = LocalAgents()
    server.client = lambda: agents
    server.ARTIFACTS = output / 'runs'
    server.ARTIFACTS.mkdir(exist_ok=True)
    server.MODEL = 'local-evaluation-stub'
    server.DIALOGUE_MODEL = server.FAST_DIALOGUE_MODEL = 'local-fast-tutor-stub'
    server.feedback.SESSIONS.clear()
    http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
    http.resume_case = None
    threading.Thread(target=http.serve_forever, daemon=True).start()
    node = shutil.which('node') or '/Users/jiecao/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    env = dict(os.environ, THREE_AGENT_BROWSER_URL=f'http://127.0.0.1:{http.server_port}', THREE_AGENT_BROWSER_OUT=str(output))
    try:
        subprocess.run([node, str(HERE / 'tests/test_three_agent_browser.mjs')], cwd=ROOT, env=env, check=True)
        contracts = [row['contract_family'] for row in agents.calls]
        assert contracts == ['EvaluationResult', 'TutorTurn', 'TutorTurn', 'TutorTurn', 'EvaluationResult', 'TutorTurn'], contracts
        assert agents.evaluation_count == 2 and agents.tutor_count == 4
        (output / 'agent_call_trace.json').write_text(json.dumps(agents.calls, ensure_ascii=False, indent=2) + '\n')
        (output / 'backend_receipt.json').write_text(json.dumps(dict(status='passed', actual_model_api_calls=0,
            evaluation_calls=2, tutor_calls=4, transformation_calls=0, contracts=contracts), indent=2) + '\n')
        print('PASS real HTTP/browser flow: initial E+T; ordinary T; modeling hint T; changed diagram E+T; no external model calls.')
    finally:
        http.shutdown()
        http.server_close()


if __name__ == '__main__':
    main()
