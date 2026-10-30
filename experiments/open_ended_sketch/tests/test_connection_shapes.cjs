const assert=require('node:assert/strict');
const G=require('../app/geometry.js');
const node=(id,x,y)=>({id,bbox:{x,y,width:40,height:40},members:[]});
const a={x:120,y:120},b={x:620,y:120};
const relation=points=>({id:'edge',source:'a',target:'b',points,direction:'both',label_position:{x:370,y:150},verbatim_text:'Connection'});
const fixture=points=>({objects:[node('a',100,100),node('b',600,100)],relations:[relation(points)]});

// Shape survives a plain JSON/schema-compatible points-only round trip.
const curved=G.connectionPoints(a,b,'curved',{x:370,y:360});
assert.equal(curved.length,25);assert.deepEqual(curved[0],a);assert.deepEqual(curved.at(-1),b);
assert.equal(G.connectionShape(JSON.parse(JSON.stringify(curved))),'curved');
assert.deepEqual(curved[12],{x:370,y:240});
assert.equal(G.connectionShape(G.connectionPoints(a,b,'straight')),'straight');
const bent=G.connectionPoints(a,b,'bent',{x:370,y:360});assert.deepEqual(bent,[a,{x:370,y:360},b]);assert.equal(G.connectionShape(bent),'bent');

// Dragging curve controls affects geometry without moving or detaching either endpoint.
let scene=fixture(curved),anchors=G.anchors(scene),r=scene.relations[0];
assert.deepEqual(G.relationControls(scene,r,anchors),[{index:0,kind:'curve',point:{x:370,y:240}}]);
assert(G.reshapeRelationControl(scene,'edge',0,370,440,anchors));
assert.deepEqual(G.points(scene,r,anchors)[12],{x:370,y:440});assert.deepEqual(r.points[0],a);assert.deepEqual(r.points.at(-1),b);
assert.equal(r.source,'a');assert.equal(r.target,'b');assert.equal(r.direction,'both');
assert.equal(G.reshapeRelationControl(scene,'edge',0,370,440,anchors),false);
G.move(scene,'a',140,130);G.move(scene,'b',630,110);
const visible=G.points(scene,r,anchors);assert.deepEqual(visible[0],{x:160,y:150});assert.deepEqual(visible.at(-1),{x:650,y:130});assert.equal(G.connectionShape(visible),'curved');
assert(G.reshapeRelationControl(scene,'edge',0,400,420,anchors));
assert.deepEqual(G.points(scene,r,anchors)[0],visible[0]);assert.deepEqual(G.points(scene,r,anchors).at(-1),visible.at(-1));
assert.deepEqual(G.exportScene(scene,anchors).relations[0].points,G.points(scene,r,anchors));
assert.equal(G.connectionShape(G.exportScene(scene,anchors).relations[0].points),'curved');

// Every interior vertex of existing hand-drawn paths remains independently editable.
const handdrawn=[a,{x:220,y:100},{x:260,y:290},{x:470,y:280},b];
scene=fixture(handdrawn);anchors=G.anchors(scene);r=scene.relations[0];
assert.equal(G.relationControls(scene,r,anchors).length,3);
assert(G.reshapeRelationControl(scene,'edge',2,300,320,anchors));
assert.deepEqual(r.points,[a,{x:220,y:100},{x:300,y:320},{x:470,y:280},b]);
assert.equal(r.source,'a');assert.equal(r.target,'b');
assert.equal(G.reshapeRelationControl(scene,'edge',0,400,400,anchors),false);
assert.equal(G.reshapeRelationControl(scene,'edge',1,NaN,400,anchors),false);

// Endpoint reshaping retains the curve even when a control reaches the canvas boundary.
scene=fixture(curved);anchors=G.anchors(scene);r=scene.relations[0];
assert(G.reshapeRelation(scene,'edge','source',1000,1000,anchors));assert.equal(G.connectionShape(r.points),'curved');
assert.deepEqual(r.points[0],{x:1000,y:1000});assert.deepEqual(r.points.at(-1),b);
assert(G.reshapeRelationControl(scene,'edge',0,-500,4000,anchors));
assert.deepEqual(G.relationControls(scene,r,anchors)[0].point,{x:405,y:780});
assert(r.points.every(p=>p.x>=0&&p.x<=1000&&p.y>=0&&p.y<=1000));

// Following attached objects near an edge clamps the control before sampling, rather than flattening individual samples.
scene=fixture(G.connectionPoints(a,b,'curved',{x:370,y:1000}));anchors=G.anchors(scene);r=scene.relations[0];
G.move(scene,'a',100,900);G.move(scene,'b',600,900);
const edgePoints=G.points(scene,r,anchors);assert.equal(G.connectionShape(edgePoints),'curved');
assert.deepEqual(edgePoints[0],{x:120,y:920});assert.deepEqual(edgePoints.at(-1),{x:620,y:920});
assert.deepEqual(G.relationControls(scene,r,anchors)[0].point,{x:370,y:960});
assert.equal(G.connectionShape(G.exportScene(scene,anchors).relations[0].points),'curved');
assert(edgePoints.every(p=>p.x>=0&&p.x<=1000&&p.y>=0&&p.y<=1000));
console.log('Connection shapes: points-only persistence, controls, preserved endpoints, attachments, legacy bends and bounds passed.');
