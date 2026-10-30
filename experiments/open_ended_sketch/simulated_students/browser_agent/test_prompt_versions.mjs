/** Offline evidence and immutability checks. No browser or external API. */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import {createPromptVersionBundle,finalizeVersionedExports,renderRunHistory} from './prompt_versions.mjs';

const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
const save=async(file,value)=>{await fs.mkdir(path.dirname(file),{recursive:true});await fs.writeFile(file,typeof value==='string'?value:JSON.stringify(value));};
const read=async file=>JSON.parse(await fs.readFile(file,'utf8'));
async function fixture(base,name,{caseId='source-A',model='student-model',studentPrompt='Shared learner <rules> & actual prompt',withCalls=true}={}){
 const out=path.join(base,name),caseConfig={id:caseId,source_id:caseId,initial_explanation:'Submitted words',initial_conceptual_state:{knowledge_components:[{component_id:'KC1',status:'unlearned',statement:'Unestablished method'}]}};
 const profiles=[{id:'P1',dimensions:{task_motivation:{level:'average'}}}];
 const manifest={started_at:'2026-10-28T00:00:00Z',ended_at:'2026-10-28T00:01:00Z',student_model:model,effort:'low',profiles,source_code_sha256:{'student_model.py':'frozen-code'},tutor_source_sha256:{'app/feedback.py':'frozen-feedback'}};
 await save(path.join(out,'code_snapshot/student_prompt.md'),studentPrompt);
 await save(path.join(out,'code_snapshot/profile_dimensions.json'),{version:'catalogue-v1'});
 await save(path.join(out,'code_snapshot/prior_analysis_prompt.md'),'Analyze task and response.');
 await save(path.join(out,'tutor_code_snapshot/prompts/feedback_tutor.md'),'Tutor base instructions');
 await save(path.join(out,'tutor_code_snapshot/prompts/feedback_evaluator.md'),'Evaluation base instructions');
 await save(path.join(out,'tutor_code_snapshot/prompts/feedback_move_examples.md'),'Complete examples library');
 await save(path.join(out,'tutor_code_snapshot/prompts/reconstruct_v1.1.md'),'Transformation source; not called');
 const native='<!doctype html><title>Raw</title><p>Original learner interaction.</p>';
 await save(path.join(out,'P1/native.case.html'),native);
 await save(path.join(out,'P1/native.exploration.json'),{feedback_session:'session-A'});
 const runs=[{run_id:'P1',profile_id:'P1',status:'student_stopped',stop_reason:'Student selected stop.',steps:[{step:1}],exports:{feedback_session:'session-A',html_path:'native.case.html',exploration_path:'native.exploration.json',revision_submissions:0}}];
 if(withCalls){
  await save(path.join(out,'P1/step_01_response.json'),{status:'ok',api:{response_id:'actual-stub-id'},prompt_sha256:sha(studentPrompt),model_visible_input:{profile:{id:'P1',prior_knowledge:{components:[{component_id:'KC1',status:'unlearned'}]}},case_config:caseConfig}});
  await save(path.join(out,'tutor_api_runs/feedback_turn_one/session.json'),{id:'session-A'});
  await save(path.join(out,'tutor_api_runs/feedback_turn_one/tutor.prompt.md'),'Tutor base instructions\n\n## selected\nCurrent-stage example');
  await save(path.join(out,'tutor_api_runs/feedback_turn_one/tutor.input.json'),{message:'Visible student message'});
  await save(path.join(out,'tutor_api_runs/feedback_turn_one/tutor.schema.json'),{type:'object'});
  await save(path.join(out,'tutor_api_runs/feedback_turn_one/tutor.response.json'),{id:'stub-tutor-response'});
  await save(path.join(out,'tutor_api_runs/feedback_turn_two/session.json'),{id:'session-A'});
  await save(path.join(out,'tutor_api_runs/feedback_turn_two/evaluation.prompt.md'),'Evaluation base instructions');
 }
 return {outputDir:out,manifest,runs,caseConfig,profiles,native};
}

