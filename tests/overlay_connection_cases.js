// Execute the shipped overlay script with controlled DOM, network and time.
// No browser package, network, model, or npm dependencies.
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const html=fs.readFileSync(0,'utf8'),script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
class Element{
 constructor(){this.style={};this.children=[];this.textContent='';this.clientHeight=100;this.scrollHeight=0;this.clientWidth=100;this.scrollWidth=0}
 append(...nodes){for(const n of nodes){n.parent=this;this.children.push(n)}}
 remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this)}
 set textContent(value){this._text=value;this.writes=(this.writes||0)+1}get textContent(){return this._text}
 get firstChild(){return this.children[0]}get lastChild(){return this.children.at(-1)}
}
function fixture(generation,id,text){return {generation,style:{font_size:36,alignment:'center',show_speaker:true,speaker_color:'#50E2BE'},blocks:id===null?[]:[{id,text,speaker:'Scout',mask_rect:[.1,.7,.9,.9],source_size:[1920,1080]}]}}
async function harness(sse,frameMs=16){
 let now=0,next=0;const timers=new Map(),requests=[],streams=[],acks=[],listeners={},body=new Element();
 function timer(fn,delay,interval=0){const id=++next;timers.set(id,{fn,due:now+delay,interval});return id}
 function fetch(url,options={}){
  if(url==='/ack'){acks.push(JSON.parse(options.body));return Promise.resolve({ok:true})}
  return new Promise((resolve,reject)=>{
   const req={resolve,reject,options,ignoreAbort:false};requests.push(req);
   options.signal?.addEventListener('abort',()=>{if(!req.ignoreAbort)reject(new Error('AbortError'))},{once:true});
  });
 }
 class EventSource{
  constructor(){this.closed=false;streams.push(this)}close(){this.closed=true}
  emit(data){this.onmessage({data:typeof data==='string'?data:JSON.stringify(data)})}
  fail(){this.onerror()}
 }
 const context=vm.createContext({document:{body,createElement:()=>new Element()},innerWidth:1920,innerHeight:1080,
  performance:{now:()=>now},AbortController,fetch,EventSource,console,
  setTimeout:(fn,delay)=>timer(fn,delay),clearTimeout:id=>timers.delete(id),
  setInterval:(fn,delay)=>timer(fn,delay,delay),clearInterval:id=>timers.delete(id),
  requestAnimationFrame:fn=>timer(fn,frameMs),addEventListener:(type,fn)=>listeners[type]=fn});
 vm.runInContext(script.replace('const USE_SSE=false;','const USE_SSE='+sse+';'),context);
 async function flush(){for(let i=0;i<20;i++)await Promise.resolve()}
 async function advance(ms){
  const end=now+ms;let count=0;
  while(true){await flush();const found=[...timers].filter(([,t])=>t.due<=end).sort((a,b)=>a[1].due-b[1].due)[0];
   if(!found)break;assert.ok(++count<10000,'timer loop');const [id,t]=found;now=t.due;timers.delete(id);
   if(t.interval)timers.set(id,{...t,due:now+t.interval});t.fn();}
  now=end;await flush();
 }
 async function reply(index,data,status=200){requests[index].resolve({ok:status>=200&&status<300,json:async()=>data});await flush()}
 async function reject(index){requests[index].reject(new Error('Connection lost'));await flush()}
 function texts(){return body.children.map(n=>n.lastChild.textContent)}
 return {advance,reply,reject,requests,streams,acks,texts,body,listeners,flush,context};
}
const cases={
 async measured_visual_geometry_resizes_without_rewrapping_and_expires(){
  const h=await harness(true),data=fixture('s',1,'İki satırlı metin.');
  Object.assign(data.blocks[0],{mask_rect:[.4,.7,.6,.9],body_rect:[.42,.8,.58,.85],name_rect:[.42,.75,.58,.79],visual_font_size:36,display_lines:['İki satırlı','metin.'],name_lines:['Scout']});
  h.streams[0].emit(data);const node=h.body.children[0],text=node.lastChild;
  assert.equal(text.textContent,'İki satırlı\nmetin.');assert.equal(text.style.fontSize,'36px');
  h.context.innerWidth=1280;h.context.innerHeight=720;h.listeners.resize();
  assert.equal(text.style.fontSize,'24px');assert.equal(text.textContent,'İki satırlı\nmetin.');
  assert.ok(Math.abs(parseFloat(node.style.width)-256)<.01);
  await h.advance(1600);assert.equal(h.body.children.length,0);h.listeners.resize();assert.equal(h.body.children.length,0);
 },
 async switching_to_fixed_restores_legacy_flow_styles(){
  const h=await harness(true),data=fixture('s',1,'A');
  Object.assign(data.blocks[0],{body_rect:[.2,.7,.8,.85],name_rect:[.2,.6,.8,.7],visual_font_size:36,display_lines:['A'],name_lines:['Scout']});
  h.streams[0].emit(data);h.streams[0].emit(fixture('s',1,'B'));
  const text=h.body.children[0].lastChild;assert.equal(text.style.position,'static');
  assert.equal(text.style.whiteSpace,'pre-wrap');assert.equal(text.style.overflowWrap,'anywhere');assert.equal(text.textContent,'B');
 },
 async unchanged_geometry_does_not_rewrite_dom_on_ocr_noise(){
  const h=await harness(true),data=fixture('s',1,'A');
  Object.assign(data.blocks[0],{body_rect:[.2,.7,.8,.85],name_rect:[.2,.6,.8,.7],visual_font_size:36,display_lines:['A'],name_lines:['Scout']});
  h.streams[0].emit(data);const text=h.body.children[0].lastChild,writes=text.writes;
  for(let i=0;i<10;i++){data.blocks[0].bounds=[.2,.7+i*.0001,.8,.9];h.streams[0].emit(data)}
  assert.equal(text.writes,writes);assert.deepEqual(h.texts(),['A']);
 },
 async polling_error_clears_and_recovers(){
  const h=await harness(false);await h.reply(0,fixture('s',1,'A'));assert.deepEqual(h.texts(),['A']);
  await h.advance(100);await h.reject(1);await h.advance(1600);assert.deepEqual(h.texts(),[]);
  const latest=h.requests.length-1;await h.reply(latest,fixture('s',2,'B'));assert.deepEqual(h.texts(),['B']);
  h.listeners.resize();assert.deepEqual(h.texts(),['B']);
 },
 async hung_poll_has_deadline_and_retries(){
  const h=await harness(false);await h.reply(0,fixture('s',1,'A'));await h.advance(1700);
  assert.deepEqual(h.texts(),[]);assert.ok(h.requests[1].options.signal.aborted);assert.ok(h.requests.length>=3);
 },
 async silent_sse_expires_and_falls_back(){
  const h=await harness(true);h.streams[0].emit(fixture('s',1,'A'));await h.advance(1600);
  assert.deepEqual(h.texts(),[]);assert.ok(h.streams[0].closed);assert.ok(h.requests.length);
  await h.reply(h.requests.length-1,fixture('s',2,'B'));assert.deepEqual(h.texts(),['B']);
 },
 async sse_without_first_snapshot_switches_to_polling(){
  const h=await harness(true);await h.advance(1600);assert.ok(h.streams[0].closed);assert.ok(h.requests.length);
  await h.reply(0,fixture('s',2,'B'));assert.deepEqual(h.texts(),['B']);
 },
 async sse_error_rejects_late_old_events(){
  const h=await harness(true),old=h.streams[0];old.emit(fixture('old-session',1,'A'));old.fail();await h.flush();
  assert.deepEqual(h.texts(),[]);await h.reply(0,fixture('new-session',2,'B'));old.emit(fixture('old-session',1,'A'));
  assert.deepEqual(h.texts(),['B']);
 },
 async healthy_heartbeats_do_not_blank_stable_caption(){
  const h=await harness(true);h.streams[0].emit(fixture('s',1,'A'));
  for(let i=0;i<10;i++){await h.advance(500);h.streams[0].emit(fixture('s',1,'A'));assert.deepEqual(h.texts(),['A'])}
  assert.equal(h.streams[0].closed,false);assert.equal(h.requests.length,0);
 },
 async healthy_heartbeats_preserve_ack_with_slow_renderer(){
  const h=await harness(true,400);h.streams[0].emit(fixture('s',1,'A'));
  for(let i=0;i<6;i++){await h.advance(500);h.streams[0].emit(fixture('s',1,'A'))}
  assert.deepEqual(h.texts(),['A']);assert.ok(h.acks.some(a=>a.ids.includes(1)));
 },
 async malformed_state_fails_closed(){
  const h=await harness(true);h.streams[0].emit(fixture('s',1,'A'));h.streams[0].emit('{bad json');await h.flush();
  assert.deepEqual(h.texts(),[]);assert.ok(h.streams[0].closed);
  await h.reply(0,{});assert.deepEqual(h.texts(),[]);
 },
 async http_503_does_not_preserve_previous_dom(){
  const h=await harness(false);await h.reply(0,fixture('s',1,'A'));await h.advance(100);
  await h.reply(1,{},503);assert.deepEqual(h.texts(),[]);h.listeners.resize();assert.deepEqual(h.texts(),[]);
 },
 async delayed_old_http_response_cannot_resurrect_after_expiry(){
  const h=await harness(false);await h.reply(0,fixture('s',1,'A'));await h.advance(100);h.requests[1].ignoreAbort=true;
  await h.advance(1600);assert.deepEqual(h.texts(),[]);assert.ok(h.requests.length>=3);
  await h.reply(h.requests.length-1,fixture('s',2,'B'));await h.reply(1,fixture('s',1,'A'));
  assert.deepEqual(h.texts(),['B']);
 },
 async old_animation_ack_is_fenced_on_same_session_recovery(){
  const h=await harness(true);h.streams[0].emit(fixture('s',1,'A'));h.streams[0].fail();
  await h.reply(0,fixture('s',2,'B'));await h.advance(40);
  assert.ok(h.acks.length);assert.ok(h.acks.every(a=>a.ids.length===1&&a.ids[0]===2));
 },
 async reconnect_empty_state_keeps_text_and_mask_removed(){
  const h=await harness(true);h.streams[0].emit(fixture('s',1,'A'));await h.advance(1600);
  await h.reply(0,fixture('new',null,''));assert.deepEqual(h.texts(),[]);h.listeners.resize();assert.equal(h.body.children.length,0);
 }
};
(async()=>{const name=process.argv[2];assert.ok(cases[name],name);await cases[name]();console.log(name+' OK')})().catch(e=>{console.error(e);process.exitCode=1});
