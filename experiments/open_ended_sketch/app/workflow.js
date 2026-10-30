/* Adapted from Mechanics Studio lib/review-boundary.ts. */
(function(root){
const clone=x=>JSON.parse(JSON.stringify(x));
function snapshotForFeedback(trigger,draft,committed){
 if(['submission','workspace-complete'].includes(trigger))return clone(draft);
 if(!committed)throw Error('Submit your work for feedback first.');
 const result=clone(committed);
 if(trigger==='revision')result.explanation=draft.explanation;
 else if(trigger!=='message')throw Error('Unsupported feedback trigger.');
 return result;
}
function changed(draft,committed){return !!draft&&!!committed&&['scene','explanation'].some(key=>JSON.stringify(draft[key])!==JSON.stringify(committed[key]));}
function reviewRequested(message){
 const text=String(message||'').trim().replace(/^(?:(?:okay|ok|yes|sure|thanks|done)[,!]?\s+)+/i,'');
 if(/^(?:please\s+)?(?:review|check|assess|look at)\s+(?:(?:my|the|this)\s+)?(?:(?:updated|revised|changed|new|completed)\s+)?(?:diagram|drawing|model|changes|revision|work)\b/i.test(text))return true;
 if(/^(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:review|check|assess|look at)\s+(?:(?:my|the|this)\s+)?(?:(?:updated|revised|changed|new|completed)\s+)?(?:diagram|drawing|model|changes|revision|work)\b/i.test(text))return true;
 if(/\b(?:why|how|explain|reasoning|help me understand|need a hint)\b|为什么|怎么|解释|提示/.test(text.toLowerCase()))return false;
 if(/^i\s+(?:have\s+)?(?:finished|completed)\s+(?:(?:making|editing|changing|revising)\s+)?(?:(?:my|the)\s+)?(?:changes|revision|diagram|drawing|model)\b/i.test(text))return true;
 if(/^i(?:'m| am)\s+done\s+(?:editing|revising|making changes)\b/i.test(text))return true;
 if(/^(?:my|the)\s+(?:diagram|drawing|model|revision|changes)\s+(?:is|are)\s+(?:ready for review|finished|complete)\b/i.test(text))return true;
 return /^(?:请|麻烦)?(?:帮我|你)?(?:检查|看看|评估)(?:一下)?(?:我(?:修改|改|画)后的|我(?:的)?|这(?:个|些))?(?:图|模型|修改|改动)|^(?:我)?(?:已经|已)?(?:改好|修改完|修改好|画好|画完)(?:了|啦)?/.test(text);
}
function submissionRequired(message,intent,draft,committed){return intent==='dialogue'&&changed(draft,committed)&&reviewRequested(message);}
function canEdit(state){return !!state.editEnabled&&!!state.scene&&!state.uploadBusy&&!state.chatBusy&&!state.referenceDraft&&!state.originalMode;}
const api={snapshotForFeedback,changed,reviewRequested,submissionRequired,canEdit};root.FeedbackWorkflow=api;if(typeof module!=='undefined')module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