test('knowledge observer and gate sources and protocol are bound to learner versions',async()=>{
 const base=await fs.mkdtemp(path.join(os.tmpdir(),'knowledge-prompt-version-'));
 try{
  const a=await fixture(base,'a'),b=await fixture(base,'b'),c=await fixture(base,'c');
  for(const f of [a,b,c]){
   await save(path.join(f.outputDir,'code_snapshot/learning_observer_prompt.md'),'Observe concrete received support.');
   await save(path.join(f.outputDir,'code_snapshot/knowledge_gate_prompt.md'),'Check action against available learner knowledge.');
   f.manifest.learner_knowledge_protocol={format:'learner-knowledge-v1',execution_policy:'gate approved'};
  }
  await save(path.join(b.outputDir,'code_snapshot/knowledge_gate_prompt.md'),'Changed knowledge gate.');
  c.manifest.learner_knowledge_protocol.execution_policy='Changed protocol';
  const av=await createPromptVersionBundle(a),bv=await createPromptVersionBundle(b),cv=await createPromptVersionBundle(c);
  assert.ok(av.files.some(v=>v.role==='learning_observer'));
  assert.ok(av.files.some(v=>v.role==='knowledge_gate'));
  assert.notEqual(av.prompt_version,bv.prompt_version);
  assert.notEqual(av.learner_prompt_version,bv.learner_prompt_version);
  assert.equal(av.system_prompt_version,bv.system_prompt_version,'Internal learner gate changes do not claim a Tutor template change.');
  assert.notEqual(av.prompt_version,cv.prompt_version);
 }finally{await fs.rm(base,{recursive:true,force:true});}
});

test('two-Agent source version binds the Knowledge Model Agent prompt without presenting legacy observer or gate templates',async()=>{
 const base=await fs.mkdtemp(path.join(os.tmpdir(),'two-agent-version-'));
 try{
  const a=await fixture(base,'a'),b=await fixture(base,'b');
  for(const f of [a,b]){
   f.manifest.learner_knowledge_protocol={format:'knowledge-model-agent-v2',protocol:'two-agent-v2',agents:['Knowledge Model Agent','Learner Agent']};
   await save(path.join(f.outputDir,'code_snapshot/knowledge_model_agent_prompt.md'),'Store scoped knowledge; check one delivered move once.');
   await save(path.join(f.outputDir,'code_snapshot/learning_observer_prompt.md'),'Historical observer source.');
   await save(path.join(f.outputDir,'code_snapshot/knowledge_gate_prompt.md'),'Historical gate source.');
  }
  await save(path.join(b.outputDir,'code_snapshot/knowledge_model_agent_prompt.md'),'Changed stateful Knowledge Model Agent prompt.');
  const av=await createPromptVersionBundle(a),bv=await createPromptVersionBundle(b);
  assert.ok(av.files.some(item=>item.role==='knowledge_model_agent'));
  assert.ok(!av.files.some(item=>['knowledge_gate','learning_observer'].includes(item.role)));
  assert.notEqual(av.learner_prompt_version,bv.learner_prompt_version);
  assert.notEqual(av.prompt_version,bv.prompt_version);
  assert.equal(av.system_prompt_version,bv.system_prompt_version);
 }finally{await fs.rm(base,{recursive:true,force:true});}
});

