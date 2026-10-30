/* Qualitative overlays on submitted paths, separate from editable geometry. */
(function(root){
const colors=['#8052c4','#218a95'];
function routes(scene,paths,geometry,anchors){
 const relations=new Map(scene.relations.map(r=>[r.id,r]));
 return paths.map((path,index)=>{
  const points=[];
  for(const step of path.steps){
   const relation=relations.get(step.relation_id);
   if(!relation)throw Error('Missing mechanism relation');
   let segment=geometry.points(scene,relation,anchors).map(p=>({x:p.x,y:p.y}));
   if(step.direction==='backward')segment.reverse();
   // Adjacent steps meet at an existing component. Their short internal bridge
   // indicates passage through that component; it never becomes a student wire.
   for(const point of segment)if(!points.length||Math.hypot(point.x-points.at(-1).x,point.y-points.at(-1).y)>.01)points.push(point);
  }
  const lengths=[];let total=0;
  for(let i=1;i<points.length;i++){const length=Math.hypot(points[i].x-points[i-1].x,points[i].y-points[i-1].y);lengths.push(length);total+=length;}
  return {label:path.label,color:colors[index%colors.length],points,lengths,total};
 });
}
function sample(route,fraction){
 let distance=Math.max(0,Math.min(1,fraction))*route.total;
 for(let i=0;i<route.lengths.length;i++){
  const length=route.lengths[i],a=route.points[i],b=route.points[i+1];
  if(distance<=length||i===route.lengths.length-1){const t=length?distance/length:0;return {x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t,angle:Math.atan2(b.y-a.y,b.x-a.x)*180/Math.PI};}
  distance-=length;
 }
 return null;
}
const api={routes,sample,colors};root.MechanismFeedback=api;
if(typeof module!=='undefined')module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
