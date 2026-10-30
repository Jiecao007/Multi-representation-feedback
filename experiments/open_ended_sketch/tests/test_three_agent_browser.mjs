import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require('/Users/jiecao/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base=process.env.THREE_AGENT_BROWSER_URL;
const out=process.env.THREE_AGENT_BROWSER_OUT;
assert(base&&out,'Run this script through run_three_agent_browser.py.');
await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,channel:'chrome'});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[],external=[],requests=[],replies=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/feedback'))requests.push(r.postDataJSON());});
await page.route('**/*',route=>{
 const url=route.request().url();
 if(url.startsWith(base+'/')||url==='about:blank'||url.startsWith('data:')||url.startsWith('blob:'))return route.continue();
 external.push(url);return route.abort();
});
async function idle(){await page.waitForFunction(()=>!chatBusy&&!uploadBusy&&!revisionAuth);}
async function feedback(action){
 const responsePromise=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/api/feedback'));
 await action();const response=await responsePromise;
 const result=await response.json();assert.equal(response.status(),200,JSON.stringify(result));
 await idle();assert.equal(await page.locator('#messages .error').count(),0);
 replies.push(result);return result;
}
try{
 await page.goto(base);await page.locator('#examples option[value="math-2"]').waitFor({state:'attached'});
 await page.locator('#examples').selectOption('math-2');await page.waitForFunction(()=>!!scene&&!uploadBusy);
 await page.locator('details.requirements summary').click();
 await page.locator('#goals').fill('Represent the first card as an arrow.');
 await page.locator('#explanation').fill('I drew the number line and its labels.');
 const initial=await feedback(()=>page.locator('#submitImage').click());
 assert.equal(initial.drawing_version,1);assert.equal(initial.talk_move,'recognize_strengths');
 assert.equal(await page.locator('#canvas g.relation').count(),0);
 assert(await page.locator('#connect').isDisabled());
 await page.screenshot({path:path.join(out,'01_initial.png'),fullPage:true});

 await page.locator('#chatInput').fill('I can identify zero.');
 const ordinary=await feedback(()=>page.locator('#send').click());
 assert.equal(ordinary.drawing_version,1);assert.equal(requests.length,2);
 const hint=await feedback(()=>page.locator('[data-intent="hint"]').click());
 assert.equal(hint.talk_move,'provide_hints_guidance');assert.equal(hint.edit_enabled,true);
 assert(await page.locator('#connect').isEnabled());
 assert.equal(await page.locator('#canvas g.relation').count(),0,'The Tutor must not draw the arrow.');
 await page.screenshot({path:path.join(out,'02_modeling_hint_editable.png'),fullPage:true});

 await page.locator('#connect').click();
 await page.locator('#connectionFrom').selectOption('label_zero');
 await page.locator('#connectionTo').selectOption('label_minus6');
 await page.locator('#connectionShape').selectOption('curved');
 await page.locator('#connectionDirection').selectOption('forward');
 await page.locator('#connectionLabel').fill('−6');
 await page.locator('#connectionForm button[type="submit"]').click();
 assert.equal(await page.locator('#canvas g.relation').count(),1);
 assert.equal(requests.length,3,'Editing the draft must not trigger Evaluation.');
 const reviewed=await feedback(()=>page.locator('#reviewChanges').click());
 assert.equal(reviewed.drawing_version,2);
 assert.equal(requests.length,4);assert.equal(requests.at(-1).trigger,'workspace-complete');
 assert.equal(requests.at(-1).scene.relations.length,1);
 await page.screenshot({path:path.join(out,'03_reviewed_arrow.png'),fullPage:true});

 const savePromise=page.waitForEvent('download');await page.locator('#save').click();
 const save=await savePromise;const savedPath=path.join(out,'browser_case.exploration.json');await save.saveAs(savedPath);
 const saved=JSON.parse(await fs.readFile(savedPath,'utf8'));
 assert.equal(saved.committed_work.scene.relations.length,1);
 assert.equal(saved.feedback_turns.length,4);
 const htmlPromise=page.waitForEvent('download');await page.locator('#exportCase').click();
 const htmlDownload=await htmlPromise;const htmlPath=path.join(out,'browser_case.html');await htmlDownload.saveAs(htmlPath);
 const offline=await browser.newPage();const offlineRequests=[],offlineErrors=[];
 offline.on('pageerror',e=>offlineErrors.push(e.message));
 await offline.route('**/*',route=>{offlineRequests.push(route.request().url());return route.abort();});
 await offline.setContent(await fs.readFile(htmlPath,'utf8'),{waitUntil:'load'});
 const text=await offline.locator('body').textContent();assert(text.includes('Use ↗ Connect'));
 assert.deepEqual(offlineRequests,[]);assert.deepEqual(offlineErrors,[]);await offline.close();
 assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
 await fs.writeFile(path.join(out,'browser_receipt.json'),JSON.stringify({status:'passed',requests:requests.map(r=>({trigger:r.trigger,intent:r.intent})),
  replies:replies.map(r=>({talk_move:r.talk_move,drawing_version:r.drawing_version,edit_enabled:r.edit_enabled})),page_errors:errors,external_requests:external},null,2)+'\n');
 console.log('PASS initial feedback, ordinary dialogue, editable modeling hint, real Connect draft, review, JSON save, offline HTML export.');
}finally{await browser.close();}
