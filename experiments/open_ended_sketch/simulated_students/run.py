"""Auditable autonomous learner prototype over the existing feedback/editor APIs.

Uses isolated in-process feedback sessions, never the running browser's session.
Only this directory and the chosen output directory are written.
"""
from __future__ import annotations
import argparse
import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Literal, Optional

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parent
ROOT = EXPERIMENT.parents[1]
sys.path[:0] = [str(EXPERIMENT / 'app'), str(EXPERIMENT)]
from pydantic import BaseModel, ConfigDict
import server as system
from schema import validate_sketch


class Action(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['none', 'begin_revision', 'move', 'reshape_endpoint', 'submit_revision']
    target_id: Optional[str]
    x: Optional[float]
    y: Optional[float]
    endpoint: Optional[Literal['source', 'target']]


class StudentTurn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    utterance: str
    current_understanding: str
    intended_change: str
    action: Action
    request_stop: bool


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def media_url(path):
    return 'data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode()


def locators(scene):
    # Opaque tool locators carry no inferred semantics or circuit graph edges.
    mapping = {f'part_{i:02d}': o['id'] for i, o in enumerate(scene['objects'], 1)}
    mapping.update({f'line_{i:02d}': r['id'] for i, r in enumerate(scene['relations'], 1)})
    return mapping


def visible_drawing(scene):
    mapping = locators(scene)
    reverse = {v: k for k, v in mapping.items()}
    return {
        'coordinate_system': '0–1000 normalized image; y increases downward; move uses bounding-box top-left',
        'parts': [{'locator': reverse[o['id']], 'visible_name': o['label'],
                   'visible_text': o['verbatim_text'], 'bbox': deepcopy(o['bbox'])} for o in scene['objects']],
        'lines': [{'locator': reverse[r['id']], 'visible_text': r['verbatim_text'],
                   'points': deepcopy(r['points']), 'visible_arrow_direction': r['direction']} for r in scene['relations']],
    }


def visible_tutor(reply):
    # Explicit allowlist. No review, criterion, routing focus, diagnosis, or repair targets.
    return {k: reply[k] for k in ('acknowledgment', 'follow_up', 'content', 'learning_goal') if k in reply}


def semantic(scene, action, enabled, dimensions, render_path=None):
    request = {'scene': scene, 'action': action, 'edit_enabled': enabled, 'dimensions': dimensions,
               'render_path': str(render_path) if render_path else None}
    result = subprocess.run(['node', str(HERE / 'student_action.cjs')], input=json.dumps(request),
                            text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError('Semantic editor/render process failed; see its safe error class: ' + result.stderr[:150])
    return json.loads(result.stdout)


class AuditClient:
    """Delegates unchanged API calls and captures returned IDs, never headers/keys."""
    def __init__(self, client):
        self.client = client
        self.responses = self
        self.calls = []

    def parse(self, **kwargs):
        start = time.perf_counter()
        response = self.client.responses.parse(**kwargs)
        self.calls.append({'model_requested': kwargs['model'], 'model_returned': response.model,
                           'response_id': response.id, 'request_id': getattr(response, '_request_id', None),
                           'status': response.status, 'elapsed_seconds': round(time.perf_counter() - start, 3),
                           'usage': response.usage.model_dump() if response.usage else None})
        return response


def tutor(client, request, payload, out):
    start = len(client.calls)
    reply = system.feedback.handle(request, client, out / 'tutor_artifacts', system.MODEL,
        question_image=(payload.get('question') or {}).get('image'), dialogue_model=system.DIALOGUE_MODEL,
        dialogue_effort=system.DIALOGUE_EFFORT, fast_dialogue_model=system.FAST_DIALOGUE_MODEL,
        fast_dialogue_effort=system.FAST_DIALOGUE_EFFORT, engaging_voice=True)
    return reply, deepcopy(client.calls[start:])


def observation(profile, payload, scene, transcript, action_results, enabled, phase, revision_used, changed):
    return {'constructed_profile': profile, 'phase': phase, 'task': payload['record'].get('task', ''),
            'current_visible_drawing': visible_drawing(scene), 'conversation': deepcopy(transcript),
            'previous_action_results': deepcopy(action_results), 'editing_enabled': enabled,
            'draft_has_unsubmitted_changes': changed, 'revision_already_submitted': revision_used,
            'available_tools': ['none'] + (['move', 'reshape_endpoint'] if enabled else ['begin_revision']) +
                               (['submit_revision'] if enabled and changed and not revision_used else []),
            'medium_limitation': 'Semantic scene/editor actions, not physical mouse dragging or a drag-usability test.'}


def report(out, run):
    rows = []
    for turn in run.get('turns', []):
        student = turn['student']
        result = turn.get('action_result', {})
        rows.append('<article><h2>Student decision ' + str(turn['turn']) + '</h2><p><b>Student:</b> ' + html.escape(student['utterance']) +
            '</p><p><b>Understanding:</b> ' + html.escape(student['current_understanding']) + '</p><p><b>Intended change:</b> ' +
            html.escape(student['intended_change']) + '</p><pre>' + html.escape(json.dumps(student['action'], indent=2)) +
            '</pre><p><b>Action result:</b> ' + html.escape(result.get('reason', 'Initial submission.')) +
            (' · ' + html.escape(result.get('outcome', '')) if result else '') + '</p>' +
            ('<p><b>Tutor:</b> ' + html.escape(turn['tutor_visible'].get('content', '')) + '</p>' if turn.get('tutor_visible') else '') +
            '<img src="turn_' + str(turn['turn']).zfill(2) + '_after.png" alt="Actual drawing after this decision"></article>')
    content = '<!doctype html><meta charset="utf-8"><title>Simulated learner prototype log</title><style>body{max-width:1000px;margin:32px auto;font:16px/1.55 system-ui;color:#253044}article{border-top:1px solid #ddd;padding:18px 0}img{max-width:100%;background:white}pre{padding:12px;background:#f4f3f7;white-space:pre-wrap}</style><h1>Autonomous simulated learner · PH007</h1><p>Constructed profile; real initial drawing; real student and tutor model calls. Semantic editor actions, not mouse usability. No claim of population fidelity or learning effectiveness.</p><p>Status: ' + html.escape(run['status']) + '</p>' + ''.join(rows)
    (out / 'transcript.html').write_text(content, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', default='sketchjudge-ph007')
    parser.add_argument('--profile', type=Path, default=HERE / 'profile_ph007.json')
    parser.add_argument('--out', type=Path, default=ROOT / 'outputs/simulated_learners_comments_1020/prototype')
    parser.add_argument('--turns', type=int, default=4, choices=range(1, 6))
    parser.add_argument('--model', default=os.getenv('SIMULATED_STUDENT_MODEL', system.DIALOGUE_MODEL))
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    if (out / 'run.json').exists():
        parser.error('Output already contains a run; choose a fresh --out directory to preserve it.')
    out.mkdir(parents=True, exist_ok=True)
    entry = next((e for e in system.examples() if e['id'] == args.case), None)
    if not entry or entry.get('upload'):
        parser.error('Choose an existing curated example, not an active uploaded student case.')
    payload = system.read_payload(entry)
    profile = json.loads(args.profile.read_text())
    scene = validate_sketch(payload['scene']).model_dump()
    dimensions = {k: payload['record'][k] for k in ('width', 'height')}
    run = {'status': 'dry_run' if args.dry_run else 'running', 'started_at': now(), 'case': args.case,
           'profile': profile, 'maximum_student_decisions': args.turns, 'maximum_revision_submissions': 1,
           'student_model': args.model, 'tutor_config': {'review': system.MODEL, 'dialogue': system.DIALOGUE_MODEL,
                                                       'fast_dialogue': system.FAST_DIALOGUE_MODEL},
           'interaction_medium': 'Same existing feedback.handle and geometry/editor semantic APIs in an isolated process. No running-service session read, resumed, or modified.',
           'initial_scene_sha256': digest(scene), 'turns': [], 'errors': []}
    save(out / 'profile.json', profile)
    save(out / 'initial_scene.json', scene)
    (out / 'student_prompt.md').write_text((HERE / 'student_prompt.md').read_text())
    (out / 'original_student.png').write_bytes(base64.b64decode(payload['original'].split(',', 1)[1]))
    public = observation(profile, payload, scene, [], [], False, 'initial_submission', False, False)
    save(out / 'dry_run_observation.json', public)
    save(out / 'student_output_schema.json', StudentTurn.model_json_schema())
    if args.dry_run:
        save(out / 'run.json', run)
        print(json.dumps({'status': 'dry_run', 'out': str(out), 'api_calls': 0}))
        return
    client = AuditClient(system.client())
    transcript, results, edits = [], [], []
    sid, explanation, enabled, revision_used = '', '', False, False
    committed = deepcopy(scene)
    try:
        for number in range(1, args.turns + 1):
            before = deepcopy(scene)
            semantic(scene, {'kind': 'none'}, enabled, dimensions, out / f'turn_{number:02d}_before.png')
            public = observation(profile, payload, scene, transcript, results, enabled,
                                 'initial_submission' if number == 1 else 'interaction', revision_used, scene != committed)
            save(out / f'turn_{number:02d}_visible_input.json', public)
            content = [{'type': 'input_text', 'text': json.dumps(public, ensure_ascii=False)},
                       {'type': 'input_text', 'text': 'ORIGINAL STUDENT DRAWING (not a reference answer):'},
                       {'type': 'input_image', 'image_url': payload['original'], 'detail': 'original'},
                       {'type': 'input_text', 'text': 'CURRENT LEARNER-VISIBLE DRAWING:'},
                       {'type': 'input_image', 'image_url': media_url(out / f'turn_{number:02d}_before.png'), 'detail': 'original'}]
            start = len(client.calls)
            response = client.parse(model=args.model, instructions=(HERE / 'student_prompt.md').read_text(),
                input=[{'role': 'user', 'content': content}], reasoning={'effort': 'low'}, max_output_tokens=2500,
                store=False, text_format=StudentTurn)
            save(out / f'turn_{number:02d}_student_response.json', response.model_dump(mode='json', warnings=False))
            if response.status != 'completed' or response.output_parsed is None:
                raise RuntimeError('Student model returned an incomplete or unparsed contribution.')
            student = response.output_parsed.model_dump()
            action = student['action']
            event = {'turn': number, 'at': now(), 'visible_input_file': f'turn_{number:02d}_visible_input.json',
                     'visible_input_sha256': digest(public), 'student_api': deepcopy(client.calls[start:]),
                     'student': student, 'before_scene': before}
            run['turns'].append(event)
            transcript.append({'role': 'student', 'content': student['utterance']})
            if number == 1:
                explanation = student['utterance']
                event['action_result'] = {'accepted': action['kind'] == 'none', 'changed': False, 'outcome': 'no_change',
                                         'reason': 'Initial submission accepts no drawing operation.', 'requested_action': action}
                request = {'trigger': 'submission', 'source_id': args.case, 'scene': scene, 'original_scene': scene,
                           'task': payload['record'].get('task', ''), 'goals': [], 'explanation': explanation, 'edits': []}
            else:
                result = {'accepted': True, 'changed': False, 'outcome': 'no_change', 'requested_action': deepcopy(action)}
                kind = action['kind']
                if kind == 'begin_revision':
                    permission = system.feedback.begin_revision({'session_id': sid})
                    enabled = permission['edit_enabled']
                    result['reason'] = 'Existing begin_revision API authorized this isolated session; no drawing change.'
                elif kind in ('move', 'reshape_endpoint'):
                    translated = deepcopy(action)
                    translated['target_id'] = locators(scene).get(action['target_id'], '')
                    applied = semantic(scene, translated, enabled, dimensions)
                    scene = validate_sketch(applied.pop('scene')).model_dump()
                    result.update(applied)
                    if result['accepted'] and result['changed']:
                        edits.append({'kind': 'move' if kind == 'move' else 'resize', 'id': translated['target_id'],
                                      'at': now(), 'detail': deepcopy(action)})
                elif kind == 'submit_revision':
                    if not enabled or revision_used or scene == committed:
                        result.update(accepted=False, reason='Submission rejected: revision must be authorized, changed and not already submitted.')
                    else:
                        result['reason'] = 'Submitting the actual current draft once through workspace-complete.'
                else:
                    result['reason'] = 'Learner chose discussion without an editor operation.'
                event['action_result'] = result
                is_submission = kind == 'submit_revision' and result['accepted']
                request = {'trigger': 'workspace-complete' if is_submission else 'message', 'session_id': sid,
                           'message': student['utterance'], 'intent': 'dialogue'}
                if is_submission:
                    request.update(scene=scene, explanation=explanation, edits=edits, revision_reason=student['utterance'])
                    revision_used = True
                    committed = deepcopy(scene)
            semantic(scene, {'kind': 'none'}, enabled, dimensions, out / f'turn_{number:02d}_after.png')
            event['after_scene'] = deepcopy(scene)
            save(out / f'turn_{number:02d}_before_scene.json', before)
            save(out / f'turn_{number:02d}_after_scene.json', scene)
            results.append(deepcopy(event['action_result']))
            if student['request_stop']:
                event['stop_honored'] = True
                run['status'] = 'learner_requested_stop'
                break
            save(out / f'turn_{number:02d}_tutor_request.json', request)
            reply, calls = tutor(client, request, payload, out)
            sid = reply['session_id']
            enabled = reply['edit_enabled']
            event.update(tutor_api=calls, tutor_visible=visible_tutor(reply), tutor_reply=reply)
            transcript.append({'role': 'tutor', 'content': reply.get('content', '')})
            save(out / 'run.json', run)
            report(out, run)
            print(json.dumps({'turn': number, 'student_action': action['kind'], 'action_outcome': event['action_result']['outcome'],
                              'student_response_id': response.id, 'tutor_calls': len(calls), 'revision_submitted': revision_used}), flush=True)
        if run['status'] == 'running':
            run['status'] = 'budget_completed'
    except Exception as error:
        run['status'] = 'failed'
        # Never serialize exception bodies, request headers or credentials.
        run['errors'].append({'type': type(error).__name__, 'status_code': getattr(error, 'status_code', None), 'at': now()})
        print(json.dumps({'status': 'failed', 'type': type(error).__name__}), flush=True)
    finally:
        run.update(finished_at=now(), isolated_session_id=sid, revision_submitted=revision_used,
                   final_scene_sha256=digest(scene), final_draft_changed=scene != committed,
                   total_model_calls=len(client.calls), all_api_calls=client.calls)
        save(out / 'final_scene.json', scene)
        save(out / 'run.json', run)
        report(out, run)
    if run['status'] == 'failed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
