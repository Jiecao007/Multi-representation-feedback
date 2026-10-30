/** A shared app must not attach another session's prompts to this experiment. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {collectTutorRecords,tutorRecordNames} from './run.mjs';

const temp=await fs.mkdtemp(path.join(os.tmpdir(),'tutor-record-capture-'));
try{
 const source=path.join(temp,'source'),output=path.join(temp,'output');
 await fs.mkdir(source);await fs.mkdir(output);
 const make=async(name,session,publicOnly=false)=>{
  const dir=path.join(source,name);await fs.mkdir(dir);
  await fs.writeFile(path.join(dir,'tutor.prompt.md'),'Exact saved instructions: '+name+'\n');
  if(session)await fs.writeFile(path.join(dir,publicOnly?'public_reply.json':'session.json'),
   JSON.stringify(publicOnly?{session_id:session}:{id:session}));
 };
 await make('feedback_turn_before','selected');
 const baseline=new Set(await tutorRecordNames(source));
 await make('feedback_turn_selected','selected');
 await make('feedback_turn_public','selected',true);
 await make('feedback_turn_unrelated','another-user-session');
 await make('feedback_turn_failed',null);
 const record=await collectTutorRecords(source,output,[{exports:{feedback_session:'selected'}}],baseline);
 assert.deepEqual([...record.copied_directories].sort(),['feedback_turn_failed','feedback_turn_public','feedback_turn_selected']);
 assert.deepEqual(record.unassociated_directories,['feedback_turn_failed']);
 assert.equal(await fs.stat(path.join(output,'tutor_api_runs/feedback_turn_unrelated')).then(()=>true,()=>false),false);
 for(const name of record.copied_directories)assert.deepEqual(
  await fs.readFile(path.join(source,name,'tutor.prompt.md')),
  await fs.readFile(path.join(output,'tutor_api_runs',name,'tutor.prompt.md')));
 assert.deepEqual(await tutorRecordNames(path.join(temp,'not-present')),[]);
 console.log('PASS tutor record capture: baseline/unrelated sessions excluded; exact selected prompts and unassociated failures preserved. Zero app/model calls.');
}finally{await fs.rm(temp,{recursive:true,force:true});}
