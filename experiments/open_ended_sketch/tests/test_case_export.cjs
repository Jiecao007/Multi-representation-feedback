/* Standalone case export checks: no server, model calls, or external requests. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('/Users/jiecao/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const Export=require('../app/case_export.js');
const source=JSON.parse(fs.readFileSync(path.join(__dirname,'../results/20260922T035929331824Z/pic1.scene.json'),'utf8'));
const copy=value=>JSON.parse(JSON.stringify(value));
const raster=base64=>'data:image/png;base64,'+base64;
const TASK_IMAGE=raster('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP8zwACTGCSAQANHQEDgslx/wAAAABJRU5ErkJggg==');
const STUDENT_IMAGE=raster('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEklEQVR4nGNkYPjPwMDAxAAGAAsfAQMU4wsAAAAAAElFTkSuQmCC');
const at=n=>'2026-10-11T12:00:'+String(n).padStart(2,'0')+'Z';
function scene(label){
 const value=copy(source);value.title='Generic transfer diagram';
 value.objects[0].label=label;value.objects[0].verbatim_text=label;
 value.objects[0].glyph=[{kind:'text',points:[{x:0,y:0}],text:label,filled:false}];
 return value;
}
function fixture(){
 const original=scene('ORIGINAL_SOURCE_LABEL'),revised=scene('REVISED_SOURCE_LABEL');
 const mechanism={condition:'If the transfer is active',paths:[{label:'TRANSFER_PATH_SENTINEL',steps:
  ['r1','r3','r7'].map(relation_id=>({relation_id,direction:'forward'}))}]};
 return {title:'Transfer exploration export',exported_at:at(10),
  question:{text:'TASK_SENTINEL: Show how the transfer connects these components.',image:TASK_IMAGE},
  learning_goal:'GOAL_SENTINEL: Explain the represented relationships.',
  learning_requirements:'REQUIREMENTS_SENTINEL: Compare the source and destination.',
  original_image:STUDENT_IMAGE,original_scene:original,initial_explanation:'INITIAL_EXPLANATION_SENTINEL: I connected the source to the destination.',
  committed_work:{scene:revised,explanation:'COMMITTED_EXPLANATION_SENTINEL: The connection begins at its source.',edits:[]},
  drawing_dimensions:{width:1800,height:1800},
  // Only the visible transcript is authoritative; a successful-turn log omits failures.
  turns:[{student:'TURN_ONLY_NOT_A_SECOND_MESSAGE',content:'TURN_ONLY_NOT_A_SECOND_MESSAGE',at:at(1)}],
  transcript:[
   {role:'user',text:'SUBMISSION_SENTINEL: Here is my drawing.',at:at(0),trigger:'submission'},
   {role:'assistant',text:'OPENING_SENTINEL: Nice work connecting these components!',at:at(1),
    feedback:{talk_move:'recognize_strengths',phase:'feedback',stage:'recognition',drawing_version:1},
    visual:{ids:['o1','r1'],action:'highlight',tone:'response',scene:original}},
   {role:'user',text:'FAILED_USER_SENTINEL: Can you explain this connection?',at:at(2)},
   {role:'system',text:'SYSTEM_ERROR_SENTINEL: Feedback could not be generated.',error:true,at:at(3)},
   {role:'user',text:'RETRY_SENTINEL: Please use the diagram to explain it.',at:at(4)},
   {role:'assistant',text:'TRACE_SENTINEL: Follow the source toward its destination.',at:at(5)},
   {role:'user',text:'REVIEW_SENTINEL: I adjusted the endpoint.',at:at(6),trigger:'workspace-complete',
    revision_reason:'REVISION_REASON_SENTINEL: The endpoint must match the transfer source.'},
   {role:'assistant',text:'REVIEW_REPLY_SENTINEL: This connection now matches your explanation.',at:at(7),
    feedback:{talk_move:'invite_dialogue',phase:'feed-forward',stage:'dialogue',drawing_version:2},
    visual:{ids:['o1','r1'],action:'trace',tone:'next',scene:revised,mechanism}}
  ]};
}
function freeze(value){
 if(value&&typeof value==='object'){Object.values(value).forEach(freeze);Object.freeze(value);}return value;
}
let passed=0;
async function check(name,run){await run();passed++;console.log('PASS '+name);}

(async()=>{
 assert.equal(typeof Export.build,'function');assert.equal(typeof Export.filename,'function');
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 const page=await browser.newPage();const external=[],errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 await page.route('**/*',route=>{external.push(route.request().url());return route.abort();});
 async function render(data){const html=Export.build(data);assert.equal(typeof html,'string');await page.goto('about:blank');await page.setContent(html,{waitUntil:'load'});return html;}
 try{
  const data=fixture();let html;
  await check('complete self-contained document opens without runtime errors',async()=>{
   html=await render(data);assert.match(html,/<!doctype html>/i);assert.match(html,/<html\b/i);assert.match(html,/<\/html>/i);
   assert.equal(await page.title(),data.title);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
   assert.equal(await page.locator('script[src],link[rel="stylesheet"][href]').count(),0);
  });
  await check('all actual messages, including failed user and system error, remain in order once',async()=>{
   const entries=await page.locator('.transcript-entry').evaluateAll(nodes=>nodes.map(n=>({text:n.textContent,role:n.dataset.role,error:n.dataset.error})));
   assert.equal(entries.length,data.transcript.length);
   for(let i=0;i<entries.length;i++)assert(entries[i].text.includes(data.transcript[i].text),`Missing or misplaced transcript entry ${i}`);
   assert.equal(entries[2].role,'user');assert.equal(entries[3].role,'system');assert.equal(entries[3].error,'true');
   const all=await page.locator('body').textContent();assert(!all.includes('TURN_ONLY_NOT_A_SECOND_MESSAGE'));
   for(const item of data.transcript)assert.equal(all.split(item.text).length-1,1,'Transcript text must not be duplicated');
  });
  await check('task figure and original student picture are embedded raster images',async()=>{
   const images=await page.locator('img').evaluateAll(nodes=>nodes.map(n=>({src:n.getAttribute('src'),width:n.naturalWidth,height:n.naturalHeight})));
   for(const src of [TASK_IMAGE,STUDENT_IMAGE]){
    const image=images.find(n=>n.src===src);assert(image,'Missing embedded task/student image');assert.equal(image.width,2);assert.equal(image.height,2);
   }
  });
  await check('goals, requirements, explanations and revision reasons remain available',async()=>{
   const all=await page.locator('body').textContent();
   for(const value of [data.question.text,data.learning_goal,data.learning_requirements,data.initial_explanation,
                       data.committed_work.explanation,data.transcript[6].revision_reason])assert(all.includes(value),'Missing exported learning context: '+value);
  });
  await check('standalone and combined dialogue moves retain distinct ordered labels',async()=>{
   for(const [primary,active,label] of [
    ['revoice',['revoice'],'Revoice'],
    ['ask_for_clarification',['ask_for_clarification'],'Ask for clarification'],
    ['revoice',['revoice','ask_for_clarification'],'Revoice + Ask for clarification']
   ]){
    const candidate=fixture();candidate.transcript[1].feedback={
     talk_move:primary,talk_moves:active,phase:'feedback',stage:'thinking-dialogue',drawing_version:1};
    await render(candidate);const details=await page.locator('.transcript-entry').nth(1).locator('.move-details').textContent();
    assert(details.includes(label),details);assert(details.includes('Supporting learning'),details);
   }
  });
  await check('legacy singular move metadata remains readable without changing stored input',async()=>{
   const candidate=fixture();candidate.transcript[1].feedback.talk_move='revoice_or_clarify';
   const before=JSON.stringify(candidate);await render(candidate);
   const details=await page.locator('.transcript-entry').nth(1).locator('.move-details').textContent();
   assert(details.includes('Revoice or clarify'));assert.equal(JSON.stringify(candidate),before);
  });
  await check('each text–visual reference retains its matching submitted scene',async()=>{
   await render(data);
   const oldReference=page.locator('.transcript-entry').nth(1).locator('.diagram-reference');
   const newReference=page.locator('.transcript-entry').nth(7).locator('.diagram-reference');
   assert.equal(await oldReference.count(),1);assert.equal(await newReference.count(),1);
   assert.equal(await oldReference.locator('svg').count(),1);assert.equal(await newReference.locator('svg').count(),1);
   assert((await oldReference.textContent()).includes('ORIGINAL_SOURCE_LABEL'));
   assert(!(await oldReference.textContent()).includes('REVISED_SOURCE_LABEL'));
   assert((await newReference.textContent()).includes('REVISED_SOURCE_LABEL'));
   assert(!(await newReference.textContent()).includes('ORIGINAL_SOURCE_LABEL'));
  });
  await check('mechanism condition and native path replay remain attached to their feedback',async()=>{
   const entry=page.locator('.transcript-entry').nth(7);
   assert((await entry.locator('.mechanism-condition').textContent()).includes('If the transfer is active'));
   assert((await entry.textContent()).includes('TRANSFER_PATH_SENTINEL'));
   assert.equal(await entry.locator('button.replay-mechanism').count(),1);
   await entry.locator('.diagram-reference').evaluate(n=>{n.open=true;});await entry.locator('button.replay-mechanism').click();
   assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  });
  await check('UI errors stored with assistant role are still distinct system notices',async()=>{
   const candidate=fixture();candidate.transcript[3].role='assistant';await render(candidate);
   const entry=page.locator('.transcript-entry').nth(3);
   assert.equal(await entry.getAttribute('data-role'),'system');assert.equal(await entry.getAttribute('data-error'),'true');
   assert((await entry.textContent()).includes(candidate.transcript[3].text));
  });
  await check('HTML and script-closing payloads stay literal text in titles, dialogue and diagram labels',async()=>{
   const attack='INJECTION_SENTINEL </script><script>window.__caseExportAttack=1</script><img src=x onerror="window.__caseExportAttack=2"> & "quoted"';
   const hostile=fixture();hostile.title=attack;hostile.question.text=attack;hostile.learning_requirements=attack;
   hostile.initial_explanation=attack;hostile.transcript[0].text=attack;hostile.transcript[6].revision_reason=attack;
   hostile.original_scene=scene(attack);hostile.committed_work.scene=scene(attack);
   hostile.transcript[1].visual.scene=scene(attack);hostile.transcript[7].visual.scene=scene(attack);
   hostile.transcript[4].text='javascript:window.__caseExportAttack=3';hostile.transcript[4].href='javascript:window.__caseExportAttack=4';
   await render(hostile);
   assert.equal(await page.title(),attack);assert((await page.locator('.transcript-entry').first().textContent()).includes(attack));
   assert((await page.locator('.transcript-entry').nth(1).locator('.diagram-reference svg').textContent()).includes(attack));
   assert.equal(await page.evaluate(()=>window.__caseExportAttack),undefined);
   assert.equal(await page.locator('[onerror],[onload],[onclick],a[href^="javascript:"],a[href^="http"]').count(),0);
   assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  });
  await check('untrusted external, javascript, SVG and wrong-magic images are excluded',async()=>{
   const badImages=['https://invalid.example/private.png','javascript:window.__caseExportAttack=5',
    'data:image/svg+xml;base64,'+Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" onload="window.__caseExportAttack=6"/>').toString('base64'),
    'data:image/png;base64,'+Buffer.from('<svg onload="window.__caseExportAttack=7"/>').toString('base64'),
    'data:text/html;base64,'+Buffer.from('<script>window.__caseExportAttack=8</script>').toString('base64')];
   for(const bad of badImages){
    const candidate=fixture();candidate.question.image=bad;candidate.original_image=bad;await render(candidate);
    assert.equal(await page.locator('img').count(),0);assert.equal(await page.evaluate(()=>window.__caseExportAttack),undefined);
   }
   assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  });
  await check('private session/model/debug fields are never serialized',async()=>{
   const candidate=fixture();const secret='PRIVATE_EXPORT_SENTINEL_49fd1';
   candidate.session_id=secret;candidate.model=secret;candidate.debug={key:secret};candidate.state={key:secret};
   candidate.question.debug=secret;candidate.turns[0].assessment={private_criteria:secret};
   candidate.transcript[1].feedback.debug=secret;candidate.transcript[1].feedback.model=secret;
   candidate.transcript[1].visual.scene.model_debug=secret;candidate.committed_work.scene.objects[0].debug=secret;
   const result=await render(candidate);assert(!result.includes(secret));assert(!(await page.locator('body').textContent()).includes(secret));
  });
  await check('build and filename do not mutate even recursively frozen input',async()=>{
   const candidate=fixture(),before=JSON.stringify(candidate);freeze(candidate);
   const result=Export.build(candidate);assert.equal(typeof result,'string');Export.filename(candidate);
   assert.equal(JSON.stringify(candidate),before);
  });
  await check('filename remains an HTML basename for unsafe or empty titles',async()=>{
   for(const title of ['../../secret\\folder:<bad>|"?*.json','\u0000\n\r\tunsafe title','',null,'Transfer / 日本語 / 中文']){
    const name=Export.filename({title});assert.equal(typeof name,'string');assert.match(name,/\.html$/i);
    assert.equal(path.basename(name),name);assert(!/[\\/:*?"<>|\u0000-\u001f]/.test(name));assert(!name.includes('..'));
    assert(name.length>5);assert(name.length<256);
   }
  });
  console.log(`Case export: ${passed} checks passed (offline HTML, complete transcript, references, safety, immutable input).`);
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
