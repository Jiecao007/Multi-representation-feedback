'use strict';
const $=id=>document.getElementById(id),G=DrawingGeometry,E=DrawingEditor,NS='http://www.w3.org/2000/svg';
const canvas=$('canvas');let catalog=null,editHistory=[],focusIds=[],focusBounds=null,focusTone='next',lastTap=null,tapId='';
let feedbackSession='',committed=null,feedbackTurns=[],editEvents=[],reviewRows=[],noteMode=false,connectionId='';
let interactionLog=[],initialExplanation=null,caseExportRequest=null;
let payload=null,scene=null,initial=null,anchors={},selected='',drag=null,view='',originalMode=false,playing=false,raf=0,highlight=new Set(),conversation=[],revision=0,chatBusy=false,uploadBusy=false;
let referenceDraft=null,currentDrawingVersion=1,activeMechanism=null,traceIds=null,screen='submission',exampleRevision=0;
let editEnabled=false,awaitingRevisionReason=false,revisionAuth=null;
let questionFigure='',questionFigureSource='',questionRevision=0,figureBusy=false;
let submissionNoticeActive=false;
function canEdit(){return FeedbackWorkflow.canEdit({editEnabled,scene,uploadBusy,chatBusy,referenceDraft,originalMode});}
function svg(tag,attrs={},text,parent=canvas){const e=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;parent.append(e);return e;}
function message(text,role='assistant',error=false,targets=[],tone='next',snapshot=null,drawingVersion=currentDrawingVersion,action='highlight',mechanism=null){
 const entry={role,text:String(text),error:!!error,at:new Date().toISOString()};
 if(targets.length&&action!=='none')entry.visual={ids:G.copy(targets),action,tone,scene:G.copy(snapshot?.scene||committed?.scene||initial),...(mechanism?{mechanism:G.copy(mechanism)}:{})};
 interactionLog.push(entry);
 return renderInteraction(entry,drawingVersion);
}
function renderInteraction(entry,drawingVersion=entry.feedback?.drawing_version??entry.drawing_version??currentDrawingVersion){
 const {role,text,error}=entry,visual=entry.visual,targets=visual?.ids||[],action=visual?.action||'none';
 const e=document.createElement('div');e.className='message '+role+(error?' error':'');
 if(visual?.tone==='response')e.classList.add('response-recognition');
 e.interactionEntry=entry;
 const avatar=document.createElement('img');avatar.className='message-avatar';avatar.src=role==='user'?'/avatars/student.svg':'/avatars/tutor.svg';avatar.alt='';avatar.setAttribute('aria-hidden','true');e.append(avatar);
 const body=document.createElement('div');body.className='message-body';const name=document.createElement('span');name.className='message-label';name.textContent=role==='user'?'You':'Tutor';body.append(name);
 const t=document.createElement('span');t.className='message-text';t.textContent=text;body.append(t);
 if(targets.length&&action!=='none'){const button=document.createElement('button');button.type='button';button.className='inline-show';button.textContent=action==='trace'?'Show again':'Show';button.setAttribute('aria-label','Show the diagram referenced by this feedback');button.onclick=()=>showDiagramReference(targets,visual.scene?{scene:visual.scene}:null,drawingVersion,visual.tone||'next',action,true,true,visual.mechanism||null,true);body.append(button);}
 e.append(body);$('messages').append(e);$('messages').scrollTop=$('messages').scrollHeight;return e;
}

function feedbackMessage(response,snapshot,trigger){
 const ack=response.acknowledgment||'',follow=response.follow_up??response.content;
 const tone=response.response_mode==='dialogue'&&response.next_focus_kind==='none'?'discussion':response.next_focus_kind==='clarification'?'clarification':response.next_focus_kind==='extension'?'extension':'next';
 const mechanism=response.mechanism_paths?.length?{paths:response.mechanism_paths,condition:response.mechanism_condition}:null;
 let targets=[...new Set([...(response.acknowledgment_ids||[]),...(response.focus_ids||[])])];
 if(!targets.length&&response.visual_action==='trace'&&mechanism)targets=[...new Set(mechanism.paths.flatMap(path=>path.steps.map(step=>step.relation_id)))];
 if(response.visual_delivery==='none'||!response.visual_delivery)targets=[];
 const bubble=message([ack,follow].filter(Boolean).join(' '),'assistant',false,targets,ack?'response':tone,snapshot,response.drawing_version,response.visual_action,mechanism);
 bubble.interactionEntry.trigger=trigger;
 bubble.interactionEntry.feedback=G.copy(Object.fromEntries(['talk_move','talk_moves','phase','stage','drawing_version','response_mode','next_focus_kind','visual_action','visual_delivery','revision_plan','edit_enabled','awaiting_revision_reason','revision_reason_required'].filter(key=>response[key]!==undefined).map(key=>[key,response[key]])));
 if(ack)bubble.classList.add('response-recognition');
 if(response.visual_delivery==='automatic'&&targets.length)showDiagramReference(targets,snapshot,response.drawing_version,ack?'response':tone,response.visual_action,false,false,mechanism);
}
function clearFeedbackCue(){if(!focusIds.length&&!activeMechanism)return;stop();focusIds=[];highlight.clear();focusBounds=null;updateGuidance();fit();draw();}
function showScreen(name){screen=name;$('submissionScreen').hidden=name!=='submission';$('feedbackScreen').hidden=name!=='feedback';document.body.dataset.screen=name;buttons();}
function returnToDraft(){if(!referenceDraft)return;stop();scene=referenceDraft.scene;anchors=referenceDraft.anchors;selected=referenceDraft.selected;view=referenceDraft.view;referenceDraft=null;focusIds=[];$('referenceNotice').hidden=true;setView(false);draw();updateDraft();}
function showDiagramReference(ids,snapshot,drawingVersion,tone,action='highlight',scroll=true,zoom=true,mechanism=null,readOnlyReplay=false){
 returnToDraft();stop();
 if(snapshot&&((readOnlyReplay&&editEnabled)||JSON.stringify(snapshot.scene)!==JSON.stringify(G.exportScene(scene,anchors)))){
  referenceDraft={scene,anchors,selected,view};scene=G.copy(snapshot.scene);anchors=G.anchors(scene);fit();
  $('referenceLabel').textContent='Submitted diagram '+drawingVersion+' · Read only';$('referenceNotice').hidden=false;
 }
 showGuidance(ids,zoom,scroll,tone);
 updateDraft();
 if(action==='trace'&&mechanism?.paths?.length){startMechanism(mechanism);return;}
 if(action==='trace'&&scene.relations.some(r=>ids.includes(r.id)&&['forward','backward','both'].includes(r.direction))){traceIds=new Set(ids);playing=true;$('play').textContent='Ⅱ Pause arrows';raf=requestAnimationFrame(animate);}
}
$('returnToDraft').onclick=returnToDraft;
$('newSubmission').onclick=()=>{returnToDraft();stop();showScreen('submission');};

