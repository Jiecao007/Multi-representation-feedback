"""Offline SVG preview of canonical scenes for reconstruction comparison.

No browser or model call. Uses the same coordinate and glyph conventions as the
editor, including original image aspect ratio. This is not browser interaction QA.
"""
import argparse
import html
import json
from pathlib import Path
import subprocess
from schema import validate_sketch


def render(scene,record):
    s=validate_sketch(scene).model_dump();ratio=record['height']/record['width']
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 {1000*ratio}" width="1000" height="{1000*ratio}">',
         '<rect width="100%" height="100%" fill="white"/>',
         '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 1 1 L 9 5 L 1 9" fill="none" stroke="context-stroke" stroke-width="1.8"/></marker></defs>',
         f'<g transform="scale(1 {ratio})" font-family="Arial, sans-serif">']
    def tag(name,attrs,text=None):
        attributes=' '.join(f'{key}="{html.escape(str(value),quote=True)}"' for key,value in attrs.items())
        out.append(f'<{name} {attributes}/>' if text is None else f'<{name} {attributes}>{html.escape(text)}</{name}>')
    def points(ps):return ' '.join(f'{p["x"]},{p["y"]}' for p in ps)
    for r in s['relations']:
        attrs=dict(points=points(r['points']),fill='none',stroke=r['color'] or '#81718e',**{'stroke-width':2})
        if r['direction'] in ('forward','both'):attrs['marker-end']='url(#arrow)'
        if r['direction'] in ('backward','both'):attrs['marker-start']='url(#arrow)'
        tag('polyline',attrs)
        if r['verbatim_text']:tag('text',dict(x=r['label_position']['x'],y=r['label_position']['y'],fill=r['color'] or '#695676',**{'font-size':22}),r['verbatim_text'])
    for o in s['objects']:
        if o['members']:continue
        b=o['bbox'];glyph=o['glyph']
        if glyph and all(g['kind']=='text' for g in glyph):
            lines=(o['verbatim_text'] or '\n'.join(g['text'] for g in glyph)).split('\n')
            physical_height=b['height']*ratio
            font=min(physical_height/(len(lines)*1.2),b['width']/(max(1,*map(len,lines))*.55))
            for i,line in enumerate(lines):tag('text',dict(x=b['x'],y=b['y']*ratio+physical_height/2+(i-(len(lines)-1)/2)*font*1.2,fill=(glyph[min(i,len(glyph)-1)]['color'] or '#43404a'),**{'font-size':font,'dominant-baseline':'middle','transform':f'scale(1 {1/ratio})'}),line)
            continue
        for g in glyph:
            color=g['color'] or '#43404a'
            if g['kind']=='text':
                p=g['points'][0];font=max(1,min(26,b['height']*.36,b['width']*(1000-p['x'])/1000/(max(1,len(g['text']))*.55)))
                tag('text',dict(x=b['x']+p['x']*b['width']/1000,y=b['y']+p['y']*b['height']/1000,fill=color,**{'font-size':font,'dominant-baseline':'hanging'}),g['text']);continue
            out.append(f'<g transform="translate({b["x"]} {b["y"]}) scale({b["width"]/1000} {b["height"]/1000})">')
            attrs=dict(fill=color if g['filled'] else 'none',stroke=color,**{'fill-opacity':.28 if g['filled'] else 1,'stroke-width':1.8,'vector-effect':'non-scaling-stroke','stroke-linejoin':'round','stroke-linecap':'round'})
            if g['kind'] in ('rect','ellipse'):
                a,z=g['points'][:2];x,y=min(a['x'],z['x']),min(a['y'],z['y']);w,h=abs(a['x']-z['x']),abs(a['y']-z['y'])
                attrs.update(dict(x=x,y=y,width=w,height=h) if g['kind']=='rect' else dict(cx=x+w/2,cy=y+h/2,rx=w/2,ry=h/2))
            else:attrs['points']=points(g['points'])
            tag(g['kind'],attrs);out.append('</g>')
    return ''.join(out+['</g></svg>'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('sample');p.add_argument('--png',action='store_true');a=p.parse_args()
    svg=a.run/(a.sample+'.vector-preview.svg')
    svg.write_text(render(json.loads((a.run/(a.sample+'.scene.json')).read_text()),json.loads((a.run/(a.sample+'.input_manifest.json')).read_text())))
    if a.png:subprocess.run(['rsvg-convert',str(svg),'-o',str(svg.with_suffix('.png'))],check=True)
    print(svg)
