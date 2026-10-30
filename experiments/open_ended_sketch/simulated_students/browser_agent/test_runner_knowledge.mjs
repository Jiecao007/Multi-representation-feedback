/** Offline runner state-boundary tests; no browser, app, or external API. */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import {knowledgeReceipt,learningObservation,learnerEpisodicMemory,validateResponseInferredPrior,
 options,collectInitialKnowledge} from './run.mjs';

test('batch runs use a persistent output-parent initial cache with an explicit override',()=>{
 const out=path.join(os.tmpdir(),'cache-example','run-one');
 assert.equal(options(['--out',out]).initialKnowledgeCacheDir,path.join(path.dirname(out),'simulated_learner_initial_knowledge_cache'));
 assert.equal(options(['--out',out,'--initial-knowledge-cache','relative-cache']).initialKnowledgeCacheDir,path.resolve('relative-cache'));
});

const knowledgeDigest=state=>crypto.createHash('sha256').update(JSON.stringify(Object.fromEntries(Object.entries(state).sort(([a],[b])=>a.localeCompare(b))))).digest('hex');
test('one run archives a common K0 and identifies reused initialization without counting it as a new call',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'shared-k0-run-'));
 try{
  const state={known:['Can locate −6.'],unknown:[],possibly_known:[]},runs=[];
  for(let i=1;i<=7;i++){
   const run={run_id:'P'+i,profile_id:'P'+i,status:'student_stopped'};runs.push(run);
   await fs.mkdir(path.join(root,run.run_id));
   await fs.writeFile(path.join(root,run.run_id,'step_01_initial_knowledge_cache.json'),JSON.stringify({
    cache_hit:i!==1,cached_initialization:{key:'a'.repeat(64),knowledge_state:state,
     knowledge_sha256:knowledgeDigest(state),origin:{response_id:'original-call'}}}));
  }
  const result=await collectInitialKnowledge(root,runs);
  assert.equal(result.shared,true);assert.equal(result.new_initialization_calls,1);assert.equal(result.cache_hits,6);
  const snapshot=JSON.parse(await fs.readFile(path.join(root,'shared_initial_knowledge.json'),'utf8'));
  assert.deepEqual(snapshot.knowledge_state,state);assert.equal(snapshot.updates_shared,false);assert.equal(snapshot.profiles.length,7);
 }finally{await fs.rm(root,{recursive:true,force:true});}
});

test('different initial states in one batch cannot be reported as shared',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'different-k0-run-'));
 try{
  const runs=[];
  for(let i=1;i<=2;i++){
   const run={run_id:'P'+i,profile_id:'P'+i,status:'student_stopped'};runs.push(run);
   const state={known:['Different '+i],unknown:[],possibly_known:[]};
   await fs.mkdir(path.join(root,run.run_id));
   await fs.writeFile(path.join(root,run.run_id,'step_01_initial_knowledge_cache.json'),JSON.stringify({
    cache_hit:i!==1,cached_initialization:{key:'a'.repeat(64),knowledge_state:state,
     knowledge_sha256:knowledgeDigest(state),origin:{}}}));
  }
  await assert.rejects(collectInitialKnowledge(root,runs),/did not share one initial knowledge state/);
 }finally{await fs.rm(root,{recursive:true,force:true});}
});

test('new runs require a response-inferred prior instead of silently using historical imposed assumptions',()=>{
 assert.equal(validateResponseInferredPrior({provenance:{prior_policy:'response_inferred'}}),'response_inferred');
 for(const value of [{},{provenance:{omission_policy:'support_needed'}},{provenance:{prior_policy:'evidence_only'}}]){
  assert.throws(()=>validateResponseInferredPrior(value),/Prepare the original Task and student Response/);
 }
});

const state=(revision=0)=>({format:'learner-knowledge-v1',revision,state_sha256:'a'.repeat(64),owner_id:'P1:run-1',
 case_binding:'case-bound',components:[{component_id:'C1',status:'unlearned'}],event_ledger:[],processed_event_ids:[]});
const result=({before=state(),after=state(1),approved=true,validated=true,status='ok'}={})=>({status,
 learner_knowledge_model:after,knowledge_audit:{before,after,events:[],update_validated:validated,gate:{approved}},
 decision:{action:{type:'send_message',text:'I am not sure.'},memory:{component_states:[{component_id:'C1',status:'known'}]}}});

