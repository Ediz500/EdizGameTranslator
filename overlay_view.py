"""OBS Browser Source view: stable DOM blocks, independent read clocks, DOM ack."""
OVERLAY_HTML=r'''<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
html,body{margin:0;background:transparent;overflow:hidden;width:100%;height:100%;font-family:"Segoe UI",Arial,sans-serif}
#subs{position:absolute;bottom:10%;left:10%;width:80%;display:flex;flex-direction:column;gap:10px;align-items:center;pointer-events:none}
.block{box-sizing:border-box;color:#fff;background:rgba(8,14,24,.86);border:1px solid rgba(164,213,239,.24);border-radius:10px;padding:9px 18px 7px;max-width:100%;min-width:18%;box-shadow:0 2px 14px #0005;text-shadow:0 2px 3px #000;text-align:center}
.speaker{font-size:.5em;color:#8edbcf;font-weight:650;text-align:left;margin-bottom:3px}
.words{font-weight:650;line-height:1.22;overflow-wrap:anywhere;white-space:pre-wrap}
.meta{display:flex;gap:8px;align-items:center;color:#b0c0cd;font-size:12px;padding-top:6px}
.track{height:2px;background:#ffffff24;flex:1}.fill{height:100%;background:#7ad9c7;transform-origin:left}.timer{min-width:34px;text-shadow:none}
</style></head><body><div id="subs"></div><script>
const nodes=new Map(),reported=new Set(),root=document.getElementById('subs');let generation='',frames=[];
const USE_SSE=false;
function reset(){nodes.clear();reported.clear();root.replaceChildren();frames=[]}
async function ack(ids,g){try{const r=await fetch('/ack',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({generation:g,ids})});if(r.ok&&g===generation)ids.forEach(id=>reported.add(id))}catch(e){}}
function apply(s){
 if(s.generation!==generation){reset();generation=s.generation}
 root.style.bottom=s.bottom+'%';root.style.fontSize=s.font+'px';
 const ids=new Set(s.blocks.map(b=>b.id)),ackIds=[];
 for(const [id,n] of nodes)if(!ids.has(id)){n.box.remove();nodes.delete(id)}
 frames=s.blocks.map(b=>({...b,received:performance.now()}));
 for(const b of s.blocks){let n=nodes.get(b.id);if(!n){
   const box=document.createElement('div');box.className='block';
   const speaker=document.createElement('div');speaker.className='speaker';speaker.textContent=b.speaker||'';speaker.hidden=!b.speaker;
   const words=document.createElement('div');words.className='words';words.textContent=b.text;
   const meta=document.createElement('div');meta.className='meta';
   const track=document.createElement('div');track.className='track';const fill=document.createElement('div');fill.className='fill';track.append(fill);
   const timer=document.createElement('span');timer.className='timer';meta.append(track,timer);box.append(speaker,words,meta);root.append(box);
   n={box,fill,timer};nodes.set(b.id,n)
 }if(!reported.has(b.id))ackIds.push(b.id)}
 const g=generation;
 if(ackIds.length&&document.visibilityState==='visible')requestAnimationFrame(()=>requestAnimationFrame(()=>{if(g===generation)ack(ackIds,g)}));
}
async function tick(){try{
 const r=await fetch('/state',{cache:'no-store'});if(!r.ok)throw Error('offline');apply(await r.json());
}catch(e){reset()}setTimeout(tick,100)}
function start(){if(USE_SSE&&window.EventSource){
 const events=new EventSource('/events');
 events.onmessage=e=>{try{apply(JSON.parse(e.data))}catch(e){reset()}};
 events.onerror=()=>{events.close();reset();tick()};
}else tick()}
function animate(){for(const b of frames){const n=nodes.get(b.id);if(!n)continue;
 let rem=Math.max(0,b.remaining-(b.started===null?0:(performance.now()-b.received)/1000*b.speed));
 n.fill.style.transform='scaleX('+Math.min(1,rem/b.duration)+')';n.timer.textContent=rem.toFixed(1)+' s';
}requestAnimationFrame(animate)}start();animate();
</script></body></html>'''