function displayName(o){return o?.label||o?.verbatim_text||'Drawing part';}
function object(id){return scene?.objects.find(o=>o.id===id)}
function relation(id){return scene?.relations.find(r=>r.id===id)}
function connectionName(id){const r=relation(id);return r?E.relationName(scene,r):'Connection';}
function captureEdit(){return {scene:G.exportScene(scene,anchors),edits:G.copy(editEvents),selected};}
function pushEdit(snapshot=captureEdit()){editHistory.push(snapshot);if(editHistory.length>40)editHistory.shift();}
function bake(){scene=G.exportScene(scene,anchors);anchors=G.anchors(scene);}
function updateGuidance(){
 if(!scene)return;const result=E.focus(G.exportScene(scene,anchors),focusIds);highlight=new Set(result.ids);focusBounds=result.bounds;
 $('guidance').hidden=!focusIds.length;$('zoomFocus').disabled=!result.bounds;
 const names=activeMechanism?activeMechanism.paths.map(path=>path.label):focusIds.filter(id=>object(id)||relation(id)).map(id=>object(id)?displayName(object(id)):connectionName(id));
 const prefix=activeMechanism?'Exploring: ':({'discussion':'Discussing: ','response':'Your response: ','clarification':'To clarify: ','extension':'Optional exploration: ','next':'Next to consider: '}[focusTone]);
 $('guidanceText').textContent=result.missing.length?(names.length?'Some referenced parts are no longer in this draft. Showing: '+names.join(' · '):'This feedback refers to parts removed from the current draft. Undo or review your changes to update the feedback.'):prefix+names.join(' · ');
 canvas.classList.toggle('spotlighting',highlight.size>0);canvas.dataset.tone=focusTone;$('guidance').dataset.tone=focusTone;
}
function zoomGuidance(){if(!focusBounds)return;const b=focusBounds,pad=55,w=Math.max(280,b.width+pad*2),h=Math.max(190,b.height+pad*2),ratio=payload.record.height/payload.record.width;view=`${b.x+b.width/2-w/2} ${(b.y+b.height/2-h/2)*ratio} ${w} ${h*ratio}`;draw();}
function showGuidance(ids,zoom=false,scroll=false,tone='next'){if(!scene)return;selected='';focusTone=tone;focusIds=[...new Set(ids||[])];setView(false);updateGuidance();if(zoom)zoomGuidance();else draw();if(scroll)$('canvasWrap').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'nearest'});}
$('zoomFocus').onclick=zoomGuidance;$('clearFocus').onclick=()=>{stop();focusIds=[];highlight.clear();fit();draw();};

function draftSnapshot(){return {scene:G.exportScene(referenceDraft?.scene||scene,referenceDraft?.anchors||anchors),explanation:$('explanation').value,edits:G.copy(editEvents)};}
function clearSubmissionNotice(){submissionNoticeActive=false;if($('submissionNotice'))$('submissionNotice').hidden=true;}
function updateSubmissionNotice(){
 if(!submissionNoticeActive)return;
 if(!scene||!FeedbackWorkflow.changed(draftSnapshot(),committed)){clearSubmissionNotice();return;}
 let notice=$('submissionNotice');
 if(!notice){
  notice=document.createElement('div');notice.id='submissionNotice';notice.className='reference-notice';notice.setAttribute('role','status');notice.setAttribute('aria-live','polite');
  const text=document.createElement('span');text.id='submissionNoticeText';notice.append(text);
  const action=document.createElement('button');action.id='submitDraftAction';action.type='button';action.setAttribute('aria-describedby','submissionNoticeText');
  action.onclick=()=>{if(chatBusy||uploadBusy||revisionAuth)return;if(editEnabled){returnToDraft();$('reviewChanges').click();}else beginRevision();};
  notice.append(action);$('messages').after(notice);
 }
 notice.hidden=false;
 $('submissionNoticeText').textContent=editEnabled?'Your changes have not been submitted yet. Select Review changes so I can check your updated diagram.':'Your changes are still a private draft. Select Begin a revision, then Review changes to share them.';
 $('submitDraftAction').textContent=editEnabled?'Review changes':'Begin a revision';$('submitDraftAction').disabled=chatBusy||uploadBusy||!!revisionAuth;
}
function showSubmissionNotice(){submissionNoticeActive=true;updateSubmissionNotice();$('chatStatus').textContent='Your draft has not been submitted.';$('submitDraftAction')?.focus();}
function recordEdit(kind,id,value){editEvents.push({kind,id,value,at:new Date().toISOString()});if(editEvents.length>2000)editEvents.shift();updateDraft();}
function updateDraft(){
 if(!scene)return;const dirty=FeedbackWorkflow.changed(draftSnapshot(),committed);
 $('draftStatus').textContent=feedbackSession?(dirty?(editEnabled?'Draft changes — select Review changes to share them.':'Your unsubmitted draft is still here.'):'Your latest submitted work is being discussed.'):'Your drawing and explanation are reviewed together.';
 $('changeHint').textContent=referenceDraft?'Viewing the visual feedback for this submitted diagram.':editEnabled?(dirty?'Changes are private until you submit them.':'Make your changes on the canvas, then select Review changes.'):'Explore your diagram. Select Begin a revision when you are ready to edit.';
 $('revisionReasonSection').hidden=!!referenceDraft||(!editEnabled&&!awaitingRevisionReason);
 $('revisionReasonLabel').textContent=awaitingRevisionReason?'Explain why your ideas changed':'Revision explanation (when needed)';
 $('revisionReasonHint').textContent=awaitingRevisionReason?editEnabled?'Explain how these changes improve your diagram.':'Continue explaining your submitted changes in chat.':'Explain conceptual changes. Small corrections do not need another explanation.';
 $('modelBadge').textContent=referenceDraft?'Feedback reference':editEnabled?'Revision mode':'View only';canvas.dataset.editable=String(canEdit());buttons();
 updateSubmissionNotice();
 $('canvasHint').textContent=editEnabled&&!referenceDraft?'Drag objects or lines to move · Drag round ends or square bends to reshape · Use + / − to resize.':'Select a part to inspect it · Show replays the matching visual feedback.';
}
function updateFeedbackHeader(response){const permissionChanged=editEnabled!==(response.edit_enabled===true);reviewRows=G.copy(response.review);$('learningGoal').textContent=response.learning_goal;currentDrawingVersion=response.drawing_version;$('modelVersion').textContent='Submitted diagram '+currentDrawingVersion;editEnabled=response.edit_enabled===true;awaitingRevisionReason=response.awaiting_revision_reason===true;if(permissionChanged)requestAnimationFrame(()=>{if(scene)draw();});}

async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined);const d=await r.json();if(!r.ok)throw Error(d.error||'The request could not be completed.');return d;}
function buttons(){
 const viewing=!!scene&&!uploadBusy,editing=canEdit(),canFeedback=viewing&&!chatBusy&&!revisionAuth;
 $('play').disabled=!viewing||(!activeMechanism&&!scene.relations.some(r=>['forward','backward','both'].includes(r.direction)));
 $('reset').disabled=!editing;$('save').disabled=!viewing;$('undo').disabled=!editing||!editHistory.length;
 $('deletePart').disabled=!editing||(!object(selected)&&!relation(selected));$('openLibrary').disabled=!editing;
 $('rename').disabled=!editing||!object(selected);
 for(const id of ['smaller','larger'])$(id).disabled=!editing||(!object(selected)&&!relation(selected));
 $('rename').textContent=E.isText(object(selected))?'Edit text':'Edit label / text';
 $('editConnection').hidden=!relation(selected);$('editConnection').disabled=!editing;
 $('send').disabled=!canFeedback||!feedbackSession;
 $('reviewChanges').disabled=!canFeedback||!!referenceDraft||(!!feedbackSession&&!editEnabled);
 $('reviewChanges').hidden=!!referenceDraft;
 $('reviewChanges').textContent=feedbackSession?'Review changes':'Retry feedback';
 $('exitRevision').hidden=!editEnabled&&revisionAuth?.enabled!==false;
 $('exitRevision').disabled=!feedbackSession||chatBusy||uploadBusy||!!revisionAuth;
 $('exitRevision').textContent=revisionAuth?.enabled===false?'Exiting…':'Exit revision';
 updateExportAvailability();
 $('addNote').disabled=!editing;$('connect').disabled=!editing||scene.objects.length<2;
 for(const id of ['submitImage','examples','task','taskFigure','clearTaskFigure','goals','file','explanation','newSubmission'])$(id).disabled=chatBusy||uploadBusy||figureBusy||!!revisionAuth;
 for(const b of document.querySelectorAll('.suggestions button'))b.disabled=!canFeedback||!feedbackSession||(b.dataset.intent==='begin_revision'&&editEnabled);
 $('revisionReason').disabled=!editEnabled||chatBusy||uploadBusy||!!referenceDraft||!!revisionAuth;
 canvas.dataset.editable=String(editing);
}