test('two-Agent exports record per-move checks and stored state reads without inventing a gate or checks for UI-only steps',async()=>{
 const base=await fs.mkdtemp(path.join(os.tmpdir(),'two-agent-export-'));
 try{
  const f=await fixture(base,'trial',{withCalls:false});
  f.manifest.learner_knowledge_protocol={format:'knowledge-model-agent-v2',protocol:'two-agent-v2',agents:['Knowledge Model Agent','Learner Agent']};
  f.runs[0].steps=[{step:1},{step:2},{step:3}];
  const knowledgePrompt='Knowledge Model Agent checks a delivered move once and stores its knowledge.',
   learnerPrompt='Shared learner <rules> & actual prompt';
  await save(path.join(f.outputDir,'code_snapshot/knowledge_model_agent_prompt.md'),knowledgePrompt);
  const state=(revision,ids)=>({format:'knowledge-model-agent-v2',revision,state_sha256:String(revision).repeat(64),
   processed_move_ids:ids,components:[{component_id:'KC1',status:revision?'tentative':'unlearned'}]});
  const start=state(0,[]),one=state(1,['message:0']),two=state(2,['message:0','message:2']);
  const rounds=[{step:1,before:start,after:one,checks:[{mode:'initialize'},{mode:'move',move_id:'message:0'}],roles:['knowledge_model_initialize','knowledge_model_move_0','learner_agent']},
   {step:2,before:one,after:one,checks:[],roles:['learner_agent']},
   {step:3,before:one,after:two,checks:[{mode:'move',move_id:'message:2'}],roles:['knowledge_model_move_2','learner_agent']}];
  for(const round of rounds){
   const prefix='step_'+String(round.step).padStart(2,'0'),audit={protocol:'two-agent-v2',before:round.before,after:round.after,
    check_complete:true,checks:round.checks,warnings:[],learner_read_state_sha256:round.after.state_sha256};
   await save(path.join(f.outputDir,'P1',prefix+'_response.json'),{status:'ok',prompt_sha256:sha(learnerPrompt),
    model_visible_input:{profile:{id:'P1'},learner_knowledge_model:round.after},learner_knowledge_model:round.after,knowledge_audit:audit});
   await save(path.join(f.outputDir,'P1',prefix+'_knowledge_audit.json'),{format:'knowledge-agent-step-v2',step:round.step,
    check_complete:true,checkpoint_committed:true,executed:true,execution_ok:true,knowledge_audit:audit,raw_response:prefix+'_response.json'});
   for(const role of round.roles){
    const stem=prefix+'_'+role,prompt=role==='learner_agent'?learnerPrompt:knowledgePrompt;
    await save(path.join(f.outputDir,'P1',stem+'.prompt.md'),prompt);
    await save(path.join(f.outputDir,'P1',stem+'.input.json'),{profile:{id:'P1'},learner_knowledge_model:round.after});
    await save(path.join(f.outputDir,'P1',stem+'.schema.json'),{type:'object'});
    await save(path.join(f.outputDir,'P1',stem+'.response.json'),{api:{role,response_id:stem,status:'completed',usage:{input_tokens:10,output_tokens:5}},parsed:{}});
   }
  }
  await save(path.join(f.outputDir,'P1/learner_knowledge_model.json'),two);
  const nativeSHA=sha(await fs.readFile(path.join(f.outputDir,'P1/native.case.html'))),version=await createPromptVersionBundle(f);
  await finalizeVersionedExports({...f,promptVersion:version});
  const index=await read(path.join(f.outputDir,'actual_prompt_index.json')),timeline=await read(path.join(f.outputDir,'P1/knowledge_timeline.json')),
   meta=await read(path.join(f.outputDir,'P1/export_metadata.json'));
  assert.equal(index.role_status.knowledge_model_agent.recorded_calls,3);
  assert.equal(index.role_status.learner.recorded_calls,3);
  assert.equal(Object.hasOwn(index.role_status,'knowledge_gate'),false);assert.equal(Object.hasOwn(index.role_status,'learning_observer'),false);
  assert.ok(index.agent_calls.every(item=>item.origin==='learner_agents'&&item.template_match===true));
  assert.deepEqual(index.agent_calls.filter(item=>item.role==='knowledge_model_agent').map(item=>item.operation).sort(),['initialize','move_check','move_check']);
  assert.ok(index.agent_calls.every(item=>item.response_id&&item.schema_path&&item.input_path&&item.response_path));
  assert.equal(meta.actual_learner_agent_prompt_paths.length,6);assert.equal(meta.learner_agent_prompt_integrity,true);
  assert.equal(Object.hasOwn(meta,'actual_learner_controller_prompt_paths'),false);
  assert.equal(timeline.protocol,'two-agent-v2');
  assert.deepEqual(timeline.steps.map(item=>item.knowledge_agent_checks.length),[2,0,1]);
  assert.ok(timeline.steps.every(item=>item.check_complete&&item.executed&&!Object.hasOwn(item,'gate')));
  assert.deepEqual(timeline.latest_checkpoint,two);assert.deepEqual(timeline.latest_agent_response_state,two);
  const review=await fs.readFile(path.join(f.outputDir,'P1/review.html'),'utf8');
  assert.ok(review.includes('Actual two-Agent instructions'));assert.ok(review.includes('Knowledge Model Agent check and storage records'));
  assert.ok(!review.includes('<th>Gate approved</th>'));assert.ok(!review.includes('Actual learner-controller instructions'));
  assert.equal(sha(await fs.readFile(path.join(f.outputDir,'P1/native.case.html'))),nativeSHA);
  await save(path.join(f.outputDir,'P1/step_04_knowledge_gate_1.prompt.md'),'A legacy gate call cannot be relabeled as part of a two-Agent run.');
  await assert.rejects(()=>finalizeVersionedExports({...f,promptVersion:version}),/two-Agent run contains legacy/);
  assert.equal(sha(await fs.readFile(path.join(f.outputDir,'P1/native.case.html'))),nativeSHA);
 }finally{await fs.rm(base,{recursive:true,force:true});}
});

