/** Autonomous student trials through the existing browser UI and its own exports. */
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';
import {BrowserDriver} from './browser_driver.mjs';
import {createPromptVersionBundle,finalizeVersionedExports} from './prompt_versions.mjs';

const HERE=path.dirname(fileURLToPath(import.meta.url));
const ROOT=path.resolve(HERE,'../../../..');
const stamp=()=>new Date().toISOString();
const hash=value=>crypto.createHash('sha256').update(value).digest('hex');
const canonical=value=>JSON.stringify(value,(_key,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);
const save=async(file,data)=>{await fs.mkdir(path.dirname(file),{recursive:true});await fs.writeFile(file,JSON.stringify(data,null,2)+'\n');};
const append=async(file,data)=>fs.appendFile(file,JSON.stringify(data)+'\n');
const ALL_PROFILES=['p1_average.json','p2_low_motivation.json','p3_low_feedback_uptake.json',
 'p4_low_textual_expression.json','p5_low_diagrammatic_expression.json',
 'p6_low_coordination_translation.json','p7_combined_support_needs.json'];
const LEARNER_SOURCES=['run.mjs','browser_driver.mjs','student_model.py','student_prompt.md','profile_dimensions.json','profile_prompt.py',
 'prepare_case.py','prior_analysis_types.py','prior_analysis_prompt.md',
 'knowledge_model_agent.py','knowledge_model_agent_prompt.md','initial_knowledge_cache.py','prompt_versions.mjs'];
const KNOWLEDGE_PROTOCOL={format:'knowledge-model-agent-v4',protocol:'two-agent-v2',
 agents:['Knowledge Model Agent','Learner Agent'],authority:'The stateful Knowledge Model Agent stores the known, unknown and possibly_known state; the Learner Agent reads it and cannot rewrite it.',
 initialization:'One cached original-Response initialization is copied into each profile; later knowledge updates remain separate. All three knowledge lists are optional.',
 profile_ownership:{KnowledgeModelAgent:['feedback_processing','initial_response_knowledge'],LearnerAgent:['task_motivation','textual_representation','diagrammatic_representation','coordination_translation']},
 check_cadence:'One semantic knowledge-update check per newly delivered Feedback move, before the next Learner Agent action. Repeated UI observations do not repeat a move check.',
 update_policy:'Concrete explanations, hints and actual attempts support local updates; a plain question does not grant a missing method.',
 checkpoint_policy:'Store the Knowledge Model Agent state before calling the Learner Agent; preserve it even if the subsequent learner API call fails.',
 execution_policy:'Execute a schema-valid Learner Agent decision only after the Knowledge Model Agent check completes. There is no independent observer or gate Agent.'};

export function options(argv){
 const args={baseURL:'http://127.0.0.1:8765',casePath:path.join(HERE,'cases/math_2_numberline.json'),profilePaths:[],
  outputDir:path.join(ROOT,'outputs/simulated_students_'+stamp().replace(/[-:]/g,'').replace(/\..*/,'')),
  model:process.env.SIMULATED_STUDENT_MODEL||'gpt-6-sol',effort:'low',maxSteps:24,headless:false,concurrency:2,
  python:process.env.SIMULATED_STUDENT_PYTHON||'python3',dryRun:false,caseResponsePath:null,prepareOnly:false,preparationModel:null,
  tutorRecordsRoot:null,runtimeConfigPath:null,initialKnowledgeCacheDir:null,historyCatalogue:path.join(ROOT,'outputs/simulated_learner_run_history.jsonl')};
 let explicitCase=false;
 for(let i=0;i<argv.length;i++){
  const key=argv[i];
  if(key==='--headless'){args.headless=true;continue;}
  if(key==='--dry-run'){args.dryRun=true;continue;}
  if(key==='--prepare-only'){args.prepareOnly=true;continue;}
  if(key==='--help'){args.help=true;continue;}
  const fields={'--base-url':'baseURL','--case':'casePath','--case-response':'caseResponsePath','--preparation-model':'preparationModel','--out':'outputDir','--model':'model','--effort':'effort','--max-steps':'maxSteps','--concurrency':'concurrency','--python':'python',
   '--tutor-records-root':'tutorRecordsRoot','--runtime-config':'runtimeConfigPath','--initial-knowledge-cache':'initialKnowledgeCacheDir','--history-catalogue':'historyCatalogue'};
  if(key==='--profile'){if(!argv[i+1])throw Error('--profile needs a file');args.profilePaths.push(path.resolve(argv[++i]));}
  else if(fields[key]){if(!argv[i+1])throw Error(key+' needs a value');args[fields[key]]=argv[++i];if(key==='--case')explicitCase=true;}
  else throw Error('Unknown argument: '+key);
 }
 if(args.caseResponsePath&&explicitCase)throw Error('Use either --case or --case-response, not both.');
 if(args.prepareOnly&&!args.caseResponsePath)throw Error('--prepare-only requires --case-response.');
 if(!args.profilePaths.length)args.profilePaths=(args.caseResponsePath?ALL_PROFILES:ALL_PROFILES.slice(0,2)).map(f=>path.join(HERE,'profiles',f));
 args.casePath=path.resolve(args.casePath);args.outputDir=path.resolve(args.outputDir);
 args.initialKnowledgeCacheDir=path.resolve(args.initialKnowledgeCacheDir||path.join(path.dirname(args.outputDir),'simulated_learner_initial_knowledge_cache'));
 if(args.caseResponsePath)args.caseResponsePath=path.resolve(args.caseResponsePath);
 for(const key of ['tutorRecordsRoot','runtimeConfigPath','historyCatalogue'])if(args[key])args[key]=path.resolve(args[key]);
 args.maxSteps=Number(args.maxSteps);args.concurrency=Number(args.concurrency);
 if(!Number.isInteger(args.maxSteps)||args.maxSteps<1||args.maxSteps>100)throw Error('--max-steps must be 1–100');
 if(!Number.isInteger(args.concurrency)||args.concurrency<1||args.concurrency>4)throw Error('--concurrency must be 1–4');
 const origin=new URL(args.baseURL);
 if(!['127.0.0.1','localhost','[::1]'].includes(origin.hostname))throw Error('This local research runner only connects to a localhost feedback app.');
 return args;
}

async function learnerSnapshot(outputDir){
 const hashes={},snapshot=path.join(outputDir,'code_snapshot');await fs.mkdir(snapshot);
 for(const name of LEARNER_SOURCES){
  const data=await fs.readFile(path.join(HERE,name));hashes[name]=hash(data);
  await fs.writeFile(path.join(snapshot,name),data);
 }
 for(const name of ['README.md','test_contracts.py'])await fs.copyFile(path.join(HERE,name),path.join(snapshot,name));
 return hashes;
}

export async function tutorRecordNames(directory){
 return (await fs.readdir(directory).catch(error=>{if(error.code==='ENOENT')return [];throw error;}))
  .filter(name=>name.startsWith('feedback_turn_'));
}

export async function collectTutorRecords(directory,outputDir,runs,baseline){
 const sessions=new Set(runs.map(run=>run.exports?.feedback_session).filter(Boolean));
 const copied=[],unassociated=[];
 for(const name of await tutorRecordNames(directory)){
  if(baseline.has(name))continue;
  const folder=path.join(directory,name);let sessionId=null;
  for(const [file,key] of [['session.json','id'],['public_reply.json','session_id']]){
   try{sessionId=JSON.parse(await fs.readFile(path.join(folder,file),'utf8'))[key]||sessionId;}
   catch(error){if(error.code!=='ENOENT'&&!(error instanceof SyntaxError))throw error;}
  }
  // In a shared application, a concurrently completed unrelated session is not
  // part of this experiment. Failed calls with no session are retained as
  // unassociated evidence, never falsely assigned to an individual learner.
  if(sessionId&&!sessions.has(sessionId))continue;
  const destination=path.join(outputDir,'tutor_api_runs',name);
  await fs.cp(folder,destination,{recursive:true,errorOnExist:true,force:false});
  copied.push(name);if(!sessionId)unassociated.push(name);
 }
 return {source_directory:directory,copied_directories:copied,unassociated_directories:unassociated,
  interpretation:'Actual API artifacts; unassociated failures are not attributed to a profile without further evidence.'};
}

/** Archive K0 once per run, without sharing any later learner memory. */
export async function collectInitialKnowledge(outputDir,runs){
 const profiles=[];let first=null;
 for(const run of runs){
  const file=path.join(outputDir,run.run_id,'step_01_initial_knowledge_cache.json');
  let receipt;
  try{receipt=JSON.parse(await fs.readFile(file,'utf8'));}
  catch(error){if(error.code==='ENOENT'&&run.status==='failed')continue;throw error;}
  const entry=receipt.cached_initialization;
  if(!entry||entry.knowledge_sha256!==hash(canonical(entry.knowledge_state)))throw Error('A shared initial knowledge snapshot failed its content check.');
  if(first&&(entry.key!==first.key||entry.knowledge_sha256!==first.knowledge_sha256))throw Error('Profiles in the same run did not share one initial knowledge state.');
  first??=entry;
  profiles.push({profile:run.profile_id,cache_hit:receipt.cache_hit===true,
   receipt_path:path.relative(outputDir,file)});
 }
 if(!first)return {profiles:[],shared:false};
 const snapshot={format:'shared-initial-knowledge-run-v1',cache_key:first.key,
  knowledge_state:first.knowledge_state,knowledge_sha256:first.knowledge_sha256,
  origin:first.origin,profiles,updates_shared:false};
 await save(path.join(outputDir,'shared_initial_knowledge.json'),snapshot);
 return {shared:true,cache_key:first.key,knowledge_sha256:first.knowledge_sha256,
  snapshot_path:'shared_initial_knowledge.json',new_initialization_calls:profiles.filter(p=>!p.cache_hit).length,
  cache_hits:profiles.filter(p=>p.cache_hit).length,profiles,updates_shared:false};
}

async function prepareResponse(args){
 const directory=path.join(args.outputDir,'case_preparation');
 const argv=['-B',path.join(HERE,'prepare_case.py'),'--request',args.caseResponsePath,'--out',directory,'--effort','low'];
 if(args.preparationModel)argv.push('--model',args.preparationModel);
 for(const profile of args.profilePaths)argv.push('--profile',profile);
 if(args.dryRun)argv.push('--dry-run');
 const code=await new Promise((resolve,reject)=>{
  const child=spawn(args.python,argv,{cwd:ROOT,stdio:['ignore','ignore','ignore']});
  child.on('error',reject);child.on('close',resolve);
 });
 let record;
 try{record=JSON.parse(await fs.readFile(path.join(directory,'preparation_record.json'),'utf8'));}
 catch{throw Error('Response preparation did not save preparation_record.json. Check the configured Python and preparation dependencies.');}
 if(code!==0||!['prepared','dry_run'].includes(record.status)){
  throw Error('Response preparation failed ('+record.status+'); inspect case_preparation/preparation_record.json.');
 }
 if(args.dryRun&&(record.status!=='dry_run'||record.api?.called!==false))throw Error('Dry-run preparation must not call the model or generate a case.');
 if(!args.dryRun&&record.status!=='prepared')throw Error('Response preparation did not produce a prepared case.');
 return {directory,record};
}

const imageHash=image=>{
 if(typeof image!=='string'||!/^data:image\/[\w.+-]+;base64,/.test(image))throw Error('The selected app example has no supported initial image.');
 return hash(Buffer.from(image.slice(image.indexOf(',')+1),'base64'));
};

export function validatePreparedSeed(caseConfig,payload){
 const provenance=caseConfig.provenance||{},figures=provenance.student_figures;
 if(!Array.isArray(figures)||figures.length!==1||typeof figures[0]?.sha256!=='string'){
  throw Error('Browser trials require exactly one analyzed student Figure matching a registered app example. Use --prepare-only for text-only, multiple-Figure, or unregistered responses.');
 }
 const originalHash=imageHash(payload.original);
 if(originalHash!==figures[0].sha256||provenance.student_crop_sha256&&provenance.student_crop_sha256!==originalHash){
  throw Error('Prepared student Figure does not match the selected app example. Register the same response before a browser trial, or use --prepare-only.');
 }
 const taskFigures=provenance.task_figures;
 if(!Array.isArray(taskFigures))throw Error('Prepared case must record which task Figures were analyzed.');
 const actualTaskHash=payload.question?.image?imageHash(payload.question.image):null;
 if(taskFigures.length!==(actualTaskHash?1:0)||actualTaskHash&&taskFigures[0]?.sha256!==actualTaskHash){
  throw Error('Analyzed task Figures do not match the app example task Figure. Use the same task scaffold or --prepare-only; an unanalyzed scaffold will not be substituted.');
 }
 const sourceId=caseConfig.source_id||caseConfig.example_id||caseConfig.case_id;
 if(payload.record?.id&&payload.record.id!==sourceId)throw Error('The app example source_id differs from the prepared response.');
 return {student_figure_sha256:originalHash,task_figure_sha256:actualTaskHash,source_id:sourceId};
}

export function validateCaseSeed(caseConfig,payload,{prepared=false}={}){
 const provenance=caseConfig.provenance||{};
 const generated=prepared||provenance.generated_prior===true||
  Object.hasOwn(provenance,'preparation_request_sha256')||
  Object.hasOwn(provenance,'student_figures')||Object.hasOwn(provenance,'task_figures')||
  String(provenance.analysis_format||'').startsWith('multimodal-response-prior');
 // A separately prepared generated_case.json must retain the same source
 // safeguards when later supplied through the existing --case option.
 return generated?validatePreparedSeed(caseConfig,payload):null;
}

/** Old imposed priors stay inspectable, but are not new response-inferred runs. */
export function validateResponseInferredPrior(caseConfig){
 if(caseConfig?.provenance?.prior_policy!=='response_inferred'){
  throw Error('Current learner runs require a response-inferred prior. Prepare the original Task and student Response with --case-response, or pass its newly generated_case.json with --case. Historical/manual priors remain readable and available to --dry-run; they are not silently reused as new inferred knowledge.');
 }
 return 'response_inferred';
}

function modelDecision(args,requestPath,responsePath){
 return new Promise((resolve,reject)=>{
  const child=spawn(args.python,['-B',path.join(HERE,'student_model.py'),'--request',requestPath,'--response',responsePath,'--model',args.model,'--effort',args.effort],
   {cwd:ROOT,stdio:['ignore','pipe','pipe']});
  let stderr='';child.stderr.on('data',b=>{stderr+=b.toString();});
  child.on('error',reject);
  child.on('close',async code=>{
   try{const result=JSON.parse(await fs.readFile(responsePath,'utf8'));
    // A completed Knowledge Model Agent check remains stored even if the
    // subsequent Learner Agent call fails. No failed helper is executable.
    resolve({result,exitCode:code});
   }catch(error){reject(Error('Student API decision failed ('+(code??'launch')+'): '+(error.message||stderr.slice(0,200))));}
  });
 });
}

/** Verify stored Agent-state receipts; learner-authored memory has no authority. */
export function knowledgeReceipt(result,previous=null,{exitCode=0}={}){
 const audit=result?.knowledge_audit;
 if(audit?.protocol==='two-agent-v2'||['knowledge-model-agent-v2','knowledge-model-agent-v3','knowledge-model-agent-v4'].includes(result?.learner_knowledge_model?.format)){
  if(audit?.protocol!=='two-agent-v2'||typeof audit.check_complete!=='boolean')throw Error('The learner helper did not return a two-Agent knowledge check receipt.');
  if(Object.hasOwn(audit,'gate'))throw Error('A two-Agent receipt must not claim an independent gate.');
  let checkpoint=null;
  if(audit.check_complete){
   const state=result.learner_knowledge_model;
   if(!['knowledge-model-agent-v2','knowledge-model-agent-v3','knowledge-model-agent-v4'].includes(state?.format)||!Number.isInteger(state.revision)||state.revision<0||!/^[a-f0-9]{64}$/.test(state.state_sha256||''))throw Error('The completed knowledge check has no supported Agent state.');
   if(!audit.after||canonical(audit.after)!==canonical(state))throw Error('The knowledge check receipt does not match its returned Agent state.');
   if(previous&&(!audit.before||canonical(audit.before)!==canonical(previous)))throw Error('The knowledge check receipt is not bound to the preceding Agent checkpoint.');
   checkpoint=structuredClone(state);
  }
  const helperOk=exitCode===0&&result.status==='ok'&&!result.error;
  if(helperOk&&typeof result.decision?.action?.type!=='string')throw Error('The two-Agent helper returned no Learner Agent action.');
  const readMatched=audit.learner_read_state_sha256===checkpoint?.state_sha256;
  if(helperOk&&audit.check_complete&&!readMatched)throw Error('The Learner Agent did not read the completed Knowledge Model Agent state.');
  const executable=helperOk&&audit.check_complete&&readMatched;
  const reason=executable?null:result.error?.message||result.error?.type||(!audit.check_complete?'The Knowledge Model Agent check did not complete.':'The Learner Agent helper did not complete successfully.');
  return {protocol:'two-agent-v2',check_complete:audit.check_complete,checkpoint,executable,
   knowledge_agent_checks:audit.checks??[],warnings:audit.warnings??[],rejection_reason:reason};
 }
 // Legacy reader only: historical observer/controller/gate receipts retain
 // their recorded meaning. Current trials declare two-agent-v2 above.
 if(!audit||typeof audit!=='object'||typeof audit.update_validated!=='boolean')throw Error('The learner helper did not return a knowledge controller receipt.');
 let checkpoint=null;
 if(audit.update_validated){
  const state=result.learner_knowledge_model;
  if(state?.format!=='learner-knowledge-v1'||!Number.isInteger(state.revision)||state.revision<0||!/^[a-f0-9]{64}$/.test(state.state_sha256||''))throw Error('The validated knowledge receipt has no supported controller state.');
  if(!audit.after||canonical(audit.after)!==canonical(state))throw Error('The knowledge receipt does not match its returned controller state.');
  if(previous&&(!audit.before||canonical(audit.before)!==canonical(previous)))throw Error('The knowledge receipt is not bound to the preceding checkpoint.');
  checkpoint=structuredClone(state);
 }
 const approved=audit.gate?.approved===true;
 const executable=exitCode===0&&result.status==='ok'&&!result.error&&audit.update_validated&&approved;
 const reason=executable?null:result.error?.message||result.error?.type||(!audit.update_validated?'Knowledge update was not validated.':!approved?'The knowledge gate did not approve the proposed learner action.':'The learner API helper did not complete successfully.');
 return {protocol:'legacy-gate-v1',update_validated:audit.update_validated,checkpoint,gate_approved:approved,executable,rejection_reason:reason};
}

/** Keep the Learner Agent's episodic channel separate from subject knowledge. */
export function learnerEpisodicMemory(result,previous=null){
 const memory=result?.learner_agent_memory;
 if(memory===undefined||memory===null)return previous===null?null:structuredClone(previous);
 if(typeof memory!=='object'||Array.isArray(memory)||Object.keys(memory).sort().join(',')!=='last_action,pending_question'||
   typeof memory.last_action!=='string'||typeof memory.pending_question!=='string')throw Error('Learner Agent episodic memory must contain only last_action and pending_question strings.');
 return structuredClone(memory);
}

/** Public UI evidence of what actually happened, never a correctness judgment. */
export function learningObservation(before,after,action,result,history=[]){
 const visibleDiagram=observation=>Array.isArray(observation?.elements)?observation.elements.map(element=>Object.fromEntries(
  ['id','kind','label','texts','canvas_bounds','points','arrow_start','arrow_end'].filter(key=>Object.hasOwn(element,key)).map(key=>[key,element[key]]))):null;
 const a=visibleDiagram(before),b=visibleDiagram(after);
 const changed=a!==null&&b!==null&&canonical(a)!==canonical(b);
 const beforeDigest=a===null?null:hash(canonical(a)),afterDigest=b===null?null:hash(canonical(b));
 const editTypes=new Set(['add_text','edit_text','add_object','move','add_connection','edit_connection','reshape_connection','resize','delete','undo']);
 const lastSubmission=history.findLastIndex(item=>item.action?.type==='submit_revisions'&&item.result?.ok!==false);
 const committedDigest=lastSubmission>=0?history[lastSubmission].learning_observation?.diagram_after_sha256:
  history.find(item=>item.learning_observation?.diagram_before_sha256)?.learning_observation.diagram_before_sha256;
 const changedDraft=typeof committedDigest==='string'&&afterDigest!==null&&committedDigest!==afterDigest;
 const signatures=new Set((before?.messages||[]).map((message,index)=>canonical([message.index??index,message.role,message.text,message.error===true])));
 const added=(after?.messages||[]).map((message,index)=>({...message,index:message.index??index})).filter(message=>!signatures.has(canonical([message.index,message.role,message.text,message.error===true])));
 const actionContext=(before?.messages||[]).map((message,index)=>({...message,index:message.index??index}))
  .filter(message=>['assistant','tutor'].includes(message.role)&&!message.error).at(-1);
 const dialogueAttempt=action?.type==='send_message'&&typeof action.text==='string'&&!!action.text.trim()&&added.some(message=>message.role==='user'&&!message.error&&message.text?.trim()===action.text.trim());
 // A rendered learner reply is an actual attempt even if the following Tutor
 // delivery fails. Only delivered nonerror Tutor messages can supply support.
 const contentAttempt=dialogueAttempt||result?.ok===true&&result?.result?.library_open!==true&&(editTypes.has(action?.type)&&changed||action?.type==='submit_revisions'&&changedDraft);
 const requestedIndex=action?.messageIndex==null?(before?.messages||[]).filter(message=>message.show_available).at(-1)?.index:
  action.messageIndex<0?(before?.messages||[]).length+action.messageIndex:action.messageIndex;
 const shownMessage=(before?.messages||[]).find(message=>message.index===requestedIndex&&message.show_available);
 const highlightIds=observation=>(observation?.elements||[]).filter(element=>element.highlighted).map(element=>element.id).sort();
 const newHighlight=highlightIds(after).length>0&&canonical(highlightIds(before))!==canonical(highlightIds(after));
 const newReference=after?.status?.model_badge==='Feedback reference'&&before?.status?.model_badge!=='Feedback reference';
 const referenceRevealed=action?.type==='show_feedback'&&result?.ok===true&&shownMessage&&b?.length>0&&(changed||newHighlight||newReference);
 return {diagram_changed:changed,diagram_before_sha256:beforeDigest,diagram_after_sha256:afterDigest,content_attempt:contentAttempt,
  action_context_move_id:actionContext?'message:'+actionContext.index:null,
  ...(dialogueAttempt?{learner_message_delivered:true,tutor_delivery_ok:result?.ok===true}:{}),
  ...((editTypes.has(action?.type)||action?.type==='submit_revisions')&&!contentAttempt?{noop:true}:{}),
  ...(referenceRevealed?{visible_support_revealed:true,message_index:requestedIndex,visible_text:after.visible_text||'',
   visible_elements:(after.elements||[]).map(element=>Object.fromEntries(['id','kind','locator_description','texts','canvas_bounds','points','arrow_start','arrow_end','highlighted'].filter(key=>Object.hasOwn(element,key)).map(key=>[key,element[key]])))}:{}),
  feedback_message_indices:added.filter(message=>message.role==='assistant'&&!message.error).map(message=>message.index),
  user_message_indices:added.filter(message=>message.role==='user'&&!message.error).map(message=>message.index)};
}

async function inspectExport(exported,dir,seed){
 const entries=Object.values(exported||{}).filter(v=>typeof v==='string');
 const jsonPath=exported.explorationPath||exported.exploration_path||exported.jsonPath||entries.find(v=>v.endsWith('.json'));
 const htmlPath=exported.htmlPath||exported.html_path||entries.find(v=>v.endsWith('.html'));
 if(!jsonPath||!htmlPath)throw Error('Existing UI did not produce both HTML and exploration JSON downloads.');
 const saved=JSON.parse(await fs.readFile(jsonPath,'utf8')),html=await fs.readFile(htmlPath,'utf8');
 const initialHash=hash(canonical(saved.original_model));
 const trace=saved.interaction_log||[];
 const result={html_path:path.relative(dir,htmlPath),exploration_path:path.relative(dir,jsonPath),
  html_bytes:Buffer.byteLength(html),feedback_session:saved.feedback_session,
  source_id:saved.source?.id,original_scene_sha256:initialHash,
  matches_initial_scene:initialHash===seed.scene_sha256,
  initial_explanation:saved.workspace_state?.initial_explanation,
  tutor_messages:trace.filter(v=>v.role==='assistant'&&!v.error).length,
  learner_messages:trace.filter(v=>v.role==='user').length,
  system_or_delivery_errors:trace.filter(v=>v.error).length,
  feedback_turns:saved.feedback_turns?.length||0,
  revision_submissions:(saved.feedback_turns||[]).filter(v=>v.trigger==='workspace-complete').length,
  edit_events:saved.current_draft?.edits?.length||0,
  unsubmitted_draft:canonical(saved.current_draft?.scene)!==canonical(saved.committed_work?.scene),
  original_relation_count:saved.original_model?.relations?.length,
  submitted_relation_count:saved.committed_work?.scene?.relations?.length,
  draft_relation_count:saved.current_draft?.scene?.relations?.length,
  export_contains_dialogue:html.includes('Feedback dialogue')};
 if(!result.matches_initial_scene||result.source_id!==seed.source_id)throw Error('Exported source differs from the selected initial real student response.');
 if(!result.export_contains_dialogue||!result.tutor_messages&&!result.system_or_delivery_errors)throw Error('Export is missing an actual tutor response or recorded system error.');
 return result;
}

async function trial(args,caseConfig,profile,seed,folder){
 const dir=path.join(args.outputDir,folder);await fs.mkdir(dir,{recursive:false});
 await save(path.join(dir,'profile.json'),profile);await save(path.join(dir,'case_config.json'),caseConfig);
 const run={run_id:folder,profile_id:profile.id,started_at:stamp(),status:'initializing',
  source_id:seed.source_id,initial_scene_sha256:seed.scene_sha256,original_image_sha256:seed.image_sha256,
  initial_explanation_sha256:hash(caseConfig.initial_explanation||''),student_model:args.model,effort:args.effort,
  max_student_decisions:args.maxSteps,interaction_medium:'Real browser UI; existing feedback endpoints and existing Export case HTML / Save buttons.',
  steps:[],errors:[],exports:null};
 const runFile=path.join(dir,'run_summary.json');await save(runFile,run);
 let driver,memory=null,knowledgeModel=null,episodic=null,history=[];
 try{
  console.log('['+folder+'] Opening independent browser session.');
  driver=await BrowserDriver.open({baseURL:args.baseURL,caseId:seed.source_id,outputDir:dir,headless:args.headless,autoStart:false});
  const initial=await driver.startSubmission({initialExplanation:caseConfig.initial_explanation||'',task:caseConfig.task??caseConfig.task_text,goals:caseConfig.learning_requirements});
  run.initial_submission={ok:initial.ok!==false,...(initial.error?{error:initial.error}:{})};
  run.status='interacting';await save(runFile,run);
  for(let step=1;step<=args.maxSteps;step++){
   const label='step_'+String(step).padStart(2,'0');
   const before=await driver.observe({label:label+'_before'});
   const request={profile,learner_instance_id:path.basename(args.outputDir)+':'+folder,case_config:caseConfig,observation:before,history,memory,
    learner_knowledge_model:knowledgeModel,learner_agent_memory:episodic,
    initial_knowledge_cache_dir:args.initialKnowledgeCacheDir};
   const requestPath=path.join(dir,label+'_request.json'),responsePath=path.join(dir,label+'_response.json');
   await save(requestPath,request);
   console.log('['+folder+'] Student decision '+step+'; reading actual interface.');
   const {result:modelResult,exitCode}=await modelDecision(args,requestPath,responsePath);
   episodic=learnerEpisodicMemory(modelResult,episodic);
   if(episodic!==null)await save(path.join(dir,'learner_agent_memory.json'),episodic);
   let receipt;
   try{
    receipt=knowledgeReceipt(modelResult,knowledgeModel,{exitCode});
    if(receipt.protocol!=='two-agent-v2')throw Error('This trial requires the two-Agent knowledge check protocol.');
   }
   catch(error){receipt={protocol:'two-agent-v2',check_complete:false,checkpoint:null,executable:false,rejection_reason:error.message,contract_error:true};}
   const knowledgeRecord={format:'knowledge-agent-step-v2',protocol:'two-agent-v2',step,at:stamp(),response_status:modelResult.status??null,helper_exit_code:exitCode,
    request_checkpoint:knowledgeModel,knowledge_audit:modelResult.knowledge_audit??null,
    check_complete:receipt.check_complete,checkpoint_committed:!!receipt.checkpoint,
    knowledge_agent_checks:receipt.knowledge_agent_checks??[],warnings:receipt.warnings??[],
    executable:receipt.executable,executed:false,rejection_reason:receipt.rejection_reason,raw_response:path.basename(responsePath)};
   const knowledgePath=path.join(dir,label+'_knowledge_audit.json');
   if(receipt.checkpoint){knowledgeModel=receipt.checkpoint;await save(path.join(dir,'learner_knowledge_model.json'),knowledgeModel);}
   await save(knowledgePath,knowledgeRecord);
   if(!receipt.executable){
    const event={step,at:stamp(),decision:modelResult.decision??null,execution:{ok:false,executed:false,error:receipt.rejection_reason},
     api:modelResult.api??null,knowledge_audit:modelResult.knowledge_audit??null,knowledge_record:path.basename(knowledgePath),
     before_screenshot:before.screenshot_path||before.screenshotPath,before_observation:before};
    await append(path.join(dir,'action_trace.jsonl'),event);
    run.steps.push({step,type:modelResult.decision?.action?.type??null,ok:false,executed:false,knowledge_checkpoint_committed:!!receipt.checkpoint,
     knowledge_check_complete:receipt.check_complete,knowledge_record:path.basename(knowledgePath),decision_file:path.basename(responsePath),error:receipt.rejection_reason});
    run.failure_phase=receipt.check_complete?'learner_agent':'knowledge_model_agent';await save(runFile,run);
    throw Error(receipt.rejection_reason);
   }
   const decision=modelResult.decision||modelResult.student||modelResult;
   if(!decision.action?.type)throw Error('Student response has no executable action type.');
   const action=decision.action;
   console.log('['+folder+'] '+action.type+(action.text?' · '+action.text.replace(/\s+/g,' ').slice(0,180):''));
   knowledgeRecord.execution_started=true;await save(knowledgePath,knowledgeRecord);
   const result=await driver.execute(action);
   knowledgeRecord.executed=true;knowledgeRecord.execution_ok=result.ok!==false;await save(knowledgePath,knowledgeRecord);
   const after=result.observation||await driver.observe({label:label+'_after'});
   const learningEvidence=learningObservation(before,after,action,result,history);
   const event={step,at:stamp(),decision,execution:result,api:modelResult.api||null,memory_audit:modelResult.memory_audit||null,
    knowledge_audit:modelResult.knowledge_audit,knowledge_record:path.basename(knowledgePath),learning_observation:learningEvidence,
    before_screenshot:before.screenshot_path||before.screenshotPath,after_screenshot:after.screenshot_path||after.screenshotPath,
    before_observation:before,after_observation:after};
   await append(path.join(dir,'action_trace.jsonl'),event);
   run.steps.push({step,type:action.type,ok:result.ok!==false,executed:true,knowledge_checkpoint_committed:!!receipt.checkpoint,knowledge_check_complete:true,
    knowledge_record:path.basename(knowledgePath),memory_audit_issues:modelResult.memory_audit?.issues||[],decision_file:path.basename(responsePath),
    before_screenshot:path.basename(event.before_screenshot||''),after_screenshot:path.basename(event.after_screenshot||'')});
   history.push({step,action,result:{ok:result.ok,result:result.result,...(result.error?{error:result.error}:{})},utterance:decision.utterance||'',memory_update:decision.memory||null,learning_observation:learningEvidence});
   memory=decision.memory??memory;
   await save(runFile,run);
   if(action.type==='stop'){
    run.status='student_stopped';run.stop_reason=action.text||action.reason||decision.stop_reason||'The student agent selected stop.';break;
   }
   if(step===args.maxSteps){run.status='step_budget_reached';run.stop_reason='Configured decision budget reached; not recorded as learner completion.';}
  }
 }catch(error){run.status='failed';run.errors.push({at:stamp(),message:error.message});console.log('['+folder+'] '+run.status+': '+error.message);}
 finally{
  if(driver){
   try{
    const artifacts=await driver.exportArtifacts({label:folder});
    run.exports=await inspectExport(artifacts,dir,seed);
    if(run.exports.initial_explanation!==caseConfig.initial_explanation)throw Error('Initial explanation does not match the common case configuration.');
    await driver.observe({label:'final'});
    console.log('['+folder+'] Existing case HTML and exploration JSON exported.');
   }catch(error){run.errors.push({at:stamp(),phase:'export',message:error.message});run.export_failed=true;}
   try{await driver.close();}catch(error){run.errors.push({phase:'close',message:error.message});}
  }
  run.ended_at=stamp();await save(runFile,run);
 }
 return run;
}

const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function index(args,runs,caseConfig){
 const rows=runs.map(r=>{
  const e=r.exports||{},folder=r.run_id;
  return '<tr><td>'+esc(r.profile_id)+'</td><td>'+esc(r.status)+'</td><td>'+r.steps.length+'</td><td>'+(e.learner_messages??'—')+' / '+(e.tutor_messages??'—')+'</td><td>'+(e.revision_submissions??'—')+'</td><td>'+(e.html_path?'<a href="'+encodeURI(folder+'/'+e.html_path)+'">Exported case HTML</a> · <a href="'+encodeURI(folder+'/'+e.exploration_path)+'">Exploration JSON</a>':'Export unavailable')+'</td></tr>';
 }).join('');
 const html='<!doctype html><html lang="en"><meta charset="utf-8"><title>Simulated learner browser trials</title><style>body{max-width:1100px;margin:40px auto;padding:0 24px;font:16px/1.55 system-ui;color:#292339}h1{font-size:30px}table{border-collapse:collapse;width:100%}td,th{text-align:left;border-bottom:1px solid #d9d2e3;padding:12px 10px}a{color:#6843a1}p{max-width:950px}.note{background:#f6f2fa;padding:16px;border-radius:10px}</style><h1>Simulated learner browser trials</h1><p>'+esc(caseConfig.title||caseConfig.source_title||caseConfig.case_id||'Common real student response')+'</p><p class="note">These are live, autonomous model–system interactions. All selected profiles use the same initial response and constructed conceptual state. The selected profile definitions and levels are preserved in the experiment manifest and each run folder. These illustrative trials do not establish population fidelity or causal effects of profile differences.</p><table><thead><tr><th>Profile</th><th>End reason</th><th>Student decisions</th><th>Learner / tutor messages</th><th>Revision submissions</th><th>Existing system exports</th></tr></thead><tbody>'+rows+'</tbody></table><p>The case HTML is downloaded using the app’s existing Export case HTML button without rewriting its content. Unsubmitted drafts and intermediate actions are preserved in the exploration JSON and each trial’s action_trace.jsonl.</p><p><a href="experiment_manifest.json">Experiment manifest</a></p></html>';
 await fs.writeFile(path.join(args.outputDir,'index.html'),html);
}

export async function main(argv=process.argv.slice(2)){
 const args=options(argv);
 if(args.help){console.log('node run.mjs [--case CASE.json | --case-response REQUEST.json [--prepare-only]] [--preparation-model MODEL] [--profile PROFILE.json ...] [--out DIR] [--base-url URL] [--model MODEL] [--max-steps 24] [--headless] [--concurrency 2] [--initial-knowledge-cache DIR] [--tutor-records-root DIR] [--runtime-config PUBLIC_CONFIG.json] [--history-catalogue HISTORY.jsonl] [--dry-run]');return;}
 const profiles=await Promise.all(args.profilePaths.map(async p=>JSON.parse(await fs.readFile(p,'utf8'))));
 let caseConfig=args.caseResponsePath?null:JSON.parse(await fs.readFile(args.casePath,'utf8'));
 if(caseConfig&&!args.dryRun)validateResponseInferredPrior(caseConfig);
 await fs.mkdir(args.outputDir,{recursive:false});
 const sourceHashes=await learnerSnapshot(args.outputDir);
 let preparation=null;
 if(args.caseResponsePath){
  preparation=await prepareResponse(args);
  if(args.dryRun){
   await save(path.join(args.outputDir,'experiment_manifest.json'),{started_at:stamp(),status:'preparation_required',profiles,dry_run:true,source_code_sha256:sourceHashes,preparation:{directory:'case_preparation',record:preparation.record},runs:[]});
   console.log(JSON.stringify({status:'preparation_required',out:args.outputDir,profiles:profiles.map(p=>p.id),api_calls:0,learner_actions:0}));return;
  }
  caseConfig=JSON.parse(await fs.readFile(path.join(preparation.directory,'generated_case.json'),'utf8'));
  validateResponseInferredPrior(caseConfig);
 }
 const sourceId=caseConfig.source_id||caseConfig.example_id||caseConfig.case_id;
 if(!sourceId||typeof caseConfig.initial_explanation!=='string')throw Error('Case configuration must provide source_id and a common initial_explanation string; it may be empty for a Figure-only response.');
 if(args.prepareOnly){
  await save(path.join(args.outputDir,'experiment_manifest.json'),{started_at:stamp(),status:'prepared_only',case_config:caseConfig,profiles,dry_run:false,source_code_sha256:sourceHashes,preparation:{directory:'case_preparation',record:preparation.record},runs:[]});
  console.log(JSON.stringify({status:'prepared_only',out:args.outputDir,case:sourceId,profiles:profiles.map(p=>p.id),preparation_api_called:preparation.record.api?.called===true,learner_actions:0,tutor_api_calls:0}));return;
 }
 const response=await fetch(args.baseURL+'/api/examples/'+encodeURIComponent(sourceId));
 if(!response.ok)throw Error(args.caseResponsePath?'Prepared source_id is not registered in the app. Use --prepare-only or register that exact response before a browser trial.':'Could not load the configured real student response.');
 const payload=await response.json();
 const preparedBinding=validateCaseSeed(caseConfig,payload,{prepared:Boolean(preparation)});
 const originalBytes=Buffer.from(payload.original.split(',')[1],'base64');
 const seed={source_id:sourceId,scene_sha256:hash(canonical(payload.scene)),image_sha256:hash(originalBytes)};
 await save(path.join(args.outputDir,'seed_payload.json'),payload);
 await fs.writeFile(path.join(args.outputDir,'original_student_response.png'),originalBytes);
 const manifest={started_at:stamp(),case_config:caseConfig,profiles,seed,
  student_model:args.model,effort:args.effort,max_student_decisions:args.maxSteps,
  source_code_sha256:sourceHashes,learner_knowledge_protocol:KNOWLEDGE_PROTOCOL,
  initial_knowledge_cache:{directory:args.initialKnowledgeCacheDir,scope:'Original Task/Response, initialization prompt/schema, model and image settings; no profile or Teacher history',updates_shared:false},
  headless:args.headless,concurrency:args.concurrency,dry_run:args.dryRun,runs:[]};
 if(preparation)manifest.preparation={directory:'case_preparation',record:preparation.record,verified_app_binding:preparedBinding};
 if(preparedBinding)manifest.prepared_case_binding=preparedBinding;
 manifest.tutor_source_sha256={};
 const experiment=path.resolve(HERE,'../..');
 for(const name of ['FEEDBACK_LOGIC.md','app/server.py','app/index.html','app/app.js','app/feedback.py','app/agent_api.py','app/agent_types.py','app/evaluation_agent.py','app/transformation_agent.py','app/tutor_agent.py','app/learner_model.py','app/tutor_context.py','app/interaction_contract.py','app/move_selection.py','app/feedback_process.py','app/revision_target.py','app/highlight_plan.py','app/case_resume.py','reconstruction.py','compact.py','schema.py','prompts/reconstruct_v1.1.md','prompts/feedback_tutor.md','prompts/feedback_move_examples.md','prompts/feedback_evaluator.md','prompts/reconstruct_v1.2_compact.md']){
  const data=await fs.readFile(path.join(experiment,name));manifest.tutor_source_sha256[name]=hash(data);
  const dest=path.join(args.outputDir,'tutor_code_snapshot',name);await fs.mkdir(path.dirname(dest),{recursive:true});await fs.writeFile(dest,data);
 }
 const runtimeSettings=args.runtimeConfigPath?JSON.parse(await fs.readFile(args.runtimeConfigPath,'utf8')):{};
 const promptVersion=await createPromptVersionBundle({outputDir:args.outputDir,manifest,caseConfig,profiles,runtimeSettings});
 manifest.prompt_version=promptVersion;
 await save(path.join(args.outputDir,'experiment_manifest.json'),manifest);
 if(args.dryRun){console.log(JSON.stringify({status:'dry_run',out:args.outputDir,case:sourceId,profiles:profiles.map(p=>p.id),api_calls:0}));return;}
 const tutorRecordsRoot=args.tutorRecordsRoot||path.join(experiment,'app/runs');
 const tutorBaseline=new Set(await tutorRecordNames(tutorRecordsRoot));
 let cursor=0;
 const results=Array(profiles.length);
 await Promise.all(Array.from({length:Math.min(args.concurrency,profiles.length)},async()=>{
  while(cursor<profiles.length){const i=cursor++;const profile=profiles[i];
   const folder=String(profile.id||'profile_'+(i+1)).replace(/[^a-zA-Z0-9_-]/g,'_');
   results[i]=await trial(args,caseConfig,profile,seed,folder);}
 }));
 manifest.runs=results;manifest.ended_at=stamp();
 manifest.initial_knowledge_cache={...manifest.initial_knowledge_cache,
  ...await collectInitialKnowledge(args.outputDir,results)};
 manifest.tutor_record_collection=await collectTutorRecords(tutorRecordsRoot,args.outputDir,results,tutorBaseline);
 manifest.versioned_exports=await finalizeVersionedExports({outputDir:args.outputDir,manifest,runs:results,caseConfig,promptVersion,cataloguePath:args.historyCatalogue});
 await save(path.join(args.outputDir,'experiment_manifest.json'),manifest);
 console.log(JSON.stringify({out:args.outputDir,runs:results.map(r=>({profile:r.profile_id,status:r.status,steps:r.steps.length,exports:!!r.exports,errors:r.errors})),index:path.join(args.outputDir,'index.html')},null,2));
 if(results.some(r=>!r.exports||r.status==='failed'||r.export_failed))process.exitCode=1;
}
const entryPath=process.argv[1]?await fs.realpath(process.argv[1]).catch(()=>path.resolve(process.argv[1])):null;
if(entryPath===fileURLToPath(import.meta.url))main().catch(error=>{console.error(error.message);process.exitCode=1;});