function fit(){const b=G.bounds([...scene.objects,...scene.relations.map(r=>({bbox:G.relationBounds(scene,r,anchors)}))]),ratio=payload.record.height/payload.record.width;view=`${b.x-35} ${(b.y-35)*ratio} ${Math.max(150,b.width+70)} ${Math.max(120,b.height+70)*ratio}`;}
function glyph(parent,o){const b=o.bbox,ink='#43404a';if(o.glyph.length&&o.glyph.every(s=>s.kind==='text')){const ratio=payload.record.height/payload.record.width,height=b.height*ratio,lines=(o.verbatim_text||o.glyph.map(s=>s.text).join('\n')).split('\n'),font=E.textSize(o,ratio);lines.forEach((line,i)=>svg('text',{x:b.x,y:b.y*ratio+height/2+(i-(lines.length-1)/2)*font*1.2,transform:`scale(1 ${1/ratio})`,'font-size':font,'dominant-baseline':'middle',fill:o.glyph[i]?.color||ink},line,parent));return;}
const local=svg('g',{transform:`translate(${b.x} ${b.y}) scale(${b.width/1000} ${b.height/1000})`},undefined,parent);for(const s of o.glyph){const color=s.color||ink,attrs={fill:s.filled?color:'none',stroke:color,'fill-opacity':s.filled?.28:1,'stroke-width':1.8,'vector-effect':'non-scaling-stroke','stroke-linejoin':'round','stroke-linecap':'round'};if(s.kind==='text'){const p=s.points[0],font=Math.max(1,Math.min(26,b.height*.36,b.width*(1000-p.x)/1000/(Math.max(1,s.text.length)*.55)));svg('text',{x:b.x+p.x*b.width/1000,y:b.y+p.y*b.height/1000,'font-size':font,'dominant-baseline':'hanging',fill:color},s.text,parent)}else if(['rect','ellipse'].includes(s.kind)){const[a,q]=s.points,x=Math.min(a.x,q.x),y=Math.min(a.y,q.y),w=Math.abs(q.x-a.x),h=Math.abs(q.y-a.y);svg(s.kind,{...attrs,...(s.kind==='rect'?{x,y,width:w,height:h}:{cx:x+w/2,cy:y+h/2,rx:w/2,ry:h/2})},undefined,local)}else svg(s.kind,{...attrs,points:s.points.map(p=>`${p.x},${p.y}`).join(' ')},undefined,local);}}
function draw(){if(!scene)return;updateGuidance();canvas.replaceChildren();canvas.setAttribute('viewBox',view);const defs=svg('defs'),marker=svg('marker',{id:'arrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:7,markerHeight:7,orient:'auto-start-reverse'},undefined,defs);svg('path',{d:'M 1 1 L 9 5 L 1 9',fill:'none',stroke:'context-stroke','stroke-width':1.8},undefined,marker);const root=svg('g',{id:'sceneRoot',transform:`scale(1 ${payload.record.height/payload.record.width})`});
for(const r of scene.relations){const ps=G.points(scene,r,anchors),g=svg('g',{'data-id':r.id,class:`relation ${selected===r.id?'selected':''} ${highlight.has(r.id)?'highlight':''}`,tabindex:0,role:'button','aria-label':connectionName(r.id)},undefined,root);const points=ps.map(p=>`${p.x},${p.y}`).join(' ');svg('polyline',{points,fill:'none',stroke:'transparent','stroke-width':18},undefined,g);const attrs={id:'edge-'+r.id,class:'ink',points,fill:'none',stroke:r.color||'#81718e','stroke-width':2,'stroke-linecap':'round','stroke-linejoin':'round'};if(['forward','both'].includes(r.direction))attrs['marker-end']='url(#arrow)';if(['backward','both'].includes(r.direction))attrs['marker-start']='url(#arrow)';if(highlight.has(r.id))svg('polyline',{points,fill:'none',class:'cue-line'},undefined,g);svg('polyline',attrs,undefined,g);const a=ps[0],b=ps.at(-1),oa=r.points[0],ob=r.points.at(-1),x=r.label_position.x+(a.x-oa.x+b.x-ob.x)/2,y=r.label_position.y+(a.y-oa.y+b.y-ob.y)/2;if(r.verbatim_text)svg('text',{x,y,'font-size':22,fill:r.color||'#695676','paint-order':'stroke',stroke:'white','stroke-width':4},r.verbatim_text,g);}

for(const o of scene.objects.filter(o=>!o.members.length)){const b=o.bbox,g=svg('g',{'data-id':o.id,class:`object ${selected===o.id?'selected':''} ${(highlight.has(o.id)||scene.objects.some(g=>highlight.has(g.id)&&g.members.includes(o.id)))?'highlight':''}`,tabindex:0,role:'button','aria-label':displayName(o)+(canEdit()?'. Use arrow keys to move.':'. View only.')},undefined,root);svg('rect',{x:b.x-7,y:b.y-7,width:b.width+14,height:b.height+14,rx:6,class:'halo'},undefined,g);glyph(g,o);if(editEvents.some(e=>e.kind==='rename'&&e.id===o.id)&&!o.glyph.every(s=>s.kind==='text'))svg('text',{x:b.x,y:b.y+b.height+16,'font-size':13,fill:'#7652b9','paint-order':'stroke',stroke:'white','stroke-width':3},o.label,g);svg('title',{},displayName(o),g);}
if(canEdit()&&relation(selected)){
 const ps=G.points(scene,relation(selected),anchors),controls=G.relationControls(scene,relation(selected),anchors);
 for(const control of controls){
  const p=control.point;
  if(control.kind==='curve')svg('polyline',{points:[ps[0],ps.at(-1)].map(q=>`${q.x},${q.y}`).join(' '),class:'relation-control-guide',fill:'none'},undefined,root);
  const handle=svg('g',{'data-id':selected,'data-control':control.index,class:'relation-control',tabindex:0,role:'button','aria-label':control.kind==='curve'?'Adjust curve of selected connection':'Move bend of selected connection'},undefined,root);
  svg('circle',{cx:p.x,cy:p.y,r:14,fill:'transparent'},undefined,handle);
  svg('rect',{x:p.x-6,y:p.y-6,width:12,height:12,rx:2,class:'relation-control-handle'},undefined,handle);
 }
 for(const [end,p]of [['source',ps[0]],['target',ps.at(-1)]]){
  const handle=svg('g',{'data-id':selected,'data-endpoint':end,class:'relation-endpoint',tabindex:0,role:'button','aria-label':`Move ${end==='source'?'start':'end'} of selected connection`},undefined,root);
  svg('circle',{cx:p.x,cy:p.y,r:13,fill:'transparent'},undefined,handle);
  svg('circle',{cx:p.x,cy:p.y,r:7,class:'relation-handle'},undefined,handle);
 }
}
if(focusBounds)svg('rect',{x:focusBounds.x-12,y:focusBounds.y-12,width:focusBounds.width+24,height:focusBounds.height+24,rx:8,class:'feedback-frame'},undefined,root);
if(activeMechanism)renderMechanism();
$('selectedName').textContent=relation(selected)?connectionName(selected):(selected?displayName(object(selected)):'Select a part to explore it.');buttons();}
function stop(){playing=false;traceIds=null;activeMechanism=null;cancelAnimationFrame(raf);$('play').textContent='▷ Follow arrows';$('mechanismNotice').hidden=true;canvas.classList.remove('mechanism-playing');canvas.querySelectorAll('.flow-dot,.mechanism-overlay').forEach(e=>e.remove());}
function renderMechanism(){
 if(!activeMechanism)return;const root=$('sceneRoot');canvas.querySelectorAll('.mechanism-overlay').forEach(e=>e.remove());
 activeMechanism.routes=MechanismFeedback.routes(scene,activeMechanism.paths,G,anchors);
 for(const route of activeMechanism.routes)svg('polyline',{points:route.points.map(p=>`${p.x},${p.y}`).join(' '),fill:'none',stroke:route.color,class:'mechanism-overlay mechanism-track','stroke-width':3,'stroke-linejoin':'round','vector-effect':'non-scaling-stroke'},undefined,root);
 mechanismArrows(activeMechanism.elapsed||0);
}
function mechanismArrows(elapsed){
 canvas.querySelectorAll('.flow-arrow').forEach(e=>e.remove());const root=$('sceneRoot');
 for(const [index,route] of activeMechanism.routes.entries())for(const offset of [.08,.4,.72]){
  const p=MechanismFeedback.sample(route,(elapsed/5500+offset+index*.12)%1);if(!p)continue;
  const arrow=svg('g',{class:'mechanism-overlay flow-arrow','data-path':index,transform:`translate(${p.x} ${p.y}) rotate(${p.angle})`},undefined,root);
  svg('path',{d:'M -12 0 H 8 M 0 -7 L 10 0 L 0 7',fill:'none',stroke:'white','stroke-width':6,'stroke-linecap':'round','stroke-linejoin':'round'},undefined,arrow);
  svg('path',{d:'M -12 0 H 8 M 0 -7 L 10 0 L 0 7',fill:'none',stroke:route.color,'stroke-width':3.5,'stroke-linecap':'round','stroke-linejoin':'round'},undefined,arrow);
 }
}
function startMechanism(mechanism){
 activeMechanism={paths:G.copy(mechanism.paths),condition:mechanism.condition||'Follow the highlighted paths',elapsed:0,started:null};
 $('mechanismCondition').textContent=activeMechanism.condition;$('mechanismLegend').replaceChildren();
 activeMechanism.paths.forEach((path,index)=>{const label=document.createElement('span');label.textContent=path.label;label.style.setProperty('--path-color',MechanismFeedback.colors[index]);$('mechanismLegend').append(label);});
 $('mechanismNotice').hidden=false;canvas.classList.add('mechanism-playing');updateGuidance();renderMechanism();
 playing=!matchMedia('(prefers-reduced-motion: reduce)').matches;$('mechanismToggle').textContent=playing?'Pause':'Play';$('play').textContent=playing?'Ⅱ Pause arrows':'▷ Follow arrows';buttons();
 if(playing)raf=requestAnimationFrame(animate);
}
function toggleMechanism(){
 if(!activeMechanism)return;playing=!playing;cancelAnimationFrame(raf);activeMechanism.started=null;
 $('mechanismToggle').textContent=playing?'Pause':'Play';$('play').textContent=playing?'Ⅱ Pause arrows':'▷ Follow arrows';
 if(playing)raf=requestAnimationFrame(animate);
}
$('mechanismToggle').onclick=toggleMechanism;
$('mechanismReplay').onclick=()=>{if(!activeMechanism)return;cancelAnimationFrame(raf);const plan={paths:activeMechanism.paths,condition:activeMechanism.condition};startMechanism(plan);};
function animate(time){
 if(!playing)return;
 if(activeMechanism){
  if(activeMechanism.started===null)activeMechanism.started=time-activeMechanism.elapsed;
  activeMechanism.elapsed=time-activeMechanism.started;mechanismArrows(activeMechanism.elapsed);raf=requestAnimationFrame(animate);return;
 }
 canvas.querySelectorAll('.flow-dot').forEach(e=>e.remove());const root=$('sceneRoot');
 for(const r of scene.relations){if(!['forward','backward','both'].includes(r.direction)||(traceIds&&!traceIds.has(r.id)))continue;const line=document.getElementById('edge-'+r.id);if(!line)continue;const length=line.getTotalLength();for(const direction of r.direction==='both'?[1,-1]:[r.direction==='backward'?-1:1]){let t=(time/2700)%1;if(direction<0)t=1-t;const p=line.getPointAtLength(length*t);svg('circle',{cx:p.x,cy:p.y,r:5,class:'flow-dot'},undefined,root)}}raf=requestAnimationFrame(animate);
}
function setView(original){originalMode=original;$('original').hidden=!original;canvas.toggleAttribute('hidden',original);$('originalView').classList.toggle('active',original);$('modelView').classList.toggle('active',!original);$('originalView').setAttribute('aria-pressed',original);$('modelView').setAttribute('aria-pressed',!original);if(original)stop();buttons();}
function currentQuestion(){const q={text:$('task').value,image:questionFigure};if(questionFigureSource==='example'&&payload?.question?.id)q.id=payload.question.id;return q;}
function renderTaskContext(){
 $('questionHeading').textContent='Task';
 $('questionText').textContent=$('task').value||(questionFigure?'':'Explain how your diagram represents your ideas and explore possible improvements.');
 $('questionText').hidden=!$('questionText').textContent;
 for(const id of ['questionImage','submissionQuestionImage']){$(id).hidden=!questionFigure;if(questionFigure)$(id).src=questionFigure;else $(id).removeAttribute('src');}
 for(const id of ['clearTaskFigure','viewTaskFigure','viewSubmissionTaskFigure'])$(id).hidden=!questionFigure;
 if($('taskFigureDialog').open){if(questionFigure)$('fullTaskFigure').src=questionFigure;else $('taskFigureDialog').close();}
 if(!questionFigure)$('fullTaskFigure').removeAttribute('src');
}
function setQuestionFigure(image='',source=''){questionFigure=image||'';questionFigureSource=source;renderTaskContext();}
function openTaskFigure(){if(!questionFigure)return;$('fullTaskFigure').src=questionFigure;$('taskFigureDialog').showModal();}
$('viewTaskFigure').onclick=openTaskFigure;$('viewSubmissionTaskFigure').onclick=openTaskFigure;$('closeTaskFigure').onclick=()=>$('taskFigureDialog').close();
function showQuestion(data){const q=data.question;if(q&&screen==='submission')$('task').value=q.text||'';setQuestionFigure(q?.image||'',q?.image===questionFigure?questionFigureSource:'example');}

async function changeRevisionMode(enabled){
 if(!scene||!feedbackSession||chatBusy||uploadBusy||revisionAuth||editEnabled===enabled)return;
 const request={session:feedbackSession,version:revision,enabled,wasEnabled:editEnabled,wasAwaiting:awaitingRevisionReason};
 revisionAuth=request;
 if(enabled){returnToDraft();stop();setView(false);}else if(drag)endDrag({type:'pointercancel'});
 editEnabled=enabled;updateDraft();draw();
 $('chatStatus').textContent=enabled?'Make your changes on the canvas, then select Review changes.':'Revision closed. Your unsubmitted changes are still here.';
 const current=()=>revisionAuth===request&&request.session===feedbackSession&&request.version===revision;
 try{
  const result=await api(enabled?'/api/begin-revision':'/api/end-revision',{session_id:request.session});
  if(current()){editEnabled=result.edit_enabled===true;awaitingRevisionReason=result.awaiting_revision_reason===true;}
 }catch(e){
  if(current()){editEnabled=request.wasEnabled;awaitingRevisionReason=request.wasAwaiting;$('chatStatus').textContent=(enabled?'Revision could not be opened. ':'Revision could not be closed. ')+e.message;}
 }finally{if(current()){revisionAuth=null;updateDraft();draw();}}
}
function beginRevision(){return changeRevisionMode(true);}
function endRevision(){return changeRevisionMode(false);}
$('exitRevision').onclick=endRevision;

function load(data){clearSubmissionNotice();showQuestion(data);revision++;revisionAuth=null;caseExportRequest=null;interactionLog=[];initialExplanation=null;$('caseExportStatus').textContent='';stop();referenceDraft=null;currentDrawingVersion=1;payload=data;initial=G.copy(data.scene);scene=G.copy(initial);anchors=G.anchors(scene);selected='';highlight.clear();conversation=[];feedbackSession='';committed=null;editEnabled=false;awaitingRevisionReason=false;$('revisionReason').value='';feedbackTurns=[];editEvents=[];reviewRows=[];editHistory=[];focusIds=[];lastTap=null;$('messages').replaceChildren();$('sceneTitle').textContent=scene.title;$('original').src=data.original;$('submissionPreview').src=data.original;$('submissionPreview').hidden=false;$('previewEmpty').hidden=true;$('previewCaption').textContent=scene.title;$('referenceNotice').hidden=true;$('empty').hidden=true;$('busy').hidden=true;$('learningGoal').textContent=$('goals').value.trim()||'Preparing your goal…';fit();setView(false);draw();updateDraft();$('canvasHint').textContent='Select a part to inspect it · Show replays the matching visual feedback.';$('chatStatus').textContent='A space to explain, explore, and revise.';}
function point(event){const p=canvas.createSVGPoint();p.x=event.clientX;p.y=event.clientY;return p.matrixTransform($('sceneRoot').getScreenCTM().inverse());}
canvas.addEventListener('pointerdown',e=>{
 const target=e.target.closest('[data-id]');tapId='';if(!target||uploadBusy)return;
 selected=target.dataset.id;const o=object(selected),r=relation(selected);
 if((!o&&!r)||!canEdit()){draw();e.preventDefault();return;}
 tapId=selected;const p=point(e),end=target.dataset.endpoint,ps=r&&G.points(scene,r,anchors),control=r&&target.dataset.control!==undefined?G.relationControls(scene,r,anchors).find(h=>h.index===Number(target.dataset.control)):null;
 drag={id:selected,x:p.x,y:p.y,b:G.copy(o?.bbox||G.relationBounds(scene,r,anchors)),snapshot:captureEdit(),end,control,
  endpoint:end?G.copy(end==='source'?ps[0]:ps.at(-1)):null};
 canvas.setPointerCapture(e.pointerId);draw();e.preventDefault();
});
canvas.addEventListener('pointermove',e=>{
 if(!drag||!canEdit()){drag=null;return;}const p=point(e),dx=p.x-drag.x,dy=p.y-drag.y;
 if(drag.control)G.reshapeRelationControl(scene,drag.id,drag.control.index,drag.control.point.x+dx,drag.control.point.y+dy,anchors);
 else if(drag.end)G.reshapeRelation(scene,drag.id,drag.end,drag.endpoint.x+dx,drag.endpoint.y+dy,anchors);
 else G.move(scene,drag.id,drag.b.x+dx,drag.b.y+dy,anchors);
 draw();
});
function endDrag(event){const id=drag?.id||tapId,o=object(id),r=relation(id);tapId='';
 const moved=drag&&JSON.stringify(G.exportScene(scene,anchors))!==JSON.stringify(drag.snapshot.scene);
 if(moved){
  if(r&&!drag.control)for(const end of drag.end?[drag.end]:['source','target'])E.reattach(scene,id,end,anchors);
  pushEdit(drag.snapshot);recordEdit(drag.end||drag.control?'resize':'move',id,o?{x:o.bbox.x,y:o.bbox.y}:{...G.copy(G.exportScene(scene,anchors).relations.find(r=>r.id===id)),endpoint:drag.end||null,control:drag.control?.index??null});
  draw();
 }
 drag=null;
// Redrawing SVG replaces its children, so detect two stationary taps by stable ID.
if(event.type==='pointercancel'||moved||!canEdit()){lastTap=null;return;}
const now=performance.now();if(id&&lastTap?.id===id&&now-lastTap.time<400){lastTap=null;if(o)openText();else if(relation(id))openConnection(id);}else lastTap={id,time:now};
 draw();
}canvas.addEventListener('pointerup',endDrag);canvas.addEventListener('pointercancel',endDrag);
canvas.addEventListener('keydown',e=>{
 const target=e.target.closest('[data-id]'),id=target?.dataset.id,end=target?.dataset.endpoint,control=target?.dataset.control;
 if(!id||uploadBusy||referenceDraft)return;selected=id;
 const o=object(id),r=relation(id),steps={ArrowLeft:[-5,0],ArrowRight:[5,0],ArrowUp:[0,-5],ArrowDown:[0,5]};
 const restoreFocus=()=>canvas.querySelector(`[data-id="${CSS.escape(id)}"]${end?`[data-endpoint="${end}"]`:control!==undefined?`[data-control="${control}"]`:''}`)?.focus();
 if(steps[e.key]&&(o||r)&&canEdit()){
  e.preventDefault();const[x,y]=steps[e.key];pushEdit();
  if(r&&control!==undefined){const h=G.relationControls(scene,r,anchors).find(h=>h.index===Number(control));if(h)G.reshapeRelationControl(scene,id,h.index,h.point.x+x,h.point.y+y,anchors);}
  else if(r&&end){const ps=G.points(scene,r,anchors),p=end==='source'?ps[0]:ps.at(-1);G.reshapeRelation(scene,id,end,p.x+x,p.y+y,anchors);E.reattach(scene,id,end,anchors);}
  else{const b=o?.bbox||G.relationBounds(scene,r,anchors);G.move(scene,id,b.x+x,b.y+y,anchors);if(r)for(const end of ['source','target'])E.reattach(scene,id,end,anchors);}
  recordEdit(end||control!==undefined?'resize':'move',id,o?{x:o.bbox.x,y:o.bbox.y}:G.copy(G.exportScene(scene,anchors).relations.find(r=>r.id===id)));draw();restoreFocus();
 }else if(['+','=','-'].includes(e.key)&&(o||r)&&canEdit()){
  e.preventDefault();const factor=e.key==='-'?.9:1.1;pushEdit();G.resize(scene,id,factor,anchors);if(r)for(const end of ['source','target'])E.reattach(scene,id,end,anchors);recordEdit('resize',id,{factor});draw();restoreFocus();
 }else if(e.key==='Delete'||e.key==='Backspace'){e.preventDefault();deleteSelected();}
 else if(e.key==='Enter'||e.key===' '){e.preventDefault();draw();restoreFocus();}
});
$('modelView').onclick=()=>setView(false);$('originalView').onclick=()=>setView(true);
$('play').onclick=()=>{if(activeMechanism){toggleMechanism();return;}if(playing){stop();return;}setView(false);playing=true;$('play').textContent='Ⅱ Pause arrows';raf=requestAnimationFrame(animate);};
$('reset').onclick=()=>{if(!canEdit())return;pushEdit();stop();focusIds=[];scene=G.copy(initial);anchors=G.anchors(scene);selected='';highlight.clear();recordEdit('reset','',{});fit();draw();};
for(const[id,factor]of [['smaller',.9],['larger',1.1]])$(id).onclick=()=>{if(!canEdit()||(!object(selected)&&!relation(selected)))return;pushEdit();G.resize(scene,selected,factor,anchors);if(relation(selected))for(const end of ['source','target'])E.reattach(scene,selected,end,anchors);recordEdit('resize',selected,{factor});draw();};
function openText(add=false){
 if(!canEdit())return;noteMode=add;const o=object(selected);if(!add&&!o)return;const pure=add||E.isText(o);$('textHeading').textContent=add?'Add text':pure?'Edit text':'Edit object label and text';$('textLabel').textContent=pure?'Text':'Object label';$('newName').value=add?'':pure?(o.verbatim_text||o.glyph.map(g=>g.text).join('\n')):o.label;$('textParts').replaceChildren();
 if(o&&!pure)o.glyph.forEach((g,i)=>{if(g.kind!=='text')return;const label=document.createElement('label');label.textContent='Text inside this object';const input=document.createElement('textarea');input.dataset.glyphIndex=i;input.value=g.text;input.maxLength=500;input.rows=2;label.append(input);$('textParts').append(label);});
 $('renameDialog').showModal();$('newName').focus();
}
$('rename').onclick=()=>openText();$('addNote').onclick=()=>openText(true);

function textOptions(){
 const context=document.createElement('canvas').getContext('2d'),family=getComputedStyle(canvas).fontFamily;
 return {ratio:payload.record.height/payload.record.width,measure:(line,size)=>{context.font=`${size}px ${family}`;return context.measureText(line).width;}};
}
$('cancelRename').onclick=()=>$('renameDialog').close();$('renameForm').onsubmit=e=>{e.preventDefault();if(!canEdit())return;const value=$('newName').value.trim();if(!value)return;pushEdit();if(noteMode){const id='note_'+crypto.randomUUID();scene.objects.push(E.createText(value,id,textOptions()));selected=id;recordEdit('add-note',id,{text:value});}else{const o=object(selected);if(!o)return;const parts=Object.fromEntries([...$('textParts').querySelectorAll('textarea')].map(e=>[e.dataset.glyphIndex,e.value]));E.editText(o,value,parts,textOptions());G.regroup(scene);recordEdit('rename',selected,{text:value,glyph_texts:parts});}$('renameDialog').close();fit();draw();};
function deleteSelected(){if(!canEdit()||(!object(selected)&&!relation(selected)))return;pushEdit();stop();bake();const deleted=E.remove(scene,selected);anchors=G.anchors(scene);recordEdit('delete',selected,{removed_ids:deleted});selected='';draw();updateDraft();}
$('deletePart').onclick=deleteSelected;
$('undo').onclick=()=>{if(!canEdit()||!editHistory.length)return;stop();const previous=editHistory.pop();scene=G.copy(previous.scene);editEvents=G.copy(previous.edits);selected=previous.selected;anchors=G.anchors(scene);fit();draw();updateDraft();};
function previewAsset(asset,parent){const icon=document.createElementNS(NS,'svg');icon.setAttribute('viewBox','0 0 1000 1000');icon.setAttribute('aria-hidden','true');for(const s of asset.glyph){const attrs={stroke:s.color||'#62516f',fill:s.filled?(s.color||'#62516f'):'none','stroke-width':28,'stroke-linejoin':'round'};if(s.kind==='text'){svg('text',{x:s.points[0].x,y:s.points[0].y,'font-size':190,fill:s.color||'#62516f'},s.text,icon);}else if(['ellipse','rect'].includes(s.kind)){const[a,b]=s.points,x=Math.min(a.x,b.x),y=Math.min(a.y,b.y),w=Math.abs(b.x-a.x),h=Math.abs(b.y-a.y);svg(s.kind,{...attrs,...(s.kind==='rect'?{x,y,width:w,height:h}:{cx:x+w/2,cy:y+h/2,rx:w/2,ry:h/2})},undefined,icon);}else svg(s.kind,{...attrs,points:s.points.map(p=>`${p.x},${p.y}`).join(' ')},undefined,icon);}parent.append(icon);}
function renderLibrary(){const topic=catalog.topics.find(t=>t.id===$('libraryTopic').value);$('libraryItems').replaceChildren();for(const asset of topic?.assets||[]){const b=document.createElement('button');b.type='button';b.className='library-item';previewAsset(asset,b);const label=document.createElement('span');label.textContent=asset.label;b.append(label);b.onclick=()=>{if(!canEdit())return;pushEdit();const id='asset_'+crypto.randomUUID(),o=E.instantiate(asset,id);scene.objects.push(o);selected=id;recordEdit('add-object',id,{topic:topic.id,asset_id:asset.id,preloaded:true,label:asset.label});$('libraryDialog').close();fit();draw();};$('libraryItems').append(b);}}
$('openLibrary').onclick=async()=>{if(!canEdit())return;try{if(!catalog){catalog=await api('/catalog.json');$('libraryTopic').replaceChildren(...catalog.topics.map(t=>new Option(t.label,t.id)));}if(!canEdit())return;renderLibrary();$('libraryDialog').showModal();}catch(e){message('The object library could not be opened. '+e.message,'assistant',true);}};$('libraryTopic').onchange=renderLibrary;$('closeLibrary').onclick=()=>$('libraryDialog').close();

function openConnection(id=''){if(!canEdit())return;connectionId=id;const r=relation(id);for(const target of ['connectionFrom','connectionTo']){$(target).replaceChildren(new Option('Unresolved endpoint',''));for(const o of scene.objects)$(target).add(new Option(displayName(o),o.id));}$('connectionFrom').value=r?.source||object(selected)?.id||scene.objects[0]?.id||'';$('connectionTo').value=r?.target||scene.objects.find(o=>o.id!==$('connectionFrom').value)?.id||'';if(r){$('connectionFrom').value=r.source||'';$('connectionTo').value=r.target||'';}$('connectionLabel').value=r?.verbatim_text||'';$('connectionShape').value=r?G.connectionShape(G.points(scene,r,anchors)):'straight';$('connectionDirection').value=r?.direction==='uncertain'?'none':r?.direction||'forward';$('connectionHeading').textContent=r?'Edit '+connectionName(id):'Connect two parts';$('connectionDialog').showModal();}
$('connect').onclick=()=>openConnection();$('editConnection').onclick=()=>openConnection(selected);$('cancelConnection').onclick=()=>$('connectionDialog').close();
$('connectionForm').onsubmit=e=>{
 e.preventDefault();if(!canEdit())return;pushEdit();scene=G.exportScene(scene,anchors);anchors=G.anchors(scene);
 const old=relation(connectionId),from=$('connectionFrom').value||null,to=$('connectionTo').value||null,shape=$('connectionShape').value;
 if(old){
  if(old.source!==from&&object(from)){const p=G.center(object(from));G.reshapeRelation(scene,old.id,'source',p.x,p.y,anchors);}
  if(old.target!==to&&object(to)){const p=G.center(object(to));G.reshapeRelation(scene,old.id,'target',p.x,p.y,anchors);}
 }
 const a=old?.points[0]||G.center(object(from))||{x:400,y:450},b=old?.points.at(-1)||G.center(object(to))||{x:600,y:450},preserve=old&&G.connectionShape(old.points)===shape;
 const ps=preserve?G.copy(old.points):G.connectionPoints(a,b,shape),middle=ps[Math.floor(ps.length/2)],label=preserve?G.copy(old.label_position):{x:shape==='straight'?(a.x+b.x)/2:middle.x,y:Math.max(0,(shape==='straight'?(a.y+b.y)/2:middle.y)-12)};
 const r={id:connectionId||'connection_'+crypto.randomUUID(),source:from,target:to,direction:$('connectionDirection').value,points:ps,verbatim_text:$('connectionLabel').value.trim(),label_position:label,interpretation:'Connection explicitly edited by the student.',origin:'student',confidence:1,evidence:'Student submitted a workspace connection.',ambiguity:from&&to?'':'An endpoint is unresolved.',color:old?.color||null};
 if(old)scene.relations[scene.relations.findIndex(v=>v.id===old.id)]=r;else scene.relations.push(r);
 selected=r.id;recordEdit('connect',r.id,{source:from,target:to,label:r.verbatim_text,direction:r.direction,shape});$('connectionDialog').close();draw();
};

function learningRequirements(){return $('goals').value.split('\n').map(s=>s.trim()).filter(Boolean);}
$('save').onclick=()=>{const data={scene:G.exportScene(scene,anchors),source:payload.record,question:currentQuestion(),provenance:payload.provenance,original_model:initial,original_image:payload.original,committed_work:committed,current_draft:draftSnapshot(),feedback_session:feedbackSession,feedback_turns:feedbackTurns,overall_feedback:reviewRows,conversation,interaction_log:G.copy(interactionLog),workspace_state:{edit_enabled:editEnabled,awaiting_revision_reason:awaitingRevisionReason,revision_reason:$('revisionReason').value,learning_requirements:learningRequirements(),initial_explanation:initialExplanation},exported_at:new Date().toISOString()},url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=(payload.record.id||'drawing')+'.exploration.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
function exporterAvailable(){return typeof window.FeedbackCaseExport?.build==='function'&&typeof window.FeedbackCaseExport?.filename==='function';}
function canExportCase(){return !!scene&&!!initial&&initialExplanation!==null&&!chatBusy&&!uploadBusy&&!figureBusy&&!revisionAuth&&!caseExportRequest&&exporterAvailable();}
function updateExportAvailability(){
 const available=exporterAvailable(),status=$('caseExportStatus');$('exportCase').disabled=!canExportCase();
 $('exportCase').title=available?'Download the submitted case as a self-contained HTML file.':'HTML export is unavailable because the export module did not load. Reload after updating the local service.';
 if(!available&&scene&&initialExplanation!==null){status.textContent='HTML export is unavailable: the export module did not load.';status.dataset.reason='module';}
 else if(available&&status.dataset.reason==='module'){status.textContent='';delete status.dataset.reason;}
}
function caseExportData(){const requirements=$('goals').value.split('\n').map(s=>s.trim()).filter(Boolean);return G.copy({title:scene.title,exported_at:new Date().toISOString(),question:currentQuestion(),learning_goal:feedbackTurns.at(-1)?.learning_goal||requirements.join('\n'),learning_requirements:requirements,original_image:payload.original,original_scene:initial,initial_explanation:initialExplanation||'',committed_work:committed,drawing_dimensions:{width:payload.record.width,height:payload.record.height},turns:feedbackTurns,transcript:interactionLog});}
async function exportCaseHTML(){
 if(!canExportCase())return;const request={version:revision,data:caseExportData()};caseExportRequest=request;buttons();$('caseExportStatus').textContent='Preparing HTML…';
 const current=()=>caseExportRequest===request&&request.version===revision;
 try{
  const html=await window.FeedbackCaseExport.build(request.data);if(!current())return;if(typeof html!=='string')throw Error('The case exporter did not return an HTML document.');
  const filename=window.FeedbackCaseExport.filename(request.data),url=URL.createObjectURL(new Blob([html],{type:'text/html;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);$('caseExportStatus').textContent='Case HTML downloaded.';
 }catch(e){if(current())$('caseExportStatus').textContent='Export failed. '+e.message;}
 finally{if(current()){caseExportRequest=null;buttons();}}
}
$('exportCase').onclick=exportCaseHTML;
async function refreshExamples(){const items=await api('/api/examples'),old=$('examples').value;$('examples').replaceChildren(new Option('Choose a drawing',''));for(const i of items)$('examples').add(new Option(i.title,i.id));$('examples').value=old;return items;}
$('examples').onchange=async()=>{const version=++exampleRevision;++questionRevision;figureBusy=false;if(!$('examples').value){payload=null;scene=null;$('submissionPreview').hidden=true;$('previewEmpty').hidden=false;if(questionFigureSource==='example')setQuestionFigure();buttons();return;}uploadBusy=true;buttons();try{const d=await api('/api/examples/'+encodeURIComponent($('examples').value));if(version===exampleRevision){$('file').value='';$('taskFigure').value='';$('task').value=d.question?.text||d.record.task||'';setQuestionFigure(d.question?.image||'','example');load(d);$('uploadStatus').textContent='Example ready. Add an explanation if you want, then start feedback.';}}catch(e){$('uploadStatus').textContent=e.message;}finally{uploadBusy=false;buttons();}};
function dataURL(file){return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=()=>reject(Error('The picture could not be read.'));r.readAsDataURL(file);});}
$('taskFigure').onchange=async()=>{
 const file=$('taskFigure').files[0],version=++questionRevision;if(!file){figureBusy=false;setQuestionFigure();buttons();return;}
 if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>10*1024*1024){$('taskFigure').value='';$('uploadStatus').textContent='Choose a PNG, JPEG or WebP task figure smaller than 10 MB.';return;}
 figureBusy=true;buttons();
 try{const image=await dataURL(file);if(version===questionRevision){setQuestionFigure(image,'upload');$('uploadStatus').textContent=payload||$('file').files[0]?'Task figure ready. Start feedback when you are ready.':'Task figure ready. Add your own diagram below.';}}
 catch(e){if(version===questionRevision){$('taskFigure').value='';$('uploadStatus').textContent=e.message;}}
 finally{if(version===questionRevision){figureBusy=false;buttons();}}
};
$('clearTaskFigure').onclick=()=>{++questionRevision;figureBusy=false;$('taskFigure').value='';setQuestionFigure();buttons();};
$('task').oninput=renderTaskContext;
$('file').onchange=async()=>{const file=$('file').files[0];if(!file)return;const version=++exampleRevision;payload=null;scene=null;$('examples').value='';try{const image=await dataURL(file);if(version!==exampleRevision)return;$('submissionPreview').src=image;$('submissionPreview').hidden=false;$('previewEmpty').hidden=true;$('previewCaption').textContent=file.name;$('uploadStatus').textContent='Diagram ready. Start feedback when you are ready.';}catch(e){if(version===exampleRevision)$('uploadStatus').textContent=e.message;}};
$('submitImage').onclick=async()=>{
 if(figureBusy||chatBusy||uploadBusy)return;const file=$('file').files[0];if(!file&&!payload){$('uploadStatus').textContent='Choose a PNG, JPEG, or WebP diagram, or an example first.';return;}
 if($('goals').value.split('\n').filter(s=>s.trim()).length>5){$('uploadStatus').textContent='Use up to five learning requirements, one per line.';return;}
 if(file&&file.size>10*1024*1024){$('uploadStatus').textContent='Please use an image smaller than 10 MB.';return;}
 const question=currentQuestion();
 if(!file){load({...payload,question});$('questionContext').open=false;showScreen('feedback');await requestFeedback('submission');return;}
 let reconstructed=false;uploadBusy=true;stop();buttons();$('uploadStatus').textContent='Reading your diagram… This can take a few minutes.';
 try{const job=await api('/api/reconstruct',{image:await dataURL(file),task:question.text,question_image:question.image});let result;do{await new Promise(r=>setTimeout(r,2000));result=await api('/api/jobs/'+job.id)}while(result.status==='running');if(result.status==='failed')throw Error(result.error);load({...result.payload,question});$('questionContext').open=false;reconstructed=true;$('examples').value='';$('uploadStatus').textContent='Your diagram is ready.';showScreen('feedback');}
 catch(e){$('uploadStatus').textContent='Could not finish this diagram. '+e.message;}
 finally{uploadBusy=false;buttons();}if(reconstructed)await requestFeedback('submission');
};
async function requestFeedback(trigger,text='',intent='dialogue'){
if(!scene||chatBusy||uploadBusy||revisionAuth||(trigger==='workspace-complete'&&!editEnabled))return;
const hintTurns=feedbackTurns.at(-1)?.hint_turns_remaining??(feedbackTurns.at(-1)?.hint_request_pending?2:0);
if(trigger==='message'&&intent==='hint'&&hintTurns){$('chatStatus').textContent=`Please answer the Dialogue question for ${hintTurns} more ${hintTurns===1?'turn':'turns'}, then try again.`;$('chatInput').focus();return;}
if(trigger==='message'&&feedbackSession&&FeedbackWorkflow.submissionRequired(text,intent,draftSnapshot(),committed)){showSubmissionNotice();return;}
clearSubmissionNotice();returnToDraft();clearFeedbackCue();chatBusy=true;buttons();const version=revision,candidate=FeedbackWorkflow.snapshotForFeedback(trigger,draftSnapshot(),committed);
const revisionReason=trigger==='workspace-complete'?$('revisionReason').value.trim():'';
if(trigger==='submission'&&initialExplanation===null)initialExplanation=candidate.explanation;
let studentBubble;
if(text){studentBubble=message(text,'user');$('chatInput').value='';}else if(trigger!=='submission')studentBubble=message(['I have finished my changes. Please review my diagram.',revisionReason&&'My reason: '+revisionReason].filter(Boolean).join(' '),'user');
if(studentBubble){studentBubble.interactionEntry.trigger=trigger;if(trigger==='workspace-complete'){studentBubble.interactionEntry.revision_reason=revisionReason;studentBubble.interactionEntry.submitted_snapshot=G.copy(candidate);}}
$('chatStatus').textContent=trigger==='message'?'Thinking with you…':'Reviewing your work and preparing feedback…';
try{const response=await api('/api/feedback',{trigger,session_id:feedbackSession,source_id:payload.record.id,original_scene:initial,scene:candidate.scene,explanation:candidate.explanation,edits:candidate.edits,task:$('task').value,goals:$('goals').value.split('\n').map(s=>s.trim()).filter(Boolean),selected_id:selected,message:text,intent,revision_reason:revisionReason,...(trigger==='submission'?{question_image:questionFigure}:{})});
if(version!==revision)return;feedbackSession=response.session_id;if(trigger!=='message')committed=G.copy(candidate);if(studentBubble)studentBubble.interactionEntry.drawing_version=response.drawing_version;const turn={...response,trigger,student:text,revision_reason:revisionReason,submitted_snapshot:G.copy(candidate),at:new Date().toISOString()};feedbackTurns.push(turn);conversation.push({role:'user',content:text||trigger},{role:'assistant',content:response.content});updateFeedbackHeader(response);if(trigger==='workspace-complete'&&!awaitingRevisionReason)$('revisionReason').value='';if(response.response_mode!=='dialogue')fit();feedbackMessage(response,candidate,trigger);$('chatStatus').textContent=awaitingRevisionReason?'Explain why your ideas changed.':response.stage==='complete'?'You can finish here or return with another question.':editEnabled?'Make your changes on the canvas, then select Review changes.':response.stage==='dialogue'?'Ask a further question, or finish here.':'Share your thinking about the diagram.';
}catch(e){if(version===revision){message(e.message,'assistant',true).interactionEntry.trigger=trigger;if(e.message.includes('session is unavailable')){feedbackSession='';committed=null;editEnabled=false;awaitingRevisionReason=false;}$('chatStatus').textContent='Your previous feedback is unchanged. Please retry.';if(text)$('chatInput').value=text;}}
finally{chatBusy=false;updateDraft();buttons();}}
async function chat(text,intent='dialogue'){if(!text.trim()||!feedbackSession)return;await requestFeedback('message',text,intent);}
$('reviewChanges').onclick=()=>requestFeedback(feedbackSession?'workspace-complete':'submission');$('explanation').oninput=()=>{if(scene)updateDraft();};

$('chatForm').onsubmit=e=>{e.preventDefault();chat($('chatInput').value)};$('chatInput').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();chat($('chatInput').value)}};for(const b of document.querySelectorAll('[data-ask]'))b.onclick=()=>chat(b.dataset.ask,b.dataset.intent||'dialogue');
document.querySelector('[data-intent="begin_revision"]').onclick=beginRevision;
function restoreSavedCase(bundle){
 const saved=bundle.case,data=bundle.payload,state=bundle.state||{},workspace=saved?.workspace_state||{};
 if(!data?.scene||!saved?.original_model||!saved.current_draft?.scene||!Array.isArray(saved.interaction_log))throw Error('The saved case is incomplete and could not be restored.');
 const turns=G.copy(saved.feedback_turns||[]),first=turns[0],last=turns.at(-1)||{};
 const requirements=state.learning_requirements??workspace.learning_requirements??(state.goals_configured===false?[]:(first?.criteria||[]).map(item=>item.label));
 $('task').value=saved.question?.text??data.question?.text??data.record.task??'';$('goals').value=requirements.join('\n');$('explanation').value=saved.current_draft.explanation||'';
 load({...data,record:saved.source||data.record,question:saved.question||data.question,original:saved.original_image||data.original,provenance:saved.provenance||data.provenance});
 initial=G.copy(saved.original_model);scene=G.copy(saved.current_draft.scene);anchors=G.anchors(scene);committed=G.copy(saved.committed_work);
 feedbackSession=state.session_id||saved.feedback_session||'';feedbackTurns=turns;reviewRows=G.copy(saved.overall_feedback||last.review||[]);
 editEvents=G.copy(saved.current_draft.edits||[]);conversation=G.copy(saved.conversation||[]);interactionLog=G.copy(saved.interaction_log);
 initialExplanation=state.initial_explanation??workspace.initial_explanation??first?.submitted_snapshot?.explanation??'';
 currentDrawingVersion=state.drawing_version??last.drawing_version??1;editEnabled=(state.edit_enabled??workspace.edit_enabled??false)===true;
 awaitingRevisionReason=(state.awaiting_revision_reason??workspace.awaiting_revision_reason??last.awaiting_revision_reason)===true;
 $('revisionReason').value=state.revision_reason??workspace.revision_reason??[...turns].reverse().find(turn=>turn.trigger==='workspace-complete')?.revision_reason??'';
 $('learningGoal').textContent=last.learning_goal||requirements.join('\n');$('modelVersion').textContent='Submitted diagram '+currentDrawingVersion;$('sceneTitle').textContent=scene.title;
 $('messages').replaceChildren();for(const entry of interactionLog)renderInteraction(entry);
 $('questionContext').open=false;showScreen('feedback');fit();setView(false);draw();updateDraft();$('messages').scrollTop=$('messages').scrollHeight;
 $('chatStatus').textContent=awaitingRevisionReason?'Explain why your ideas changed.':'Your saved feedback and draft have been restored.';
}
async function resumeSavedCase(){
 const response=await fetch('/api/resume-case');if(response.status===204||response.status===404)return false;
 if(!response.ok)throw Error('The saved case could not be restored.');restoreSavedCase(await response.json());return true;
}
async function startWorkspace(){
 showScreen('submission');uploadBusy=true;buttons();
 try{await resumeSavedCase();}catch(e){$('uploadStatus').textContent=e.message;}
 finally{uploadBusy=false;buttons();}
 try{const items=await refreshExamples(),requested=new URLSearchParams(location.search).get('example'),chosen=items.find(item=>item.id===requested);if(chosen&&!scene&&!uploadBusy){$('examples').value=chosen.id;await $('examples').onchange();}}
 catch(e){$('uploadStatus').textContent='The local service could not load the examples. '+e.message;}
}
startWorkspace();
