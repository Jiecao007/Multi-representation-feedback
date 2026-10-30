/* The compact chat keeps one diagram reference and a single visible response. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../app/app.js'),'utf8');
function setup(){
 const messages=[],cues=[];
 const context={G:{copy:value=>JSON.parse(JSON.stringify(value))},message:(...args)=>{messages.push(args);return {interactionEntry:{},classList:{add(){}}};},showDiagramReference:(...args)=>cues.push(args)};
 vm.createContext(context);
 vm.runInContext(source.slice(source.indexOf('function feedbackMessage'),source.indexOf('function showScreen')),context);
 return {context,messages,cues};
}
const snapshot={scene:{objects:[{id:'r1'}]}};
const response={acknowledgment:'You drew two branch paths.',acknowledgment_ids:['r1','r2'],
 follow_up:'How do they represent parallel branches?',focus_ids:['r1'],next_focus_kind:'extension',
 drawing_version:1,visual_action:'highlight',visual_delivery:'automatic'};
{
 const {context,messages,cues}=setup();context.feedbackMessage(response,snapshot);
 assert.equal(messages.length,1);
 assert.equal(messages[0][0],response.acknowledgment+' '+response.follow_up);
 assert.deepEqual(Array.from(messages[0][3]),['r1','r2']);
 assert.equal(messages[0][5],snapshot);assert.equal(messages[0][6],1);
 assert.deepEqual(Array.from(cues[0][0]),['r1','r2']);assert.equal(cues[0][3],'response');
}
{
 const {context,messages,cues}=setup();
 context.feedbackMessage({content:'You can finish here.',follow_up:'You can finish here.',acknowledgment:'',
 focus_ids:[],next_focus_kind:'none',response_mode:'dialogue',drawing_version:2,visual_action:'none'},snapshot);
 assert.equal(messages.length,1);assert.equal(messages[0][3].length,0);assert.equal(messages[0][6],2);
 assert.equal(cues.length,0);
}
{
 const {context,messages,cues}=setup();
 const paths=[{label:'First route',steps:[{relation_id:'r1',direction:'forward'},{relation_id:'r2',direction:'forward'}]}];
 context.feedbackMessage({content:'Watch the current follow this route. Which object does it pass through?',
 focus_ids:['r1'],next_focus_kind:'gap',drawing_version:2,visual_action:'trace',visual_delivery:'automatic',
 mechanism_paths:paths,mechanism_condition:'When the route is open'},snapshot);
 assert.equal(cues.length,1);assert.equal(cues[0][4],'trace');
 assert.equal(cues[0][7].paths,paths);assert.equal(cues[0][7].condition,'When the route is open');
 assert.equal(messages[0][7],'trace');assert.equal(messages[0][8].paths,paths);
}
{
 const {context,messages,cues}=setup();
 const paths=[{label:'Current route',steps:[{relation_id:'wire1',direction:'forward'},{relation_id:'wire2',direction:'backward'}]}];
 context.feedbackMessage({content:'Watch this current route.',focus_ids:[],drawing_version:2,
 visual_action:'trace',visual_delivery:'automatic',mechanism_paths:paths,mechanism_condition:'If the circuit is closed'},snapshot);
 assert.deepEqual(Array.from(cues[0][0]),['wire1','wire2']);assert.equal(cues[0][4],'trace');
 assert.deepEqual(Array.from(messages[0][3]),['wire1','wire2']);assert.equal(messages[0][5],snapshot);
 context.feedbackMessage({content:'Think about the relationship.',focus_ids:[],drawing_version:2,
 visual_action:'trace',visual_delivery:'none',mechanism_paths:paths},snapshot);
 assert.equal(cues.length,1);assert.equal(messages[1][3].length,0);
}
{
 const context={scene:{},selected:'template-ramp',focusTone:'',focusIds:[],setView(){},updateGuidance(){},draw(){},zoomGuidance(){}};
 vm.createContext(context);vm.runInContext(source.match(/^function showGuidance.*$/m)[0],context);
 context.showGuidance(['r1'],false,false,'response');assert.equal(context.selected,'');assert.equal(context.focusTone,'response');
}
{
 const fields={guidance:{dataset:{}},zoomFocus:{},guidanceText:{}};
 const context={scene:{},anchors:{},focusIds:['r1','r2'],focusTone:'next',
 activeMechanism:{paths:[{label:'First route'},{label:'Second route'}]},
 E:{focus:()=>({ids:['r1','r2'],bounds:{},missing:[]})},G:{exportScene:()=>({})},
 object:()=>null,relation:id=>({id}),connectionName:id=>'Long connection name '+id,
 $:id=>fields[id],canvas:{classList:{toggle(){}},dataset:{}}};
 vm.createContext(context);vm.runInContext(source.slice(source.indexOf('function updateGuidance'),source.indexOf('function zoomGuidance')),context);
 context.updateGuidance();assert.equal(fields.guidanceText.textContent,'Exploring: First route · Second route');
 context.activeMechanism=null;context.updateGuidance();
 assert.equal(fields.guidanceText.textContent,'Next to consider: Long connection name r1 · Long connection name r2');
}
console.log('Compact feedback: one visible paragraph, shared targets, version provenance, closure, automatic mechanism forwarding, and selection clearing passed.');
