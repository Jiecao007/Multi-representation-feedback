const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const G=require('../app/geometry.js'),E=require('../app/editor.js');
const original=JSON.parse(fs.readFileSync(path.join(__dirname,'../results/20260922T035929331824Z/pic1.scene.json')));
const scene=G.copy(original);
const text=scene.objects.find(o=>o.id==='o1');E.editText(text,'New text\nSecond line');assert.equal(text.verbatim_text,'New text\nSecond line');assert.equal(text.glyph[0].text,text.verbatim_text);
// Short labels must release the unused box width, preserving font size and
// allowing the actual text to reach the right side of the drawing.
const note=E.createText('A much longer label','compact-note',{ratio:.2});
const oldWidth=note.bbox.width,oldFont=E.textSize(note,.2);E.editText(note,'12',{}, {ratio:.2});
assert(note.bbox.width<oldWidth/4);assert(Math.abs(E.textSize(note,.2)-oldFont)<1e-8);
const textScene={objects:[note],relations:[]};G.move(textScene,note.id,999,450);
assert(Math.abs(note.bbox.x+note.bbox.width-1000)<1e-8);assert(note.bbox.x>980);
const multiline=E.createText('12\n34','multiline',{ratio:.2});assert.equal(multiline.bbox.height,90);
const wide=E.createText('WW中文','wide',{ratio:.2,measure:s=>Array.from(s).length});
assert(wide.bbox.width>=E.textSize(wide,.2)*4);
const large=E.createText('W'.repeat(500),'large',{ratio:2,measure:s=>Array.from(s).length});
assert(large.bbox.x+large.bbox.width<=1000&&large.bbox.y+large.bbox.height<=1000);
const catalog=JSON.parse(fs.readFileSync(path.join(__dirname,'../app/catalog.json')));
let count=0;for(const topic of catalog.topics)for(const asset of topic.assets){const obj=E.instantiate(asset,'test_'+(++count),{x:999,y:999});assert.ok(obj.bbox.x+obj.bbox.width<=1000&&obj.bbox.y+obj.bbox.height<=1000);assert.match(obj.evidence,/preloaded/);scene.objects.push(obj);}
const mixed=E.instantiate(catalog.topics[0].assets.find(a=>a.id==='process'),'mixed');const index=mixed.glyph.findIndex(g=>g.kind==='text');const before=G.copy(mixed.glyph[0]);E.editText(mixed,'Custom process',{[index]:'Edited inside'});assert.equal(mixed.glyph[index].text,'Edited inside');assert.deepEqual(mixed.glyph[0],before);
const saved=G.copy(scene),removed=E.remove(scene,'o4');assert.ok(removed.includes('o4'));assert.ok(scene.objects.some(o=>o.id==='o6'));assert.ok(scene.objects.find(o=>o.id==='o6').members.every(id=>id!=='o4'));
const incident=scene.relations.filter(r=>r.source==='o5'||r.target==='o5'||r.source==='o6'||r.target==='o6').map(r=>r.id);E.remove(scene,'o5');assert.ok(!scene.objects.some(o=>o.id==='o6'));assert.ok(incident.every(id=>!scene.relations.some(r=>r.id===id)));assert.ok(original.objects.some(o=>o.id==='o4'));assert.ok(saved.objects.some(o=>o.id==='o4'));
const cue=E.focus(original,['o6',original.relations[0].id,'deleted-id']);assert.ok(cue.ids.includes('o4')&&cue.ids.includes('o5'));assert.deepEqual(cue.missing,['deleted-id']);assert.ok(cue.bounds.width>0);
const noCue=E.focus(scene,['does-not-exist']);assert.equal(noCue.bounds,null);
for(const r of original.relations)assert.doesNotMatch(E.relationName(original,r),/^Connection \d/);
// Used by the Python schema check, not a browser screenshot or DOM test.
fs.writeFileSync('/tmp/drawing_editor_scene_test.json',JSON.stringify(scene));
console.log(`Editor: ${count} library assets; multiline/mixed text; safe deletion; group cleanup; immutable undo snapshot; multiple visual targets passed.`);
