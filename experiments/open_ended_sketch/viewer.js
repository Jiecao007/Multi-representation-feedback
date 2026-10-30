'use strict';
const payload=JSON.parse(document.getElementById('payload').textContent);
const initial=structuredClone(payload.scene);
const $=id=>document.getElementById(id), NS='http://www.w3.org/2000/svg';
const canvas=$('canvas'), height=1000*payload.record.height/payload.record.width, yScale=height/1000;
let scene=structuredClone(initial), selected=scene.objects[0]?.id??'', history=[], drag=null;
let tracing=false, playing=false, animationId=null, fitted=true, tick=0;
const center=o=>o?({x:o.bbox.x+o.bbox.width/2,y:o.bbox.y+o.bbox.height/2}):null;
const obj=id=>scene.objects.find(o=>o.id===id);
const rel=id=>scene.relations.find(r=>r.id===id);
const current=()=>obj(selected)||rel(selected);
const copy=x=>structuredClone(x);
function el(tag,attrs={},text){const e=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,String(v));if(text!==undefined)e.textContent=text;return e;}
function put(parent,tag,attrs,text){const e=el(tag,attrs,text);parent.append(e);return e;}
function option(value,label){const o=document.createElement('option');o.value=value;o.textContent=label;return o;}
function download(name,data,type='application/json'){const u=URL.createObjectURL(new Blob([data],{type}));const a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}
function snapshot(){history.push(copy(scene));if(history.length>50)history.shift();}
function markEdited(item,operation){item.edits??=[];item.edits.push({operation,at:new Date().toISOString()});}
function initializeAnchors(){for(const r of scene.relations){r._source=center(obj(r.source));r._target=center(obj(r.target));}}
function delta(id,anchor){const c=center(obj(id));return c&&anchor?{x:c.x-anchor.x,y:c.y-anchor.y}:{x:0,y:0};}
function relationPoints(r){const a=delta(r.source,r._source),b=delta(r.target,r._target);return r.points.map((p,i)=>{const t=i/(r.points.length-1);return {x:p.x+(1-t)*a.x+t*b.x,y:p.y+(1-t)*a.y+t*b.y};});}
function labelPosition(r){const a=delta(r.source,r._source),b=delta(r.target,r._target);return{x:r.label_position.x+(a.x+b.x)/2,y:r.label_position.y+(a.y+b.y)/2};}
function exportScene(){const result=copy(scene);for(const r of result.relations){r.points=relationPoints(r);r.label_position=labelPosition(r);delete r._source;delete r._target;}return result;}
function descendants(id,seen=new Set()){if(seen.has(id))return seen;seen.add(id);for(const child of obj(id)?.members??[])descendants(child,seen);return seen;}
function bounds(objects){if(!objects.length)return{x:0,y:0,width:1000,height:1000};const xs=objects.flatMap(o=>[o.bbox.x,o.bbox.x+o.bbox.width]),ys=objects.flatMap(o=>[o.bbox.y,o.bbox.y+o.bbox.height]);const x=Math.min(...xs),y=Math.min(...ys);return{x,y,width:Math.max(...xs)-x,height:Math.max(...ys)-y};}
function updateGroupBounds(){for(let k=0;k<scene.objects.length;k++)for(const o of scene.objects){if(o.members.length)o.bbox=bounds(o.members.map(obj).filter(Boolean));}}
function name(id){return obj(id)?.label||id||'未确定';}
function traceResult(){return tracing?SketchGraph.trace(scene,$('traceStart').value):{nodes:[],edges:[],blocked:[],depth:{}};}
function setView(){const b=fitted?bounds(scene.objects):{x:0,y:0,width:1000,height:1000};const pad=fitted?35:0;canvas.setAttribute('viewBox',`${b.x-pad} ${(b.y-pad)*yScale} ${Math.max(1,b.width+pad*2)} ${Math.max(1,b.height+pad*2)*yScale}`);}

