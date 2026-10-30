const assert=require('node:assert/strict');
const {trace}=require('../graph.js');
const edge=(id,source,target,extra={})=>({id,source,target,direction:'forward',confidence:1,origin:'student',ambiguity:'',...extra});
const scene={objects:['a','b','c','d','e'].map(id=>({id})),relations:[
  edge('ab','a','b'),edge('bc','b','c'),edge('ca','c','a'),
  edge('cd','c','d',{ambiguity:'uncertain endpoint'}),edge('ce','c','e',{direction:'none'})
]};
assert.deepEqual(trace(scene,'a').nodes,['a','b','c']);
scene.relations[3].confirmed=true;
assert.deepEqual(trace(scene,'a').nodes,['a','b','c','d']);
scene.objects[1].enabled=false;
assert.deepEqual(trace(scene,'a').nodes,['a']);
assert.deepEqual(trace(scene,'a').blocked,['b']);
scene.objects[1].enabled=true;scene.relations[0].direction='backward';
assert.deepEqual(trace(scene,'a').nodes,['a']);
scene.relations[0].direction='both';
assert.deepEqual(trace(scene,'a').nodes,['a','b','c','d']);
scene.relations[0].source=null;
assert.deepEqual(trace(scene,'a').nodes,['a']);
console.log('Graph: cycles, disabled nodes, ambiguity confirmation, direction and unresolved endpoints passed.');
