/** Versioned, source-linked wrappers around unchanged native experiment exports. */
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';

const digest=value=>crypto.createHash('sha256').update(value).digest('hex');
const canonical=value=>JSON.stringify(value,(_key,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const href=value=>esc(encodeURI(String(value).split(path.sep).join('/')));
const json=value=>'<pre>'+esc(JSON.stringify(value,null,2))+'</pre>';
const detail=(title,content)=>'<details><summary>'+esc(title)+'</summary>'+content+'</details>';
const pre=value=>'<pre>'+esc(value)+'</pre>';
const readJSON=async file=>JSON.parse(await fs.readFile(file,'utf8'));
const save=async(file,value)=>{await fs.mkdir(path.dirname(file),{recursive:true});await fs.writeFile(file,JSON.stringify(value,null,2)+'\n');};
const exists=async file=>fs.stat(file).then(()=>true,()=>false);
const walk=async dir=>{
 if(!await exists(dir))return [];
 const result=[];
 for(const item of (await fs.readdir(dir,{withFileTypes:true})).sort((a,b)=>a.name.localeCompare(b.name))){
  const file=path.join(dir,item.name);
  if(item.isDirectory())result.push(...await walk(file));else if(item.isFile())result.push(file);
 }
 return result;
};
const relative=(base,file)=>path.relative(base,file).split(path.sep).join('/');
async function attachCallArtifacts(item,outputDir,dir,stem){
 for(const [key,suffix] of [['input_path','.input.json'],['schema_path','.schema.json'],['response_path','.response.json'],['error_path','.error.json']]){
  const candidate=path.join(dir,stem+suffix);if(await exists(candidate))item[key]=relative(outputDir,candidate);
 }
 if(item.response_path){
  const response=await readJSON(path.join(outputDir,item.response_path));
  const metadata=response?.api??response;
  item.response_id=metadata?.response_id??metadata?.id??null;
  item.api_status=metadata?.status??null;
  if(metadata?.model_returned||metadata?.model_requested||metadata?.model)item.model=metadata.model_returned||metadata.model_requested||metadata.model;
  if(metadata?.usage)item.usage=metadata.usage;
  if(metadata?.error_type)item.error_type=metadata.error_type;
 }
}
const RUNTIME_SEMANTIC_KEYS=['api_destination_origin','packages','evaluation_model','transformation_model',
 'tutor_model','tutor_effort','transformation_profile','automatic_api_retries','api_timeout_seconds',
 'transformation_used_for_this_seed','learner_knowledge_controller_proposal_implemented',
 'student_model','student_effort','learner_model','models','effort','reasoning','temperature','top_p',
 'seed','max_output_tokens','image_detail','reconstruction_profile','learning_controller','learning_policy',
 'simulated_learner_architecture','knowledge_model_agent','knowledge_check_cadence'];
const link=(file,label)=>'<a href="'+href(file)+'">'+esc(label)+'</a>';
const css=`:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#f3f6f8;color:#26384a;font:16px/1.6 system-ui,-apple-system,"PingFang SC",sans-serif}main{max-width:1200px;margin:auto;padding:30px 24px 65px}h1{font-size:30px;line-height:1.3}h2{font-size:22px}p{overflow-wrap:anywhere}section,.card{background:white;border:1px solid #dbe3ea;border-radius:12px;padding:22px;margin:20px 0}a{color:#265f91;overflow-wrap:anywhere}.note{padding:15px;border-left:4px solid #789bb7;background:#edf4f8}.versions{display:flex;flex-wrap:wrap;gap:10px}.versions code{background:#eaf0f5;padding:8px;border-radius:6px;font-size:13px;overflow-wrap:anywhere}pre{background:#f4f7f9;border-radius:7px;padding:16px;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;font:12px/1.6 ui-monospace,Menlo,monospace;max-height:640px;overflow:auto}details{margin:12px 0;border:1px solid #dbe3ea;border-radius:7px;padding:12px}summary{cursor:pointer;font-weight:600;overflow-wrap:anywhere;word-break:break-word}.table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{text-align:left;vertical-align:top;padding:11px;border-bottom:1px solid #dbe3ea;min-width:90px}th{background:#edf3f7}iframe{display:block;width:100%;height:950px;border:1px solid #dbe3ea;background:white;border-radius:7px}.muted{color:#607387;font-size:13px}@media(max-width:650px){main{padding:18px 12px 40px}section,.card{padding:16px}h1{font-size:25px}iframe{height:760px}}`;
const page=(title,body)=>'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+'</title><style>'+css+'</style><main>'+body+'</main></html>';
const versions=value=>'<div class="versions"><code>Prompt '+esc(value.prompt_version)+'</code><code>Learner '+esc(value.learner_prompt_version)+'</code><code>System '+esc(value.system_prompt_version)+'</code></div>';

async function sourceBundle(outputDir){
 const files=[];
 const twoAgent=await exists(path.join(outputDir,'code_snapshot','knowledge_model_agent_prompt.md'));
 const learnerRoles={'student_prompt.md':'learner','profile_dimensions.json':'profile_catalogue','prior_analysis_prompt.md':'prior_analysis',
  ...(twoAgent?{'knowledge_model_agent_prompt.md':'knowledge_model_agent'}:
   {'learning_observer_prompt.md':'learning_observer','knowledge_gate_prompt.md':'knowledge_gate'})};
 for(const [name,role] of Object.entries(learnerRoles)){
  const file=path.join(outputDir,'code_snapshot',name);
  if(await exists(file)){const text=await fs.readFile(file,'utf8');files.push({role,path:relative(outputDir,file),sha256:digest(text),text});}
 }
 if(!files.some(v=>v.role==='learner'))throw Error('Prompt version needs the frozen shared student_prompt.md.');
 for(const file of await walk(path.join(outputDir,'tutor_code_snapshot','prompts'))){
  if(!file.endsWith('.md'))continue;
  const text=await fs.readFile(file,'utf8');
  files.push({role:path.basename(file).includes('evaluator')?'evaluation':path.basename(file)==='feedback_tutor.md'?'tutor':path.basename(file).includes('examples')?'tutor_examples':'transformation_template',path:relative(outputDir,file),sha256:digest(text),text});
 }
 return files;
}

export async function createPromptVersionBundle({outputDir,manifest,caseConfig,profiles,runtimeSettings={}}){
 const rejectSecrets=value=>{
  if(!value||typeof value!=='object')return;
  for(const [key,item] of Object.entries(value)){
   if(/^(?:api_?key|openai_api_key|access_token|authorization|password|secret)$/i.test(key))throw Error('Capture model settings, not credentials, in prompt versions.');
   rejectSecrets(item);
  }
 };
 rejectSecrets(runtimeSettings);
 const files=await sourceBundle(outputDir),base=files.map(({text,...item})=>item);
 const learnerParts=base.filter(v=>!v.path.startsWith('tutor_code_snapshot/'));
 const systemParts=base.filter(v=>v.path.startsWith('tutor_code_snapshot/'));
 const learnerHash=digest(canonical(learnerParts)),systemHash=digest(canonical(systemParts));
 // Process IDs, timestamps, output roots and localhost ports identify a run,
 // rather than a prompt/model configuration. Keep them out of content IDs.
 const semanticSettings=Object.fromEntries(RUNTIME_SEMANTIC_KEYS.filter(key=>Object.hasOwn(runtimeSettings,key)).map(key=>[key,runtimeSettings[key]]));
 const identity={format:'prompt-version-v1',learner_prompt_sha256:learnerHash,system_prompt_sha256:systemHash,
  case_sha256:digest(canonical(caseConfig)),profiles_sha256:digest(canonical(profiles)),
  student_model:manifest.student_model??null,student_effort:manifest.effort??null,runtime_settings:semanticSettings,
  learner_source_sha256:manifest.source_code_sha256||{},system_source_sha256:manifest.tutor_source_sha256||{}};
 if(manifest.learner_knowledge_protocol)identity.learner_knowledge_protocol=manifest.learner_knowledge_protocol;
 const version={format:'prompt-version-v1',run_id:path.basename(outputDir),created_at:new Date().toISOString(),
  prompt_version:'pv1-'+digest(canonical(identity)).slice(0,16),
  learner_prompt_version:'learner-'+learnerHash.slice(0,12),system_prompt_version:'feedback-'+systemHash.slice(0,12),
  experiment_format:manifest.format??null,experiment_scope:manifest.scope??null,system_source_template_count:systemParts.length,
  identity,files:base,scope:'Prompt version binds templates, case/prior, selected profiles, captured models and frozen runtime source. Actual assembled per-turn instructions are indexed separately; a saved template does not imply an API call.',
  original_native_exports_unchanged:true};
 const destination=path.join(outputDir,'prompt_version.json');
 if(await exists(destination)){
  const previous=await readJSON(destination);
  if(previous.prompt_version!==version.prompt_version)throw Error('Existing prompt_version.json binds different content; use a new output directory.');
  return previous;
 }
 await save(destination,version);
 await save(path.join(outputDir,'prompt_bundle.json'),{version,case_config:caseConfig,selected_profiles:profiles,source_templates:files});
 await renderPrompts(outputDir,version,files,caseConfig,profiles,[]);
 return version;
}

async function renderPrompts(outputDir,version,files,caseConfig,profiles,records){
 let body='<h1>Prompts and versions for this run</h1>'+versions(version)+'<p>Run ID: <code>'+esc(version.run_id)+'</code></p>';
 if(version.experiment_scope)body+='<p class="note">'+esc(version.experiment_scope)+'</p>';
 if(version.system_source_template_count===0)body+='<p>No feedback-system source template was captured. The feedback version hash represents an empty template set, not a Tutor prompt. Only actual captured role calls below establish what was called.</p>';
 body+='<p class="note">Source templates and actual calls are recorded separately. Each captured call preserves its exact instructions. Current two-Agent runs distinguish the stateful Knowledge Model Agent from the Learner Agent; legacy observer/gate records remain explicitly labeled. Feedback-system calls are a separate pipeline. A saved template alone does not establish an actual call.</p>';
 body+='<p>'+link('index.html','Interaction results')+' · '+link('prompt_version.json','Version JSON')+' · '+link('actual_prompt_index.json','Actual call index')+'</p>';
 body+=detail('Models, settings, and source hashes bound to this version',json(version.identity));
 body+='<section><h2>Frozen source templates</h2>';
 for(const item of files)body+=detail(item.role+' · '+path.basename(item.path)+' · '+item.sha256.slice(0,12),pre(item.text)+'<p>'+link(item.path,'Source file')+'</p>');
 body+='</section><section><h2>Shared response and selected profile values</h2>'+detail('Task / Response-conditioned prior',json(caseConfig))+detail('Profiles selected for this run',json(profiles))+'</section>';
 body+='<section><h2>Actual instructions</h2><p>'+records.length+' recorded Agent prompts. Each is identified by its content SHA-256; repeated calls using identical text are still listed separately. If no Transformation call is recorded, template presence must not be taken as evidence that it was called.</p>';
 for(const item of records){
  body+=detail((item.profile_id||'Unassigned')+' · '+item.origin+' · '+item.role+' · '+(item.call_name||item.directory)+' · '+item.sha256.slice(0,12),pre(item.text)+'<p>'+link(item.path,'Actual prompt')+(item.input_path?' · '+link(item.input_path,'Actual input'):'')+(item.schema_path?' · '+link(item.schema_path,'Actual schema'):'')+(item.response_path?' · '+link(item.response_path,'Raw response'):'')+(item.error_path?' · '+link(item.error_path,'Raw failure'):'')+'</p>');
 }
 body+='</section>';
 await fs.writeFile(path.join(outputDir,'prompts.html'),page('Prompts · '+version.prompt_version,body));
}

async function actualRecords(outputDir,runs,version,runAssociations){
 const records=[],sessions=new Map(runs.map(r=>[r.exports?.feedback_session,r]).filter(([id])=>id));
 const templates=await sourceBundle(outputDir);
 const actualPromptFiles=(await walk(path.join(outputDir,'tutor_api_runs'))).filter(v=>v.endsWith('.prompt.md'));
 for(const file of actualPromptFiles){
  const dir=path.dirname(file),directory=path.basename(dir),role=path.basename(file).replace('.prompt.md','');
  let session=null;
  for(const name of ['session.json','public_reply.json']){
   if(await exists(path.join(dir,name))){const data=await readJSON(path.join(dir,name));session=data.id||data.session_id||session;}
  }
  const text=await fs.readFile(file,'utf8'),template=templates.find(v=>v.role===role);
  const associated=runAssociations[directory],associatedRuns=associated?runs.filter(run=>run.run_id===associated||run.profile_id===associated):[];
  const assignedRun=associatedRuns.length===1?associatedRuns[0]:!associated?sessions.get(session):null;
  const item={directory,role,origin:'feedback_system',profile_id:assignedRun?.profile_id||associated||null,run_id:assignedRun?.run_id??null,session_id:session,
   path:relative(outputDir,file),sha256:digest(text),text,
   template_match:template?(role==='tutor'?text.startsWith(template.text.trimEnd()):text===template.text):null};
  await attachCallArtifacts(item,outputDir,dir,role);
  records.push(item);
 }
 const student=[];
 const expected=version.files.find(v=>v.role==='learner')?.sha256;
 for(const run of runs){
  for(const file of (await walk(path.join(outputDir,run.run_id))).filter(v=>v.endsWith('.prompt.md'))){
   const callName=path.basename(file).replace('.prompt.md',''),match=/^step_(\d+)_(knowledge_model_initialize|knowledge_model_move_\d+|learner_agent|learning_observer|learner_candidate_\d+|knowledge_gate_\d+)$/.exec(callName);
   if(!match)continue;
   const twoAgent=match[2]==='learner_agent'||match[2].startsWith('knowledge_model_');
   const role=match[2]==='learner_agent'||match[2].startsWith('learner_candidate_')?'learner':
    match[2].startsWith('knowledge_model_')?'knowledge_model_agent':match[2].startsWith('knowledge_gate_')?'knowledge_gate':'learning_observer';
   const text=await fs.readFile(file,'utf8'),template=templates.find(v=>v.role===role);
   const item={directory:run.run_id,call_name:callName,step:Number(match[1]),role,
    origin:twoAgent?'learner_agents':'learner_controller',profile_id:run.profile_id,run_id:run.run_id,
    ...(twoAgent?{agent_name:role==='learner'?'Learner Agent':'Knowledge Model Agent',
      operation:match[2]==='knowledge_model_initialize'?'initialize':role==='learner'?'act':'move_check'}:{}),
    path:relative(outputDir,file),sha256:digest(text),text,template_match:template?text===template.text:null};
   await attachCallArtifacts(item,outputDir,path.dirname(file),callName);
   records.push(item);
  }
  for(const file of (await walk(path.join(outputDir,run.run_id))).filter(v=>/step_\d+_response\.json$/.test(v))){
   const data=await readJSON(file);
   const twoAgent=data.knowledge_audit?.protocol==='two-agent-v2';
   student.push({profile_id:run.profile_id,run_id:run.run_id,path:relative(outputDir,file),status:data.status,
    response_id:data.api?.response_id||null,prompt_sha256:data.prompt_sha256??null,
    api_calls:data.api_calls??[],knowledge_state_sha256:data.learner_knowledge_model?.state_sha256??null,
    ...(twoAgent?{knowledge_protocol:'two-agent-v2',knowledge_check_complete:data.knowledge_audit.check_complete,
      knowledge_agent_checks:data.knowledge_audit.checks??[],learner_read_state_sha256:data.knowledge_audit.learner_read_state_sha256??null}:
      {knowledge_update_validated:data.knowledge_audit?.update_validated??null,knowledge_gate_approved:data.knowledge_audit?.gate?.approved??null}),
    matches_frozen_prompt:data.prompt_sha256?data.prompt_sha256===expected:null});
  }
 }
 return {records,student};
}

async function knowledgeTimeline(outputDir,run){
 const dir=path.join(outputDir,run.run_id),steps=[];
 for(const file of (await walk(dir)).filter(value=>/step_\d+_knowledge_audit\.json$/.test(value))){
  const record=await readJSON(file),audit=record.knowledge_audit||{};
  if(audit.protocol==='two-agent-v2'){
   steps.push({protocol:'two-agent-v2',source:'runner_receipt',step:record.step,response_status:record.response_status,
    check_complete:record.check_complete===true,checkpoint_committed:record.checkpoint_committed===true,
    knowledge_agent_checks:audit.checks??record.knowledge_agent_checks??[],warnings:audit.warnings??record.warnings??[],
    learner_read_state_sha256:audit.learner_read_state_sha256??null,
    execution_started:record.execution_started===true,executed:record.executed===true,execution_ok:record.execution_ok??null,
    before:audit.before??record.request_checkpoint??null,after:audit.after??null,rejection_reason:record.rejection_reason??null,
    receipt_path:relative(dir,file),raw_response:record.raw_response??null});
   continue;
  }
  steps.push({source:'runner_receipt',step:record.step,response_status:record.response_status,update_validated:record.update_validated===true,
   checkpoint_committed:record.checkpoint_committed===true,gate_approved:record.gate_approved===true,
   execution_started:record.execution_started===true,executed:record.executed===true,execution_ok:record.execution_ok??null,
   before:audit.before??record.request_checkpoint??null,events:audit.events??[],after:audit.after??null,
   proposed_after:audit.proposed_after??null,gate:audit.gate??null,rejection_reason:record.rejection_reason??null,
   receipt_path:relative(dir,file),raw_response:record.raw_response??null});
 }
 let latestResponseState=null;
 for(const file of (await walk(dir)).filter(value=>/step_\d+_response\.json$/.test(value))){
  const response=await readJSON(file),audit=response.knowledge_audit;
  if(!audit)continue;
  const step=Number(/step_(\d+)_response\.json$/.exec(file)[1]);
  if(audit.update_validated===true||audit.check_complete===true)latestResponseState=response.learner_knowledge_model??null;
  if(steps.some(record=>record.step===step))continue;
  if(audit.protocol==='two-agent-v2'){
   steps.push({protocol:'two-agent-v2',source:'helper_response_only',step,response_status:response.status,
    check_complete:audit.check_complete===true,checkpoint_committed:null,knowledge_agent_checks:audit.checks??[],warnings:audit.warnings??[],
    learner_read_state_sha256:audit.learner_read_state_sha256??null,
    execution_started:null,executed:null,execution_ok:null,before:audit.before??null,after:audit.after??null,
    rejection_reason:response.error?.message??response.error?.type??null,receipt_path:null,raw_response:relative(dir,file)});
   continue;
  }
  // Focused API replays have a helper response but no browser runner receipt.
  // Preserve its knowledge audit without inventing a saved checkpoint/action.
  steps.push({source:'helper_response_only',step,response_status:response.status,update_validated:audit.update_validated===true,
   checkpoint_committed:null,gate_approved:audit.gate?.approved===true,execution_started:null,executed:null,execution_ok:null,
   before:audit.before??null,events:audit.events??[],after:audit.after??null,proposed_after:audit.proposed_after??null,
   gate:audit.gate??null,rejection_reason:response.error?.message??response.error?.type??null,
   receipt_path:null,raw_response:relative(dir,file)});
 }
 steps.sort((a,b)=>a.step-b.step);
 const checkpoint=path.join(dir,'learner_knowledge_model.json');
 if(steps.some(record=>record.protocol==='two-agent-v2'))return {
  format:'knowledge-model-agent-timeline-v2',protocol:'two-agent-v2',profile_id:run.profile_id,run_id:run.run_id,recorded:steps.length>0,
  interpretation:'The stateful Knowledge Model Agent initializes from the submitted response/prior and checks each newly delivered Feedback move once. It stores its knowledge state before the Learner Agent reads it. UI-only actions reuse the stored state. These are two Agents; no independent observer or knowledge gate is involved. Helper-only evidence does not establish browser execution. Agent knowledge states are simulation records, not measured human mastery.',
  steps,latest_agent_response_state:latestResponseState,latest_checkpoint:await exists(checkpoint)?await readJSON(checkpoint):null};
 return {format:'learner-knowledge-timeline-v1',profile_id:run.profile_id,run_id:run.run_id,recorded:steps.length>0,
  interpretation:'Controller response records, saved runner checkpoints, and executed actions are recorded separately. A helper-only replay does not establish checkpoint persistence or action execution. A validated update concerns past received support or completed attempts and can be retained when a new candidate is rejected. Actor memory is not used to infer knowledge. These simulation states do not measure human mastery.',
  steps,latest_controller_response_state:latestResponseState,latest_checkpoint:await exists(checkpoint)?await readJSON(checkpoint):null};
}

function renderKnowledgeTimeline(timeline){
 let body='<section><h2>Learner knowledge timeline</h2>';
 if(!timeline.recorded)return body+'<p>No independent learner knowledge receipt was recorded for this run. Knowledge changes are not inferred from learner memory.</p></section>';
 if(timeline.protocol==='two-agent-v2'){
  body+='<p class="note">'+esc(timeline.interpretation)+'</p><p>'+link('knowledge_timeline.json','Knowledge Model Agent check and storage records')+(timeline.latest_checkpoint?' · '+link('learner_knowledge_model.json','Latest stored Agent knowledge'):'')+'</p>';
  body+='<div class="table"><table><thead><tr><th>Learner action step</th><th>Knowledge check complete</th><th>New Agent check records</th><th>State stored</th><th>Action executed</th><th>Evidence</th></tr></thead><tbody>';
  for(const item of timeline.steps)body+='<tr><td>'+item.step+'</td><td>'+(item.check_complete?'Yes':'No')+'</td><td>'+item.knowledge_agent_checks.length+'</td><td>'+(item.checkpoint_committed===null?'Not recorded':item.checkpoint_committed?'Yes':'No')+'</td><td>'+(item.executed===null?'Not recorded':item.executed?(item.execution_ok===false?'Attempted; failed':'Yes'):item.execution_started?'Started; outcome unavailable':'No')+'</td><td>'+(item.receipt_path?link(item.receipt_path,'Agent check receipt'):'Helper response only')+(item.raw_response?' · '+link(item.raw_response,'Raw response'):'')+(item.rejection_reason?'<p>'+esc(item.rejection_reason)+'</p>':'')+'</td></tr>';
  body+='</tbody></table></div>';
  for(const item of timeline.steps)body+=detail('Step '+item.step+' · Knowledge Model Agent checks / stored state / Learner Agent read',json(item));
  return body+detail('Latest Knowledge Model Agent response state',json(timeline.latest_agent_response_state))+detail('Latest stored Agent checkpoint',json(timeline.latest_checkpoint))+'</section>';
 }
 body+='<p class="note">'+esc(timeline.interpretation)+'</p><p>'+link('knowledge_timeline.json','Complete knowledge timeline JSON')+(timeline.latest_checkpoint?' · '+link('learner_knowledge_model.json','Latest validated checkpoint'):'')+'</p>';
 body+='<div class="table"><table><thead><tr><th>Step</th><th>Checkpoint saved</th><th>Gate approved</th><th>Action executed</th><th>Evidence / controller record</th></tr></thead><tbody>';
 for(const item of timeline.steps)body+='<tr><td>'+item.step+'</td><td>'+(item.checkpoint_committed===null?'Not recorded':item.checkpoint_committed?'Yes':'No')+'</td><td>'+(item.gate_approved?'Yes':'No')+'</td><td>'+(item.executed===null?'Not recorded':item.executed?(item.execution_ok===false?'Attempted; failed':'Yes'):item.execution_started?'Started; outcome unavailable':'No')+'</td><td>'+(item.receipt_path?link(item.receipt_path,'Receipt'):'Helper response only')+(item.raw_response?' · '+link(item.raw_response,'Raw decision'):'')+(item.rejection_reason?'<p>'+esc(item.rejection_reason)+'</p>':'')+'</td></tr>';
 body+='</tbody></table></div>';
 for(const item of timeline.steps)body+=detail('Step '+item.step+' · knowledge before / evidence / after / gate',json(item));
 return body+detail('Latest validated controller response state',json(timeline.latest_controller_response_state))+detail('Latest saved runner checkpoint',json(timeline.latest_checkpoint))+'</section>';
}

export async function finalizeVersionedExports({outputDir,manifest,runs,caseConfig,promptVersion,cataloguePath=null,runAssociations={},writeOverview=true}){
 const version=promptVersion||await readJSON(path.join(outputDir,'prompt_version.json'));
 const files=await sourceBundle(outputDir);
 for(const item of version.files){
  const actual=files.find(v=>v.path===item.path);
  if(!actual||actual.sha256!==item.sha256)throw Error('Frozen prompt content changed after version registration: '+item.path);
 }
 const {records,student}=await actualRecords(outputDir,runs,version,runAssociations);
 const mismatches=[...records.filter(v=>v.template_match===false).map(v=>v.path),...student.filter(v=>v.matches_frozen_prompt===false).map(v=>v.path)];
 const twoAgent=manifest.learner_knowledge_protocol?.protocol==='two-agent-v2'||files.some(item=>item.role==='knowledge_model_agent');
 if(twoAgent&&records.some(item=>item.origin==='learner_controller'))throw Error('A two-Agent run contains legacy observer or gate call records; retain them in their original historical run.');
 const roleNames=twoAgent?['evaluation','tutor','transformation','knowledge_model_agent','learner']:
  ['evaluation','tutor','transformation','learner','learning_observer','knowledge_gate'];
 const roleStatus=Object.fromEntries(roleNames.map(role=>[role,{recorded_calls:records.filter(v=>v.role===role).length,status:records.some(v=>v.role===role)?'recorded':'not_recorded'}]));
 await save(path.join(outputDir,'actual_prompt_index.json'),{prompt_version:version.prompt_version,
  source_integrity:mismatches.length?'mismatch':records.length+student.length?'matched_for_recorded_prompts':'no_recorded_prompts',mismatches,role_status:roleStatus,
  student_calls:student,agent_calls:records.map(({text,...item})=>item),
  interpretation:'Only captured requests are compared. Missing call records are not silently invented; template presence does not imply execution.'});
 const profiles=manifest.profiles||[];
 await renderPrompts(outputDir,version,files,caseConfig,profiles,records);
 const rows=[];
 for(const run of runs){
  const dir=path.join(outputDir,run.run_id),native=run.exports?.html_path;
  const belongs=item=>item.run_id===run.run_id;
  const focused=manifest.format==='knowledge-focused-replay-v1',label=run.profile_id+(run.run_id===run.profile_id?'':' · '+run.run_id);
  const timeline=await knowledgeTimeline(outputDir,run);
  if(timeline.recorded)await save(path.join(dir,'knowledge_timeline.json'),timeline);
  let fullProfile=null,firstInput=null,inputLabel='Complete text input sent in the first recorded learner call';
  for(const call of student.filter(belongs)){
   const data=await readJSON(path.join(outputDir,call.path));
   if(data.model_visible_input?.profile){fullProfile=data.model_visible_input.profile;firstInput=data.model_visible_input;break;}
  }
  if(!firstInput){
   const firstController=records.find(item=>belongs(item)&&['learner_agents','learner_controller'].includes(item.origin)&&item.input_path);
   if(firstController){firstInput=await readJSON(path.join(outputDir,firstController.input_path));fullProfile=firstInput.profile??null;inputLabel='Actual '+firstController.role+' input; no learner generation is implied';}
  }
  const diagnosticFile=path.join(dir,'candidate_audit.json');
  const diagnostic=await exists(diagnosticFile)?await readJSON(diagnosticFile):null;
  const metadata={format:'versioned-export-v1',run_id:version.run_id,profile_id:run.profile_id,
   profile_run_id:run.run_id,experiment_format:manifest.format??null,scope:run.scope??manifest.scope??null,
   prompt_version:version.prompt_version,learner_prompt_version:version.learner_prompt_version,
   system_prompt_version:version.system_prompt_version,version_record:'../prompt_version.json',
   status:run.status,student_decisions:run.steps?.length||0,stop_reason:run.stop_reason??null,
   native_html:native??null,native_html_sha256:native?digest(await fs.readFile(path.join(dir,native))):null,
   native_exploration:run.exports?.exploration_path??null,
   actual_tutor_prompt_paths:records.filter(v=>belongs(v)&&v.origin==='feedback_system').map(v=>'../'+v.path),
   ...(twoAgent?{actual_learner_agent_prompt_paths:records.filter(v=>belongs(v)&&v.origin==='learner_agents').map(v=>'../'+v.path)}:
    {actual_learner_controller_prompt_paths:records.filter(v=>belongs(v)&&v.origin==='learner_controller').map(v=>'../'+v.path)}),
   learner_knowledge_protocol:manifest.learner_knowledge_protocol??null,knowledge_timeline:timeline.recorded?'knowledge_timeline.json':null,
   student_prompt_integrity:student.some(belongs)?student.filter(belongs).every(v=>v.matches_frozen_prompt!==false):null,
   system_prompt_integrity:records.some(v=>belongs(v)&&v.origin==='feedback_system')?records.filter(v=>belongs(v)&&v.origin==='feedback_system').every(v=>v.template_match!==false):null,
   ...(twoAgent?{learner_agent_prompt_integrity:records.some(v=>belongs(v)&&v.origin==='learner_agents')?records.filter(v=>belongs(v)&&v.origin==='learner_agents').every(v=>v.template_match!==false):null}:
    {learner_controller_prompt_integrity:records.some(v=>belongs(v)&&v.origin==='learner_controller')?records.filter(v=>belongs(v)&&v.origin==='learner_controller').every(v=>v.template_match!==false):null})};
  await save(path.join(dir,'export_metadata.json'),metadata);
  if(fullProfile)await save(path.join(dir,'resolved_profile.json'),fullProfile);
  let body='<h1>'+esc(label)+' · '+(focused?'Focused replay and prompt version':'Interaction and prompt version')+'</h1>'+versions(version)+'<p>Run <code>'+esc(version.run_id)+'</code> · Status <strong>'+esc(run.status)+'</strong> · Student decisions '+(run.steps?.length||0)+'</p>';
  body+='<p>'+link('../index.html','Run overview')+' · '+link('../prompts.html','All prompts')+' · '+link('export_metadata.json','Export version record')+(native?' · '+link(native,'Open original interaction HTML'):'')+'</p>';
  body+='<p class="note">'+(focused?'This is a focused learner-side replay of saved public context. No new Tutor call or browser action was made. Learner action proposals and controller judgments are recorded without claiming a closed-loop interaction or task completion.': 'This page combines the settings actually used with the original interaction. The native HTML below is unchanged. step_budget_reached means the external decision limit was reached; failed means an execution or call failure. Neither means that the learner completed the task.')+'</p>';
  body+='<section><h2>Settings used for this learner</h2>'+detail('Complete shared learner prompt',pre(files.find(v=>v.role==='learner').text));
  body+=detail(fullProfile?'Actual expanded profile, including prior knowledge':'Selected profile; no actual learner input was saved for expansion in this run',json(fullProfile||profiles.find(v=>v.id===run.profile_id)||{}));
  body+=detail('Shared task, response, and initial prior',json(caseConfig));
  if(firstInput)body+=detail(inputLabel,json(firstInput));
  body+='</section>';
  if(diagnostic)body+='<section><h2>Gate-only candidate diagnostic</h2><p>This condition checks a historical or constructed candidate. It does not imply a new learner generation or browser action.</p>'+detail('Actual diagnostic verdict and call metadata',json(diagnostic))+'<p>'+link('candidate_audit.json','Raw diagnostic record')+(await exists(path.join(dir,'source_candidate.json'))?' · '+link('source_candidate.json','Candidate checked'):'')+'</p></section>';
  body+=renderKnowledgeTimeline(timeline)+'<section><h2>Actual feedback-system instructions for this learner</h2>';
  const calls=records.filter(v=>belongs(v)&&v.origin==='feedback_system');
  if(!calls.length)body+='<p>'+(focused?'No feedback-system API call was made in this focused replay.':'No recorded Agent prompt can currently be assigned to this learner by session. See the run-wide index; unassigned failure records are retained.')+'</p>';
  for(const item of calls)body+=detail(item.role+' · '+item.directory+' · '+item.sha256.slice(0,12),pre(item.text)+'<p>'+link('../'+item.path,'Actual prompt')+(item.input_path?' · '+link('../'+item.input_path,'Input'):'')+(item.response_path?' · '+link('../'+item.response_path,'Response'):'')+'</p>');
  body+='</section><section><h2>'+(twoAgent?'Actual two-Agent instructions':'Actual learner-controller instructions')+'</h2>';
  const learnerCalls=records.filter(v=>belongs(v)&&v.origin===(twoAgent?'learner_agents':'learner_controller'));
  if(!learnerCalls.length)body+='<p>'+(twoAgent?'No Knowledge Model Agent or Learner Agent prompt was recorded for this run.':'No learner-controller role prompt was recorded for this run.')+'</p>';
  for(const item of learnerCalls)body+=detail(item.role+' · '+item.call_name+' · '+item.sha256.slice(0,12),pre(item.text)+'<p>'+link('../'+item.path,'Actual prompt')+(item.input_path?' · '+link('../'+item.input_path,'Input'):'')+(item.schema_path?' · '+link('../'+item.schema_path,'Schema'):'')+(item.response_path?' · '+link('../'+item.response_path,'Raw response'):'')+(item.error_path?' · '+link('../'+item.error_path,'Raw failure'):'')+'</p>');
  body+='</section><section><h2>Original system interaction</h2>';
  body+=native?'<p>'+link(native,'Open native HTML separately')+'</p><iframe title="'+esc(run.profile_id)+' original interaction" src="'+href(native)+'"></iframe>':focused?'<p>This focused replay did not create a browser or native interaction export. The exact saved observation is available in the recorded inputs above.</p>':'<p>No native HTML was successfully exported for this run. '+esc((run.errors||[]).map(v=>v.message).join(' / '))+'</p>';
  body+='</section>'+detail('Run summary',json(run));
  await fs.writeFile(path.join(dir,'review.html'),page(label+' · '+version.prompt_version,body));
  rows.push('<tr><td>'+esc(label)+'</td><td>'+esc(run.status)+'</td><td>'+(run.steps?.length||0)+'</td><td>'+(run.exports?.revision_submissions??'—')+'</td><td>'+link(run.run_id+'/review.html',focused?'Focused replay and corresponding prompts':'Interaction and corresponding prompts')+(native?' · '+link(run.run_id+'/'+native,'Native HTML'):'')+'</td></tr>');
 }
 const knowledgeNote=twoAgent?' This run uses two learner-side Agents: the stateful Knowledge Model Agent checks each new Feedback move once and stores knowledge before the Learner Agent acts. Per-step receipts show checks, stored state, exact Agent reads and actual execution. There is no independent observer or gate Agent.':manifest.learner_knowledge_protocol?' This historical run declares an independent learner knowledge controller; its recorded receipts retain checkpoints, evidence, action gates, and execution outcomes.':' No independent learning controller is inferred for a historical run without its own receipts.';
 const index='<h1>Simulated learner interactions and version records</h1>'+versions(version)+'<p>Run ID: <code>'+esc(version.run_id)+'</code></p><p class="note">All learners use the same submitted response and content prior; their selected ability values are saved separately. Open Interaction and corresponding prompts to see the native dialogue, complete learner prompt, actual expanded profile/prior, and per-call system instructions together.'+knowledgeNote+'</p><p>'+link('prompts.html','All actual prompts and source templates')+' · '+link('prompt_version.json','Version record')+' · '+link('actual_prompt_index.json','Actual call index')+' · '+link('experiment_manifest.json','Experiment configuration')+'</p><div class="table"><table><thead><tr><th>Profile</th><th>End status</th><th>Student decisions</th><th>Revision submissions</th><th>Interaction records</th></tr></thead><tbody>'+rows.join('')+'</tbody></table></div><p>Generating these review pages added no model calls. Prompt versions use content hashes; changes to source templates, case, profiles, model settings, or frozen implementation produce a new version. Original exports and API records remain unchanged.</p>';
 if(writeOverview)await fs.writeFile(path.join(outputDir,'index.html'),page('Simulated learners · '+version.prompt_version,index));
 if(cataloguePath)await registerCatalogue(cataloguePath,{run_id:version.run_id,output_dir:path.resolve(outputDir),prompt_version:version.prompt_version,learner_prompt_version:version.learner_prompt_version,system_prompt_version:version.system_prompt_version,started_at:manifest.started_at,ended_at:manifest.ended_at,case_id:caseConfig.id||caseConfig.source_id,profiles:runs.map(v=>({id:v.profile_id,status:v.status,decisions:v.steps?.length||0}))});
 return {prompt_version:version.prompt_version,source_integrity:mismatches.length?'mismatch':records.length+student.length?'matched_for_recorded_prompts':'no_recorded_prompts',mismatches,agent_prompt_records:records.length,student_call_records:student.length,versioned_profile_exports:runs.length};
}

async function registerCatalogue(file,entry){
 await fs.mkdir(path.dirname(file),{recursive:true});
 const entries=await exists(file)?(await fs.readFile(file,'utf8')).split('\n').filter(Boolean).map(JSON.parse):[];
 const previous=entries.find(v=>v.output_dir===entry.output_dir);
 if(previous&&canonical(previous)!==canonical(entry))throw Error('Run catalogue already has different metadata for this immutable output directory.');
 if(!previous)await fs.appendFile(file,JSON.stringify(entry)+'\n');
 await renderRunHistory(file);
}

/** Rebuild only the English presentation; do not append or alter run records. */
export async function renderRunHistory(file){
 const entries=await exists(file)?(await fs.readFile(file,'utf8')).split('\n').filter(Boolean).map(JSON.parse):[];
 const base=path.dirname(file),links=[];
 const rows=await Promise.all(entries.map(async v=>{
  const english=path.join(v.output_dir+'_english','index.html');
  const target=await exists(english)?english:path.join(v.output_dir,'index.html');
  const destination=relative(base,target);links.push({run_id:v.run_id,path:destination});
  return '<tr><td>'+esc(v.run_id)+'</td><td><code>'+esc(v.prompt_version)+'</code></td><td>'+esc(v.started_at)+'</td><td>'+esc(v.profiles.map(p=>p.id+': '+p.status).join('; '))+'</td><td>'+link(destination,'View results and prompts')+'</td></tr>';
 }));
 const destination=file.replace(/\.jsonl$/,'')+'.html';
 await fs.writeFile(destination,page('Simulated learner run and version history','<h1>Simulated learner run and version history</h1><p>Runs are registered by appending records; earlier experiments are not rewritten. This index includes only runs registered after version tracking was enabled. Older materials remain in their original archives. Where an English review edition exists, the result link opens that edition without registering a new experiment.</p><div class="table"><table><thead><tr><th>Run ID</th><th>Prompt version</th><th>Start time</th><th>Profile status</th><th>Records</th></tr></thead><tbody>'+rows.join('')+'</tbody></table></div>'));
 return {path:destination,entries:entries.length,links};
}
