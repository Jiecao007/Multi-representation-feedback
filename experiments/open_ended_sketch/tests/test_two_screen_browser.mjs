import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require('/Users/jiecao/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const out=path.resolve('outputs/system_progressive_feedback_1010');await fs.mkdir(out,{recursive:true});
const appURL=process.env.DRAW_TO_EXPLORE_URL||'http://127.0.0.1:8765';
const browser=await chromium.launch({headless:true,channel:'chrome'});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[],requests=[];page.on('pageerror',e=>errors.push(e.message));
const typedHint='I need a hint. Please give me a concrete next step.';
let strength=[],issue=[],repair=[],version=1,turn=0,failNext=false;
const authorizations=[];let holdAuthorization=false,releaseAuthorization=null,failAuthorization=false;
const exitAuthorizations=[];let holdExit=false,releaseExit=null,failExit=false;
const paths=[{label:'L1 branch',steps:['wire_l1_a1','wire_a1_l1','wire_l1_right'].map(relation_id=>({relation_id,direction:'forward'}))},{label:'L2 branch',steps:['wire_l2_a2','wire_a2_l2','wire_l2_right'].map(relation_id=>({relation_id,direction:'forward'}))}];
await page.route('**/api/resume-case',route=>route.fulfill({status:204,body:''}));
await page.route('**/api/feedback',async route=>{
 const data=route.request().postDataJSON();requests.push(data);++turn;
 if(failNext){failNext=false;await route.fulfill({status:502,json:{error:'The test feedback request did not finish.'}});return;}
 const initial=data.trigger==='submission',review=data.trigger==='workspace-complete',hint=data.intent==='hint'||data.message===typedHint,editGuide=data.message==='Help me make the indicated change.',plan=data.intent==='begin_revision'||data.message==='I know what to change now.',reason=data.message==='I changed it so the diagram matches the task.',close=data.message==='I am done.';
 if(initial){version=1;strength=data.scene.objects.filter(o=>/Ammeter A1/.test(o.label)).map(o=>o.id);issue=data.scene.objects.filter(o=>/Ammeter A2/.test(o.label)).map(o=>o.id);const j=data.scene.objects.find(o=>/Left junction/.test(o.label))?.id,b=data.scene.objects.find(o=>/Battery/.test(o.label))?.id;repair=data.scene.relations.filter(r=>[r.source,r.target].includes(j)&&[r.source,r.target].includes(b)).slice(0,1).map(r=>r.id);}
 if(review)version++;
 const pending=review&&!data.revision_reason,trace=!initial&&!review&&!hint&&!editGuide&&!plan&&!reason&&!close;
 const acknowledgment=initial?'Nice work! You correctly placed A₁ in series with L₁ 😊':review?'You added a note to explain your change.':'';
 const follow=initial?'Why does this placement measure the current through L₁?':hint?'Compare both bulb paths and check which pass through A₂. Use their shared path to reason about total current.':editGuide?'Move the indicated meter onto the shared connection, then review the change.':plan?'Move the meter to the shared wire you identified, then explain why that change meets the goal.':pending?'What was your reason for making this change?':reason||review?'Your revision and explanation connect clearly. Do you have any further questions?':close?'You can finish here.':'Watch the two paths when the switch is closed. Does the L₁ path pass through A₂?';
 const targets=initial?strength:plan?repair:hint||editGuide||trace?issue:[];
 const response={session_id:'browser-fixture',version:turn,drawing_version:version,response_mode:initial||review?'review':'dialogue',acknowledgment,acknowledgment_ids:initial?strength:[],follow_up:follow,content:[acknowledgment,follow].filter(Boolean).join(' '),focus_ids:trace?[]:targets,highlight_ids:initial?strength:[],next_focus_kind:close?'none':plan?'gap':'extension',learning_goal:'Represent two parallel bulbs and explain the current paths.',revision_plan:plan?'Revise one connection using the reason you explained.':'',revision_plan_ids:plan?repair:[],edit_enabled:plan||editGuide,awaiting_revision_reason:pending,guidance_requires_edit:editGuide,stage:close?'complete':pending?'revision-explanation':plan?'revision-planning':hint||editGuide?'thinking-dialogue':reason||review?'dialogue':initial?'recognition':'inquiry',talk_move:plan?'propose_revision_plan':pending?'invite_elaboration_reasoning':hint||editGuide?'provide_hints_guidance':trace?'press_for_accuracy':reason||review||close?'invite_dialogue':'recognize_strengths',review:[],criteria:[],visual_action:trace?'trace':targets.length?'highlight':'none',visual_delivery:trace||targets.length?'automatic':'none',mechanism_paths:trace?paths:[],mechanism_condition:trace?'If the switch is closed':''};
 await route.fulfill({json:response});
});
await page.route('**/api/begin-revision',async route=>{
 const data=route.request().postDataJSON();authorizations.push(data);
 if(holdAuthorization)await new Promise(resolve=>{releaseAuthorization=resolve;});
 if(failAuthorization){failAuthorization=false;await route.fulfill({status:502,json:{error:'Revision mode could not be opened.'}});return;}
 await route.fulfill({json:{session_id:data.session_id,edit_enabled:true,awaiting_revision_reason:false}});
});
await page.route('**/api/end-revision',async route=>{
 const data=route.request().postDataJSON();exitAuthorizations.push(data);
 if(holdExit)await new Promise(resolve=>{releaseExit=resolve;});
 if(failExit){failExit=false;await route.fulfill({status:502,json:{error:'Revision mode could not be closed.'}});return;}
 await route.fulfill({json:{session_id:data.session_id,edit_enabled:false,awaiting_revision_reason:false}});
});
const waitForReply=async count=>page.waitForFunction(n=>document.querySelectorAll('#messages .assistant:not(.error)').length===n,count);
const send=async(text,count)=>{await page.locator('#chatInput').fill(text);await page.locator('#send').click();await waitForReply(count);};
const workflowState=async()=>page.evaluate(()=>JSON.stringify({feedbackSession,currentDrawingVersion,editEnabled,awaitingRevisionReason,
 committed,feedbackTurns,conversation,revisionReason:document.getElementById('revisionReason').value,
 chatStatus:document.getElementById('chatStatus').textContent,draft:draftSnapshot()}));
const showWithoutWorkflowChange=async button=>{
 const before=await workflowState(),count=requests.length,authCount=authorizations.length,messages=await page.locator('#messages .message').count();
 await button.click();
 assert.equal(await workflowState(),before,'Show must preserve workflow, conversation, reason and draft state');
 assert.equal(requests.length,count,'Show must not generate feedback');
 assert.equal(authorizations.length,authCount,'Show must not authorize a revision');
 assert.equal(await page.locator('#messages .message').count(),messages,'Show must not add revision instructions or canned messages');
};
const exportWithoutWorkflowChange=async filename=>{
 const before=await workflowState(),count=requests.length,authCount=authorizations.length,exitCount=exitAuthorizations.length;
 const transcript=await page.evaluate(()=>interactionLog.map(entry=>({role:entry.role,text:entry.text,error:entry.error})));
 const downloadPromise=page.waitForEvent('download');await page.locator('#exportCase').click();const download=await downloadPromise;
 assert.match(download.suggestedFilename(),/\.html$/i);
 const destination=path.join(out,filename);await download.saveAs(destination);
 assert.equal(await workflowState(),before,'HTML export must preserve live workflow and private draft');
 assert.equal(requests.length,count,'HTML export must not call AI feedback');assert.equal(authorizations.length,authCount);assert.equal(exitAuthorizations.length,exitCount);
 assert.deepEqual(await page.evaluate(()=>interactionLog.map(entry=>({role:entry.role,text:entry.text,error:entry.error}))),transcript,'Export must not add a message');
 const html=await fs.readFile(destination,'utf8');const offline=await browser.newPage({viewport:{width:1440,height:1000}}),remote=[],offlineErrors=[];
 offline.on('pageerror',error=>offlineErrors.push(error.message));await offline.route('**/*',route=>{remote.push(route.request().url());return route.abort();});
 await offline.setContent(html,{waitUntil:'load'});
 const exported=await offline.locator('.transcript-entry').evaluateAll(nodes=>nodes.map(node=>({text:node.textContent,error:node.dataset.error})));
 assert.equal(exported.length,transcript.length);for(let i=0;i<transcript.length;i++)assert(exported[i].text.includes(transcript[i].text));
 assert.deepEqual(remote,[]);assert.deepEqual(offlineErrors,[]);
 assert((await offline.locator('body').textContent()).includes('The bulbs are connected in parallel.'));
 assert.equal(await offline.locator('script[src],link[href]').count(),0);assert(await offline.locator('img').count()>0);
 await offline.screenshot({path:path.join(out,filename.replace(/\.html$/,'.png')),fullPage:true});await offline.close();
 return {html,transcript};
};
const canvasPoint=async p=>page.evaluate(({x,y})=>{
 const q=document.getElementById('canvas').createSVGPoint();q.x=x;q.y=y;
 const result=q.matrixTransform(document.getElementById('sceneRoot').getScreenCTM());return {x:result.x,y:result.y};
},p);
const dragCanvas=async(from,to)=>{
 const a=await canvasPoint(from),b=await canvasPoint(to);
 await page.mouse.move(a.x,a.y);await page.mouse.down();await page.mouse.move(b.x,b.y,{steps:4});await page.mouse.up();
};
const assertRelationEditing=async()=>{
 const requestCount=requests.length,authorizationCount=authorizations.length;
 await page.evaluate(()=>{
  window.qaLineRestore={scene:G.copy(scene),anchors:G.copy(anchors),selected,view,focusIds:G.copy(focusIds),focusTone,
   editEvents:G.copy(editEvents),editHistory:G.copy(editHistory),record:G.copy(payload.record)};
  const node=(id,x,y)=>({id,label:id,verbatim_text:'',kind:'box',bbox:{x,y,width:80,height:80},
   glyph:[{kind:'rect',points:[{x:0,y:0},{x:1000,y:1000}],text:'',filled:false}],members:[],origin:'student',confidence:1,evidence:'Browser fixture.',ambiguity:''});
  stop();payload.record.width=1000;payload.record.height=1000;
  scene={...G.copy(scene),objects:[node('qa_a',100,100),node('qa_b',650,200)],relations:[{id:'qa_line',source:'qa_a',target:'qa_b',
   points:[{x:180,y:140},{x:350,y:140},{x:350,y:240},{x:650,y:240}],direction:'forward',verbatim_text:'Student connection',
   label_position:{x:350,y:110},interpretation:'Student connection.',origin:'student',confidence:1,evidence:'Browser fixture.',ambiguity:'',color:null}]};
  anchors=G.anchors(scene);selected='qa_line';focusIds=[];editEvents=[];editHistory=[];fit();draw();updateDraft();
 });
 try{
  const exported=async()=>page.evaluate(()=>G.exportScene(scene,anchors));
  const baseline=await exported(),line=()=>page.locator('#canvas .relation[data-id="qa_line"]');
  const undo=async()=>{await page.locator('#undo').click();assert.deepEqual(await exported(),baseline,'Undo must restore the exact exported student scene');};
  assert.equal(await page.locator('#canvas [data-id="qa_line"][data-endpoint]').count(),2);
  assert(await page.locator('#smaller').isEnabled());assert(await page.locator('#larger').isEnabled());
  await dragCanvas({x:350,y:190},{x:450,y:240});
  let changed=await exported();assert.deepEqual(changed.objects,baseline.objects);assert.equal(changed.relations[0].points.length,4);
  for(let i=0;i<4;i++){assert(Math.abs(changed.relations[0].points[i].x-baseline.relations[0].points[i].x-100)<2);assert(Math.abs(changed.relations[0].points[i].y-baseline.relations[0].points[i].y-50)<2);}
  assert.equal(changed.relations[0].source,null);assert.equal(changed.relations[0].target,null);await undo();
  await line().focus();await page.keyboard.press('ArrowRight');changed=await exported();
  assert.deepEqual(changed.relations[0].points,baseline.relations[0].points.map(p=>({x:p.x+5,y:p.y})));assert.deepEqual(changed.objects,baseline.objects);await undo();
  const width=value=>Math.max(...value.relations[0].points.map(p=>p.x))-Math.min(...value.relations[0].points.map(p=>p.x));
  for(const [control,grows]of [['larger',true],['smaller',false]]){
   await page.locator('#'+control).click();changed=await exported();assert(grows?width(changed)>width(baseline):width(changed)<width(baseline));assert.deepEqual(changed.objects,baseline.objects);await undo();
  }
  for(const [key,grows]of [['+',true],['-',false]]){
   await line().focus();await page.keyboard.press(key);changed=await exported();assert(grows?width(changed)>width(baseline):width(changed)<width(baseline));await undo();
  }
  await dragCanvas(baseline.relations[0].points[0],{x:245,y:185});changed=await exported();
  assert.notDeepEqual(changed.relations[0].points[0],baseline.relations[0].points[0]);assert.deepEqual(changed.relations[0].points.at(-1),baseline.relations[0].points.at(-1));
  assert.equal(changed.relations[0].source,null);assert.equal(changed.relations[0].target,'qa_b');assert.deepEqual(changed.objects,baseline.objects);await undo();
  await dragCanvas(baseline.relations[0].points.at(-1),{x:590,y:335});changed=await exported();
  assert.notDeepEqual(changed.relations[0].points.at(-1),baseline.relations[0].points.at(-1));assert.deepEqual(changed.relations[0].points[0],baseline.relations[0].points[0]);
  assert.equal(changed.relations[0].source,'qa_a');assert.equal(changed.relations[0].target,null);await undo();
  // Replaying the matching visual temporarily locks the line and hides its handles.
  await page.evaluate(()=>{showDiagramReference(['qa_line'],{scene:G.exportScene(scene,anchors)},currentDrawingVersion,'next','highlight',false,false,null,true);selected='qa_line';draw();});
  assert.equal(await page.locator('#canvas [data-endpoint]').count(),0);assert(await page.locator('#smaller').isDisabled());assert(await page.locator('#larger').isDisabled());
  await page.evaluate(()=>{$('smaller').onclick();$('larger').onclick();});await line().focus();await page.keyboard.press('ArrowRight');await page.keyboard.press('+');await page.keyboard.press('-');
  await dragCanvas({x:350,y:190},{x:390,y:220});assert.deepEqual(await exported(),baseline);assert.deepEqual(await page.evaluate(()=>draftSnapshot().scene),baseline);
  await page.locator('#returnToDraft').click();assert.equal(await page.locator('#canvas [data-endpoint]').count(),2);assert(await page.locator('#larger').isEnabled());
  assert.equal(requests.length,requestCount);assert.equal(authorizations.length,authorizationCount);
 }finally{
  await page.evaluate(()=>{returnToDraft();stop();const saved=window.qaLineRestore;scene=saved.scene;anchors=saved.anchors;selected=saved.selected;view=saved.view;focusIds=saved.focusIds;focusTone=saved.focusTone;
   editEvents=saved.editEvents;editHistory=saved.editHistory;payload.record=saved.record;delete window.qaLineRestore;draw();updateDraft();});
 }
};
try{
 await page.goto(appURL);await page.locator('#examples option:nth-child(2)').waitFor({state:'attached'});
 assert(await page.locator('#submissionScreen').isVisible());
 assert(await page.locator('#exportCase').isDisabled());
 await page.screenshot({path:path.join(out,'submission.png'),fullPage:true});
 const example=await page.locator('#examples option').evaluateAll(os=>os.find(o=>o.textContent.includes('PH_007'))?.value||os[1].value);
 await page.locator('#examples').selectOption(example);
 await page.waitForFunction(()=>!document.getElementById('submitImage').disabled&&document.getElementById('submissionPreview').src.startsWith('data:'));
 await page.locator('#explanation').fill('The bulbs are connected in parallel.');
 await page.locator('#submitImage').click();await waitForReply(1);
 assert(await page.locator('#feedbackScreen').isVisible());assert(!await page.locator('#submissionScreen').isVisible());
 assert(await page.locator('#exportCase').isEnabled());
 assert.equal(await page.locator('#questionHeading').textContent(),'Task');
 assert(!await page.locator('#questionText').isVisible());await page.locator('#questionHeading').click();assert(await page.locator('#questionText').isVisible());assert((await page.locator('#questionText').textContent()).includes('power supply'));await page.locator('#questionHeading').click();
 assert((await page.locator('.workspace-top').boundingBox()).height<70);
 const left=await page.locator('.model-panel').boundingBox(),right=await page.locator('.chat-panel').boundingBox();assert(left.x+left.width<=right.x);
 assert.equal(await page.locator('.fixed-feedforward').count(),0);assert.equal(await page.locator('#feedforwardPlan').count(),0);
 assert(await page.locator('#guidance').isVisible());assert.equal(await page.locator('.flow-arrow').count(),0);
 assert(await page.locator('#addNote').isDisabled());assert(await page.locator('#reviewChanges').isDisabled());assert.equal(await page.locator('#modelBadge').textContent(),'View only');assert(!await page.locator('#revisionReasonSection').isVisible());
 await showWithoutWorkflowChange(page.locator('#messages .assistant .inline-show').first());
 assert.deepEqual(await page.evaluate(()=>focusIds),strength);assert(await page.locator('#addNote').isDisabled());assert(await page.locator('#reviewChanges').isDisabled());assert(!await page.locator('#revisionReasonSection').isVisible());
 // Locked editor must reject direct handlers and keyboard/pointer mutations as well as disable buttons.
 const locked=await page.evaluate(()=>JSON.stringify(draftSnapshot().scene));
 await page.evaluate(()=>{selected=scene.objects[0].id;openText(true);openConnection();$('reset').onclick();$('smaller').onclick();deleteSelected();});
 assert(!await page.locator('#renameDialog').isVisible());assert(!await page.locator('#connectionDialog').isVisible());
 const part=page.locator('#canvas .object').first();await part.focus();await page.keyboard.press('ArrowRight');await page.keyboard.press('Delete');
 const box=await part.boundingBox();await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();await page.mouse.move(box.x+box.width/2+30,box.y+box.height/2+20);await page.mouse.up();
 assert.equal(await page.evaluate(()=>JSON.stringify(draftSnapshot().scene)),locked);
 await page.evaluate(()=>{selected=scene.relations[0].id;draw();$('smaller').onclick();$('larger').onclick();});
 const lockedRelation=page.locator('#canvas .relation').first();assert.equal(await page.locator('#canvas [data-endpoint]').count(),0);await lockedRelation.focus();await page.keyboard.press('ArrowRight');await page.keyboard.press('+');await page.keyboard.press('-');
 assert.equal(await page.evaluate(()=>JSON.stringify(draftSnapshot().scene)),locked);
 await page.screenshot({path:path.join(out,'feedback_view_only.png'),fullPage:true});
 await send('The branches connect across the same junctions.',2);
 await page.waitForFunction(()=>document.querySelectorAll('.flow-arrow').length===6);
 assert.equal(await page.locator('#mechanismCondition').textContent(),'If the switch is closed');assert.equal(await page.evaluate(()=>focusIds.length),6);assert.equal(await page.locator('#guidanceText').textContent(),'Exploring: L1 branch · L2 branch');assert.equal(await page.locator('.mechanism-track').count(),2);
 const before=await page.locator('.flow-arrow').first().getAttribute('transform');await page.waitForFunction(v=>document.querySelector('.flow-arrow').getAttribute('transform')!==v,before);
 assert(await page.evaluate(()=>scene.relations.every(r=>r.direction==='none')));
 await page.locator('#mechanismToggle').click();const paused=await page.locator('.flow-arrow').first().getAttribute('transform');await page.waitForTimeout(100);assert.equal(await page.locator('.flow-arrow').first().getAttribute('transform'),paused);await page.locator('#mechanismReplay').click();
 await page.screenshot({path:path.join(out,'matched_mechanism.png'),fullPage:true});
 assert.equal(await page.locator('[data-intent=hint]').count(),0,'Feedback must not offer a hint button');
 await send(typedHint,3);
 assert.equal(requests.at(-1).intent,'dialogue');assert.equal(requests.at(-1).message,typedHint);assert.equal(await page.evaluate(()=>feedbackTurns.at(-1).talk_move),'provide_hints_guidance');assert.equal(await page.locator('.flow-arrow').count(),0);assert(!await page.locator('#mechanismNotice').isVisible());assert(await page.locator('#guidance').isVisible());assert(await page.locator('#canvas .highlight').count()>0);
 assert((await page.locator('#guidanceText').textContent()).includes('Ammeter A2'));assert((await page.locator('#messages .assistant').last().textContent()).includes('Compare both'));assert(await page.locator('#addNote').isDisabled());
 await page.screenshot({path:path.join(out,'direct_hint_static_highlight.png'),fullPage:true});
 await showWithoutWorkflowChange(page.locator('#messages .assistant .inline-show').last());
 assert.deepEqual(await page.evaluate(()=>focusIds),issue);assert.equal(await page.locator('.flow-arrow').count(),0);assert(await page.locator('#addNote').isDisabled());
 assert.equal(await page.locator('[data-intent=begin_revision]').textContent(),'Begin a revision');
 const beforeBegin={feedback:requests.length,authorizations:authorizations.length,messages:await page.locator('#messages .message').count(),
  state:await page.evaluate(()=>JSON.stringify({feedbackSession,currentDrawingVersion,awaitingRevisionReason,committed,feedbackTurns,conversation}))};
 await page.locator('#chatInput').fill('My unsent thinking stays here.');holdAuthorization=true;
 await page.locator('[data-intent=begin_revision]').click();
 await page.waitForFunction(()=>!!revisionAuth);
 assert(await page.locator('#addNote').isEnabled(),'Begin a revision must unlock before authorization returns');
 assert(await page.locator('#reviewChanges').isDisabled());assert(await page.locator('#send').isDisabled());
 assert.equal(requests.length,beforeBegin.feedback);assert.equal(await page.locator('#messages .message').count(),beforeBegin.messages);
 assert.equal(await page.locator('#chatInput').inputValue(),'My unsent thinking stays here.');
 assert.equal(await page.evaluate(()=>JSON.stringify({feedbackSession,currentDrawingVersion,awaitingRevisionReason,committed,feedbackTurns,conversation})),beforeBegin.state);
 assert.equal(authorizations.length,beforeBegin.authorizations+1);assert.deepEqual(authorizations.at(-1),{session_id:'browser-fixture'});
 await page.evaluate(()=>{$('reviewChanges').onclick();});assert.equal(requests.length,beforeBegin.feedback);
 releaseAuthorization();holdAuthorization=false;await page.waitForFunction(()=>!revisionAuth);
 await page.locator('#chatInput').fill('');await waitForReply(3);
 assert(await page.locator('#addNote').isEnabled());assert(await page.locator('#revisionReasonSection').isVisible());assert.equal(await page.locator('#modelBadge').textContent(),'Revision mode');
 // Even a replay of the unchanged current submission is view only while revision permission stays intact.
 await showWithoutWorkflowChange(page.locator('#messages .assistant .inline-show').last());
 assert(await page.locator('#referenceNotice').isVisible());assert(await page.locator('#addNote').isDisabled());assert(!await page.locator('#revisionReasonSection').isVisible());assert(!await page.locator('#reviewChanges').isVisible());
 assert.equal(await page.evaluate(()=>editEnabled),true);await page.locator('#returnToDraft').click();assert(await page.locator('#addNote').isEnabled());assert(await page.locator('#revisionReasonSection').isVisible());
 await assertRelationEditing();
 await page.locator('#addNote').click();await page.locator('#newName').fill('My revision explanation');await page.locator('#renameForm button[type=submit]').click();
 const draft=await page.evaluate(()=>JSON.stringify(draftSnapshot().scene));
 await page.locator('#revisionReason').fill('I am comparing the earlier feedback with my private draft.');
 await showWithoutWorkflowChange(page.locator('#messages .assistant .inline-show').first());assert(await page.locator('#referenceNotice').isVisible());assert(await page.locator('#addNote').isDisabled());assert.equal(await page.evaluate(()=>JSON.stringify(draftSnapshot().scene)),draft);assert.equal(await page.evaluate(()=>editEnabled),true);await page.locator('#returnToDraft').click();assert(await page.locator('#addNote').isEnabled());
 await showWithoutWorkflowChange(page.locator('#messages .assistant .inline-show').nth(1));await page.waitForFunction(()=>document.querySelectorAll('.flow-arrow').length===6);assert(await page.locator('#referenceNotice').isVisible());assert.equal(await page.evaluate(()=>JSON.stringify(draftSnapshot().scene)),draft);assert.equal(await page.evaluate(()=>editEnabled),true);await page.screenshot({path:path.join(out,'historical_mechanism.png'),fullPage:true});await page.locator('#returnToDraft').click();assert(!await page.locator('#mechanismNotice').isVisible());await page.locator('#revisionReason').fill('');
 // Export while viewing historical cues and carrying private edits: only submitted evidence enters the case.
 await showWithoutWorkflowChange(page.locator('#messages .assistant .inline-show').nth(1));
 const caseExport=await exportWithoutWorkflowChange('html_export_fixture.html');
 assert(!caseExport.html.includes('My revision explanation'),'Unsubmitted draft changes must not be presented as submitted work');
 assert(await page.locator('#referenceNotice').isVisible());await page.locator('#returnToDraft').click();
 // Exit is permission-only: no model/chat turn, no draft commit or discard.
 await page.locator('#revisionReason').fill('A private explanation to preserve.');
 const preserved=()=>page.evaluate(()=>JSON.stringify({feedbackSession,currentDrawingVersion,awaitingRevisionReason,committed,feedbackTurns,conversation,
  draft:draftSnapshot(),history:editHistory,reason:$('revisionReason').value,explanation:$('explanation').value}));
 const beforeExit=await preserved(),beforeExitRequests=requests.length,beforeExitMessages=await page.locator('#messages .message').count();
 holdExit=true;await page.locator('#exitRevision').click();await page.waitForFunction(()=>!!revisionAuth);
 assert(await page.locator('#addNote').isDisabled());assert(await page.locator('#reviewChanges').isDisabled());assert(await page.locator('#send').isDisabled());
 assert.equal(await preserved(),beforeExit);assert.equal(requests.length,beforeExitRequests);assert.equal(await page.locator('#messages .message').count(),beforeExitMessages);
 assert.deepEqual(exitAuthorizations.at(-1),{session_id:'browser-fixture'});
 releaseExit();holdExit=false;await page.waitForFunction(()=>!revisionAuth);
 assert.equal(await preserved(),beforeExit);assert.equal(await page.locator('#modelBadge').textContent(),'View only');assert(!await page.locator('#exitRevision').isVisible());
 await showWithoutWorkflowChange(page.locator('#messages .assistant .inline-show').first());assert(await page.locator('#addNote').isDisabled());
 if(await page.locator('#returnToDraft').isVisible())await page.locator('#returnToDraft').click();
 await page.locator('[data-intent=begin_revision]').click();await page.waitForFunction(()=>!revisionAuth&&editEnabled);
 assert.equal(await preserved(),beforeExit);assert(await page.locator('#addNote').isEnabled());
 // Failed exits restore permission without adding any conversation or losing the draft.
 holdExit=true;failExit=true;await page.locator('#exitRevision').click();await page.waitForFunction(()=>!!revisionAuth);
 assert(await page.locator('#addNote').isDisabled());releaseExit();holdExit=false;await page.waitForFunction(()=>!revisionAuth);
 assert(await page.locator('#addNote').isEnabled());assert.equal(await preserved(),beforeExit);assert.equal(await page.locator('#messages .message').count(),beforeExitMessages);
 assert.match(await page.locator('#chatStatus').textContent(),/Revision could not be closed/);
 // Exit also works during a read-only Show replay, without converting it into editable geometry.
 await showWithoutWorkflowChange(page.locator('#messages .assistant .inline-show').first());await page.locator('#exitRevision').click();await page.waitForFunction(()=>!revisionAuth);
 assert(await page.locator('#referenceNotice').isVisible());assert.equal(await page.evaluate(()=>editEnabled),false);await page.locator('#returnToDraft').click();assert(await page.locator('#addNote').isDisabled());assert.equal(await preserved(),beforeExit);
 // A guidance reply that requests an actual diagram modification can unlock editing.
 await send('Help me make the indicated change.',4);assert.equal(await page.evaluate(()=>editEnabled),true);assert.equal(requests.at(-1).intent,'dialogue');
 // The response still refers to the submitted drawing, not the private unsent draft.
 assert.equal(await page.evaluate(()=>JSON.stringify(draftSnapshot().scene)),draft);
 if(await page.locator('#referenceNotice').isVisible())await page.locator('#returnToDraft').click();
 assert(await page.locator('#addNote').isEnabled());
 await page.locator('#revisionReason').fill('');
 await page.locator('#reviewChanges').click();await waitForReply(5);
 assert.equal(requests.at(-1).trigger,'workspace-complete');assert.equal(requests.at(-1).revision_reason,'');assert(requests.at(-1).scene.objects.some(o=>o.label==='My revision explanation'));
 assert.equal(await page.locator('#chatStatus').textContent(),'Explain why your ideas changed.');assert.equal(await page.evaluate(()=>JSON.stringify(committed.scene)),draft);assert(await page.locator('#revisionReasonSection').isVisible());assert(await page.locator('#addNote').isDisabled());assert(await page.locator('#reviewChanges').isDisabled());assert.equal(await page.evaluate(()=>editEnabled),false);
 await showWithoutWorkflowChange(page.locator('#messages .assistant .inline-show').first());if(await page.locator('#returnToDraft').isVisible())await page.locator('#returnToDraft').click();assert(await page.locator('#addNote').isDisabled(),'Returning from Show must keep reasoning-only feedback read only');
 await page.screenshot({path:path.join(out,'revision_reason_follow_up.png'),fullPage:true});
 await send('I changed it so the diagram matches the task.',6);assert(await page.locator('#addNote').isDisabled());assert(!await page.locator('#revisionReasonSection').isVisible());
 await send('I am done.',7);assert.equal(await page.locator('#messages .assistant').last().locator('.inline-show').count(),0);
 const palette=await page.locator('#messages .message:not(.error) .message-body').evaluateAll(es=>es.map(e=>({bg:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color,font:parseFloat(getComputedStyle(e).fontSize)})));assert.equal(new Set(palette.map(v=>v.bg)).size,1);assert.equal(new Set(palette.map(v=>v.color)).size,1);assert(palette.every(v=>v.font>=18));
 for(const role of ['assistant','user'])assert(await page.locator('.message.'+role+' .message-avatar').first().evaluate(img=>img.complete&&img.naturalWidth>0));
 await page.setViewportSize({width:860,height:1000});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(out,'feedback_tablet.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(out,'feedback_mobile.png'),fullPage:true});
 // The normal Feed forward path also enables revisions, and the reason travels with the committed geometry.
 await page.locator('#newSubmission').click();await page.locator('#submitImage').click();await waitForReply(1);
 await send('I know what to change now.',2);assert(await page.locator('#addNote').isEnabled());
 await page.locator('#revisionReason').fill('I am clarifying how the two paths connect.');await page.locator('#reviewChanges').click();await waitForReply(3);assert.equal(requests.at(-1).revision_reason,'I am clarifying how the two paths connect.');assert.equal(await page.locator('#revisionReason').inputValue(),'');assert(await page.locator('#addNote').isDisabled());assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 // Authorization failure rolls back permission, while immediate private edits remain recoverable.
 await page.locator('#newSubmission').click();await page.locator('#submitImage').click();await waitForReply(1);
 const beforeFailedAuthorization=requests.length;holdAuthorization=true;failAuthorization=true;
 await page.locator('[data-intent=begin_revision]').click();await page.waitForFunction(()=>!!revisionAuth);
 assert(await page.locator('#addNote').isEnabled());await page.locator('#addNote').click();await page.locator('#newName').fill('Private edit during authorization');await page.locator('#renameForm button[type=submit]').click();
 const recoverableDraft=await page.evaluate(()=>JSON.stringify(draftSnapshot()));
 releaseAuthorization();holdAuthorization=false;await page.waitForFunction(()=>!revisionAuth);
 assert(await page.locator('#addNote').isDisabled());assert(await page.locator('#reviewChanges').isDisabled());assert.equal(await page.evaluate(()=>JSON.stringify(draftSnapshot())),recoverableDraft);
 assert.equal(requests.length,beforeFailedAuthorization);assert.equal(await page.locator('#messages .user').count(),0);await waitForReply(1);
 assert.match(await page.locator('#chatStatus').textContent(),/Revision.+not be opened/i);assert.equal(await page.locator('#messages .error').count(),0);
 await page.locator('[data-intent=begin_revision]').click();await page.waitForFunction(()=>!revisionAuth&&editEnabled);assert(await page.locator('#addNote').isEnabled());assert.equal(await page.evaluate(()=>JSON.stringify(draftSnapshot())),recoverableDraft);assert.equal(requests.length,beforeFailedAuthorization);
 await page.locator('#newSubmission').click();const uploadPayload=await(await page.request.get(appURL+'/api/examples/'+example)).json();
 await page.route('**/api/reconstruct',route=>route.fulfill({status:202,json:{id:'mock-upload'}}));await page.route('**/api/jobs/mock-upload',route=>route.fulfill({json:{status:'completed',payload:uploadPayload}}));
 await page.locator('#file').setInputFiles({name:'diagram.png',mimeType:'image/png',buffer:Buffer.from(uploadPayload.original.split(',')[1],'base64')});failNext=true;await page.locator('#submitImage').click();await page.locator('#messages .error').waitFor();assert.equal(await page.locator('#reviewChanges').textContent(),'Retry feedback');await page.locator('#reviewChanges').click();await waitForReply(1);assert.equal(requests.at(-1).trigger,'submission');assert(await page.locator('#reviewChanges').isDisabled());
 const withFailure=await exportWithoutWorkflowChange('html_export_with_error_fixture.html');assert(withFailure.transcript.some(entry=>entry.error));
 assert.deepEqual(errors,[]);
 const checks={twoScreenLayout:true,taskCollapsedLiteralHeading:true,noPinnedFeedforward:true,htmlExportDownloadsStandaloneCase:true,htmlExportPreservesWorkflowAndDraft:true,htmlExportNoModelCalls:true,htmlExportKeepsActualMessagesAndErrors:true,htmlExportExcludesPrivateDraft:true,lockedUntilRevision:true,lockedPointerKeyboardAndHandlerMutations:true,lockedRelationKeyboardAndScale:true,editableRelationDragAndKeys:true,relationEndpointReshape:true,oppositeEndpointKeepsAttachment:true,relationScaleButtonsAndKeys:true,relationUndoRestoresExactScene:true,relationReplayLocksWithoutStateChange:true,noHintButton:true,typedHintUsesDialogueIntent:true,typedHintTriggersGuidance:true,hintUsesStaticCue:true,observationHintKeepsReadOnly:true,editGuidanceUnlocks:true,exitRevisionLocksImmediately:true,exitHasNoTutorOrCannedMessage:true,exitPreservesDraftReasonAndHistory:true,exitFailureRestoresPermission:true,exitDuringShowKeepsReferenceReadOnly:true,beginResumesPreservedDraft:true,mechanismMatchesText:true,animatedUndirectedRelations:true,focuslessMechanismAutoPlays:true,compactMechanismBanner:true,staticReferencesUnchanged:true,pauseReplayAndHistoricalShow:true,beginRevisionUnlocksImmediately:true,beginRevisionNoTutorOrCannedMessage:true,beginRevisionAuthorizesWithoutGeneratingFeedback:true,authorizationFailurePreservesPrivateEdits:true,showOnlyReplaysMatchingVisuals:true,showPreservesWorkflowAndRevisionState:true,feedForwardUnlocks:true,revisionReasonSent:true,missingReasonKeepsSubmittedGeometry:true,reasonFollowUp:true,authoritativeRelock:true,historicalReferencesReadOnly:true,draftPreserved:true,avatarsAndConsistentPalette:true,readableFonts:true,responsiveNoOverflow:true,uploadRetry:true,pageErrors:errors,provider:'mocked browser fixtures'};
 await fs.writeFile(path.join(out,'browser_checks.json'),JSON.stringify(checks,null,2));console.log(JSON.stringify(checks,null,2));
}finally{await browser.close();}