test('knowledge timelines retain rejected candidates, validated checkpoints, and actual controller role prompts',async()=>{
 const base=await fs.mkdtemp(path.join(os.tmpdir(),'knowledge-export-'));
 try{
  const f=await fixture(base,'trial');
  f.manifest.learner_knowledge_protocol={format:'learner-knowledge-v1'};
  const prompts={learning_observer:'Observe concrete support only.',knowledge_gate:'Ground every action in the learner model.',learner:'Shared learner <rules> & actual prompt'};
  await save(path.join(f.outputDir,'code_snapshot/learning_observer_prompt.md'),prompts.learning_observer);
  await save(path.join(f.outputDir,'code_snapshot/knowledge_gate_prompt.md'),prompts.knowledge_gate);
  const before={format:'learner-knowledge-v1',revision:0,components:[{component_id:'KC1',status:'unlearned'}]},
   after={...before,revision:1,components:[{component_id:'KC1',status:'tentative',available_knowledge:['A narrow received hint.']}]};
  const rejectedGate={approved:false,checks:[{claim:'Full solution',supported:false}]},acceptedGate={approved:true,checks:[{claim:'Narrow response',supported:true}]};
  await save(path.join(f.outputDir,'P1/step_01_knowledge_audit.json'),{step:1,response_status:'blocked',update_validated:true,checkpoint_committed:true,gate_approved:false,executed:false,
   raw_response:'step_01_response.json',rejection_reason:'Unsupported proposed action.',knowledge_audit:{before,after,events:[{event_id:'message:0',kind:'concrete_hint'}],gate:rejectedGate}});
  await save(path.join(f.outputDir,'P1/step_02_knowledge_audit.json'),{step:2,response_status:'ok',update_validated:true,checkpoint_committed:true,gate_approved:true,execution_started:true,executed:true,execution_ok:true,
   raw_response:'step_02_response.json',knowledge_audit:{before:after,after,events:[],gate:acceptedGate}});
  await save(path.join(f.outputDir,'P1/learner_knowledge_model.json'),after);
  const first=await read(path.join(f.outputDir,'P1/step_01_response.json'));
  first.status='blocked';first.decision={memory:{component_states:[{component_id:'KC1',status:'known'}]}};
  await save(path.join(f.outputDir,'P1/step_01_response.json'),first);
  await save(path.join(f.outputDir,'P1/step_02_response.json'),{status:'ok',prompt_sha256:first.prompt_sha256});
  const names=['step_01_learning_observer','step_01_learner_candidate_1','step_01_knowledge_gate_1','step_02_learner_candidate_2','step_02_knowledge_gate_2'];
  for(const name of names){
   const role=name.includes('learning_observer')?'learning_observer':name.includes('knowledge_gate')?'knowledge_gate':'learner';
   await save(path.join(f.outputDir,'P1/'+name+'.prompt.md'),prompts[role]);
   await save(path.join(f.outputDir,'P1/'+name+'.input.json'),{role,knowledge:before});
   await save(path.join(f.outputDir,'P1/'+name+'.schema.json'),{type:'object'});
   await save(path.join(f.outputDir,'P1/'+name+'.response.json'),name==='step_01_knowledge_gate_1'?rejectedGate:
    {api:{response_id:name,model_returned:'offline-stub',status:'completed',usage:{input_tokens:10,output_tokens:5}},parsed:{}});
  }
  await save(path.join(f.outputDir,'P1/step_01_knowledge_gate_1.error.json'),{type:'candidate_rejected',message:'Unsupported proposed action.'});
  const version=await createPromptVersionBundle(f),nativeSHA=sha(await fs.readFile(path.join(f.outputDir,'P1/native.case.html')));
  await finalizeVersionedExports({...f,promptVersion:version});
  const index=await read(path.join(f.outputDir,'actual_prompt_index.json')),
   meta=await read(path.join(f.outputDir,'P1/export_metadata.json')),
   timeline=await read(path.join(f.outputDir,'P1/knowledge_timeline.json'));
  assert.equal(index.role_status.learning_observer.recorded_calls,1);
  assert.equal(index.role_status.knowledge_gate.recorded_calls,2);
  assert.equal(index.role_status.learner.recorded_calls,2);
  assert.equal(meta.actual_tutor_prompt_paths.length,2);
  assert.equal(meta.actual_learner_controller_prompt_paths.length,5);
  assert.equal(meta.learner_controller_prompt_integrity,true);
  const failedCall=index.agent_calls.find(v=>v.call_name==='step_01_knowledge_gate_1');
  assert.equal(failedCall.profile_id,'P1');assert.equal(failedCall.origin,'learner_controller');
  assert.ok(failedCall.input_path&&failedCall.schema_path&&failedCall.response_path);
  assert.ok(failedCall.error_path);
  const observerCall=index.agent_calls.find(v=>v.role==='learning_observer');
  assert.equal(observerCall.response_id,'step_01_learning_observer');
  assert.deepEqual(observerCall.usage,{input_tokens:10,output_tokens:5});
  assert.deepEqual(await read(path.join(f.outputDir,failedCall.response_path)),rejectedGate);
  assert.equal(timeline.steps[0].checkpoint_committed,true);
  assert.equal(timeline.steps[0].executed,false);
  assert.equal(timeline.steps[0].gate.approved,false);
  assert.equal(timeline.steps[1].executed,true);
  assert.equal(timeline.latest_checkpoint.components[0].status,'tentative','Actor memory cannot make an exported knowledge state known.');
  const review=await fs.readFile(path.join(f.outputDir,'P1/review.html'),'utf8');
  assert.ok(review.includes('Learner knowledge timeline')&&review.includes('Actual learner-controller instructions'));
  assert.ok(review.includes('Unsupported proposed action.')&&review.includes('knowledge_gate'));
  assert.equal(sha(await fs.readFile(path.join(f.outputDir,'P1/native.case.html'))),nativeSHA);
 }finally{await fs.rm(base,{recursive:true,force:true});}
});

