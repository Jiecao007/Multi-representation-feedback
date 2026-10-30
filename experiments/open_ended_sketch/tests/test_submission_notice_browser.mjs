/* Private drafts get an action reminder only when the learner asks for review. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require('/Users/jiecao/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const app=fileURLToPath(new URL('../app/',import.meta.url));
const image='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP8zwACTGCSAQANHQEDgslx/wAAAABJRU5ErkJggg==';
const scene={title:'Draft submission example',objects:[{id:'part',label:'Student part',verbatim_text:'',kind:'box',bbox:{x:200,y:200,width:160,height:100},glyph:[{kind:'rect',points:[{x:0,y:0},{x:1000,y:1000}],text:'',filled:false}],members:[],origin:'student',confidence:1,evidence:'Visible student mark.',ambiguity:''}],relations:[]};
const payload={scene,record:{id:'submission-fixture',title:scene.title,width:1000,height:1000,task:'Explain your diagram.'},original:image,question:{text:'Explain your diagram.',image:''}};
const browser=await chromium.launch({headless:true,channel:'chrome'}),page=await browser.newPage({viewport:{width:1400,height:1000}});
const calls=[],authorizations=[],errors=[],unexpected=[];let version=0,drawingVersion=0,editable=false,pending=false,hintRemaining=0;
page.on('pageerror',error=>errors.push(error.message));
await page.route('http://submission.test/**',async route=>{
 const request=route.request(),p=new URL(request.url()).pathname;
 if(p==='/api/resume-case'){await route.fulfill({status:204,body:''});return;}
 if(p==='/api/examples'){await route.fulfill({json:[{id:payload.record.id,title:scene.title}]});return;}
 if(p==='/api/examples/'+payload.record.id){await route.fulfill({json:payload});return;}
 if(['/api/begin-revision','/api/end-revision'].includes(p)){
  authorizations.push(p);editable=p==='/api/begin-revision';await route.fulfill({json:{session_id:'submission-session',edit_enabled:editable,awaiting_revision_reason:pending}});return;
 }
 if(p==='/api/feedback'){
  const data=request.postDataJSON();calls.push(data);
  if(data.trigger==='message')hintRemaining=data.intent==='hint'?2:Math.max(0,hintRemaining-1);
  if(data.trigger==='submission'){drawingVersion=1;editable=false;}
  if(data.trigger==='workspace-complete'){drawingVersion++;editable=false;pending=true;}
  if(data.message.startsWith('My reason is')){pending=false;editable=false;}
  const content=data.trigger==='workspace-complete'?'Your updated diagram was submitted. What was your reason for the change?':'Let us continue thinking about your diagram.';
  await route.fulfill({json:{session_id:'submission-session',version:++version,drawing_version:drawingVersion,response_mode:data.trigger==='message'?'dialogue':'review',acknowledgment:'',acknowledgment_ids:[],follow_up:content,content,focus_ids:['part'],learning_goal:'Explain your diagram.',revision_plan:'',edit_enabled:editable,awaiting_revision_reason:pending,hint_request_pending:hintRemaining>0,hint_turns_remaining:hintRemaining,stage:pending?'revision-explanation':'thinking-dialogue',review:[],criteria:[],visual_action:'highlight',visual_delivery:'automatic'}});return;
 }
 if(p.startsWith('/api/')){unexpected.push(p);await route.fulfill({status:500,json:{error:'Unexpected API request.'}});return;}
 try{await route.fulfill({body:await fs.readFile(path.join(app,p==='/'?'index.html':p.slice(1))),contentType:p.endsWith('.js')?'application/javascript':p.endsWith('.css')?'text/css':p.endsWith('.svg')?'image/svg+xml':'text/html'});}catch{await route.fulfill({status:404,body:''});}
});
const state=()=>page.evaluate(()=>JSON.stringify({feedbackSession,currentDrawingVersion,editEnabled,awaitingRevisionReason,committed,feedbackTurns,conversation,interactionLog,draft:draftSnapshot()}));
const snapshot=()=>page.evaluate(()=>draftSnapshot());
async function send(text){await page.locator('#chatInput').fill(text);await page.locator('#send').click();await page.waitForFunction(()=>!chatBusy);}
async function begin(){await page.locator('[data-intent=begin_revision]').click();await page.waitForFunction(()=>!revisionAuth&&editEnabled);}
async function move(){await page.locator('#canvas .object').focus();await page.keyboard.press('ArrowRight');}
try{
 await page.goto('http://submission.test/',{waitUntil:'networkidle'});await page.locator('#examples').selectOption(payload.record.id);await page.waitForFunction(()=>!!scene&&!uploadBusy);
 await page.locator('#submitImage').click();await page.waitForFunction(()=>!!feedbackSession&&!chatBusy);
 await begin();const committed=await page.evaluate(()=>structuredClone(window.committed||committed));await move();const privateDraft=await snapshot();assert.notDeepEqual(privateDraft.scene,committed.scene);
 await send('Why does my diagram need this connection?');assert.equal(calls.at(-1).trigger,'message');assert.deepEqual(calls.at(-1).scene,committed.scene);assert.deepEqual(await snapshot(),privateDraft);
 await page.locator('[data-intent=hint]').click();await page.waitForFunction(()=>!chatBusy);assert.equal(calls.at(-1).intent,'hint');assert.deepEqual(calls.at(-1).scene,committed.scene);
 const afterHint=await state(),hintCalls=calls.length;
 await page.locator('#chatInput').fill('My unfinished answer');
 await page.locator('[data-intent=hint]').click();
 assert.equal(calls.length,hintCalls);assert.equal(await state(),afterHint);
 assert.equal(await page.locator('#chatStatus').textContent(),'Please answer the Dialogue question for 2 more turns, then try again.');
 assert.equal(await page.locator('#chatInput').inputValue(),'My unfinished answer');assert(await page.locator('#chatInput').evaluate(el=>el===document.activeElement));
 await send('The source supplies the energy.');
 await page.locator('[data-intent=hint]').click();assert.equal(calls.length,hintCalls+1);
 assert.equal(await page.locator('#chatStatus').textContent(),'Please answer the Dialogue question for 1 more turn, then try again.');
 await send('It transfers energy to the next part.');
 await page.locator('[data-intent=hint]').click();await page.waitForFunction(()=>!chatBusy);assert.equal(calls.length,hintCalls+3);assert.equal(calls.at(-1).intent,'hint');
 // Earlier Show remains a read-only reference; reminders still identify the actual private draft.
 await page.locator('.inline-show').first().click();assert(await page.locator('#referenceNotice').isVisible());
 const before=await state(),count=calls.length,messages=await page.locator('.message').count(),auth=authorizations.length;
 await send('I have finished my changes. Please review my diagram.');
 assert.equal(calls.length,count);assert.equal(authorizations.length,auth);assert.equal(await state(),before);assert.equal(await page.locator('.message').count(),messages);
 assert(await page.locator('#submissionNotice').isVisible());assert.equal(await page.locator('#submissionNotice').getAttribute('role'),'status');assert.equal(await page.locator('#submitDraftAction').textContent(),'Review changes');assert.equal(await page.locator('.message.error').count(),0);
 assert.match(await page.locator('#submissionNoticeText').textContent(),/have not been submitted/);assert.equal(await page.locator('#chatInput').inputValue(),'I have finished my changes. Please review my diagram.');
 await page.locator('#submitDraftAction').click();await page.waitForFunction(()=>!chatBusy&&currentDrawingVersion===2);
 assert.equal(calls.length,count+1);assert.equal(calls.at(-1).trigger,'workspace-complete');assert.deepEqual(calls.at(-1).scene,privateDraft.scene);assert(!await page.locator('#submissionNotice').isVisible());assert.equal(await page.locator('#modelBadge').textContent(),'View only');
 await send('My reason is that this position expresses the connection.');assert.equal(calls.at(-1).message,'My reason is that this position expresses the connection.');assert.equal(await page.evaluate(()=>awaitingRevisionReason),false);
 // Undo leaves edit history but no net new diagram: no submission reminder.
 await begin();const undoBaseline=await snapshot();await move();await page.locator('#undo').click();assert.deepEqual((await snapshot()).scene,undoBaseline.scene);
 const beforeUndoReview=calls.length;await send('Please review my diagram.');assert.equal(calls.length,beforeUndoReview+1);assert(!await page.locator('#submissionNotice').isVisible());
 // Exit preserves an unsubmitted draft. The reminder must not silently reopen editing.
 await move();const lockedDraft=await snapshot();await page.locator('#exitRevision').click();await page.waitForFunction(()=>!revisionAuth&&!editEnabled);
 const lockedBefore=await state(),lockedCalls=calls.length,lockedAuth=authorizations.length;
 await send('Can you check my revised drawing?');assert.equal(await state(),lockedBefore);assert.equal(calls.length,lockedCalls);assert.equal(authorizations.length,lockedAuth);
 assert.equal(await page.locator('#submitDraftAction').textContent(),'Begin a revision');assert.match(await page.locator('#submissionNoticeText').textContent(),/Begin a revision, then Review changes/);assert(await page.locator('#reviewChanges').isDisabled());
 await page.locator('#submitDraftAction').click();await page.waitForFunction(()=>!revisionAuth&&editEnabled);assert.equal(authorizations.length,lockedAuth+1);assert.equal(calls.length,lockedCalls);assert.equal(await page.locator('#submitDraftAction').textContent(),'Review changes');assert.deepEqual(await snapshot(),lockedDraft);
 await page.locator('#submitDraftAction').click();await page.waitForFunction(()=>!chatBusy&&currentDrawingVersion===3);assert.equal(calls.at(-1).trigger,'workspace-complete');assert.deepEqual(calls.at(-1).scene,lockedDraft.scene);
 assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[]);
 console.log('PASS submission reminder: real net changes + explicit review only, no invented dialogue or AI call, reasoning/hints preserved, historical Show isolation, CTA submission, pending reasons, Undo, and locked Begin-then-Review. All requests mocked.');
}finally{await browser.close();}
