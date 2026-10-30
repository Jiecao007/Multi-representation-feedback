const assert=require('node:assert/strict');
const G=require('../app/geometry.js'),E=require('../app/editor.js');
const node=(id,x,y)=>({id,label:id,bbox:{x,y,width:40,height:40},members:[]});
const path=(id,points,source=null,target=null)=>({id,source,target,points,direction:'forward',label_position:{x:200,y:40},verbatim_text:'Student arrow'});
const original={objects:[node('a',70,80),node('b',280,80)],relations:[path('curve',[{x:100,y:100},{x:200,y:50},{x:300,y:100}])]};
let scene=G.copy(original),anchors=G.anchors(scene),r=scene.relations[0];

// Whole-path translation preserves a curved math arrow and moves its annotation.
assert(G.move(scene,r.id,400,200,anchors));
assert.deepEqual(r.points,[{x:400,y:250},{x:500,y:200},{x:600,y:250}]);assert.deepEqual(r.label_position,{x:500,y:190});assert.equal(r.direction,'forward');assert.deepEqual(scene.objects,original.objects);
const vector={x:r.points[1].x-r.points[0].x,y:r.points[1].y-r.points[0].y};G.move(scene,r.id,9999,-9999,anchors);assert.deepEqual(G.relationBounds(scene,r,anchors),{x:800,y:0,width:200,height:50});assert.deepEqual({x:r.points[1].x-r.points[0].x,y:r.points[1].y-r.points[0].y},vector);

// Scaling also handles zero-height straight arrows and clamps without distorting the path.
scene=G.copy(original);anchors=G.anchors(scene);r=scene.relations[0];assert(G.resize(scene,r.id,2,anchors));assert.deepEqual(r.points,[{x:0,y:125},{x:200,y:25},{x:400,y:125}]);assert.deepEqual(r.label_position,{x:200,y:5});assert.equal(G.resize(scene,r.id,2,anchors),false);
scene.relations.push(path('straight',[{x:100,y:500},{x:300,y:500}]));assert(G.resize(scene,'straight',.5,anchors));assert.deepEqual(scene.relations[1].points,[{x:150,y:500},{x:250,y:500}]);

// Moving an attached circuit wire makes a free path; unrelated nodes never move.
scene=G.copy(original);scene.relations=[path('wire',[{x:100,y:100},{x:180,y:100},{x:180,y:180},{x:300,y:180}],'a','b')];anchors=G.anchors(scene);G.move(scene,'a',100,100);const nodes=G.copy(scene.objects),visible=G.points(scene,scene.relations[0],anchors),b=G.relationBounds(scene,'wire',anchors);assert(G.move(scene,'wire',b.x+30,b.y+20,anchors));r=scene.relations[0];assert.equal(r.source,null);assert.equal(r.target,null);assert.deepEqual(r.points,visible.map(p=>({x:p.x+30,y:p.y+20})));assert.deepEqual(scene.objects,nodes);const free=G.copy(r.points);G.move(scene,'b',400,400);assert.deepEqual(G.points(scene,r,anchors),free);

// Adjusting one endpoint keeps the other attached and retains the polyline's bends.
scene=G.copy(original);scene.relations=[path('wire',[{x:100,y:100},{x:180,y:100},{x:180,y:180},{x:300,y:180}],'a','b')];anchors=G.anchors(scene);assert(G.reshapeRelation(scene,'wire','source',50,60,anchors));r=scene.relations[0];assert.equal(r.source,null);assert.equal(r.target,'b');assert.equal(r.points.length,4);assert.deepEqual(G.points(scene,r,anchors)[0],{x:50,y:60});assert.deepEqual(G.points(scene,r,anchors).at(-1),{x:300,y:180});const beforeNode=G.points(scene,r,anchors);G.move(scene,'b',310,100);const followed=G.points(scene,r,anchors);assert.deepEqual(followed[0],beforeNode[0]);assert.deepEqual(followed.at(-1),{x:330,y:200});

// Reattaching an endpoint to a moved or newly inserted object never jumps the path.
G.move(scene,'a',120,140);G.reshapeRelation(scene,'wire','source',140,160,anchors);const beforeAttach=G.points(scene,r,anchors);assert.equal(E.reattach(scene,'wire','source',anchors),'a');assert.equal(r.source,'a');assert.deepEqual(G.points(scene,r,anchors),beforeAttach);G.move(scene,'a',140,150);assert.deepEqual(G.points(scene,r,anchors)[0],{x:160,y:170});scene.objects.push(node('new',500,500));G.reshapeRelation(scene,'wire','source',520,520,anchors);assert.equal(E.reattach(scene,'wire','source',anchors),'new');G.move(scene,'new',510,510);assert.deepEqual(G.points(scene,r,anchors)[0],{x:530,y:530});

const exported=G.exportScene(scene,anchors);assert.deepEqual(exported.relations[0].points,G.points(scene,r,anchors));assert.deepEqual(original.relations[0].points,[{x:100,y:100},{x:200,y:50},{x:300,y:100}]);assert.equal(G.reshapeRelation(scene,'wire','bad',1,1,anchors),false);assert.equal(G.move(scene,'missing',1,1,anchors),false);assert.equal(G.resize(scene,'wire',NaN,anchors),false);
assert.equal(E.endpointTarget({objects:[node('large',0,0),{...node('small',10,10),bbox:{x:10,y:10,width:10,height:10}}]}, {x:15,y:15}), 'small');
console.log('Relation geometry: curved/straight path translation and scale, circuit endpoint reshape, boundaries, attachments, node following, labels and immutable source passed.');