test('legacy learner memory is never converted into an invented independent knowledge timeline',async()=>{
 const base=await fs.mkdtemp(path.join(os.tmpdir(),'knowledge-absent-'));
 try{
  const f=await fixture(base,'trial'),version=await createPromptVersionBundle(f);
  const response=await read(path.join(f.outputDir,'P1/step_01_response.json'));
  response.decision={memory:{component_states:[{component_id:'KC1',status:'known'}]}};
  await save(path.join(f.outputDir,'P1/step_01_response.json'),response);
  await finalizeVersionedExports({...f,promptVersion:version});
  assert.equal((await read(path.join(f.outputDir,'P1/export_metadata.json'))).knowledge_timeline,null);
  assert.equal(await fs.stat(path.join(f.outputDir,'P1/knowledge_timeline.json')).then(()=>true,()=>false),false);
  assert.ok((await fs.readFile(path.join(f.outputDir,'P1/review.html'),'utf8')).includes('Knowledge changes are not inferred from learner memory.'));
 }finally{await fs.rm(base,{recursive:true,force:true});}
});

test('focused condition replays keep same-profile records separate and preserve the advisor overview',async()=>{
 const base=await fs.mkdtemp(path.join(os.tmpdir(),'focused-knowledge-export-'));
 try{
  const f=await fixture(base,'trial',{withCalls:false});
  await fs.rm(path.join(f.outputDir,'tutor_code_snapshot'),{recursive:true});
  f.manifest.format='knowledge-focused-replay-v1';f.manifest.scope='Focused learner-side replay; no new Tutor or browser action.';
  f.runs=[{run_id:'P1',profile_id:'P1',status:'ok',steps:[{step:1}],exports:null},
   {run_id:'hint',profile_id:'P1',status:'ok',steps:[{step:1}],exports:null}];
  const state={format:'learner-knowledge-v1',revision:0,components:[{component_id:'KC1',status:'unlearned'}]};
  await save(path.join(f.outputDir,'code_snapshot/knowledge_gate_prompt.md'),'Gate source.');
  for(const run of f.runs){
   await save(path.join(f.outputDir,run.run_id,'step_01_response.json'),{status:'ok',prompt_sha256:sha('Shared learner <rules> & actual prompt'),
    model_visible_input:{profile:{id:'P1',condition:run.run_id}},learner_knowledge_model:state,
    knowledge_audit:{before:state,after:state,events:[],update_validated:true,gate:{approved:true}}});
   await save(path.join(f.outputDir,run.run_id,'step_01_knowledge_gate_1.prompt.md'),'Gate source.');
  }
  f.runs.push({run_id:'diagnostic',profile_id:'P1',status:'candidate_rejected',steps:[],exports:null});
  await save(path.join(f.outputDir,'diagnostic/step_01_knowledge_gate_1.prompt.md'),'Gate source.');
  await save(path.join(f.outputDir,'diagnostic/step_01_knowledge_gate_1.input.json'),{profile:{id:'P1',condition:'diagnostic'},candidate:{action:{type:'send_message'}}});
  await save(path.join(f.outputDir,'diagnostic/candidate_audit.json'),{gate:{approved:false},learner_generation_called:false,executed:false});
  await save(path.join(f.outputDir,'diagnostic/source_candidate.json'),{action:{type:'send_message'}});
  const overview='<!doctype html><title>Advisor report owned by another task</title>';
  await save(path.join(f.outputDir,'index.html'),overview);
  const version=await createPromptVersionBundle(f);
  await finalizeVersionedExports({...f,promptVersion:version,writeOverview:false});
  assert.equal(await fs.readFile(path.join(f.outputDir,'index.html'),'utf8'),overview);
  assert.equal((await read(path.join(f.outputDir,'P1/resolved_profile.json'))).condition,'P1');
  assert.equal((await read(path.join(f.outputDir,'hint/resolved_profile.json'))).condition,'hint');
  const meta=await read(path.join(f.outputDir,'hint/export_metadata.json'));
  assert.equal(meta.actual_learner_controller_prompt_paths.length,1);
  assert.ok(meta.actual_learner_controller_prompt_paths[0].includes('/hint/'));
  assert.equal(meta.actual_tutor_prompt_paths.length,0);
  const timeline=await read(path.join(f.outputDir,'hint/knowledge_timeline.json'));
  assert.equal(timeline.steps[0].source,'helper_response_only');
  assert.equal(timeline.steps[0].executed,null);assert.equal(timeline.steps[0].checkpoint_committed,null);
  assert.equal(timeline.latest_checkpoint,null);assert.deepEqual(timeline.latest_controller_response_state,state);
  const review=await fs.readFile(path.join(f.outputDir,'hint/review.html'),'utf8');
  assert.ok(review.includes('Focused replay and prompt version'));
  assert.ok(review.includes('No new Tutor call or browser action was made.'));
  assert.ok(!review.includes('<iframe'));
  assert.ok((await fs.readFile(path.join(f.outputDir,'prompts.html'),'utf8')).includes('hash represents an empty template set, not a Tutor prompt'));
  const diagnosticMeta=await read(path.join(f.outputDir,'diagnostic/export_metadata.json'));
  assert.equal(diagnosticMeta.student_decisions,0);assert.equal(diagnosticMeta.knowledge_timeline,null);
  assert.equal((await read(path.join(f.outputDir,'diagnostic/resolved_profile.json'))).condition,'diagnostic');
  const diagnosticReview=await fs.readFile(path.join(f.outputDir,'diagnostic/review.html'),'utf8');
  assert.ok(diagnosticReview.includes('Gate-only candidate diagnostic'));
  assert.ok(diagnosticReview.includes('no learner generation is implied'));
 }finally{await fs.rm(base,{recursive:true,force:true});}
});