const agentState=(revision=0)=>({...state(revision),format:'knowledge-model-agent-v2',processed_move_ids:['message:0'],move_checks:[]});
const agentResult=({before=agentState(),after=agentState(1),complete=true,status='ok'}={})=>({status,
 learner_knowledge_model:after,knowledge_audit:{protocol:'two-agent-v2',before,after,check_complete:complete,
  checks:[{mode:'move',move_id:'message:0'}],warnings:[],learner_read_state_sha256:after.state_sha256},
 decision:{action:{type:'send_message',text:'I need a local hint.'},memory:{component_states:[{component_id:'C1',status:'known'}]}}});

test('current simple knowledge receipt preserves three optional lists without component or permission machinery',()=>{
 const make=revision=>({format:'knowledge-model-agent-v4',revision,state_sha256:String(revision).repeat(64),
  owner_id:'P1:simple',knowledge_state:{known:['Can locate A.'],unknown:[],possibly_known:[]},processed_move_ids:['message:0'],move_checks:[]});
 const before=make(0),after=make(1),response=agentResult({before,after});
 const receipt=knowledgeReceipt(response,before);
 assert.equal(receipt.executable,true);
 assert.deepEqual(receipt.checkpoint.knowledge_state,after.knowledge_state);
 for(const key of ['components','current_turn','response_permissions'])assert.equal(Object.hasOwn(receipt.checkpoint,key),false);
});

test('Learner Agent episodic memory is copied and carried independently from knowledge checkpoints',()=>{
 const output={learner_agent_memory:{last_action:'Requested a hint.',pending_question:'Which part should I revise?'}},
  memory=learnerEpisodicMemory(output);
 assert.deepEqual(memory,output.learner_agent_memory);
 output.learner_agent_memory.last_action='Changed later';assert.equal(memory.last_action,'Requested a hint.');
 const next=learnerEpisodicMemory({},memory);assert.deepEqual(next,memory);assert.notEqual(next,memory);
 assert.equal(learnerEpisodicMemory({}),null);
 assert.equal(Object.hasOwn(memory,'components'),false);
});

test('Learner Agent episodic channel cannot smuggle knowledge-state fields',()=>{
 for(const memory of [{last_action:'A',pending_question:'B',components:[{status:'known'}]},
  {last_action:'A',pending_question:'B',component_states:[]},{last_action:'A'},[],{last_action:3,pending_question:'B'}]){
  assert.throws(()=>learnerEpisodicMemory({learner_agent_memory:memory}),/only last_action and pending_question/);
 }
});

test('public attempt receipts retain the actual preceding Feedback move, excluding errors and future replies',()=>{
 const before={elements:[],messages:[{index:0,role:'assistant',text:'First move.'},
  {index:1,role:'user',text:'A reply.'},{index:2,role:'assistant',text:'Second move.'},
  {index:3,role:'assistant',text:'Delivery error',error:true}]},
  after={...before,messages:[...before.messages,{index:4,role:'user',text:'My attempt.'},{index:5,role:'assistant',text:'New feedback.'}]};
 const proof=learningObservation(before,after,{type:'send_message',text:'My attempt.'},{ok:true});
 assert.equal(proof.action_context_move_id,'message:2');
 assert.deepEqual(proof.feedback_message_indices,[5]);
 assert.equal(learningObservation({elements:[],messages:[]},after,{type:'send_message',text:'My attempt.'},{ok:true}).action_context_move_id,null);
});

test('two-Agent receipt stores the Knowledge Model Agent state before a Learner Agent action without a gate',()=>{
 const response=agentResult(),receipt=knowledgeReceipt(response,agentState());
 assert.equal(receipt.protocol,'two-agent-v2');assert.equal(receipt.check_complete,true);assert.equal(receipt.executable,true);
 assert.equal(receipt.checkpoint.components[0].status,'unlearned','Learner-authored compatibility memory is not knowledge authority.');
 assert.equal(Object.hasOwn(receipt,'gate_approved'),false);assert.equal(Object.hasOwn(receipt,'update_validated'),false);
 assert.deepEqual(receipt.knowledge_agent_checks,[{mode:'move',move_id:'message:0'}]);
 response.learner_knowledge_model.components[0].status='known';
 assert.equal(receipt.checkpoint.components[0].status,'unlearned','Stored state is copied from the Agent receipt.');
});

test('two-Agent check can persist even if the subsequent learner call fails, while an unfinished check cannot execute',()=>{
 const failed=agentResult({status:'api_error'});delete failed.knowledge_audit.learner_read_state_sha256;
 const receipt=knowledgeReceipt(failed,agentState(),{exitCode:1});
 assert.equal(receipt.executable,false);assert.equal(receipt.checkpoint.revision,1);
 const unfinished=knowledgeReceipt(agentResult({complete:false}),agentState());
 assert.equal(unfinished.executable,false);assert.equal(unfinished.checkpoint,null);
});

