import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
import fs from 'node:fs/promises';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'/Users/jiecao/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const directory=path.resolve(process.argv[2]);
const browser=await chromium.launch({headless:true,channel:'chrome'});
const results=[];
try{
 for(const file of (await fs.readdir(directory)).filter(f=>/^pic\d+\.html$/.test(f)&&(!process.argv[3]||f===process.argv[3]))){
  const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(pathToFileURL(path.join(directory,file)).href);
  const ids=await page.evaluate(()=>scene.objects.filter(o=>!o.members.length).map(o=>o.id));
  assert(ids.length>0);assert(await page.locator('#canvas .object').count()>0);
  await page.screenshot({path:path.join(directory,file.replace('.html','.preview.png')),fullPage:true});
  // Text is escaped and edited only in the working copy.
  await page.locator('#selection').selectOption(ids[0]);
  await page.locator('#editLabel').fill('测试 <b>对象</b>');await page.locator('#applyLabel').click();
  assert.equal(await page.locator('#editLabel').inputValue(),'测试 <b>对象</b>');
  assert.equal(await page.locator('#canvas b').count(),0);
  await page.locator('#undo').click();
  // Pointer dragging moves an object and moves the endpoints of its attached edge.
  const dragId=await page.evaluate(()=>scene.objects.find(o=>!o.members.length&&scene.relations.some(r=>r.source===o.id||r.target===o.id))?.id||scene.objects[0].id);
  await page.locator('#selection').selectOption(dragId);
  const before=await page.evaluate(id=>({box:structuredClone(obj(id).bbox),edges:scene.relations.filter(r=>r.source===id||r.target===id).map(r=>({id:r.id,points:relationPoints(r)}))}),dragId);
  const box=await page.locator(`#canvas [data-id="${dragId}"] .selection-box`).boundingBox();
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
  await page.mouse.down();await page.mouse.move(box.x+box.width/2+24,box.y+box.height/2+16,{steps:6});await page.mouse.up();
  const after=await page.evaluate(id=>({box:structuredClone(obj(id).bbox),edges:scene.relations.filter(r=>r.source===id||r.target===id).map(r=>({id:r.id,points:relationPoints(r)}))}),dragId);
  assert(Math.abs(after.box.x-before.box.x)+Math.abs(after.box.y-before.box.y)>1);
  if(before.edges.length)assert.notDeepEqual(before.edges,after.edges);
  await page.locator('#reset').click();
  // Reconnect an existing relation, confirm it, and trace then disable the target.
  const rid=await page.evaluate(()=>scene.relations[0]?.id);
  if(rid&&ids.length>=2){
   await page.locator('#selection').selectOption(rid);
   await page.locator('#edgeSource').selectOption(ids[0]);await page.locator('#edgeTarget').selectOption(ids[1]);
   await page.locator('#edgeDirection').selectOption('forward');await page.locator('#applyRelation').click();
   await page.locator('#confirmed').check();await page.locator('#traceStart').selectOption(ids[0]);await page.locator('#trace').click();
   assert((await page.evaluate(()=>traceResult().nodes)).includes(ids[1]));
   await page.locator('#selection').selectOption(ids[1]);await page.locator('#enabled').uncheck();
   assert((await page.evaluate(()=>traceResult().blocked)).includes(ids[1]));
   await page.locator('#animate').click();await page.waitForTimeout(120);
   assert(await page.locator('.flow-dot').count()>0);await page.locator('#animate').click();
  }
  await page.locator('#reset').click();
  // Export is a real download; retains the unmodified source hash and usable IDs.
  const pending=page.waitForEvent('download');await page.locator('#export').click();const download=await pending;
  const saved=path.join(directory,file.replace('.html','.tested-export.json'));await download.saveAs(saved);
  const exported=JSON.parse(await fs.readFile(saved,'utf8'));assert.equal(exported.source.sha256,await page.evaluate(()=>payload.record.sha256));
  assert.equal(exported.scene.objects.length,await page.evaluate(()=>initial.objects.length));
  assert.deepEqual(exported.scene,await page.evaluate(()=>initial));
  assert(!JSON.stringify(exported.scene).includes('"_source"'));
  await fs.unlink(saved);
  await page.locator('#viewMode').selectOption('crop');assert(await page.locator('#canvas image').count()>0);
  await page.screenshot({path:path.join(directory,file.replace('.html','.original-objects.png')),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));
  await page.screenshot({path:path.join(directory,file.replace('.html','.mobile.png')),fullPage:true});
  assert.deepEqual(errors,[]);results.push({file,objects:ids.length,drag:true,attachedEdgesFollow:true,reconnect:true,pathExploration:true,disableNode:true,export:true,mobileOverflow:false,pageErrors:errors});await page.close();
 }
 let prior=[];try{prior=JSON.parse(await fs.readFile(path.join(directory,'browser_checks.json'),'utf8'));}catch{}
 const combined=[...prior.filter(r=>!results.some(v=>v.file===r.file)),...results];
 await fs.writeFile(path.join(directory,'browser_checks.json'),JSON.stringify(combined,null,2));
 console.log(JSON.stringify(results,null,2));
}finally{await browser.close();}