test('content versions are deterministic and bind case, selected models, and source prompts',async()=>{
 const base=await fs.mkdtemp(path.join(os.tmpdir(),'prompt-versions-'));
 try{
  const one=await fixture(base,'one'),two=await fixture(base,'two');
  const a=await createPromptVersionBundle(one),b=await createPromptVersionBundle(two);
  assert.equal(a.prompt_version,b.prompt_version,'Output directory/run ID does not alter same content identity.');
  assert.notEqual(a.run_id,b.run_id);
  assert.equal(a.prompt_version,(await createPromptVersionBundle(one)).prompt_version,'Registration is idempotent.');
  const processOne=await fixture(base,'process-one'),processTwo=await fixture(base,'process-two');
  const staticSettings={tutor_model:'same-tutor',tutor_effort:'low',packages:{openai:'2.38.0'}};
  const p1=await createPromptVersionBundle({...processOne,runtimeSettings:{...staticSettings,started_at:'time-A',process_id:1,artifact_root:'/path-A',base_url:'http://127.0.0.1:8767',server_source_path:'/source-A'}});
  const p2=await createPromptVersionBundle({...processTwo,runtimeSettings:{...staticSettings,started_at:'time-B',process_id:2,artifact_root:'/path-B',base_url:'http://127.0.0.1:8768',server_source_path:'/source-B'}});
  assert.equal(p1.prompt_version,p2.prompt_version,'Timestamps, PID, ports and paths do not change semantic prompt version.');
  const changedTutor=await createPromptVersionBundle({...await fixture(base,'tutor-change'),runtimeSettings:{...staticSettings,tutor_model:'different-tutor'}});
  assert.notEqual(p1.prompt_version,changedTutor.prompt_version,'Effective Tutor model remains part of version identity.');
  const changedCase=await createPromptVersionBundle(await fixture(base,'case-change',{caseId:'source-B'}));
  const changedModel=await createPromptVersionBundle(await fixture(base,'model-change',{model:'different-model'}));
  const changedPrompt=await createPromptVersionBundle(await fixture(base,'prompt-change',{studentPrompt:'Different instructions'}));
  assert.notEqual(a.prompt_version,changedCase.prompt_version);
  assert.notEqual(a.prompt_version,changedModel.prompt_version);
  assert.notEqual(a.prompt_version,changedPrompt.prompt_version);
  assert.equal(a.learner_prompt_version,changedCase.learner_prompt_version);
  assert.notEqual(a.learner_prompt_version,changedPrompt.learner_prompt_version);
  await assert.rejects(()=>createPromptVersionBundle({...one,runtimeSettings:{OPENAI_API_KEY:'do-not-write'}}),/credentials/);
  assert.ok(!(await fs.readFile(path.join(one.outputDir,'prompt_version.json'),'utf8')).includes('do-not-write'));
 }finally{await fs.rm(base,{recursive:true,force:true});}
});