test('two-Agent protocol rejects stale reads, mismatched state and fake independent gate approval',()=>{
 const stale=agentResult();stale.knowledge_audit.learner_read_state_sha256='b'.repeat(64);
 assert.throws(()=>knowledgeReceipt(stale,agentState()),/did not read/);
 const gate=agentResult();gate.knowledge_audit.gate={approved:true};
 assert.throws(()=>knowledgeReceipt(gate,agentState()),/must not claim an independent gate/);
 const mismatch=agentResult();mismatch.knowledge_audit.after=agentState(7);
 assert.throws(()=>knowledgeReceipt(mismatch,agentState()),/does not match/);
 assert.throws(()=>knowledgeReceipt(agentResult(),agentState(8)),/preceding Agent checkpoint/);
 const noAction=agentResult();delete noAction.decision;
 assert.throws(()=>knowledgeReceipt(noAction,agentState()),/no Learner Agent action/);
});

test('runner executes only approved, validated controller decisions and ignores actor memory claims',()=>{
 const received=result(),receipt=knowledgeReceipt(received,state());
 assert.equal(receipt.executable,true);
 assert.equal(receipt.checkpoint.components[0].status,'unlearned');
 received.learner_knowledge_model.components[0].status='known';
 assert.equal(receipt.checkpoint.components[0].status,'unlearned','Checkpoint is copied from the validated controller receipt.');
 assert.throws(()=>knowledgeReceipt({status:'ok',decision:{action:{type:'send_message'},memory:{}}}),/controller receipt/);
});

test('gate or helper failure blocks action while retaining a validated update from past evidence',()=>{
 const rejected=knowledgeReceipt(result({approved:false,status:'blocked'}),state(),{exitCode:1});
 assert.equal(rejected.executable,false);
 assert.equal(rejected.gate_approved,false);
 assert.equal(rejected.checkpoint.revision,1,'Already received support is not rolled back because a candidate failed.');
 const helperFailure=knowledgeReceipt(result(),state(),{exitCode:1});
 assert.equal(helperFailure.executable,false);
 assert.equal(helperFailure.checkpoint.revision,1);
 const unsupported=knowledgeReceipt(result({validated:false,approved:false}),state());
 assert.equal(unsupported.executable,false);
 assert.equal(unsupported.checkpoint,null);
});

test('runner refuses mismatched controller receipts and stale predecessor states',()=>{
 const missing=result();delete missing.learner_knowledge_model;
 assert.throws(()=>knowledgeReceipt(missing,state()),/controller state/);
 const mismatched=result();mismatched.knowledge_audit.after=state(9);
 assert.throws(()=>knowledgeReceipt(mismatched,state()),/does not match/);
 assert.throws(()=>knowledgeReceipt(result(),state(8)),/preceding checkpoint/);
 const badFormat=result();badFormat.learner_knowledge_model={...state(),format:'actor-memory'};
 assert.throws(()=>knowledgeReceipt(badFormat,state()),/supported controller state/);
});

const element=(texts=['A'])=>({id:'object-a',kind:'object',texts,canvas_bounds:{x:1,y:2,width:20,height:10},selected:false});
test('completed attempt evidence requires actual public content changes and a successful action',()=>{
 const before={elements:[element()],messages:[]},after={elements:[element(['B'])],messages:[]};
 const edited=learningObservation(before,after,{type:'edit_text'},{ok:true});
 assert.equal(edited.diagram_changed,true);assert.equal(edited.content_attempt,true);
 assert.notEqual(edited.diagram_before_sha256,edited.diagram_after_sha256);
 assert.deepEqual(edited.feedback_message_indices,[]);assert.deepEqual(edited.user_message_indices,[]);
 assert.equal(learningObservation(before,after,{type:'edit_text'},{ok:false}).content_attempt,false);
 assert.equal(learningObservation(before,before,{type:'edit_text'},{ok:true}).content_attempt,false);
 assert.equal(learningObservation(before,before,{type:'edit_text'},{ok:true}).noop,true);
 assert.equal(learningObservation(before,after,{type:'add_object'},{ok:true,result:{library_open:true}}).noop,true,
  'Inspecting the object library does not count as a completed diagram attempt.');
 const selected={elements:[{...element(),selected:true,highlighted:true,bounds:{x:50}}],messages:[]};
 assert.equal(learningObservation(before,selected,{type:'select'},{ok:true}).diagram_changed,false);
 assert.equal(learningObservation(before,{...after,elements:[]},{type:'show_feedback'},{ok:true}).content_attempt,false);
});

