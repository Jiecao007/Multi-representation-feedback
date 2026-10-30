const assert=require('node:assert/strict');
const W=require('../app/workflow.js');
const committed={scene:{objects:[{label:'Energy'}]},explanation:'Initial reasoning',edits:[]};
const draft=structuredClone(committed);draft.scene.objects[0].label='New label';draft.explanation='New reasoning';
assert.deepEqual(W.snapshotForFeedback('message',draft,committed),committed);
assert.deepEqual(W.snapshotForFeedback('workspace-complete',draft,committed),draft);
const rev=W.snapshotForFeedback('revision',draft,committed);assert.equal(rev.explanation,'New reasoning');assert.equal(rev.scene.objects[0].label,'Energy');
assert.throws(()=>W.snapshotForFeedback('drag',draft,committed));
const clone=W.snapshotForFeedback('submission',draft,null);clone.scene.objects[0].label='Mutated';assert.equal(draft.scene.objects[0].label,'New label');
assert.ok(W.changed(draft,committed));assert.equal(W.changed(committed,committed),false);
const historyOnly=structuredClone(committed);historyOnly.edits.push({kind:'move',id:'example'});
assert.equal(W.changed(historyOnly,committed),false,'Edit history alone does not mean the visible work is unsubmitted.');
const explanationOnly=structuredClone(committed);explanationOnly.explanation='A new explanation';assert.equal(W.changed(explanationOnly,committed),true);
for(const message of ['Please review my updated diagram.','Can you check my model?','I have finished my changes. Please review my diagram.','I am done editing.','My drawing is ready for review.','我改好了','请帮我检查一下我修改后的图']){
 assert.equal(W.reviewRequested(message),true,message);assert.equal(W.submissionRequired(message,'dialogue',draft,committed),true,message);
 assert.equal(W.submissionRequired(message,'hint',draft,committed),false);assert.equal(W.submissionRequired(message,'dialogue',committed,committed),false);
}
for(const message of ['Why does the arrow start there?','I need a hint.','I am done.','I have finished my changes, but why does this work?','I am done editing. Help me understand this idea.','I have not finished my changes.','After I finish my changes, please review my model.','You asked me to check my model.','My reason is that both parts connect.','I want to begin a revision.','我还没改好','我改好了，为什么这样做？','为什么要检查我的图？']){
 assert.equal(W.reviewRequested(message),false,message);assert.equal(W.submissionRequired(message,'dialogue',draft,committed),false,message);
}
const editable={editEnabled:true,scene:{objects:[]}};assert.equal(W.canEdit(editable),true);
assert.equal(W.canEdit({...editable,editEnabled:false}),false);
for(const key of ['uploadBusy','chatBusy','referenceDraft','originalMode'])assert.equal(W.canEdit({...editable,[key]:true}),false);
assert.equal(W.canEdit({...editable,scene:null}),false);
console.log('Feedback workflow: immutable submitted snapshots and authoritative revision editing gates passed.');
