"""Transparent output: opaque black masks, separately colored names, no clocks."""
OVERLAY_HTML = r'''<!doctype html><html lang="tr"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ediz · Canlı altyazı</title><style>
html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}
.block{position:absolute;box-sizing:border-box;background:#000000;color:#FFFFFF;
display:flex;flex-direction:column;justify-content:center;overflow:hidden;padding:8px 18px;
font-family:'Segoe UI',sans-serif;line-height:1.28;white-space:pre-wrap;overflow-wrap:anywhere}
.name{color:#50E2BE;font-weight:600;font-size:.7em;flex-shrink:0}.dialogue{color:#FFFFFF;font-weight:600}
</style><body><script>
const USE_SSE=false;
// A snapshot is a short lease, never permission to display forever.
const STATE_TTL_MS=1500,REQUEST_TIMEOUT_MS=800;
let generation='',nodes=new Map(),latest=null,poll=null,stream=null,inflight=null;
let transportEpoch=0,renderEpoch=0,lastStateAt=null;
function clearView(){
 renderEpoch++;latest=null;generation='';lastStateAt=null;
 for(const n of nodes.values())n.remove();nodes.clear();
}
function position(node,b,s){
 const [sw,sh]=b.source_size||[1920,1080],k=Math.min(innerWidth/sw,innerHeight/sh),
 ox=(innerWidth-sw*k)/2,oy=(innerHeight-sh*k)/2,r=b.mask_rect;
 Object.assign(node.style,{left:(ox+r[0]*sw*k)+'px',top:(oy+r[1]*sh*k)+'px',
 width:((r[2]-r[0])*sw*k)+'px',height:((r[3]-r[1])*sh*k)+'px',
 padding:(8*k*sw/1920)+'px '+(18*k*sw/1920)+'px',
 textAlign:s.alignment,fontSize:(s.font_size*k*sw/1920*(b.font_scale||1))+'px'});
 const name=node.firstChild;name.textContent=s.show_speaker&&b.speaker?b.speaker:'';
 name.style.display=name.textContent?'block':'none';name.style.color=s.speaker_color;
 node.lastChild.textContent=b.text;
 let size=parseFloat(node.style.fontSize);
 while(size>8&&(node.scrollHeight>node.clientHeight||node.scrollWidth>node.clientWidth)){
   size--;node.style.fontSize=size+'px';
 }
}
function render(data){
 if(!data||typeof data.generation!=='string'||!Array.isArray(data.blocks)||data.blocks.length>3||!data.style)
   throw new Error('Invalid overlay snapshot');
 for(const b of data.blocks)if(!Number.isInteger(b.id)||typeof b.text!=='string'||!Array.isArray(b.mask_rect)||b.mask_rect.length!==4)
   throw new Error('Invalid overlay block');
 latest=data;const revision=renderEpoch,oldGeneration=generation;generation=data.generation;
 if(oldGeneration!==generation){for(const n of nodes.values())n.remove();nodes.clear()}
 const ids=new Set(data.blocks.map(b=>b.id)),removed=[];
 for(const [id,n] of nodes){if(!ids.has(id)){n.remove();nodes.delete(id);removed.push(id)}}
 for(const b of data.blocks){let n=nodes.get(b.id);if(!n){n=document.createElement('div');n.className='block';
 const name=document.createElement('div');name.className='name';const text=document.createElement('div');text.className='dialogue';
 n.append(name,text);document.body.append(n);nodes.set(b.id,n)}position(n,b,data.style)}
 lastStateAt=performance.now();const gen=generation;
 requestAnimationFrame(()=>requestAnimationFrame(()=>{if(gen!==generation||revision!==renderEpoch||[...ids].some(id=>!nodes.has(id)))return;
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),REQUEST_TIMEOUT_MS);
 fetch('/ack',{method:'POST',signal:controller.signal,headers:{'Content-Type':'application/json'},
 body:JSON.stringify({generation:gen,ids:[...ids],removed:removed.filter(id=>!nodes.has(id))})}).catch(()=>{}).finally(()=>clearTimeout(timer));}));
}
addEventListener('resize',()=>{if(latest)for(const b of latest.blocks)position(nodes.get(b.id),b,latest.style)});
function startPolling(){
 transportEpoch++;if(stream){stream.close();stream=null}
 if(poll!==null){clearTimeout(poll);poll=null}if(inflight){inflight.abort();inflight=null}
 clearView();tick(transportEpoch);
}
async function tick(epoch){
 if(epoch!==transportEpoch)return;
 const controller=new AbortController(),began=performance.now();inflight=controller;
 const timer=setTimeout(()=>controller.abort(),REQUEST_TIMEOUT_MS);
 try{
  const r=await fetch('/state',{cache:'no-store',signal:controller.signal});
  if(!r.ok)throw new Error('Overlay request failed');
  const data=await r.json();
  if(epoch!==transportEpoch||controller.signal.aborted||performance.now()-began>=REQUEST_TIMEOUT_MS)return;
  render(data);
 }catch(_){if(epoch===transportEpoch)clearView()}
 finally{
  clearTimeout(timer);if(inflight===controller)inflight=null;
  if(epoch===transportEpoch)poll=setTimeout(()=>{poll=null;tick(epoch)},100);
 }
}
if(USE_SSE){
 lastStateAt=performance.now();const epoch=++transportEpoch;stream=new EventSource('/events');
 stream.onmessage=e=>{if(epoch!==transportEpoch)return;
  try{render(JSON.parse(e.data))}catch(_){startPolling()}};
 stream.onerror=()=>{if(epoch===transportEpoch)startPolling()};
}else startPolling();
setInterval(()=>{
 if(lastStateAt!==null&&performance.now()-lastStateAt>=STATE_TTL_MS)startPolling();
},100);

</script></body></html>'''