test('submission evidence reflects changed committed content; delivered message indices preserve errors separately',()=>{
 const initial={elements:[element()],messages:[{index:0,role:'assistant',text:'Which part?'}]},before={...initial,elements:[element(['B'])]};
 const after={elements:[element(['B'])],messages:[...before.messages,{index:1,role:'user',text:'This one.'},
  {index:2,role:'assistant',text:'Here is a concrete hint.'},{index:3,role:'assistant',text:'Delivery error',error:true}]};
 const editProof=learningObservation(initial,before,{type:'edit_text'},{ok:true});
 const history=[{step:1,action:{type:'edit_text'},result:{ok:true},learning_observation:editProof}];
 const received=learningObservation(before,after,{type:'submit_revisions'},{ok:true},history);
 assert.equal(received.content_attempt,true);
 assert.deepEqual(received.feedback_message_indices,[2]);
 assert.deepEqual(received.user_message_indices,[1]);
 assert.equal(learningObservation(before,after,{type:'submit_revisions'},{ok:true},[...history,
  {step:2,action:{type:'submit_revisions'},result:{ok:true},learning_observation:received}]).content_attempt,false);
 assert.equal(learningObservation(before,after,{type:'request_hint'},{ok:true}).content_attempt,false);
 const undoProof=learningObservation(before,initial,{type:'undo'},{ok:true},history);
 assert.equal(undoProof.content_attempt,true,'The real undo remains its own completed action.');
 assert.equal(learningObservation(initial,initial,{type:'submit_revisions'},{ok:true},[...history,
  {step:2,action:{type:'undo'},result:{ok:true},learning_observation:undoProof}]).content_attempt,false,
 'Editing then restoring the committed content does not make an unchanged submission a fresh attempt.');
});

test('delivered dialogue is eligible attempt evidence, without treating it as knowledge acquisition',()=>{
 const before={elements:[],messages:[{index:0,role:'assistant',text:'What do you think?'}]},
  after={...before,messages:[...before.messages,{index:1,role:'user',text:'Maybe this part.'}]};
 const proof=learningObservation(before,after,{type:'send_message',text:'Maybe this part.'},{ok:true});
 assert.equal(proof.content_attempt,true);
 assert.deepEqual(proof.user_message_indices,[1]);
 assert.equal(Object.hasOwn(proof,'knowledge'),false);
 assert.equal(learningObservation(before,before,{type:'send_message',text:'Maybe this part.'},{ok:true}).content_attempt,false);
 assert.equal(learningObservation(before,after,{type:'send_message',text:''},{ok:true}).content_attempt,false);
 const failedTutor=learningObservation(before,after,{type:'send_message',text:'Maybe this part.'},{ok:false});
 assert.equal(failedTutor.content_attempt,true,'A visibly rendered student response remains an actual attempt when Tutor delivery fails.');
 assert.equal(failedTutor.learner_message_delivered,true);assert.equal(failedTutor.tutor_delivery_ok,false);
 const failedWithoutReply=learningObservation(before,before,{type:'send_message',text:'Maybe this part.'},{ok:false});
 assert.equal(failedWithoutReply.content_attempt,false,'An unsent response is not attempt evidence.');
});

test('Show receipts require a successful operation and a newly revealed public reference',()=>{
 const before={elements:[element()],messages:[{index:0,role:'assistant',text:'Look at this part.',show_available:true}],visible_text:'Look at this part.'},
  after={...before,elements:[{...element(),locator_description:'Written letter A',highlighted:true}],visible_text:'Look at this part. To clarify: A'};
 const proof=learningObservation(before,after,{type:'show_feedback'},{ok:true});
 assert.equal(proof.visible_support_revealed,true);
 assert.equal(proof.message_index,0);
 assert.equal(proof.visible_text,after.visible_text);
 assert.equal(proof.visible_elements[0].highlighted,true);
 assert.equal(proof.visible_elements[0].locator_description,'Written letter A');
 assert.deepEqual(proof.visible_elements[0].texts,['A']);
 assert.equal(proof.content_attempt,false,'Viewing support is separate from making a conceptual attempt.');
 assert.equal(learningObservation(after,after,{type:'show_feedback'},{ok:true}).visible_support_revealed,undefined,'Replaying an unchanged reference is not new support.');
 assert.equal(learningObservation(before,after,{type:'show_feedback'},{ok:false}).visible_support_revealed,undefined);
 assert.equal(learningObservation({...before,messages:[]},after,{type:'show_feedback'},{ok:true}).visible_support_revealed,undefined);
});
