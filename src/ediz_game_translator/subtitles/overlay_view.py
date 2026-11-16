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
let generation='',nodes=new Map(),latest=null,poll=null;
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
 latest=data;const oldGeneration=generation;generation=data.generation;
 if(oldGeneration!==generation){for(const n of nodes.values())n.remove();nodes.clear()}
 const ids=new Set(data.blocks.map(b=>b.id)),removed=[];
 for(const [id,n] of nodes){if(!ids.has(id)){n.remove();nodes.delete(id);removed.push(id)}}
 for(const b of data.blocks){let n=nodes.get(b.id);if(!n){n=document.createElement('div');n.className='block';
 const name=document.createElement('div');name.className='name';const text=document.createElement('div');text.className='dialogue';
 n.append(name,text);document.body.append(n);nodes.set(b.id,n)}position(n,b,data.style)}
 const gen=generation;
 requestAnimationFrame(()=>requestAnimationFrame(()=>{if(gen===generation)
 fetch('/ack',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({generation:gen,ids:[...ids],removed})}).catch(()=>{})}));
}
addEventListener('resize',()=>{if(latest)for(const b of latest.blocks)position(nodes.get(b.id),b,latest.style)});
async function tick(){try{const r=await fetch('/state',{cache:'no-store'});if(r.ok)render(await r.json())}catch(_){}finally{poll=setTimeout(tick,100)}}
if(USE_SSE){const stream=new EventSource('/events');stream.onmessage=e=>{if(poll){clearTimeout(poll);poll=null}render(JSON.parse(e.data))};
stream.onerror=()=>{stream.close();if(!poll)tick()}}else tick();
</script></body></html>'''
