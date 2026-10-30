/* UI regression for compact text and editable connection shapes; all APIs mocked. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';
const require=createRequire(import.meta.url);
const {chromium}=require('/Users/jiecao/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const out=path.resolve('outputs/editor_text_connections_1012');
await fs.mkdir(out,{recursive:true});
const appURL=process.env.DRAW_TO_EXPLORE_URL||'http://127.0.0.1:8765';
const image='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP8zwACTGCSAQANHQEDgslx/wAAAABJRU5ErkJggg==';
const node=(id,x,y,width=80,height=80)=>({id,label:id,verbatim_text:'',kind:'box',bbox:{x,y,width,height},
 glyph:[{kind:'rect',points:[{x:0,y:0},{x:1000,y:1000}],text:'',filled:false,color:null}],
 members:[],origin:'student',confidence:1,evidence:'Browser fixture.',ambiguity:''});
const fixtureScene={title:'Text and connection regression',summary:'Local editor fixture.',representation:'diagram',
 objects:[node('A',100,200),node('B',650,420),node('Right boundary',975,800,20,20)],
 relations:[{id:'legacy_line',source:'A',target:'B',direction:'forward',
  points:[{x:180,y:200},{x:280,y:100},{x:430,y:120},{x:590,y:180},{x:650,y:420}],
  verbatim_text:'Legacy hand-drawn connection',label_position:{x:290,y:85},interpretation:'Existing student marks.',
  origin:'student',confidence:1,evidence:'Browser fixture.',ambiguity:'',color:null}],
 uncertainties:[],omitted_details:[],simulation_readiness:'qualitative_only',simulation_requirements:[],suggested_interactions:[]};
const fixture={scene:fixtureScene,record:{id:'text-connection-fixture',filename:'fixture.png',width:1000,height:1000,task:'Explain this diagram.'},
 original:image,question:{text:'Explain this diagram.',image:''},provenance:{provider:'mocked browser fixture'}};
const browser=await chromium.launch({headless:true,channel:'chrome'});
const page=await browser.newPage({viewport:{width:1440,height:1100}});
const errors=[],unexpected=[],calls=[],authorizations=[],checks={};
let savedCase=null;
async function mockAPIs(target,{resume=false,sourceFixture=fixture}={}){
 target.on('pageerror',error=>errors.push(error.message));
 await target.route('**/api/**',async route=>{
  const request=route.request(),pathname=new URL(request.url()).pathname;
  if(pathname==='/api/resume-case'){
   await route.fulfill(resume&&savedCase?{json:{case:savedCase,payload:sourceFixture,state:{session_id:'text-connection-session'}}}:{status:204,body:''});return;
  }
  if(pathname==='/api/examples'){await route.fulfill({json:[{id:sourceFixture.record.id,title:sourceFixture.scene.title}]});return;}
  if(pathname==='/api/examples/'+sourceFixture.record.id){await route.fulfill({json:sourceFixture});return;}
  if(pathname==='/api/begin-revision'){
   authorizations.push(request.postDataJSON());await route.fulfill({json:{session_id:'text-connection-session',edit_enabled:true,awaiting_revision_reason:false}});return;
  }
  if(pathname==='/api/feedback'){
   calls.push(request.postDataJSON());
   await route.fulfill({json:{session_id:'text-connection-session',version:1,drawing_version:1,response_mode:'review',
    acknowledgment:'',acknowledgment_ids:[],follow_up:'Explore your diagram, then begin a revision.',content:'Explore your diagram, then begin a revision.',
    focus_ids:[],highlight_ids:[],next_focus_kind:'none',learning_goal:'Explain this diagram.',revision_plan:'',revision_plan_ids:[],
    edit_enabled:false,awaiting_revision_reason:false,stage:'dialogue',talk_move:'invite_dialogue',review:[],criteria:[],
    visual_action:'none',visual_delivery:'none',mechanism_paths:[],mechanism_condition:''}});return;
  }
  unexpected.push(pathname);await route.fulfill({status:500,json:{error:'Unexpected API request blocked by local regression test.'}});
 });
}
const exported=()=>page.evaluate(()=>G.exportScene(scene,anchors));
const item=async id=>(await exported()).objects.find(o=>o.id===id);
const connection=async id=>(await exported()).relations.find(r=>r.id===id);
const canvasPoint=(target,p)=>target.evaluate(({x,y})=>{
 const point=document.getElementById('canvas').createSVGPoint();point.x=x;point.y=y;
 const result=point.matrixTransform(document.getElementById('sceneRoot').getScreenCTM());return{x:result.x,y:result.y};
},p);
async function drag(from,to,target=page){
 const a=await canvasPoint(target,from),b=await canvasPoint(target,to);
 await target.mouse.move(a.x,a.y);await target.mouse.down();await target.mouse.move(b.x,b.y,{steps:6});await target.mouse.up();
}
async function select(id,type='object'){
 await page.locator(`#canvas .${type}[data-id="${id}"]`).focus();await page.keyboard.press('Enter');
 assert.equal(await page.evaluate(()=>selected),id);
}
async function addText(value){
 await page.locator('#addNote').click();await page.locator('#newName').fill(value);await page.locator('#renameForm button[type=submit]').click();
 return page.evaluate(()=>selected);
}
async function renameText(id,value){
 await select(id);assert.equal(await page.locator('#rename').textContent(),'Edit text');await page.locator('#rename').click();
 assert.equal(await page.locator('#textHeading').textContent(),'Edit text');await page.locator('#newName').fill(value);
 await page.locator('#renameForm button[type=submit]').click();
}
async function textMetrics(id){
 return page.evaluate(id=>{
  const object=scene.objects.find(o=>o.id===id),group=canvas.querySelector(`.object[data-id="${CSS.escape(id)}"]`);
  return {bbox:G.copy(object.bbox),lines:[...group.querySelectorAll('text')].map(text=>{
   const b=text.getBBox();return{text:text.textContent,font:Number(text.getAttribute('font-size')),bbox:{x:b.x,y:b.y,width:b.width,height:b.height}};
  })};
 },id);
}
function containedText(metrics){
 const b=metrics.bbox;
 for(const line of metrics.lines){
  assert(line.bbox.x>=b.x-1,'Rendered text starts inside its object box');
  assert(line.bbox.x+line.bbox.width<=b.x+b.width+1,'Rendered glyphs must fit the measured text width');
  // SVG getBBox includes font ascender space above dominant-baseline:middle;
  // the editor deliberately supplies seven units of selectable halo padding.
  assert(line.bbox.y>=b.y-7&&line.bbox.y+line.bbox.height<=b.y+b.height+7,'Rendered text fits the selectable height: '+JSON.stringify(metrics));
 }
}
async function undoTo(before){await page.locator('#undo').click();assert.deepEqual(await exported(),before,'Undo restores exact scene geometry and text');}
async function createConnection(shape){
 await page.locator('#connect').click();await page.locator('#connectionFrom').selectOption('A');await page.locator('#connectionTo').selectOption('B');
 await page.locator('#connectionShape').selectOption(shape);await page.locator('#connectionLabel').fill(shape+' relation');
 await page.locator('#connectionForm button[type=submit]').click();return page.evaluate(()=>selected);
}
const sameEnds=(before,after)=>{
 assert.deepEqual(after.points[0],before.points[0]);assert.deepEqual(after.points.at(-1),before.points.at(-1));
 assert.equal(after.source,before.source);assert.equal(after.target,before.target);
};
async function editConnectionLabel(id,value){
 await select(id,'relation');await page.locator('#editConnection').click();await page.locator('#connectionLabel').fill(value);
 await page.locator('#connectionForm button[type=submit]').click();
}
try{
 await mockAPIs(page);await page.goto(appURL,{waitUntil:'networkidle'});
 await page.locator('#examples').selectOption(fixture.record.id);await page.waitForFunction(()=>!!scene&&!uploadBusy);
 await page.locator('#explanation').fill('This is a browser-only editor test.');await page.locator('#submitImage').click();
 await page.waitForFunction(()=>!!feedbackSession&&!chatBusy);await page.locator('[data-intent=begin_revision]').click();
 await page.waitForFunction(()=>editEnabled&&!revisionAuth);

 const shortId=await addText('12'),short=await item(shortId);
 assert(short.bbox.width<70&&short.bbox.width>8,'Two digits get a compact selectable text box');containedText(await textMetrics(shortId));
 const beforeShortDrag=await exported(),center={x:short.bbox.x+short.bbox.width/2,y:short.bbox.y+short.bbox.height/2};
 await drag(center,{x:990,y:center.y});const movedShort=await item(shortId);
 assert(movedShort.bbox.x>940,'Short text reaches the right edge instead of clamping at a wide invisible box');
 assert(movedShort.bbox.x+movedShort.bbox.width<=1000.01);containedText(await textMetrics(shortId));
 await page.screenshot({path:path.join(out,'short_text_at_right_edge.png'),fullPage:true});
 await undoTo(beforeShortDrag);await drag(center,{x:990,y:center.y});checks.shortTextCompactAndRightDrag=true;checks.shortTextUndo=true;

 const longId=await addText('A long connection explanation label'),beforeRename=await exported(),longMetrics=await textMetrics(longId);
 await renameText(longId,'12');const compactMetrics=await textMetrics(longId);
 assert(compactMetrics.bbox.width<longMetrics.bbox.width*.2,'Editing a long label to two digits shrinks its box');
 assert(Math.abs(compactMetrics.lines[0].font-longMetrics.lines[0].font)<1,'Text editing preserves readable font size');
 containedText(compactMetrics);await undoTo(beforeRename);await renameText(longId,'12');checks.longToShortTextShrinks=true;checks.textFontPreserved=true;

 const cjkValue='寬字漢字ＷＷ１２\n第二行 🚀',cjkId=await addText(cjkValue),cjkMetrics=await textMetrics(cjkId);
 assert.equal((await item(cjkId)).verbatim_text,cjkValue);assert.equal(cjkMetrics.lines.length,2);containedText(cjkMetrics);
 checks.multilineAndWideGlyphContainment=true;

 const legacyBefore=await exported(),legacy=await connection('legacy_line');await editConnectionLabel('legacy_line','Only the label changed');
 const legacyAfter=await connection('legacy_line');assert.deepEqual(legacyAfter.points,legacy.points);assert.deepEqual(legacyAfter.label_position,legacy.label_position);
 sameEnds(legacy,legacyAfter);await undoTo(legacyBefore);checks.legacyFivePointLabelEditPreservesShape=true;

 const connectionIds={};
 for(const shape of ['curved','bent']){
  const id=await createConnection(shape);connectionIds[shape]=id;
  const original=await connection(id),originalScene=await exported();assert.equal(original.points.length,shape==='curved'?25:3);
  const controls=await page.evaluate(id=>G.relationControls(scene,id,anchors),id);assert.equal(controls.length,1);
  const control=controls[0],handle=page.locator(`#canvas .relation-control[data-id="${id}"][data-control="${control.index}"]`);
  assert(await handle.isVisible());await drag(control.point,{x:control.point.x+70,y:control.point.y-60});
  const changed=await connection(id);sameEnds(original,changed);assert.notDeepEqual(changed.points,original.points);
  const shifted=await page.evaluate(id=>G.relationControls(scene,id,anchors)[0],id);
  assert(Math.abs(shifted.point.x-control.point.x-70)<1&&Math.abs(shifted.point.y-control.point.y+60)<1);
  await undoTo(originalScene);checks[shape+'ControlDragPreservesEndpoints']=true;

  await drag(control.point,{x:control.point.x+70,y:control.point.y-60});
  const beforeKey=await exported(),beforeKeyConnection=await connection(id);
  await handle.focus();await page.keyboard.press('ArrowRight');const afterKey=await connection(id);sameEnds(beforeKeyConnection,afterKey);
  const keyControl=await page.evaluate(id=>G.relationControls(scene,id,anchors)[0],id);
  assert(Math.abs(keyControl.point.x-shifted.point.x-5)<.01);await undoTo(beforeKey);checks[shape+'ControlKeyboardAndUndo']=true;

  const labelBefore=await connection(id);await editConnectionLabel(id,'Updated '+shape+' meaning');const labelAfter=await connection(id);
  assert.deepEqual(labelAfter.points,labelBefore.points);assert.deepEqual(labelAfter.label_position,labelBefore.label_position);sameEnds(labelBefore,labelAfter);
  checks[shape+'LabelEditPreservesShape']=true;

  const objectMoveBefore=await exported(),beforeSourceMove=await connection(id),a=(await item('A')).bbox;
  await drag({x:a.x+a.width/2,y:a.y+a.height/2},{x:a.x+a.width/2+20,y:a.y+a.height/2+20});
  const afterSourceMove=await connection(id);
  assert(Math.abs(afterSourceMove.points[0].x-beforeSourceMove.points[0].x-20)<1);
  assert(Math.abs(afterSourceMove.points[0].y-beforeSourceMove.points[0].y-20)<1);
  assert.deepEqual(afterSourceMove.points.at(-1),beforeSourceMove.points.at(-1));assert.equal(afterSourceMove.source,'A');assert.equal(afterSourceMove.target,'B');
  await undoTo(objectMoveBefore);checks[shape+'EndpointObjectBindingSurvivesControlEdit']=true;
 }
 const straightId=await createConnection('straight');connectionIds.straight=straightId;
 assert.equal((await connection(straightId)).points.length,2);assert.equal(await page.locator('#canvas .relation-control').count(),0);checks.straightHasNoInteriorHandle=true;

 await select(connectionIds.curved,'relation');await page.screenshot({path:path.join(out,'text_and_curved_connection.png'),fullPage:true});
 await select(connectionIds.bent,'relation');await page.screenshot({path:path.join(out,'text_and_bent_connection.png'),fullPage:true});
 const finalScene=await exported(),beforeSave=JSON.stringify(await page.evaluate(()=>({draft:draftSnapshot(),editHistory,feedbackTurns,interactionLog})));
 const downloadPromise=page.waitForEvent('download');await page.locator('#save').click();const download=await downloadPromise;
 assert.match(download.suggestedFilename(),/\.exploration\.json$/);const savedPath=path.join(out,'text_connections.exploration.json');await download.saveAs(savedPath);
 savedCase=JSON.parse(await fs.readFile(savedPath,'utf8'));assert.deepEqual(savedCase.scene,finalScene);assert.deepEqual(savedCase.current_draft.scene,finalScene);
 assert.equal(JSON.stringify(await page.evaluate(()=>({draft:draftSnapshot(),editHistory,feedbackTurns,interactionLog}))),beforeSave,'Saving does not mutate the private draft or interaction history');
 assert(savedCase.scene.relations.every(r=>!('shape'in r)&&!('control'in r)),'Connection shapes remain compatible with the existing points schema');
 const validate=spawnSync(process.env.PYTHON||'python3',['-c',
  'import json,sys; sys.path.insert(0,"experiments/open_ended_sketch"); from schema import validate_sketch; s=json.load(open(sys.argv[1])); validate_sketch(s["scene"]); validate_sketch(s["original_model"]); validate_sketch(s["current_draft"]["scene"]); print("Strict schema accepted original and edited scenes")',savedPath],{encoding:'utf8'});
 assert.equal(validate.status,0,validate.stderr||validate.stdout);checks.savedDownloadStrictSchemaCompatible=true;checks.saveDoesNotMutateState=true;

 const restored=await browser.newPage({viewport:{width:1440,height:1100}});await mockAPIs(restored,{resume:true});await restored.goto(appURL,{waitUntil:'networkidle'});
 await restored.waitForFunction(()=>!!scene&&!!feedbackSession&&!uploadBusy);assert.deepEqual(await restored.evaluate(()=>G.exportScene(scene,anchors)),finalScene);
 assert.equal(await restored.evaluate(()=>editEnabled),true);assert.equal(await restored.locator('#messages .assistant').count(),1);
 const recovered=await restored.evaluate(()=>Object.fromEntries(scene.relations.map(r=>[r.id,G.connectionShape(G.points(scene,r,anchors))])));
 for(const shape of ['straight','curved','bent'])assert.equal(recovered[connectionIds[shape]],shape);
 await restored.screenshot({path:path.join(out,'saved_case_restored.png'),fullPage:true});await restored.close();checks.saveRestorePreservesTextAndConnectionShapes=true;
 // The user's number-line drawings are wide images: test their transformed
 // screen bounds independently instead of comparing SVG coordinates directly.
 const wideFixture=structuredClone(fixture);wideFixture.record={...wideFixture.record,id:'wide-text-fixture',width:1000,height:200};
 wideFixture.scene.title='Wide number-line text regression';
 const wide=await browser.newPage({viewport:{width:1440,height:1100}});await mockAPIs(wide,{sourceFixture:wideFixture});
 await wide.goto(appURL,{waitUntil:'networkidle'});await wide.locator('#examples').selectOption(wideFixture.record.id);
 await wide.waitForFunction(()=>!!scene&&!uploadBusy);await wide.locator('#submitImage').click();await wide.waitForFunction(()=>!!feedbackSession&&!chatBusy);
 await wide.locator('[data-intent=begin_revision]').click();await wide.waitForFunction(()=>editEnabled&&!revisionAuth);
 const wideAdd=async value=>{await wide.locator('#addNote').click();await wide.locator('#newName').fill(value);await wide.locator('#renameForm button[type=submit]').click();return wide.evaluate(()=>selected);};
 const wideMetrics=id=>wide.evaluate(id=>{
  const group=canvas.querySelector(`.object[data-id="${CSS.escape(id)}"]`),o=scene.objects.find(o=>o.id===id),rect=e=>{
   const r=e.getBoundingClientRect();return {left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height};
  };
  return {bbox:G.copy(o.bbox),font:Number(group.querySelector('text').getAttribute('font-size')),halo:rect(group.querySelector('.halo')),texts:[...group.querySelectorAll('text')].map(rect)};
 },id);
 const wideContains=metrics=>{for(const text of metrics.texts){const h=metrics.halo;
  assert(text.left>=h.left-1&&text.right<=h.right+1&&text.top>=h.top-1&&text.bottom<=h.bottom+1,'Wide-image text fits its selectable halo in screen coordinates: '+JSON.stringify(metrics));
 }};
 const wideShortId=await wideAdd('12'),wideShort=await wideMetrics(wideShortId);assert(wideShort.bbox.width<20);wideContains(wideShort);
 const wideCenter={x:wideShort.bbox.x+wideShort.bbox.width/2,y:wideShort.bbox.y+wideShort.bbox.height/2};
 await drag(wideCenter,{x:990,y:wideCenter.y},wide);const wideMoved=await wideMetrics(wideShortId);
 assert(wideMoved.bbox.x>975&&wideMoved.bbox.x+wideMoved.bbox.width<=1000.01);wideContains(wideMoved);checks.wideImageShortTextCompactAndRightDrag=true;
 const wideLongId=await wideAdd('A long number-line annotation'),wideLong=await wideMetrics(wideLongId);
 await wide.locator('#rename').click();await wide.locator('#newName').fill('12');await wide.locator('#renameForm button[type=submit]').click();
 const wideCompact=await wideMetrics(wideLongId);assert(wideCompact.bbox.width<wideLong.bbox.width*.2);
 assert(Math.abs(wideCompact.font-wideLong.font)<.01);wideContains(wideCompact);checks.wideImageLongToShortTextPreservesFont=true;checks.wideImageScreenGlyphsInsideSelectionHalo=true;
 await wide.screenshot({path:path.join(out,'wide_number_line_text.png'),fullPage:true});await wide.close();
 assert.equal(calls.length,2,'Only one mocked initial submission per isolated editor fixture requests feedback');assert.equal(authorizations.length,2);assert.deepEqual(unexpected,[]);assert.deepEqual(errors,[]);
 const result={passed:true,checks,feedbackCalls:calls.length,revisionAuthorizations:authorizations.length,unexpectedAPIs:unexpected,pageErrors:errors,
  schemaValidation:validate.stdout.trim(),provider:'All /api/* requests intercepted with local fixtures; no live AI calls.'};
 await fs.writeFile(path.join(out,'browser_result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
}catch(error){
 await page.screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});
 await fs.writeFile(path.join(out,'browser_failure.json'),JSON.stringify({error:error.message,stack:error.stack,checks,pageErrors:errors,unexpectedAPIs:unexpected},null,2));throw error;
}finally{await browser.close();}