function renderGlyph(g,o){
  const b=o.bbox;
  const purelyText=o.glyph.length>0 && o.glyph.every(s=>s.kind==='text');
  if(purelyText){
    const lines=(o.verbatim_text||o.glyph.map(s=>s.text).join('\n')).split('\n');
    const max=Math.max(1,...lines.map(s=>s.length));
    const font=Math.min(b.height/(lines.length*1.2),b.width/(max*.55));
    lines.forEach((line,i)=>put(g,'text',{x:b.x,y:b.y+b.height/2+(i-(lines.length-1)/2)*font*1.2,'font-size':font,'dominant-baseline':'middle',fill:'#263e36'},line));
    return;
  }
  const local=put(g,'g',{transform:`translate(${b.x} ${b.y}) scale(${b.width/1000} ${b.height/1000})`});
  for(const s of o.glyph){
    const attrs={fill:s.filled?'#263e36':'none',stroke:'#263e36','stroke-width':1.8,'vector-effect':'non-scaling-stroke','stroke-linejoin':'round','stroke-linecap':'round'};
    if(s.kind==='text'){
      const p=s.points[0],available=b.width*(1000-p.x)/1000;
      const font=Math.min(26,b.height*.36,available/(Math.max(1,s.text.length)*.58));
      put(g,'text',{x:b.x+p.x*b.width/1000,y:b.y+p.y*b.height/1000,'font-size':font,'dominant-baseline':'hanging',fill:'#263e36'},s.text);continue;
    }
    if(s.kind==='rect'||s.kind==='ellipse'){
      const a=s.points[0],q=s.points[1],x=Math.min(a.x,q.x),y=Math.min(a.y,q.y),w=Math.abs(q.x-a.x),h=Math.abs(q.y-a.y);
      if(s.kind==='rect')put(local,'rect',{...attrs,x,y,width:w,height:h});
      else put(local,'ellipse',{...attrs,cx:x+w/2,cy:y+h/2,rx:w/2,ry:h/2});
    }else put(local,s.kind,{...attrs,points:s.points.map(p=>p.x+','+p.y).join(' ')});
  }
}

function draw(){
  const trace=traceResult();
  canvas.replaceChildren();setView();
  const defs=put(canvas,'defs');
  const marker=put(defs,'marker',{id:'arrowhead',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:7,markerHeight:7,orient:'auto-start-reverse'});
  put(marker,'path',{d:'M 0 0 L 10 5 L 0 10',fill:'none',stroke:'context-stroke','stroke-width':1.5});
  const root=put(canvas,'g',{id:'sceneRoot',transform:`scale(1 ${yScale})`});
  for(const o of scene.objects.filter(o=>o.members.length)){
    if(!$('groups').checked && selected!==o.id)continue;
    const b=o.bbox,g=put(root,'g',{'data-id':o.id,class:`object ${selected===o.id?'selected':''} ${trace.nodes.includes(o.id)?'traced':''} ${o.enabled===false?'disabled':''}`});
    put(g,'rect',{x:b.x-7,y:b.y-7,width:b.width+14,height:b.height+14,rx:8,fill:'none',stroke:selected===o.id?'#287558':'#bccdc0','stroke-width':1.5,'stroke-dasharray':'6 4','pointer-events':'stroke'});
    put(g,'text',{x:b.x,y:b.y-12,'font-size':12,fill:'#687b74'},o.label+'（分组）');
  }
  for(const r of scene.relations){
    const ps=relationPoints(r),g=put(root,'g',{'data-id':r.id,class:`relation ${selected===r.id?'selected':''} ${r.enabled===false?'disabled':''}`});
    const points=ps.map(p=>p.x+','+p.y).join(' ');
    put(g,'polyline',{points,stroke:'transparent','stroke-width':18,fill:'none','pointer-events':'stroke'});
    const uncertain=!!r.ambiguity||r.origin==='uncertain'||r.confidence<.7;
    const attrs={points,stroke:trace.edges.includes(r.id)?'#268365':'#516c60','stroke-width':trace.edges.includes(r.id)?3:2,fill:'none','stroke-linecap':'round','stroke-linejoin':'round',class:'ink'};
    if(uncertain&&!r.confirmed)attrs['stroke-dasharray']='6 5';
    if(['forward','both'].includes(r.direction))attrs['marker-end']='url(#arrowhead)';
    if(['backward','both'].includes(r.direction))attrs['marker-start']='url(#arrowhead)';
    put(g,'polyline',attrs);
    if(r.verbatim_text){const p=labelPosition(r);put(g,'text',{x:p.x,y:p.y,'font-size':24,fill:'#365848','paint-order':'stroke',stroke:'white','stroke-width':4,'stroke-linejoin':'round'},r.verbatim_text);}
  }
  for(const o of scene.objects.filter(o=>!o.members.length)){
    const b=o.bbox,g=put(root,'g',{'data-id':o.id,class:`object ${selected===o.id?'selected':''} ${o.enabled===false?'disabled':''} ${trace.nodes.includes(o.id)?'traced':''} ${trace.blocked.includes(o.id)?'blocked':''}`});
    put(g,'rect',{x:b.x-5,y:b.y-5,width:b.width+10,height:b.height+10,rx:5,class:'selection-box'});
    const original=initial.objects.find(v=>v.id===o.id);
    if($('viewMode').value==='crop' && original){
      const s=original.bbox,nested=put(g,'svg',{x:b.x,y:b.y,width:b.width,height:b.height,viewBox:`${s.x} ${s.y} ${s.width} ${s.height}`,preserveAspectRatio:'none','pointer-events':'none'});
      put(nested,'image',{href:payload.original,x:0,y:0,width:1000,height:1000,preserveAspectRatio:'none'});
    }else renderGlyph(g,o);
    if($('captions').checked||o.edits?.some(e=>e.operation==='rename'))put(g,'text',{x:b.x,y:b.y+b.height+17,'font-size':12,fill:'#257055','paint-order':'stroke',stroke:'white','stroke-width':3},o.label);
  }
  updateSource();updateTraceStatus(trace);
}

