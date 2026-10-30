/* Server permissions remain authoritative; pedagogical labels never unlock the editor. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require('/Users/jiecao/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const app=fileURLToPath(new URL('../app/',import.meta.url));
const image='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP8zwACTGCSAQANHQEDgslx/wAAAABJRU5ErkJggg==';
const part=(id,x)=>({id,label:id,verbatim_text:'',kind:'box',bbox:{x,y:180,width:100,height:80},glyph:[{kind:'rect',points:[{x:0,y:0},{x:1000,y:1000}],text:'',filled:false}],members:[],origin:'student',confidence:1,evidence:'Student-drawn part.',ambiguity:''});
const scene={title:'Generic relationship diagram',objects:[part('part_a',120),part('part_b',650)],relations:[{id:'line',source:'part_a',target:'part_b',points:[{x:220,y:220},{x:650,y:220}],direction:'none',verbatim_text:'',label_position:{x:435,y:200},interpretation:'Student-drawn connection.',origin:'student',confidence:1,evidence:'Visible connection.',ambiguity:'',color:null}]};
const payload={scene,record:{id:'permission-fixture',title:scene.title,width:1000,height:1000,task:'Explain how the two parts connect.'},original:image,question:{text:'Explain how the two parts connect.',image:''}};
const browser=await chromium.launch({headless:true,channel:'chrome'}),page=await browser.newPage({viewport:{width:1400,height:1000}});
const errors=[],feedbackCalls=[],authCalls=[],unexpected=[];let version=0,pending=false,failNext=false;
page.on('pageerror',error=>errors.push(error.message));
const policies={
 'I need help thinking about the connection.':{talk_move:'provide_hints_guidance',phase:'feedback',follow_up:'Compare the two parts and explain the connection.',edit_enabled:false},
 'What should I consider next?':{talk_move:'propose_revision_plan',phase:'feedforward',stage:'revision-planning',revision_plan:'A plan may be discussed later.',follow_up:'Consider how the connection relates to the goal.',edit_enabled:false},
 'I want to revise my diagram now.':{talk_move:'provide_hints_guidance',phase:'feedback',follow_up:'You can revise your diagram now.',edit_enabled:true,awaiting_revision_reason:true},
 'I understand the connection and am ready for the plan.':{talk_move:'propose_revision_plan',phase:'feedforward',stage:'revision-planning',follow_up:'Move the second part so the intended connection is visible.',edit_enabled:true},
 'Let us discuss why the connection matters.':{talk_move:'invite_elaboration_reasoning',phase:'feedback',stage:'revision-explanation',follow_up:'Why does this connection express your intended relationship?',edit_enabled:false,awaiting_revision_reason:true},
 'Give me guidance for making the change.':{talk_move:'provide_hints_guidance',phase:'feedback',stage:'thinking-dialogue',follow_up:'Move the second part to the indicated position, then review your change.',edit_enabled:true,guidance_requires_edit:true},
};
await page.route('http://permission.test/**',async route=>{
 const request=route.request(),p=new URL(request.url()).pathname;
 if(p==='/api/resume-case'){await route.fulfill({status:204,body:''});return;}
 if(p==='/api/examples'){await route.fulfill({json:[{id:payload.record.id,title:scene.title}]});return;}
 if(p==='/api/examples/'+payload.record.id){await route.fulfill({json:payload});return;}
 if(['/api/begin-revision','/api/end-revision'].includes(p)){
  authCalls.push({path:p,data:request.postDataJSON()});await route.fulfill({json:{session_id:'permission-session',edit_enabled:p==='/api/begin-revision',awaiting_revision_reason:pending}});return;
 }
 if(p==='/api/feedback'){
  const data=request.postDataJSON();feedbackCalls.push(data);
  if(failNext){failNext=false;await route.fulfill({status:502,json:{error:'A mocked reply failed.'}});return;}
  const initial=data.trigger==='submission',review=data.trigger==='workspace-complete';
  const policy=initial?{talk_move:'recognize_strengths',phase:'feedback',follow_up:'You have connected the two parts. What does that connection mean?',edit_enabled:false,focus_ids:['part_a'],visual_action:'highlight',visual_delivery:'automatic'}:review?policies['Let us discuss why the connection matters.']:policies[data.message];
  assert(policy,'The matrix must specify every feedback reply.');pending=policy.awaiting_revision_reason===true;
  const response={session_id:'permission-session',version:++version,drawing_version:review?2:1,response_mode:initial||review?'review':'dialogue',acknowledgment:'',acknowledgment_ids:[],follow_up:policy.follow_up,content:policy.follow_up,focus_ids:[],learning_goal:'Explain the intended relationship between the parts.',revision_plan:'',edit_enabled:false,awaiting_revision_reason:false,stage:'thinking-dialogue',review:[],criteria:[],visual_action:'none',visual_delivery:'none',...policy};
  await route.fulfill({json:response});return;
 }
 if(p.startsWith('/api/')){unexpected.push(p);await route.fulfill({status:500,json:{error:'Unexpected API request.'}});return;}
 const name=path.join(app,p==='/'?'index.html':p.slice(1));
 try{await route.fulfill({body:await fs.readFile(name),contentType:p.endsWith('.js')?'application/javascript':p.endsWith('.css')?'text/css':p.endsWith('.svg')?'image/svg+xml':'text/html'});}catch{await route.fulfill({status:404,body:''});}
});
const draft=()=>page.evaluate(()=>JSON.stringify(draftSnapshot()));
const state=()=>page.evaluate(()=>JSON.stringify({feedbackSession,currentDrawingVersion,editEnabled,awaitingRevisionReason,committed,feedbackTurns,conversation,interactionLog,draft:draftSnapshot(),reason:$('revisionReason').value}));
async function expectPermission(editable){
 await page.waitForFunction(want=>!chatBusy&&!revisionAuth&&editEnabled===want,editable);
 assert.equal(await page.locator('#addNote').isEnabled(),editable);assert.equal(await page.locator('#reviewChanges').isEnabled(),editable);
 assert.equal(await page.locator('#canvas').getAttribute('data-editable'),String(editable));
 if(!editable)await page.waitForFunction(()=>document.querySelectorAll('#canvas [data-endpoint]').length===0);
}
async function send(text){await page.locator('#chatInput').fill(text);await page.locator('#send').click();await page.waitForFunction(()=>!chatBusy);}
async function replay(){
 const before=await state(),feedback=feedbackCalls.length,auth=authCalls.length;await page.locator('.inline-show').first().click();
 assert.equal(await state(),before);assert.equal(feedbackCalls.length,feedback);assert.equal(authCalls.length,auth);assert(await page.locator('#addNote').isDisabled());
 if(await page.locator('#returnToDraft').isVisible())await page.locator('#returnToDraft').click();assert.equal(await state(),before);
}
async function begin(){
 const before=await page.evaluate(()=>JSON.stringify({feedbackSession,currentDrawingVersion,awaitingRevisionReason,committed,feedbackTurns,conversation,interactionLog,draft:draftSnapshot(),reason:$('revisionReason').value})),count=feedbackCalls.length;
 await page.locator('[data-intent=begin_revision]').click();await expectPermission(true);
 assert.equal(feedbackCalls.length,count,'Begin must not call the tutoring endpoint or create a canned student turn');
 assert.equal(await page.evaluate(()=>JSON.stringify({feedbackSession,currentDrawingVersion,awaitingRevisionReason,committed,feedbackTurns,conversation,interactionLog,draft:draftSnapshot(),reason:$('revisionReason').value})),before);
}
try{
 await page.goto('http://permission.test/',{waitUntil:'networkidle'});await page.locator('#examples').selectOption(payload.record.id);await page.waitForFunction(()=>!!scene&&!uploadBusy);
 await page.locator('#submitImage').click();await expectPermission(false);await replay();
 await send('I need help thinking about the connection.');await expectPermission(false);
 await send('What should I consider next?');await expectPermission(false);assert.equal(await page.evaluate(()=>feedbackTurns.at(-1).phase),'feedforward');
 await begin();await page.locator('#canvas .relation').focus();await page.keyboard.press('Enter');await page.waitForFunction(()=>document.querySelectorAll('#canvas [data-endpoint]').length===2);
 const beforeEdit=await draft();await page.locator('#canvas .relation').focus();await page.keyboard.press('ArrowRight');assert.notEqual(await draft(),beforeEdit);
 await page.locator('#revisionReason').fill('My unsent revision explanation.');const privateDraft=await draft();
 await send('Let us discuss why the connection matters.');await expectPermission(false);
 assert.equal(await draft(),privateDraft);assert.equal(await page.locator('#revisionReason').inputValue(),'My unsent revision explanation.');assert(await page.locator('#revisionReasonSection').isVisible());
 assert.match(await page.locator('#canvas .object').first().getAttribute('aria-label'),/View only/,'Permission changes must refresh object accessibility labels');
 const locked=await draft();await page.evaluate(()=>{selected='line';$('reset').onclick();$('smaller').onclick();$('larger').onclick();deleteSelected();openText(true);openConnection();});
 await page.locator('#canvas .relation').focus();await page.keyboard.press('ArrowRight');await page.keyboard.press('+');await page.keyboard.press('Delete');assert.equal(await draft(),locked);
 assert(!await page.locator('#renameDialog').isVisible());assert(!await page.locator('#connectionDialog').isVisible());await replay();await expectPermission(false);
 await begin();assert.equal(await draft(),privateDraft);assert.equal(await page.evaluate(()=>awaitingRevisionReason),true);await replay();await expectPermission(true);
 const beforeExit=await draft(),exitMessages=await page.locator('.message').count(),exitFeedback=feedbackCalls.length;await page.locator('#exitRevision').click();await expectPermission(false);
 assert.equal(await draft(),beforeExit);assert.equal(await page.locator('.message').count(),exitMessages);assert.equal(feedbackCalls.length,exitFeedback);assert.equal(await page.locator('#revisionReason').inputValue(),'My unsent revision explanation.');
 await send('I want to revise my diagram now.');await expectPermission(true);assert.equal(feedbackCalls.at(-1).intent,'dialogue');assert.equal(await page.locator('.message.user .message-text').last().textContent(),'I want to revise my diagram now.');
 await send('I understand the connection and am ready for the plan.');await expectPermission(true);
 await send('Let us discuss why the connection matters.');await expectPermission(false);
 await send('I need help thinking about the connection.');await expectPermission(false);
 await send('Give me guidance for making the change.');await expectPermission(true);assert.equal(await draft(),privateDraft);
 await page.locator('#revisionReason').fill('');await page.locator('#reviewChanges').click();await expectPermission(false);assert.equal(feedbackCalls.at(-1).trigger,'workspace-complete');
 assert.equal(await page.evaluate(()=>awaitingRevisionReason),true);assert(await page.locator('#revisionReasonSection').isVisible());await replay();await expectPermission(false);
 failNext=true;await send('I need help thinking about the connection.');await expectPermission(false);assert.equal(await page.locator('.message.error').count(),1);assert.equal(await draft(),privateDraft);
 assert.equal(authCalls.filter(call=>call.path==='/api/begin-revision').length,2);assert.equal(authCalls.filter(call=>call.path==='/api/end-revision').length,1);
 assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[]);
 console.log('PASS revision permissions: server flag only, Begin/no canned turn, natural request, concrete Feed forward, actionable guidance, reasoning relock and handle/aria redraw, locked mutations, Show isolation, pending reason/draft preservation, Exit, and failed reply. All requests mocked.');
}finally{await browser.close();}