test('profile review embeds raw interaction and complete actual prompts without changing native files',async()=>{
 const base=await fs.mkdtemp(path.join(os.tmpdir(),'versioned-export-'));
 try{
  const f=await fixture(base,'trial'),promptVersion=await createPromptVersionBundle(f);
  const nativeBefore=sha(await fs.readFile(path.join(f.outputDir,'P1/native.case.html')));
  const summary=await finalizeVersionedExports({...f,promptVersion});
  assert.equal(summary.source_integrity,'matched_for_recorded_prompts');
  assert.equal(summary.agent_prompt_records,2);
  assert.equal(summary.student_call_records,1);
  assert.equal(sha(await fs.readFile(path.join(f.outputDir,'P1/native.case.html'))),nativeBefore);
  const review=await fs.readFile(path.join(f.outputDir,'P1/review.html'),'utf8');
  assert.ok(review.includes('Shared learner &lt;rules&gt; &amp; actual prompt'));
  assert.ok(review.includes('Current-stage example'));
  assert.ok(review.includes('prior_knowledge'));
  assert.ok(review.includes('<iframe'));
  assert.ok(review.includes('src="native.case.html"'));
  assert.ok(review.includes(promptVersion.prompt_version));
  assert.ok(!review.includes('Shared learner <rules>'));
  const meta=await read(path.join(f.outputDir,'P1/export_metadata.json'));
  assert.equal(meta.native_html_sha256,nativeBefore);
  assert.equal(meta.actual_tutor_prompt_paths.length,2);
  const index=await read(path.join(f.outputDir,'actual_prompt_index.json'));
  assert.equal(index.role_status.transformation.status,'not_recorded');
  assert.equal(index.role_status.transformation.recorded_calls,0);
  assert.ok(index.agent_calls.every(v=>v.profile_id==='P1'));
  assert.ok(index.agent_calls.every(v=>v.template_match===true));
  assert.ok(!(await fs.readFile(path.join(f.outputDir,'prompts.html'),'utf8')).includes('src="https://'));
 }finally{await fs.rm(base,{recursive:true,force:true});}
});

test('prompt drift is visible in metadata; raw failed records remain available and can be associated explicitly',async()=>{
 const base=await fs.mkdtemp(path.join(os.tmpdir(),'prompt-drift-'));
 try{
  const f=await fixture(base,'trial'),promptVersion=await createPromptVersionBundle(f);
  await save(path.join(f.outputDir,'tutor_api_runs/feedback_turn_failed/tutor.prompt.md'),'Different live Tutor prompt');
  const file=path.join(f.outputDir,'P1/step_01_response.json'),response=await read(file);
  response.prompt_sha256='not-frozen';await save(file,response);
  const summary=await finalizeVersionedExports({...f,promptVersion,runAssociations:{feedback_turn_failed:'P1'}});
  assert.equal(summary.source_integrity,'mismatch');
  assert.equal(summary.mismatches.length,2);
  const index=await read(path.join(f.outputDir,'actual_prompt_index.json'));
  assert.equal(index.agent_calls.find(v=>v.directory==='feedback_turn_failed').profile_id,'P1');
  assert.equal(await fs.readFile(path.join(f.outputDir,'tutor_api_runs/feedback_turn_failed/tutor.prompt.md'),'utf8'),'Different live Tutor prompt');
  await save(path.join(f.outputDir,'code_snapshot/student_prompt.md'),'Changed frozen source');
  await assert.rejects(()=>finalizeVersionedExports({...f,promptVersion}),/Frozen prompt content changed/);
 }finally{await fs.rm(base,{recursive:true,force:true});}
});

test('assembled Tutor prompt permits only source trailing whitespace normalization, retaining actual full hash',async()=>{
 const base=await fs.mkdtemp(path.join(os.tmpdir(),'prompt-whitespace-'));
 try{
  const f=await fixture(base,'trial');
  await save(path.join(f.outputDir,'tutor_code_snapshot/prompts/feedback_tutor.md'),'Tutor base instructions\n\n\n');
  const promptVersion=await createPromptVersionBundle(f);
  const result=await finalizeVersionedExports({...f,promptVersion});
  assert.equal(result.source_integrity,'matched_for_recorded_prompts');
  const index=await read(path.join(f.outputDir,'actual_prompt_index.json'));
  const tutor=index.agent_calls.find(v=>v.role==='tutor');
  assert.equal(tutor.sha256,sha('Tutor base instructions\n\n## selected\nCurrent-stage example'));
 }finally{await fs.rm(base,{recursive:true,force:true});}
});

test('no recorded requests are not represented as verified actual model calls; failed exports still get a review',async()=>{
 const base=await fs.mkdtemp(path.join(os.tmpdir(),'prompt-empty-'));
 try{
  const f=await fixture(base,'trial',{withCalls:false}),promptVersion=await createPromptVersionBundle(f);
  f.runs[0]={run_id:'P1',profile_id:'P1',status:'failed',steps:[],errors:[{message:'Initial API failed'}],exports:null};
  const summary=await finalizeVersionedExports({...f,promptVersion});
  assert.equal(summary.source_integrity,'no_recorded_prompts');
  const meta=await read(path.join(f.outputDir,'P1/export_metadata.json'));
  assert.equal(meta.native_html,null);
  assert.equal(meta.student_prompt_integrity,null);
  assert.equal(meta.system_prompt_integrity,null);
  assert.ok((await fs.readFile(path.join(f.outputDir,'P1/review.html'),'utf8')).includes('Initial API failed'));
 }finally{await fs.rm(base,{recursive:true,force:true});}
});

