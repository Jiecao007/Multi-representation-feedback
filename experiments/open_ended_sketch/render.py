"""Render saved API scenes offline. Does not call any model."""
import argparse
import base64
import html
import hashlib
import json
import mimetypes
from pathlib import Path
from schema import validate_sketch

HERE=Path(__file__).resolve().parent


def embedded(path):
    return 'data:'+(mimetypes.guess_type(path.name)[0] or 'image/png')+';base64,'+base64.b64encode(path.read_bytes()).decode()


def render_run(out):
    out=Path(out)
    report=json.loads((out/'report.json').read_text())
    files=['render.py','viewer.html','viewer.js','graph.js']
    (out/'render_manifest.json').write_text(json.dumps({
        'renderer_files':{f:hashlib.sha256((HERE/f).read_bytes()).hexdigest() for f in files},
        'model_scene_manually_edited':False,
        'visual_glyphs_are_approximations':True,
        'exploration_is_graph_reachability_not_physics':True,
    },indent=2),encoding='utf-8')
    cards=[]
    for item in report:
        sid=item['id']
        if item['status']!='generated_not_accuracy_certified':
            cards.append('<article>'+html.escape(sid+': '+item['status'])+'</article>')
            continue
        scene=validate_sketch(json.loads((out/f'{sid}.scene.json').read_text())).model_dump()
        record=json.loads((out/f'{sid}.input_manifest.json').read_text())
        payload=dict(scene=scene,record=record,original=embedded(Path(record['original_path'])),
                     provenance=item,run_id=out.name)
        data=json.dumps(payload,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
        template=(HERE/'viewer.html').read_text()
        for key,value in [('/*__GRAPH__*/',(HERE/'graph.js').read_text()),
                          ('/*__VIEWER__*/',(HERE/'viewer.js').read_text()),('/*__DATA__*/',data)]:
            template=template.replace(key,value)
        (out/f'{sid}.html').write_text(template,encoding='utf-8')
        cards.append(f'<article><a href="{html.escape(sid)}.html"><img src="{payload["original"]}" alt="原始学生作品"><h2>{html.escape(sid)} · {html.escape(scene["title"])}</h2></a><p>{html.escape(scene["summary"])}</p><p>{len(scene["objects"])} 个对象 · {len(scene["relations"])} 条关系</p></article>')
    page='''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>学生绘图交互实验</title><style>body{max-width:1200px;margin:40px auto;padding:0 24px;background:#f3f5f1;color:#173d37;font:16px/1.7 system-ui}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:24px}article{padding:24px;background:white;border:1px solid #d3dfd8;border-radius:16px}img{width:100%;height:300px;object-fit:contain}h2{font-size:21px}a{color:#176b59}</style><h1>从学生的图，到可探索的对象</h1><p>GPT‑6 独立识别对象与关系；固定编辑器提供拖动、改接、原图核对和路径探索。点击作品进入。</p><p>这是两例可行性实验。沿箭头探索不等同物理模拟，生成成功也不代表保真准确。</p><div class="grid">'''
    (out/'index.html').write_text(page+''.join(cards)+'</div></html>',encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run_dir',type=Path)
    render_run(p.parse_args().run_dir)
