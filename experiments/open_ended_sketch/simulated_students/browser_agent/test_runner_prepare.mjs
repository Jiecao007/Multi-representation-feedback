/** Preparation is once per batch; no browser, app server, or model API calls. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {fileURLToPath} from 'node:url';
import {options,validatePreparedSeed,validateCaseSeed} from './run.mjs';

const exec=promisify(execFile),HERE=path.dirname(fileURLToPath(import.meta.url));
const temporary=await fs.mkdtemp(path.join(os.tmpdir(),'learner-runner-prepare-'));
const agent=path.join(temporary,'experiments/example/simulated_students/browser_agent');
const log=path.join(temporary,'preparer_calls.jsonl');
const sourceNames=['run.mjs','browser_driver.mjs','prompt_versions.mjs'];
const allProfiles=['p1_average.json','p2_low_motivation.json','p3_low_feedback_uptake.json',
 'p4_low_textual_expression.json','p5_low_diagrammatic_expression.json',
 'p6_low_coordination_translation.json','p7_combined_support_needs.json'];
const digest=value=>crypto.createHash('sha256').update(value).digest('hex');
const data=value=>'data:image/png;base64,'+Buffer.from(value).toString('base64');

try{
 assert.equal(options([]).profilePaths.length,2,'Legacy defaults remain P1/P2.');
 assert.equal(options(['--case-response','request.json']).profilePaths.length,7);
 assert.equal(options(['--case-response','request.json','--profile','p4.json']).profilePaths.length,1);
 assert.throws(()=>options(['--case-response','request.json','--case','case.json']),/either/);
 assert.throws(()=>options(['--prepare-only']),/requires/);

 const prepared={source_id:'source-A',initial_explanation:'',provenance:{
  student_figures:[{sha256:digest('student-A')}],student_crop_sha256:digest('student-A'),task_figures:[]}};
 const payload={record:{id:'source-A'},original:data('student-A')};
 assert.equal(validatePreparedSeed(prepared,payload).source_id,'source-A');
 assert.equal(validateCaseSeed({...prepared,provenance:{...prepared.provenance,generated_prior:true}},payload).source_id,'source-A');
 assert.throws(()=>validateCaseSeed({...prepared,provenance:{...prepared.provenance,generated_prior:true}},
  {...payload,original:data('other')}),/does not match/,'Separately prepared --case input keeps its Figure binding.');
 assert.throws(()=>validateCaseSeed({source_id:'source-A',provenance:{generated_prior:true}},payload),/exactly one/);
 assert.throws(()=>validateCaseSeed({source_id:'source-A',provenance:{preparation_request_sha256:'request-hash'}},payload),/exactly one/);
 assert.throws(()=>validateCaseSeed({source_id:'source-A',provenance:{analysis_format:'multimodal-response-prior-v1'}},payload),/exactly one/);
 assert.equal(validateCaseSeed({source_id:'source-A',provenance:{student_crop_sha256:digest('student-A')}},payload),null,
  'Historical handwritten cases without generated metadata preserve their existing path.');
 assert.throws(()=>validatePreparedSeed(prepared,{...payload,original:data('other')}),/does not match/);
 assert.throws(()=>validatePreparedSeed(prepared,{...payload,record:{id:'source-B'}}),/source_id differs/);
 for(const studentFigures of [[],[{sha256:'one'},{sha256:'two'}]]){
  assert.throws(()=>validatePreparedSeed({...prepared,provenance:{...prepared.provenance,student_figures:studentFigures}},payload),/exactly one/);
 }
 assert.throws(()=>validatePreparedSeed(prepared,{...payload,question:{image:data('task')}}),/task Figures/);
 const withTask={...prepared,provenance:{...prepared.provenance,task_figures:[{sha256:digest('task')}]}};
 assert.equal(validatePreparedSeed(withTask,{...payload,question:{image:data('task')}}).task_figure_sha256,digest('task'));
 assert.throws(()=>validatePreparedSeed(withTask,payload),/task Figures/);

 await fs.mkdir(path.join(agent,'profiles'),{recursive:true});
 for(const name of sourceNames)await fs.copyFile(path.join(HERE,name),path.join(agent,name));
 for(const name of ['student_model.py','student_prompt.md','profile_dimensions.json','profile_prompt.py','prepare_case.py',
  'prior_analysis_types.py','prior_analysis_prompt.md','learner_knowledge.py','knowledge_model_agent.py',
  'knowledge_model_agent_prompt.md','initial_knowledge_cache.py','learner_grounding.py','README.md','test_contracts.py']){
  await fs.writeFile(path.join(agent,name),'Offline runner fixture; never executed as a model helper.\n');
 }
 for(const name of allProfiles)await fs.copyFile(path.join(HERE,'profiles',name),path.join(agent,'profiles',name));
 const python=path.join(temporary,'fake-python');
 await fs.writeFile(python,`#!${process.execPath}
const fs=require('node:fs'),path=require('node:path');
const argv=process.argv.slice(2),get=key=>argv[argv.indexOf(key)+1];
const request=JSON.parse(fs.readFileSync(get('--request'),'utf8'));
fs.appendFileSync(${JSON.stringify(log)},JSON.stringify({argv,profiles:argv.filter(v=>v==='--profile').length})+'\\n');
const out=get('--out');fs.mkdirSync(out,{recursive:false});
const dry=argv.includes('--dry-run');
fs.writeFileSync(path.join(out,'preparation_record.json'),JSON.stringify({status:dry?'dry_run':'prepared',api:{called:request.pretend_api===true},fixture:true}));
if(!dry){fs.writeFileSync(path.join(out,'generated_case.json'),JSON.stringify({source_id:'fixture-source',initial_explanation:'',provenance:{prior_policy:'response_inferred'}}));fs.writeFileSync(path.join(out,'resolved_profiles.json'),'{}');}
`,{mode:0o700});
 const request=path.join(temporary,'request.json');await fs.writeFile(request,'{}');
 const invoke=async(name,extra=[])=>{
  const output=path.join(temporary,name);
  const result=await exec(process.execPath,[path.join(agent,'run.mjs'),'--case-response',request,
   '--python',python,'--out',output,'--base-url','http://127.0.0.1:1',...extra]);
  return {output,status:JSON.parse(result.stdout.trim().split('\n').at(-1))};
 };
 const dry=await invoke('dry',['--dry-run']);
 assert.equal(dry.status.status,'preparation_required');
 assert.equal(dry.status.api_calls,0);
 assert.equal(dry.status.profiles.length,7);
 assert.equal(await fs.stat(path.join(dry.output,'case_preparation','generated_case.json')).then(()=>true,()=>false),false);
 const prep=await invoke('prepare',['--prepare-only']);
 assert.equal(prep.status.status,'prepared_only');
 assert.equal(prep.status.tutor_api_calls,0);
 const manifest=JSON.parse(await fs.readFile(path.join(prep.output,'experiment_manifest.json'),'utf8'));
 assert.equal(manifest.case_config.initial_explanation,'','Figure-only response text is not invented.');
 assert.equal(manifest.runs.length,0);
 const subset=await invoke('subset',['--prepare-only','--profile',path.join(agent,'profiles',allProfiles[3])]);
 assert.deepEqual(subset.status.profiles,['P4']);
 await fs.writeFile(request,JSON.stringify({pretend_api:true}));
 await assert.rejects(()=>invoke('bad-dry',['--dry-run']),/Dry-run preparation must not call/);
 const calls=(await fs.readFile(log,'utf8')).trim().split('\n').map(JSON.parse);
 assert.equal(calls.length,4,'Exactly one preparer invocation per batch, never per learner.');
 assert.deepEqual(calls.map(c=>c.profiles),[7,7,1,7]);
 console.log('PASS runner preparation: one shared preparation, seven/subset profiles, zero-API dry-run, no app/browser calls, exact Figure/task binding, Figure-only text preserved.');
}finally{await fs.rm(temporary,{recursive:true,force:true});}