test('run catalogue appends new batches and preserves previous entries without duplicating same export',async()=>{
 const base=await fs.mkdtemp(path.join(os.tmpdir(),'prompt-catalogue-'));
 try{
  const cataloguePath=path.join(base,'history.jsonl');
  const first=await fixture(base,'first'),v1=await createPromptVersionBundle(first);
  await finalizeVersionedExports({...first,promptVersion:v1,cataloguePath});
  const original=await fs.readFile(cataloguePath,'utf8');
  await finalizeVersionedExports({...first,promptVersion:v1,cataloguePath});
  assert.equal(await fs.readFile(cataloguePath,'utf8'),original);
  const second=await fixture(base,'second',{studentPrompt:'Edited learner prompt'}),v2=await createPromptVersionBundle(second);
  await finalizeVersionedExports({...second,promptVersion:v2,cataloguePath});
  const lines=(await fs.readFile(cataloguePath,'utf8')).trim().split('\n');
  assert.equal(lines.length,2);
  assert.equal(lines[0]+'\n',original);
  const history=await fs.readFile(path.join(base,'history.html'),'utf8');
  assert.ok(history.includes(v1.prompt_version)&&history.includes(v2.prompt_version));
  assert.ok(history.includes('first/index.html')&&history.includes('second/index.html'));
 }finally{await fs.rm(base,{recursive:true,force:true});}
});

test('generated review materials use English labels while original dialogue is preserved',async()=>{
 const base=await fs.mkdtemp(path.join(os.tmpdir(),'prompt-english-'));
 try{
  const f=await fixture(base,'trial'),promptVersion=await createPromptVersionBundle(f);
  const native='<!doctype html><title>Original dialogue</title><p>\u6211\u4e0d\u77e5\u9053\u4ece\u54ea\u91cc\u5f00\u59cb\u3002</p>';
  await save(path.join(f.outputDir,'P1/native.case.html'),native);
  const cataloguePath=path.join(base,'history.jsonl');
  await finalizeVersionedExports({...f,promptVersion,cataloguePath});
  const materials=['index.html','prompts.html','P1/review.html'];
  for(const name of materials){
   const html=await fs.readFile(path.join(f.outputDir,name),'utf8');
   assert.ok(html.includes('<html lang="en">'),name+' declares English.');
   assert.ok(!/[\u3400-\u9fff]/u.test(html),name+' has no untranslated Chinese UI labels.');
  }
  const history=await fs.readFile(path.join(base,'history.html'),'utf8');
  assert.ok(history.includes('<html lang="en">'));
  assert.ok(!/[\u3400-\u9fff]/u.test(history));
  assert.ok(history.includes('Simulated learner run and version history'));
  const review=await fs.readFile(path.join(f.outputDir,'P1/review.html'),'utf8');
  assert.ok(review.includes('Actual feedback-system instructions for this learner'));
  assert.ok(review.includes('Interaction and prompt version'));
  assert.equal(await fs.readFile(path.join(f.outputDir,'P1/native.case.html'),'utf8'),native,
   'Presentation language must not translate or rewrite the original dialogue.');
 }finally{await fs.rm(base,{recursive:true,force:true});}
});

test('history presentation prefers an existing English edition without changing the run catalogue',async()=>{
 const base=await fs.mkdtemp(path.join(os.tmpdir(),'prompt-english-history-'));
 try{
  const f=await fixture(base,'original'),promptVersion=await createPromptVersionBundle(f);
  const cataloguePath=path.join(base,'history.jsonl');
  await finalizeVersionedExports({...f,promptVersion,cataloguePath});
  const before=await fs.readFile(cataloguePath,'utf8');
  await save(path.join(f.outputDir+'_english','index.html'),'<!doctype html><html lang="en"><p>English review edition.</p></html>');
  const result=await renderRunHistory(cataloguePath);
  assert.equal(result.entries,1);
  assert.equal(await fs.readFile(cataloguePath,'utf8'),before,'A translation is not registered as a new experiment.');
  const history=await fs.readFile(path.join(base,'history.html'),'utf8');
  assert.ok(history.includes('original_english/index.html'));
  assert.ok(!history.includes('href="original/index.html"'));
  assert.ok(history.includes(promptVersion.prompt_version));
  assert.ok(!/[\u3400-\u9fff]/u.test(history));
 }finally{await fs.rm(base,{recursive:true,force:true});}
});
