const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const M=require('../app/mechanism.js'),G=require('../app/geometry.js');
const scene=JSON.parse(fs.readFileSync(path.join(__dirname,'../results/curated_ph007_ans_02/PH_007_ans_02.scene.json')));
const snapshot=JSON.stringify(scene);
const paths=[{label:'L1 branch',steps:['wire_l1_a1','wire_a1_l1','wire_l1_right'].map(relation_id=>({relation_id,direction:'forward'}))},
 {label:'L2 branch',steps:['wire_l2_a2','wire_a2_l2','wire_l2_right'].map(relation_id=>({relation_id,direction:'forward'}))}];
const routes=M.routes(scene,paths,G,G.anchors(scene));
assert.equal(routes.length,2);assert(routes.every(r=>r.total>0));
// The overlay crosses the terminals of the existing ammeter/bulb without
// turning that internal passage into a new editable wire.
const a1=scene.objects.find(o=>o.id==='a1');
assert(routes[0].points.some(p=>p.x<a1.bbox.x+a1.bbox.width/2));
assert(routes[0].points.some(p=>p.x>a1.bbox.x+a1.bbox.width/2));
const first=M.sample(routes[0],.1),later=M.sample(routes[0],.3);
assert(first.x<later.x);assert(Number.isFinite(first.angle));
const reverse=M.routes(scene,[{label:'Reverse inspection',steps:[{relation_id:'wire_l1_a1',direction:'backward'}]}],G,G.anchors(scene))[0];
assert(M.sample(reverse,.1).x>M.sample(reverse,.8).x);
assert.equal(JSON.stringify(scene),snapshot);
assert(scene.relations.every(r=>r.direction==='none'));
assert.throws(()=>M.routes(scene,[{label:'Invalid',steps:[{relation_id:'missing',direction:'forward'}]}],G,G.anchors(scene)));
console.log('Mechanism overlays: connected branch geometry, direction, moving samples and unchanged original scene passed.');
