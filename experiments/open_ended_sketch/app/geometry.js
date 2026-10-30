/* Pure drawing operations; no domain vocabulary or inferred physical solver. */
(function(root){
const copy=x=>JSON.parse(JSON.stringify(x));
const center=o=>o?{x:o.bbox.x+o.bbox.width/2,y:o.bbox.y+o.bbox.height/2}:null;
function bounds(objects){if(!objects.length)return{x:0,y:0,width:1000,height:1000};const xs=objects.flatMap(o=>[o.bbox.x,o.bbox.x+o.bbox.width]),ys=objects.flatMap(o=>[o.bbox.y,o.bbox.y+o.bbox.height]);return{x:Math.min(...xs),y:Math.min(...ys),width:Math.max(...xs)-Math.min(...xs),height:Math.max(...ys)-Math.min(...ys)};}
function anchors(scene){return Object.fromEntries(scene.objects.map(o=>[o.id,center(o)]));}
function endpointDelta(scene,id,original={}){const a=original[id],b=center(scene.objects.find(o=>o.id===id));return a&&b?{x:b.x-a.x,y:b.y-a.y}:{x:0,y:0};}
function points(scene,r,original={}){const a=endpointDelta(scene,r.source,original),b=endpointDelta(scene,r.target,original),ps=r.points.map((p,i)=>{const t=i/Math.max(1,r.points.length-1);return{x:p.x+a.x*(1-t)+b.x*t,y:p.y+a.y*(1-t)+b.y*t}});return connectionShape(r.points)==='curved'?connectionPoints(ps[0],ps.at(-1),'curved',curveControl(ps)):ps;}
const clampPoint=p=>({x:Math.max(0,Math.min(1000,p.x)),y:Math.max(0,Math.min(1000,p.y))});
function curveControl(ps){const a=ps[0],b=ps.at(-1),m=ps[12];return{x:2*m.x-(a.x+b.x)/2,y:2*m.y-(a.y+b.y)/2};}
function connectionPoints(a,b,shape='straight',control){
 a=clampPoint(a);b=clampPoint(b);if(shape==='straight')return[a,b];
 if(!['curved','bent'].includes(shape))throw new Error('Unknown connection shape');
 const dx=b.x-a.x,dy=b.y-a.y,length=Math.hypot(dx,dy),offset=Math.min(100,Math.max(35,length*.3));
 const c=clampPoint(control||{x:(a.x+b.x)/2-(length?dy/length:0)*offset,y:(a.y+b.y)/2+(length?dx/length:1)*offset});
 if(shape==='bent')return[a,c,b];
 return Array.from({length:25},(_,i)=>{const t=i/24,u=1-t;return{x:u*u*a.x+2*u*t*c.x+t*t*b.x,y:u*u*a.y+2*u*t*c.y+t*t*b.y};});
}
function connectionShape(ps){
 if(ps.length===2)return'straight';
 if(ps.length===25){const a=ps[0],b=ps.at(-1),c=curveControl(ps);if(ps.every((p,i)=>{const t=i/24,u=1-t;return Math.hypot(p.x-(u*u*a.x+2*u*t*c.x+t*t*b.x),p.y-(u*u*a.y+2*u*t*c.y+t*t*b.y))<.001;}))return'curved';}
 return'bent';
}
function relationControls(scene,relation,original=anchors(scene)){
 const r=typeof relation==='string'?scene.relations.find(r=>r.id===relation):relation;if(!r?.points?.length)return[];
 const ps=points(scene,r,original),shape=connectionShape(ps);
 if(shape==='curved')return[{index:0,kind:'curve',point:ps[12]}];
 return ps.slice(1,-1).map((point,i)=>({index:i+1,kind:'bend',point}));
}
function reshapeRelationControl(scene,id,index,x,y,original=anchors(scene)){
 const r=scene.relations.find(r=>r.id===id);if(!r||!Number.isFinite(x)||!Number.isFinite(y))return false;
 const handle=relationControls(scene,r,original).find(h=>h.index===index);if(!handle)return false;
 const p=clampPoint({x,y});if(Math.hypot(p.x-handle.point.x,p.y-handle.point.y)<.00001)return false;
 const geometry=relationGeometry(scene,r,original);
 if(handle.kind==='curve'){const a=geometry.points[0],b=geometry.points.at(-1);geometry.points=connectionPoints(a,b,'curved',{x:2*p.x-(a.x+b.x)/2,y:2*p.y-(a.y+b.y)/2});}
 else geometry.points[index]=p;
 const moved=handle.kind==='curve'?geometry.points[12]:p,weight=handle.kind==='curve'?1:.5;
 geometry.label.x+=(moved.x-handle.point.x)*weight;geometry.label.y+=(moved.y-handle.point.y)*weight;
 writeRelation(scene,r,geometry,original);return true;
}
function relationBounds(scene,relation,original=anchors(scene)){const r=typeof relation==='string'?scene.relations.find(r=>r.id===relation):relation;if(!r?.points.length)return null;const ps=points(scene,r,original),xs=ps.map(p=>p.x),ys=ps.map(p=>p.y);return{x:Math.min(...xs),y:Math.min(...ys),width:Math.max(...xs)-Math.min(...xs),height:Math.max(...ys)-Math.min(...ys)};}
function relationGeometry(scene,r,original){const ps=points(scene,r,original),a=ps[0],b=ps.at(-1),oa=r.points[0],ob=r.points.at(-1);return{points:ps,label:{x:r.label_position.x+(a.x-oa.x+b.x-ob.x)/2,y:r.label_position.y+(a.y-oa.y+b.y-ob.y)/2}};}
function writeRelation(scene,r,geometry,original){const a=endpointDelta(scene,r.source,original),b=endpointDelta(scene,r.target,original);r.points=geometry.points.map((p,i)=>{const t=i/Math.max(1,geometry.points.length-1);return{x:p.x-a.x*(1-t)-b.x*t,y:p.y-a.y*(1-t)-b.y*t}});r.label_position={x:Math.max(0,Math.min(1000,geometry.label.x))-(a.x+b.x)/2,y:Math.max(0,Math.min(1000,geometry.label.y))-(a.y+b.y)/2};}
function moveRelation(scene,id,x,y,original=anchors(scene)){const r=scene.relations.find(r=>r.id===id),b=relationBounds(scene,r,original);if(!r||!b||!Number.isFinite(x)||!Number.isFinite(y))return false;const dx=Math.max(0,Math.min(1000-b.width,x))-b.x,dy=Math.max(0,Math.min(1000-b.height,y))-b.y;if(!dx&&!dy)return false;const geometry=relationGeometry(scene,r,original);geometry.points=geometry.points.map(p=>({x:p.x+dx,y:p.y+dy}));geometry.label.x+=dx;geometry.label.y+=dy;r.source=null;r.target=null;writeRelation(scene,r,geometry,original);return true;}
function resizeRelation(scene,id,factor,original=anchors(scene)){const r=scene.relations.find(r=>r.id===id),b=relationBounds(scene,r,original);if(!r||!b||!Number.isFinite(factor)||factor<=0||!Math.max(b.width,b.height))return false;const c={x:b.x+b.width/2,y:b.y+b.height/2},limit=Math.min(b.width?2*Math.min(c.x,1000-c.x)/b.width:Infinity,b.height?2*Math.min(c.y,1000-c.y)/b.height:Infinity),scale=Math.min(limit,Math.max(8/Math.max(b.width,b.height),factor));if(scale===1||scale<=0)return false;const geometry=relationGeometry(scene,r,original),transform=p=>({x:c.x+(p.x-c.x)*scale,y:c.y+(p.y-c.y)*scale});geometry.points=geometry.points.map(transform);geometry.label=transform(geometry.label);r.source=null;r.target=null;writeRelation(scene,r,geometry,original);return true;}
function reshapeRelation(scene,id,end,x,y,original=anchors(scene)){const r=scene.relations.find(r=>r.id===id);if(!r||!['source','target'].includes(end)||!Number.isFinite(x)||!Number.isFinite(y))return false;const geometry=relationGeometry(scene,r,original),old=end==='source'?geometry.points[0]:geometry.points.at(-1),dx=Math.max(0,Math.min(1000,x))-old.x,dy=Math.max(0,Math.min(1000,y))-old.y;if(!dx&&!dy)return false;const control=connectionShape(geometry.points)==='curved'?curveControl(geometry.points):null;geometry.points=geometry.points.map((p,i)=>{const t=i/Math.max(1,geometry.points.length-1),weight=end==='source'?1-t:t;return{x:Math.max(0,Math.min(1000,p.x+dx*weight)),y:Math.max(0,Math.min(1000,p.y+dy*weight))}});if(control)geometry.points=connectionPoints(geometry.points[0],geometry.points.at(-1),'curved',{x:control.x+dx/2,y:control.y+dy/2});geometry.label.x+=dx/2;geometry.label.y+=dy/2;r[end]=null;writeRelation(scene,r,geometry,original);return true;}
function attachRelation(scene,id,end,objectId,original=anchors(scene)){const r=scene.relations.find(r=>r.id===id),o=scene.objects.find(o=>o.id===objectId);if(!r||!['source','target'].includes(end)||(objectId&&!o))return false;const geometry=relationGeometry(scene,r,original);r[end]=o?.id||null;if(o&&!original[o.id])original[o.id]=center(o);writeRelation(scene,r,geometry,original);return true;}
function regroup(scene){const objects=new Map(scene.objects.map(o=>[o.id,o]));const done=new Set();function visit(o){if(done.has(o.id))return;done.add(o.id);const members=o.members.map(id=>objects.get(id)).filter(Boolean);members.forEach(visit);if(members.length)o.bbox=bounds(members)}scene.objects.forEach(visit);}
function move(scene,id,x,y,original){const o=scene.objects.find(o=>o.id===id);if(!o)return moveRelation(scene,id,x,y,original);if(o.members.length)return;o.bbox.x=Math.max(0,Math.min(1000-o.bbox.width,x));o.bbox.y=Math.max(0,Math.min(1000-o.bbox.height,y));regroup(scene);}
function resize(scene,id,factor,original){const o=scene.objects.find(o=>o.id===id);if(!o)return resizeRelation(scene,id,factor,original);if(o.members.length)return;const c=center(o),b=o.bbox;b.width=Math.max(8,Math.min(1000,b.width*factor));b.height=Math.max(8,Math.min(1000,b.height*factor));move(scene,id,c.x-b.width/2,c.y-b.height/2);}
function exportScene(scene,original){const out=copy(scene);for(const r of out.relations){const ps=points(scene,r,original),a=ps[0],z=ps.at(-1),oa=r.points[0],oz=r.points.at(-1);r.label_position.x=Math.max(0,Math.min(1000,r.label_position.x+(a.x-oa.x+z.x-oz.x)/2));r.label_position.y=Math.max(0,Math.min(1000,r.label_position.y+(a.y-oa.y+z.y-oz.y)/2));r.points=ps.map(p=>({x:Math.max(0,Math.min(1000,p.x)),y:Math.max(0,Math.min(1000,p.y))}));}return out;}
const api={copy,center,bounds,anchors,points,connectionPoints,connectionShape,relationControls,reshapeRelationControl,relationBounds,move,resize,reshapeRelation,attachRelation,exportScene,regroup};root.DrawingGeometry=api;if(typeof module!=='undefined')module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