function updateSource(){
  const source=$('source');source.replaceChildren();source.setAttribute('viewBox',`0 0 1000 ${height}`);
  put(source,'image',{href:payload.original,x:0,y:0,width:1000,height,preserveAspectRatio:'none'});
  const original=initial.objects.find(o=>o.id===selected),edge=initial.relations.find(r=>r.id===selected);
  let box=null;
  if(original){box=original.bbox;put(source,'rect',{x:box.x,y:box.y*yScale,width:box.width,height:box.height*yScale,fill:'#72c092','fill-opacity':.13,stroke:'#24734f','stroke-width':4});}
  if(edge){put(source,'polyline',{points:edge.points.map(p=>p.x+','+p.y*yScale).join(' '),fill:'none',stroke:'#ce7b24','stroke-width':6,opacity:.85});const xs=edge.points.map(p=>p.x),ys=edge.points.map(p=>p.y);box={x:Math.min(...xs)-20,y:Math.min(...ys)-20,width:Math.max(...xs)-Math.min(...xs)+40,height:Math.max(...ys)-Math.min(...ys)+40};}
  const crop=$('sourceCrop');crop.replaceChildren();
  if(box){crop.hidden=false;crop.setAttribute('viewBox',`${box.x-6} ${(box.y-6)*yScale} ${box.width+12} ${(box.height+12)*yScale}`);put(crop,'image',{href:payload.original,x:0,y:0,width:1000,height,preserveAspectRatio:'none'});}
  else crop.hidden=true;
}

function updateTraceStatus(trace){
  if(!tracing){$('traceStatus').textContent='选择一个起点，查看学生画出的连接通向哪里。';return;}
  const count=scene.relations.filter(r=>!SketchGraph.eligible(r)&&r.enabled!==false).length;
  const names=trace.nodes.filter(id=>id!==$('traceStart').value).map(name);
  $('traceStatus').textContent=(names.length?'沿当前箭头可到达：'+names.join(' → '):'从当前起点没有可继续到达的对象。')+
    (names.length>1?'\n上面的排列是发现顺序，分支不代表一条连续链。':'')+
    (trace.blocked.length?'\n停用处停止：'+trace.blocked.map(name).join('、'):'')+
    (count?`\n${count} 条关系因端点、低置信或歧义尚未纳入探索。`:'');
}

