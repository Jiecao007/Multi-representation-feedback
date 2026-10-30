"""Portable independent GPT-6 image experiment, with immutable run artifacts."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
import time

from PIL import Image
from schema import Sketch, validate_sketch
from reconstruction import profile, decode

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    from dotenv import load_dotenv
    for path in [HERE/'.env', ROOT/'.env', ROOT/'experiments/sketch_to_interactive/.env']:
        load_dotenv(path, override=False, interpolate=False)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-dir', type=Path, default=ROOT/'data/energy')
    p.add_argument('--images', nargs='+', type=Path, help='Explicit images instead of input-dir')
    p.add_argument('--task-file', type=Path, help='Optional task context, never a reference answer')
    p.add_argument('--question-image',type=Path,help='Optional unsolved task figure, separate from the student response')
    p.add_argument('--question-id',help='Dataset question identifier for provenance')
    p.add_argument('--model', default='gpt-6-astra')
    p.add_argument('--profile', default='fast', choices=['fast','full'])
    p.add_argument('--effort', choices=['low','medium','high','xhigh','max'])
    p.add_argument('--max-output-tokens', type=int)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--prompt', type=Path)
    args = p.parse_args()
    config=profile(args.profile)
    format_=config['format']
    args.effort=args.effort or config['effort']
    args.max_output_tokens=args.max_output_tokens or config['max_output_tokens']
    args.prompt=args.prompt or config['prompt']
    files = args.images or sorted(f for f in args.input_dir.iterdir()
                                  if f.suffix.lower() in {'.png','.jpg','.jpeg','.webp'})
    if not files:
        p.error('No supported images')
    if len({f.stem for f in files}) != len(files):
        p.error('Image filenames must have unique stems')
    if not args.dry_run and not os.getenv('OPENAI_API_KEY'):
        p.error('OPENAI_API_KEY is not configured; no request made')
    context = args.task_file.read_text(encoding='utf-8') if args.task_file else ''
    prompt = args.prompt.read_text(encoding='utf-8')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+('_dry' if args.dry_run else '')
    out = HERE/'results'/run_id
    out.mkdir(parents=True)
    (out/'prompt.md').write_text(prompt, encoding='utf-8')
    save(out/'schema.json', format_.model_json_schema())
    save(out/'run_config.json', dict(run_id=run_id, profile=args.profile,model=args.model, effort=args.effort,
         max_output_tokens=args.max_output_tokens, task_context=context,
         image_detail='original', timeout_seconds=600, automatic_retries=0,
         task_context_provided=bool(context), image_files=[str(f.resolve()) for f in files],
         question_id=args.question_id,question_image=str(args.question_image.resolve()) if args.question_image else None,
         prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(), dry_run=args.dry_run,
         reference_answers_sent=False, caption_labels_sent=False))
    print(f'Run directory: {out}', flush=True)
    client = None
    if not args.dry_run:
        from openai import OpenAI
        client = OpenAI(timeout=600, max_retries=0)
    report=[]
    for file in files:
        data=file.read_bytes()
        with Image.open(file) as im:
            width,height=im.size
        sid=file.stem
        mime=mimetypes.guess_type(file.name)[0] or 'image/png'
        image_url=f'data:{mime};base64,'+base64.b64encode(data).decode()
        record=dict(id=sid, filename=file.name, original_path=str(file.resolve()),
                    width=width,height=height,sha256=hashlib.sha256(data).hexdigest(),
                    task=context or '未提供原始题干或学生口头解释；仅使用图片中的证据。')
        record['question_id']=args.question_id
        question_parts=[]
        if args.question_image:
            qdata=args.question_image.read_bytes()
            qmime=mimetypes.guess_type(args.question_image.name)[0] or 'image/png'
            record['question_image_path']=str(args.question_image.resolve())
            record['question_image_sha256']=hashlib.sha256(qdata).hexdigest()
            question_parts=[dict(type='input_text',text='QUESTION IMAGE — unsolved task figure for context only. Not a student response or a reference answer.'),
                dict(type='input_image',image_url='data:'+qmime+';base64,'+base64.b64encode(qdata).decode(),detail='original')]
        save(out/f'{sid}.input_manifest.json',record)
        text=f'STUDENT DRAWING. Image dimensions: {width} x {height} pixels.\n'
        text+=('TASK CONTEXT:\n'+context) if context else 'No task context or student explanation provided.'
        inputs=[dict(role='user',content=question_parts+[dict(type='input_text',text=text),
                 dict(type='input_image',image_url=image_url,detail='original')])]
        request=dict(model=args.model,instructions=prompt,input=inputs,store=False,
                     reasoning={'effort':args.effort},max_output_tokens=args.max_output_tokens)
        if args.dry_run:
            request['text']={'format':{'type':'json_schema','name':format_.__name__,'strict':True,
                                     'schema':format_.model_json_schema()}}
            save(out/f'{sid}.request.json',request)
            report.append(dict(id=sid,status='dry_run_no_api_call'))
        else:
            print(f'{sid}: requesting {args.model}',flush=True)
            started=time.perf_counter()
            try:
                response=client.responses.parse(**request,text_format=format_)
                api_seconds=round(time.perf_counter()-started,3)
                # SDK generic parsed-output serialization emits spurious type
                # warnings in this version; semantic validation still runs below.
                save(out/f'{sid}.response.json',response.model_dump(mode='json',warnings=False))
                if response.status!='completed' or response.output_parsed is None:
                    raise ValueError(f'No complete structured output: {response.status}')
                if args.profile=='fast':save(out/f'{sid}.compact.json',response.output_parsed.model_dump())
                scene=decode(response.output_parsed,args.profile).model_dump()
                save(out/f'{sid}.scene.json',scene)
                timing=dict(api_seconds=api_seconds,total_seconds=round(time.perf_counter()-started,3))
                save(out/f'{sid}.timing.json',timing)
                report.append(dict(id=sid,status='generated_not_accuracy_certified',model=response.model,
                    profile=args.profile,effort=args.effort,**timing,
                    response_id=response.id,objects=len(scene['objects']),relations=len(scene['relations']),
                    usage=response.usage.model_dump() if response.usage else None))
                print(f'{sid}: {len(scene["objects"])} objects; {len(scene["relations"])} relations',flush=True)
            except Exception as exc:
                error=str(exc).replace(os.getenv('OPENAI_API_KEY','NO_KEY'),'[REDACTED]')
                error=re.sub(r'sk-[A-Za-z0-9_*.-]+','[REDACTED]',error)
                report.append(dict(id=sid,status='failed',total_seconds=round(time.perf_counter()-started,3),error=f'{type(exc).__name__}: {error}'))
                print(f'{sid}: {type(exc).__name__}: {error}',flush=True)
        save(out/'report.json',report)
    # Rendering can also be rerun separately without API calls.
    if not args.dry_run:
        from render import render_run
        render_run(out)
    print(f'Complete: {out}',flush=True)
    return int(any(r['status']=='failed' for r in report))


if __name__=='__main__':
    sys.exit(main())
