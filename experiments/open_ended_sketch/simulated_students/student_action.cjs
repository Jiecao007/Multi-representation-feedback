/* Semantic editor API adapter, not a mouse/drag usability test. No domain repair rules. */
'use strict';
const fs=require('node:fs'),path=require('node:path');
const G=require('../app/geometry.js'),E=require('../app/editor.js'),Export=require('../app/case_export.js');
let input='';process.stdin.on('data',chunk=>input+=chunk);process.stdin.on('end',async()=>{
 try{
  const data=JSON.parse(input),scene=G.copy(data.scene),before=G.copy(scene),anchors=G.anchors(scene),action=data.action||{kind:'none'};
  let accepted=true,reason='No drawing operation requested.';
  const target=scene.objects.find(o=>o.id===action.target_id)||scene.relations.find(r=>r.id===action.target_id);
  if(['move','reshape_endpoint'].includes(action.kind)){
   if(!data.edit_enabled){accepted=false;reason='Editing is disabled; begin a revision first.';}
   else if(!target){accepted=false;reason='No visible element matches the requested locator.';}
   else if(!Number.isFinite(action.x)||!Number.isFinite(action.y)){accepted=false;reason='Finite x and y coordinates are required.';}
   else if(action.kind==='move'){
    G.move(scene,target.id,action.x,action.y,anchors);
    if(scene.relations.includes(target))for(const end of ['source','target'])E.reattach(scene,target.id,end,anchors);
    reason='Applied one move with the existing geometry/editor behavior; no circuit rewiring or correctness repair was added.';
   }else if(!scene.relations.includes(target)||!['source','target'].includes(action.endpoint)){
    accepted=false;reason='Endpoint dragging requires a line and source or target endpoint.';
   }else{
    G.reshapeRelation(scene,target.id,action.endpoint,action.x,action.y,anchors);E.reattach(scene,target.id,action.endpoint,anchors);
    reason='Applied one endpoint drag and the ordinary proximity attachment.';
   }
  }else if(action.kind!=='none'){accepted=false;reason='This adapter only performs none, move and reshape_endpoint.';}
  const after=G.exportScene(scene,anchors),changed=JSON.stringify(after)!==JSON.stringify(before);
  if(data.render_path){
   const pw=require(process.env.SIMULATED_STUDENT_PLAYWRIGHT||'/Users/jiecao/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
   const browser=await pw.chromium.launch({headless:true,channel:'chrome'});
   try{
    const page=await browser.newPage({viewport:{width:1100,height:900}});await page.route('**/*',route=>route.abort());
    const html=Export.build({title:'Student drawing',original_scene:after,drawing_dimensions:data.dimensions,transcript:[]});
    const diagram=html.match(/<svg class="diagram-svg"[\s\S]*?<\/svg>/)[0];
    fs.writeFileSync(data.render_path.replace(/\.png$/,'.svg'),diagram);
    await page.setContent('<html><body style="margin:0;background:white">'+diagram+'</body></html>');
    await page.locator('svg').screenshot({path:data.render_path});
   }finally{await browser.close();}
  }
  process.stdout.write(JSON.stringify({accepted,changed,outcome:changed?'changed':'no_change',reason,scene:after}));
 }catch(error){process.stderr.write('Semantic action/render adapter failed: '+error.name+'\n');process.exitCode=1;}
});
