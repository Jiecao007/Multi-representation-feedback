/* Missing exporter is reported without losing an existing case; no AI requests. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require('/Users/jiecao/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const appURL=process.env.APP_URL||'http://127.0.0.1:8766';
const original=JSON.parse(await fs.readFile(new URL('../results/20260922T035929331824Z/pic1.scene.json',import.meta.url),'utf8'));
const image='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP8zwACTGCSAQANHQEDgslx/wAAAABJRU5ErkJggg==';
const payload={record:{id:'export-regression',title:'Generic transfer case',width:1800,height:1800,task:'Explain the transfer.'},
 scene:original,original:image,question:{text:'Explain the transfer.',image:''}};
const browser=await chromium.launch({headless:true,channel:'chrome'});
const workflow=page=>page.evaluate(()=>JSON.stringify({feedbackSession,committed,feedbackTurns,interactionLog,conversation,
 editEnabled,awaitingRevisionReason,currentDrawingVersion,initialExplanation,revision,scene:G.exportScene(scene,anchors),
 draft:draftSnapshot(),reason:document.getElementById('revisionReason').value}));
let passed=0;
try{
 for(const missing of [true,false]){
  const page=await browser.newPage({acceptDownloads:true}),calls=[],errors=[],resumeChecks=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/api/**',async route=>{
   const request=route.request();if(new URL(request.url()).pathname==='/api/examples'){await route.fulfill({json:[]});return;}
   if(new URL(request.url()).pathname==='/api/resume-case'){
    resumeChecks.push(request.method());await route.fulfill({status:204,body:''});return;
   }
   calls.push({method:request.method(),path:new URL(request.url()).pathname});
   await route.fulfill({status:404,json:{error:'No API action is expected in this export regression.'}});
  });
  if(missing)await page.route('**/case_export.js*',route=>route.fulfill({status:404,contentType:'text/plain',body:'Not found'}));
  await page.goto(appURL,{waitUntil:'networkidle'});
  await page.evaluate(data=>{
   load(data);initialExplanation='Initial explanation preserved for export.';feedbackSession='feedback_existing_export_case';
   committed={scene:G.copy(initial),explanation:initialExplanation,edits:[]};currentDrawingVersion=3;
   const response={content:'Tutor conversation preserved for export.',learning_goal:'Explain the transfer.',talk_move:'prompt_reflection',
    phase:'feed-back',stage:'thinking-dialogue',drawing_version:3,submitted_snapshot:G.copy(committed)};
   feedbackTurns=[response];conversation=[{role:'user',content:'Learner conversation preserved for export.'},{role:'assistant',content:response.content}];
   message('Learner conversation preserved for export.','user');message(response.content,'assistant');
   editEnabled=false;awaitingRevisionReason=true;document.getElementById('revisionReason').value='Existing unfinished reason.';
   scene.objects[0].label='PRIVATE DRAFT MUST NOT EXPORT';scene.objects[0].verbatim_text='PRIVATE DRAFT MUST NOT EXPORT';
   showScreen('feedback');updateDraft();buttons();
  },payload);
  const before=await workflow(page);
  if(missing){
   assert(await page.locator('#exportCase').isDisabled());
   const description=[await page.locator('#caseExportStatus').textContent(),await page.locator('#exportCase').getAttribute('title')].filter(Boolean).join(' ');
   assert(description.trim().length>=10,'A missing export module must have a clear explanatory status or title');
   assert.match(description,/export|module|reload|available|version|load/i);
   await page.evaluate(()=>buttons());assert.equal(await workflow(page),before,'Reporting missing exporter must preserve the full existing case');
   passed++;console.log('PASS missing export module is explained and preserves the existing session');
  }else{
   assert(await page.locator('#exportCase').isEnabled());
   const pending=page.waitForEvent('download');await page.locator('#exportCase').click();const download=await pending;
   assert.match(download.suggestedFilename(),/\.html$/i);const html=await fs.readFile(await download.path(),'utf8');
   assert(html.includes('Learner conversation preserved for export.'));assert(html.includes('Tutor conversation preserved for export.'));
   assert(html.includes('Initial explanation preserved for export.'));assert(!html.includes('PRIVATE DRAFT MUST NOT EXPORT'));
   assert.equal(await workflow(page),before,'Successful export must preserve pending reasons, workflow and private draft');
   passed++;console.log('PASS available export module downloads the preserved case without altering it');
  }
  assert.deepEqual(calls,[],'Export checks must not call model or revision APIs');assert.deepEqual(resumeChecks,['GET']);assert.deepEqual(errors,[]);
  await page.close();
 }
 console.log(`Missing export module: ${passed} browser checks passed, no AI or authorization calls.`);
}finally{await browser.close();}