function refreshMenus(){
  const values=[...scene.objects.map(o=>option(o.id,'对象 · '+o.label)),...scene.relations.map(r=>option(r.id,'关系 · '+(r.verbatim_text||r.id)))];
  $('selection').replaceChildren(...values);if(!current())selected=scene.objects[0]?.id??scene.relations[0]?.id??'';$('selection').value=selected;
  const old=$('traceStart').value;
  $('traceStart').replaceChildren(...scene.objects.map(o=>option(o.id,o.label)));
  if(obj(old))$('traceStart').value=old;
  else{const first=scene.relations.find(r=>SketchGraph.eligible(r)&&SketchGraph.arcs(r).length);if(first)$('traceStart').value=SketchGraph.arcs(first)[0][0];}
  for(const id of ['edgeSource','edgeTarget'])$(id).replaceChildren(option('','未确定'),...scene.objects.map(o=>option(o.id,o.label)));
  $('counts').textContent=`${scene.objects.length} 个对象 · ${scene.relations.length} 条关系`;
  $('undo').disabled=!history.length;
}
function inspector(){
  const item=current(),isObject=!!obj(selected);
  $('emptyInspector').hidden=!!item;$('inspector').hidden=!item;
  if(!item){$('inspectorEvidence').textContent='';$('inspectorAmbiguity').textContent='';$('confidence').textContent='';return;}
  $('editLabel').value=isObject?item.label:item.verbatim_text;
  $('objectEditor').hidden=!isObject;$('relationEditor').hidden=isObject;
  $('enabled').checked=item.enabled!==false;
  if(isObject){$('posX').value=Math.round(item.bbox.x);$('posY').value=Math.round(item.bbox.y);}
  else{$('edgeSource').value=item.source??'';$('edgeTarget').value=item.target??'';$('edgeDirection').value=item.direction;$('confirmed').checked=!!item.confirmed;}
  $('inspectorEvidence').textContent=item.evidence+(isObject?'':'\n解释：'+item.interpretation);
  $('inspectorAmbiguity').textContent=item.ambiguity;
  $('confidence').textContent=item.edits?.some(e=>e.operation==='add')?'编辑者新增项；不属于模型识别结果。':`模型自报置信度 ${Math.round(item.confidence*100)}%（未经校准）`+(item.origin==='uncertain'?' · 推断/不确定项':'');
}
function update(){refreshMenus();inspector();draw();}
function select(id){selected=id;$('selection').value=id;inspector();draw();}
function notify(text){$('editStatus').textContent=text;}
function point(e){const p=canvas.createSVGPoint();p.x=e.clientX;p.y=e.clientY;return p.matrixTransform($('sceneRoot').getScreenCTM().inverse());}
function moveObjects(ids,boxes,dx,dy){
  const values=[...ids].map(id=>boxes[id]);
  dx=Math.max(-Math.min(...values.map(b=>b.x)),Math.min(dx,1000-Math.max(...values.map(b=>b.x+b.width))));
  dy=Math.max(-Math.min(...values.map(b=>b.y)),Math.min(dy,1000-Math.max(...values.map(b=>b.y+b.height))));
  for(const id of ids){obj(id).bbox.x=boxes[id].x+dx;obj(id).bbox.y=boxes[id].y+dy;}
  updateGroupBounds();
}
canvas.addEventListener('pointerdown',e=>{
  const target=e.target.closest('[data-id]');if(!target)return;
  selected=target.dataset.id;
  if(obj(selected)){
    snapshot();const ids=descendants(selected),boxes=Object.fromEntries([...ids].map(id=>[id,copy(obj(id).bbox)]));
    drag={start:point(e),ids,boxes,viewBox:canvas.getAttribute('viewBox')};canvas.setPointerCapture(e.pointerId);
  }
  select(selected);e.preventDefault();
});
canvas.addEventListener('pointermove',e=>{if(!drag)return;const p=point(e);moveObjects(drag.ids,drag.boxes,p.x-drag.start.x,p.y-drag.start.y);draw();canvas.setAttribute('viewBox',drag.viewBox);inspector();});
function endDrag(){if(drag){for(const id of drag.ids)markEdited(obj(id),'move');drag=null;update();}}
canvas.addEventListener('pointerup',endDrag);canvas.addEventListener('pointercancel',endDrag);
$('selection').onchange=()=>select($('selection').value);
$('applyLabel').onclick=()=>{const v=current();if(!v)return;snapshot();if(obj(selected))v.label=$('editLabel').value;else v.verbatim_text=$('editLabel').value;markEdited(v,'rename');update();notify('名称已更新；原始笔迹仍可核对。');};
$('applyPosition').onclick=()=>{const o=obj(selected);if(!o)return;const x=Number($('posX').value),y=Number($('posY').value);if(!Number.isFinite(x)||!Number.isFinite(y))return;snapshot();const ids=descendants(selected),boxes=Object.fromEntries([...ids].map(id=>[id,copy(obj(id).bbox)]));moveObjects(ids,boxes,x-o.bbox.x,y-o.bbox.y);markEdited(o,'move');update();};
$('applyRelation').onclick=()=>{
  const r=rel(selected);if(!r)return;snapshot();
  const old=relationPoints(r);r.source=$('edgeSource').value||null;r.target=$('edgeTarget').value||null;r.direction=$('edgeDirection').value;
  const a=center(obj(r.source))||old[0],b=center(obj(r.target))||old.at(-1);
  r.points=[a,b];r.label_position={x:(a.x+b.x)/2,y:(a.y+b.y)/2-10};r._source=center(obj(r.source));r._target=center(obj(r.target));
  r.confirmed=false;markEdited(r,'reconnect');update();notify('连接已更新。有歧义的解释仍需单独确认。');
};
$('confirmed').onchange=()=>{const r=rel(selected);if(r){snapshot();r.confirmed=$('confirmed').checked;markEdited(r,'confirm_relation');update();}};
$('enabled').onchange=()=>{const item=current();if(!item)return;snapshot();item.enabled=$('enabled').checked;markEdited(item,'toggle_participation');update();};
$('delete').onclick=()=>{
  if(!current())return;snapshot();
  if(obj(selected)){
    const previousPoints=new Map(scene.relations.map(r=>[r.id,relationPoints(r)]));
    const previousLabels=new Map(scene.relations.map(r=>[r.id,labelPosition(r)]));
    scene.objects=scene.objects.filter(o=>o.id!==selected);
    for(const o of scene.objects)o.members=o.members.filter(id=>id!==selected);
    for(const r of scene.relations){if(r.source===selected||r.target===selected){r.label_position=previousLabels.get(r.id);r.points=previousPoints.get(r.id);if(r.source===selected)r.source=null;if(r.target===selected)r.target=null;r._source=center(obj(r.source));r._target=center(obj(r.target));r.ambiguity='编辑者删除了一个端点对象。';r.confirmed=false;}}
    updateGroupBounds();
  }else scene.relations=scene.relations.filter(r=>r.id!==selected);
  selected='';update();
};
$('addObject').onclick=()=>{snapshot();const id='user_object_'+Date.now();scene.objects.push({id,label:$('newLabel').value||'新对象',verbatim_text:$('newLabel').value||'新对象',kind:'user_annotation',bbox:{x:420,y:420,width:180,height:55},glyph:[{kind:'text',points:[{x:0,y:500}],text:$('newLabel').value||'新对象',filled:false}],members:[],origin:'uncertain',confidence:1,evidence:'编辑者新增；不来自学生原图。',ambiguity:'',edits:[{operation:'add',at:new Date().toISOString()}]});selected=id;update();};
$('addRelation').onclick=()=>{if(scene.objects.length<2){notify('至少需要两个对象。');return;}snapshot();const a=obj(selected)||scene.objects[0],b=scene.objects.find(o=>o.id!==a.id);const id='user_relation_'+Date.now(),pa=center(a),pb=center(b);scene.relations.push({id,source:a.id,target:b.id,direction:'forward',points:[pa,pb],verbatim_text:'',label_position:{x:(pa.x+pb.x)/2,y:(pa.y+pb.y)/2},interpretation:'编辑者新增连接',origin:'uncertain',confidence:1,evidence:'编辑者新增；不来自学生原图。',ambiguity:'',confirmed:true,_source:pa,_target:pb,edits:[{operation:'add',at:new Date().toISOString()}]});selected=id;update();};
function stopAnimation(){playing=false;if(animationId)cancelAnimationFrame(animationId);animationId=null;$('animate').textContent='播放路径';canvas.querySelectorAll('.flow-dot').forEach(e=>e.remove());}
function onPolyline(ps,t){const lengths=ps.slice(1).map((p,i)=>Math.hypot(p.x-ps[i].x,p.y-ps[i].y));let d=t*lengths.reduce((a,b)=>a+b,0);for(let i=0;i<lengths.length;i++){if(d<=lengths[i]||i===lengths.length-1){const u=lengths[i]?d/lengths[i]:0;return{x:ps[i].x+(ps[i+1].x-ps[i].x)*u,y:ps[i].y+(ps[i+1].y-ps[i].y)*u};}d-=lengths[i];}return ps[0];}
function animateFrame(time){if(!playing)return;const root=$('sceneRoot'),trace=traceResult();root.querySelectorAll('.flow-dot').forEach(e=>e.remove());for(const r of scene.relations.filter(r=>trace.edges.includes(r.id))){const ps=relationPoints(r);const directions=r.direction==='both'?[1,-1]:[r.direction==='backward'?-1:1];for(const dir of directions){let t=(time/2400)%1;if(dir<0)t=1-t;const p=onPolyline(ps,t);put(root,'circle',{cx:p.x,cy:p.y,r:4,class:'flow-dot'});}}animationId=requestAnimationFrame(animateFrame);}
$('trace').onclick=()=>{tracing=true;draw();};
$('traceStart').onchange=()=>{if(tracing)draw();};
$('animate').onclick=()=>{if(playing){stopAnimation();return;}tracing=true;playing=true;draw();$('animate').textContent='暂停路径';animationId=requestAnimationFrame(animateFrame);};
$('clearTrace').onclick=()=>{stopAnimation();tracing=false;draw();};
$('undo').onclick=()=>{if(!history.length)return;stopAnimation();scene=history.pop();update();};
$('reset').onclick=()=>{stopAnimation();snapshot();scene=copy(initial);initializeAnchors();tracing=false;selected=scene.objects[0]?.id??'';update();notify('已恢复本次 GPT‑6 的原始输出。');};
$('fit').onclick=()=>{fitted=true;draw();};$('full').onclick=()=>{fitted=false;draw();};
for(const id of ['viewMode','captions','groups'])$(id).onchange=draw;
$('export').onclick=()=>download(payload.record.id+'.edited.json',JSON.stringify({scene:exportScene(),source:payload.record,provenance:payload.provenance,exported_at:new Date().toISOString()},null,2));
$('exportSvg').onclick=()=>{const clone=canvas.cloneNode(true);clone.setAttribute('xmlns',NS);clone.setAttribute('width','1000');clone.setAttribute('height',String(Math.round(height)));const style=el('style');style.textContent='.selection-box{fill:none;stroke:none}.flow-dot{display:none}';clone.prepend(style);download(payload.record.id+'.svg',new XMLSerializer().serializeToString(clone),'image/svg+xml');};
$('exportReview').onclick=()=>download(payload.record.id+'.review.json',JSON.stringify({review:$('review').value,scene:exportScene(),source:payload.record,provenance:payload.provenance,date:new Date().toISOString()},null,2));
$('title').textContent=payload.record.id+' · '+scene.title;$('summary').textContent=scene.summary;$('task').textContent=payload.record.task;
for(const [id,values] of [['uncertainties',scene.uncertainties],['omissions',scene.omitted_details],['requirements',scene.simulation_requirements],['suggestions',scene.suggested_interactions]])for(const text of values){const li=document.createElement('li');li.textContent=text;$(id).append(li);}
$('provenance').textContent=`独立 API 实验 · ${payload.provenance.model} · ${payload.provenance.response_id} · ${payload.run_id} · 原图 SHA256 ${payload.record.sha256}`;
initializeAnchors();update();
