/* Task-independent editor operations over the existing scene schema. */
(function(root){
const G=typeof module!=='undefined'&&module.exports?require('./geometry.js'):root.DrawingGeometry;
function isText(o){return !!o?.glyph?.length&&o.glyph.every(g=>g.kind==='text');}
function textSize(o,ratio=1){
 const lines=(o.verbatim_text||o.glyph.map(g=>g.text).join('\n')).split('\n');
 return Math.min(o.bbox.height*ratio/(lines.length*1.2),o.bbox.width/(Math.max(1,...lines.map(line=>Array.from(line).length))*.55));
}
function fitText(o,value,{ratio=1,fontSize=textSize(o,ratio),measure}={}){
 const lines=value.split('\n'),b=o.bbox,cy=b.y+b.height/2;
 const widthFor=line=>Math.max(Array.from(line).length*.55,measure?measure(line,1):0);
 // Keep enough width for the shared live/export font-fitting rule as well as
 // actual wide glyphs. The selection halo already supplies drag padding.
 const units=Math.max(1,...lines.map(widthFor)),font=Math.max(.01,Math.min(fontSize,1000/(units+.1),1000*ratio/(lines.length*1.2)));
 b.width=Math.max(8,(units+.1)*font);b.height=Math.max(.01,font*lines.length*1.2/ratio);
 b.x=Math.max(0,Math.min(1000-b.width,b.x));b.y=Math.max(0,Math.min(1000-b.height,cy-b.height/2));
}
function createText(value,id,options={}){
 const ratio=options.ratio||1;
 const o={id,label:value,verbatim_text:value,kind:'student_note',bbox:{x:400,y:450,width:1000,height:45},glyph:[{kind:'text',points:[{x:0,y:500}],text:value,filled:false,color:'#7652b9'}],members:[],origin:'student',confidence:1,evidence:'Student added a note in the workspace.',ambiguity:''};
 fitText(o,value,{...options,fontSize:options.fontSize||37.5*ratio});return o;
}
function editText(o,value,parts={},options={}){
 const pure=isText(o);if(pure)fitText(o,value,options);
 o.label=value;
 if(pure){
  o.verbatim_text=value;o.glyph=[{kind:'text',points:[{x:0,y:500}],text:value,filled:false,color:o.glyph[0]?.color||null}];
 }else{
  for(const[index,text]of Object.entries(parts)){const g=o.glyph[Number(index)];if(g?.kind==='text')g.text=text;}
  if(Object.keys(parts).length)o.verbatim_text=o.glyph.filter(g=>g.kind==='text').map(g=>g.text).join('\n');
 }
}
function remove(scene,id){
 const removed=new Set([id]);
 scene.objects=scene.objects.filter(o=>o.id!==id);
 let changed=true;
 while(changed){changed=false;for(const o of scene.objects){if(!o.members.length)continue;o.members=o.members.filter(child=>!removed.has(child));if(!o.members.length){removed.add(o.id);changed=true;}}
  scene.objects=scene.objects.filter(o=>!removed.has(o.id));
 }
 for(const r of scene.relations)if(removed.has(r.source)||removed.has(r.target))removed.add(r.id);
 scene.relations=scene.relations.filter(r=>!removed.has(r.id));
 // Retain unrelated drawn paths, including unresolved endpoints.
 G.regroup?.(scene);return [...removed];
}
function instantiate(asset,id,center={x:500,y:500}){
 const width=asset.width||160,height=asset.height||160;
 return {id,label:asset.label,verbatim_text:asset.glyph.filter(g=>g.kind==='text').map(g=>g.text).join('\n'),kind:asset.kind||'library_object',bbox:{x:Math.max(0,Math.min(1000-width,center.x-width/2)),y:Math.max(0,Math.min(1000-height,center.y-height/2)),width,height},glyph:G.copy(asset.glyph),members:[],origin:'student',confidence:1,evidence:'Student inserted preloaded asset '+asset.id+'. Its preset marks are library content, not independently authored student evidence.',ambiguity:''};
}
function focus(scene,ids){
 const objects=new Map(scene.objects.map(o=>[o.id,o])),relations=new Map(scene.relations.map(r=>[r.id,r]));
 const expanded=new Set(),missing=[];
 function visit(id){if(expanded.has(id))return;if(objects.has(id)){expanded.add(id);objects.get(id).members.forEach(visit);}else if(relations.has(id))expanded.add(id);else missing.push(id);}
 ids.forEach(visit);
 const boxes=[];for(const id of expanded){if(objects.has(id))boxes.push(objects.get(id));else{const ps=relations.get(id).points;const x=Math.min(...ps.map(p=>p.x)),y=Math.min(...ps.map(p=>p.y));boxes.push({bbox:{x,y,width:Math.max(5,Math.max(...ps.map(p=>p.x))-x),height:Math.max(5,Math.max(...ps.map(p=>p.y))-y)}});}}
 return {ids:[...expanded],missing,bounds:boxes.length?G.bounds(boxes):null};
}
function relationName(scene,r){
 if(r.verbatim_text)return r.verbatim_text;
 const name=id=>scene.objects.find(o=>o.id===id)?.label;
 const a=name(r.source),b=name(r.target);
 if(a&&b)return `Line between ${a} and ${b}`;
 if(a||b)return `Line near ${a||b}`;
 const x=r.points.reduce((a,p)=>a+p.x,0)/r.points.length,y=r.points.reduce((a,p)=>a+p.y,0)/r.points.length;
 return `Unlabeled line (${y<333?'upper':y>667?'lower':'middle'} ${x<333?'left':x>667?'right':'center'})`;
}
function endpointTarget(scene,point,tolerance=6){return scene.objects.filter(o=>{const b=o.bbox;return point.x>=b.x-tolerance&&point.x<=b.x+b.width+tolerance&&point.y>=b.y-tolerance&&point.y<=b.y+b.height+tolerance;}).sort((a,b)=>a.bbox.width*a.bbox.height-b.bbox.width*b.bbox.height)[0]?.id||null;}
function reattach(scene,id,end,original=G.anchors(scene)){const r=scene.relations.find(r=>r.id===id);if(!r||!['source','target'].includes(end))return null;const ps=G.points(scene,r,original),point=end==='source'?ps[0]:ps.at(-1),target=endpointTarget(scene,point);G.attachRelation(scene,id,end,target,original);return target;}
const api={isText,textSize,fitText,createText,editText,remove,instantiate,focus,relationName,endpointTarget,reattach};root.DrawingEditor=api;if(typeof module!=='undefined')module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
