import {referenceList,groundArrowReference,arrowReferenceProblem,elementReference} from '@/lib/diagram-references';
import { EVALUATOR_PROMPT,TUTOR_PROMPT,feedbackTrigger,selectTalkMove,movePhase,shortTurnProblem,TALK_MOVES } from '@/lib/talk-moves';
import { normalizeSubmission,normalizeGuide,normalizeReview,latestReview,CRITERIA } from '@/lib/feedback-workflow';
import { validFocus,normalizeWorkspace } from '@/lib/workspace';
import { completion,readInput,errorResponse,ApiError } from '@/lib/ai';
import { TASK,normalizeAnalysis } from '@/lib/domain';
import { EMPTY_SETUP,normalizeSetup,normalizeSize,validateParameters,simulateDrawing } from '@/lib/embedded-physics';
export async function POST(req:Request){try{
 const b=await readInput(req,250000);
 let trigger;try{trigger=feedbackTrigger(b.trigger);}catch(e){throw new ApiError((e as Error).message,409);}
 if(typeof b.original!=='string'||b.original.length>6000||typeof b.revision!=='string'||b.revision.length>6000)throw new ApiError('The response is too long.',400);
 if(!Array.isArray(b.messages)||b.messages.length>60)throw new ApiError('The conversation payload is too long.',400);
 const messages=b.messages.slice(-24).map((m:Record<string,unknown>)=>({role:m.role==='assistant'?'assistant':'user',content:String(m.content||'').slice(0,1800),origin:m.origin==='workspace'?'workspace':m.origin==='submission'?'submission':'conversation',move:String(m.move||'').slice(0,60)}));
 const previousAssistant=b.messages.filter((m:Record<string,unknown>)=>m.role==='assistant').at(-1);
 const previousReview=latestReview(b.messages);
 const priorGuide=previousAssistant?.guide;
 const previousFocus=priorGuide&&Object.hasOwn(CRITERIA,String(priorGuide.criterion))?{criterion:priorGuide.criterion,focusId:String(previousAssistant.focusId||'').slice(0,40)}:null;
 const submission=normalizeSubmission(b.submission,b.original);
 const analysis=normalizeAnalysis(b.analysis),parameters=validateParameters(b.drawing?.parameters||b.lab);
 const setup=normalizeSetup(b.drawing?.setup||EMPTY_SETUP,analysis.elements);
 const dimensions=normalizeSize(b.drawing?.dimensions||{width:1000,height:650});
 const workspace=normalizeWorkspace(b.workspace,analysis.elements.map(e=>e.id),[]);
 const runs=Array.isArray(b.drawing?.runs)?b.drawing.runs.slice(-5).map((r:Record<string,unknown>)=>{
  const elements=normalizeAnalysis({elements:r.elements}).elements;
  const settings=normalizeSetup(r.setup,elements),p=validateParameters(r.parameters),size=normalizeSize(r.dimensions);
  return {setup:settings,parameters:p,dimensions:size,elements,prediction:String(r.prediction||'').slice(0,1000),time:String(r.time||'').slice(0,50),result:simulateDrawing(settings,p,elements,size)};
 }):[];
 let calculatedMotion=null;try{calculatedMotion=simulateDrawing(setup,parameters,analysis.elements,dimensions);}catch{/* Incomplete authoring is a valid discussion context. */}
 const last=runs.at(-1);const latestExperimentMatchesCurrent=!!last&&JSON.stringify(last.setup)===JSON.stringify(setup)&&JSON.stringify(last.parameters)===JSON.stringify(parameters)&&JSON.stringify(last.elements)===JSON.stringify(analysis.elements);
 const context={task:TASK,previousFocus,previousReview,references:referenceList(analysis.elements),trigger,workspace,submission,original:b.original,revision:b.revision,analysis,selectedId:String(b.selectedId||''),drawing:trigger==='submission'?{available:submission.imageRole!=='none',runs:[]}:{available:submission.imageRole!=='none',setup,parameters,dimensions,calculatedMotion,runs,latestExperimentMatchesCurrent},messages};
 // Keep evaluator output entirely server-side; return only the validated student turn.
 const assessment=await completion(EVALUATOR_PROMPT,JSON.stringify(context),2200);
 const move=selectTalkMove(assessment.talkMove,trigger,assessment.readyForRevision===true);
 const writerContext={context,privateAssessment:assessment,selectedTalkMove:move};
 let result=await completion(TUTOR_PROMPT,JSON.stringify(writerContext),1600);
 result=groundArrowReference(result,analysis.elements);
 const reviewProblem=(r:Record<string,unknown>)=>normalizeReview(r.review).length!==3?'Include all three current criterion reviews for the separate Overall feedback panel, including on ordinary dialogue turns. Keep them out of content.':'';
 let problem=reviewProblem(result)||shortTurnProblem(result.content,trigger,String(previousAssistant?.content||''))||arrowReferenceProblem(result,analysis.elements);
 if(problem){result=await completion(TUTOR_PROMPT,JSON.stringify({...writerContext,rewriteRequirement:problem,previousDraft:result.content}),1600);result=groundArrowReference(result,analysis.elements);problem=reviewProblem(result)||shortTurnProblem(result.content,trigger,String(previousAssistant?.content||''))||arrowReferenceProblem(result,analysis.elements);}
 if(problem)throw new ApiError('The tutor could not produce a concise question. Please retry.',502);
 result.criterion=assessment.criterion;
 const guide=normalizeGuide(result,b.original,b.revision,submission.imageRole!=='none');
 const action=guide.nextStep.kind==='experiment'?'experiment':guide.nextStep.kind==='revise'?'revise':['identify','annotate'].includes(guide.nextStep.kind)?'inspect':'none';
 return Response.json({review:normalizeReview(result.review),content:result.content.slice(0,2200),phase:movePhase(move),move:TALK_MOVES[move],talkMove:move,...validFocus(result,analysis.elements.map(e=>e.id),[]),focusLabel:analysis.elements.some(e=>e.id===result.focusId)?elementReference(analysis.elements.find(e=>e.id===result.focusId)!):'',workspaceRevision:workspace.revision,action,guide,engine:'live'},{headers:{'Cache-Control':'no-store'}});
}catch(e){return errorResponse(e);}}
