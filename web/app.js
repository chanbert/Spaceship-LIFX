const $=id=>document.getElementById(id),audio=$('audio');
let assignments={},roleInfo={},deviceList=[],saveQueue=Promise.resolve();
let show,words={},token,session=null,seq=0,lastScene=-1,lastLine=-1,busy=false,clockBusy=false,windowStart=0,span=30,needsTimeline=true,scriptNodes=[],wordNodes=[],timelineWordNodes=[];
$('editLights').onclick=()=>$('lightSettings').showModal();
$('closeLights').onclick=()=>$('lightSettings').close();
$('lightSettings').addEventListener('click',e=>{if(e.target===$('lightSettings')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close()}});
const fmt=t=>`${Math.floor(t/60)}:${String(Math.floor(t%60)).padStart(2,'0')}`;
const precise=t=>`${fmt(t)}.${Math.floor(t%1*10)}`;
const status=(s,error=false)=>{$('status').textContent=s;$('status').hidden=!error;$('status').classList.toggle('error',error)};
async function api(path,data={}){const r=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...data,token})});const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d}
function lockSettings(on){for(const id of ['enable','discover','cap','delay'])$(id).disabled=on;$('devices').inert=on;document.querySelectorAll('.light-card').forEach(e=>e.draggable=!on)}
async function stop(){audio.pause();audio.currentTime=0;try{await api('stop')}catch(e){status(e.message,true);return}session=null;$('lightingNotice').hidden=true;lockSettings(false);$('mode').textContent='PREVIEW · NO LIGHT COMMANDS';status('Stopped · light restore commands sent');render()}
async function sync(seek=false){if(!session||clockBusy&&!seek)return;clockBusy=true;try{await api('clock',{session,seq:++seq,position:audio.currentTime,playing:!audio.paused&&!audio.seeking,seek})}catch(e){audio.pause();status(e.message,true)}finally{clockBusy=false}}
function selection(){
 const summary=$('selectionSummary');summary.replaceChildren();
 for(const [role,info] of Object.entries(roleInfo)){
  const row=document.createElement('div'),label=document.createElement('strong'),names=document.createElement('span');
  label.textContent=role+' · '+info.name;
  names.textContent=deviceList.filter(d=>assignments[d.mac]===role).map(d=>(d.label||d.mac)+(d.zone_count>1?' ('+d.zone_count+' zones)':'')+(d.online===false?' · offline':'')).join(', ')||'Preview only · no lights selected';
  row.append(label,names);summary.append(row);
 }

 $('fixtures').replaceChildren();
 for(const [role,info] of Object.entries(roleInfo)){
  const ds=deviceList.filter(d=>assignments[d.mac]===role),f=document.createElement('div');f.className='fixture';f.dataset.role=role;
  for(const cls of ['fixture-mount','fixture-head','fixture-beam']){const el=document.createElement('div');el.className=cls;f.append(el)}
  const level=document.createElement('span');level.className='level';level.textContent='0%';const label=document.createElement('label');label.textContent=`${role} · ${info.name}`;
  const count=document.createElement('small');count.textContent=ds.length?`${ds.length} light${ds.length===1?'':'s'}`:'Preview only';label.append(document.createElement('br'),count);f.title=ds.map(d=>d.label||d.mac).join(', ')||'No lights assigned';f.append(level,label);
  const strips=document.createElement('div');strips.className='device-zones';
  for(const d of ds){
   const item=document.createElement('div'),name=document.createElement('small'),strip=document.createElement('div');
   name.textContent=(d.label||d.mac)+(d.zone_count>1?' · '+d.zone_count+' zones':d.zone_count===1?' · single zone':' · zone count unavailable');
   strip.className='zone-strip';strip.dataset.mac=d.mac;
   for(let i=0;i<(d.zone_count||1);i++){const cell=document.createElement('span');cell.title='Zone '+(i+1);strip.append(cell)}
   item.append(name,strip);strips.append(item);
  }
  f.append(strips);$('fixtures').append(f);
 }
}
function saveMapping(){
 const snapshot={...assignments};$('mappingStatus').textContent='Saving assignments…';
 saveQueue=saveQueue.catch(()=>{}).then(()=>api('assignments',{assignments:snapshot})).then(()=>{$('mappingStatus').textContent='Assignments saved on this Mac.';}).catch(e=>{$('mappingStatus').textContent='Could not save: '+e.message;status(e.message,true)});
}
let pickedLight=null;
function devices(list){
 deviceList=[...list];
 for(const mac of Object.keys(assignments))if(!deviceList.some(d=>d.mac===mac))deviceList.push({mac,label:mac,online:false});
 const root=$('devices');root.replaceChildren();
 const move=(mac,role)=>{if(session||busy||!deviceList.some(d=>d.mac===mac))return;if(role)assignments[mac]=role;else delete assignments[mac];pickedLight=null;devices(deviceList);saveMapping()};
 for(const [role,name] of [['A','Tree 1'],['B','Tree 2'],['G','Ground'],['','Available lights']]){
  const zone=document.createElement('section');zone.className='light-zone'+(role?'':' available-zone');zone.dataset.role=role;
  const heading=document.createElement('h3');heading.textContent=name;zone.append(heading);
  const drop=document.createElement('button');drop.className='drop-target';drop.textContent=pickedLight?'Move selected light here':'Drag lights here';drop.setAttribute('aria-label','Move selected light to '+name);drop.onclick=()=>{if(pickedLight)move(pickedLight,role)};zone.append(drop);
  zone.ondragover=e=>{if(session||busy)return;e.preventDefault();zone.classList.add('drag-over')};zone.ondragleave=()=>zone.classList.remove('drag-over');zone.ondrop=e=>{e.preventDefault();zone.classList.remove('drag-over');move(e.dataTransfer.getData('text/plain'),role)};
  for(const d of deviceList.filter(d=>(assignments[d.mac]||'')===role)){
   const card=document.createElement('button');card.className='light-card';card.draggable=true;card.classList.toggle('picked',pickedLight===d.mac);card.setAttribute('aria-pressed',String(pickedLight===d.mac));
   const title=document.createElement('strong');title.textContent=d.label||d.mac;const detail=document.createElement('small');detail.textContent=(d.group||'')+(d.zone_count?` · ${d.zone_count} color zones`:'')+(d.online===false?' · Offline in last scan':'');card.append(title,detail);
   card.ondragstart=e=>{e.dataTransfer.setData('text/plain',d.mac);e.dataTransfer.effectAllowed='move'};
   card.onclick=()=>{pickedLight=pickedLight===d.mac?null:d.mac;devices(deviceList)};zone.append(card);
  }root.append(zone);
 }root.inert=!!session||busy;selection();
}
function seek(t){audio.currentTime=Math.max(0,Math.min(show.duration-.01,t));if($('followTimeline').checked){windowStart=Math.max(0,audio.currentTime-span*.2);needsTimeline=true}render()}
$('play').onclick=async()=>{try{if(audio.paused){await audio.play();status(session?'Playing · selected garden lights':'Playing · audio and light preview')}else{audio.pause();status('Paused')}}catch(e){status(e.message,true)}};
$('stop').onclick=stop;$('repeat').onchange=()=>audio.loop=$('repeat').checked;$('seek').oninput=()=>seek(Number($('seek').value));
audio.addEventListener('seeked',()=>sync(true));audio.addEventListener('play',()=>{sync(true);$('play').textContent='Ⅱ Pause'});audio.addEventListener('pause',()=>{sync();$('play').textContent='▶ Play'});audio.addEventListener('ended',stop);audio.addEventListener('error',()=>status('Audio could not load. Restart the local player.',true));
$('cap').oninput=()=>{$('capValue').textContent=$('cap').value+'%';needsTimeline=true};$('delay').onchange=()=>needsTimeline=true;
$('enable').onclick=async()=>{if(busy)return;busy=true;lockSettings(true);status('Checking assigned lights; refreshing network addresses if needed…');try{await saveQueue;const r=await api('start',{assignments,cap:Number($('cap').value)/100,delay:Number($('delay').value)/1000});session=r.session;seq=0;const skipped=r.skipped||[];$('lightingNotice').hidden=!skipped.length;$('lightingNotice').textContent=skipped.length?'Playing reachable lights. Skipped: '+skipped.map(d=>d.label||d.mac).join(', ')+'. Stop and enable again to retry.':'';await sync(true);$('mode').textContent='LIVE COMMANDS · ESTIMATED OUTPUT';$('lightSettings').close();status('Lights enabled · press Play when ready')}catch(e){lockSettings(false);status(e.message,true)}finally{busy=false}};
$('discover').onclick=async()=>{$('discover').disabled=true;status('Discovering lights…');try{const found=await api('discover');devices(found);status(`Discovery complete · ${found.filter(d=>d.online!==false).length} responding · no lights changed`)}catch(e){status(e.message,true)}finally{$('discover').disabled=false}};

$('zoom').onchange=()=>{span=Number($('zoom').value);windowStart=Math.max(0,audio.currentTime-span*.2);needsTimeline=true;render()};
for(const [id,sign] of [['earlier',-1],['later',1]])$(id).onclick=()=>{$('followTimeline').checked=false;windowStart=Math.max(0,Math.min(show.duration-span,windowStart+sign*span*.75));needsTimeline=true;render()};
$('followTimeline').onchange=()=>{if($('followTimeline').checked){windowStart=Math.max(0,audio.currentTime-span*.2);needsTimeline=true;render()}};
$('timelineViewport').onclick=e=>{if(e.target.closest('button'))return;const rect=$('timelineViewport').getBoundingClientRect();seek(windowStart+(e.clientX-rect.left)/rect.width*span)};
function buildScript(){scriptNodes=[];wordNodes=[];$('lines').replaceChildren();show.lines.forEach((l,i)=>{const div=document.createElement('div');div.className='line';div.tabIndex=0;const b=document.createElement('b');b.textContent=`${l.voice} · ${fmt(l.time)}`;const p=document.createElement('p');if(words[i])for(const w of words[i]){const el=document.createElement('span');el.textContent=w.text+' ';el.onclick=e=>{e.stopPropagation();seek(w.start)};p.append(el);wordNodes.push({el,...w})}else p.textContent=l.text;div.append(b,p);div.onclick=()=>seek(l.time);div.onkeydown=e=>{if(e.key==='Enter')seek(l.time)};scriptNodes.push(div);$('lines').append(div)})}
function lightingAt(t,role){let state=[225,.85,0],origin=state,start=0,duration=0,active=null;const delay=Number($('delay').value)/1000,cap=Number($('cap').value)/100;function interpolate(at){const f=duration?Math.max(0,Math.min(1,(at-start)/duration)):1;const hd=(state[0]-origin[0]+540)%360-180;return[(origin[0]+hd*f+360)%360,origin[1]+(state[1]-origin[1])*f,origin[2]+(state[2]-origin[2])*f]}for(const c of show.cues){if(c.roles&&!c.roles.includes(role))continue;const at=c.time+delay;if(at>t)break;origin=interpolate(at);state=[c.hue,c.saturation,c.brightness*cap];start=at;duration=c.fade/1000;active=c}return{state:interpolate(t),active}}

function zoneTarget(c,d,role,i){
 let h=c.hue,s=c.saturation,b=c.brightness,at=c.time||0;
 if(d.product===171){
  const phase=(i+(role==='B'?1:0)+Math.floor(at*4))%3;
  h=(h+[-25,0,30][phase]+360)%360;b*=phase===1?1:.82;
  if(phase===1&&c.brightness>.7)s*=.45;
  if(c.cue_id==='IDLE')h=(c.hue+[-35,0,35][i]+360)%360;
 }else if(role==='G'&&d.zone_count>1){
  const pos=i/Math.max(1,d.zone_count-1);
  if(c.cue_id==='IDLE'){h=[180,260,115][i%3];s=.7;b*=.8+.2*Math.sin(i*1.7)**2}
  else if(c.cue_id==='GROUND'){
   const center=at*.65%1,distance=Math.min(Math.abs(pos-center),1-Math.abs(pos-center));
   let active=distance<((c.name||'').toLowerCase().includes('goop')?.18:.12);
   if((c.name||'').toLowerCase().includes('red'))active=(i+Math.floor(at*5))%2===0;
   if(!active){h=[180,260,115][i%3];s=.7;b=.28}
  }else if(b>0){const wave=(1+Math.sin(pos*Math.PI*2-at*4))/2;h=(h+(1-wave)*35)%360;b*=.55+.45*wave}
 }
 return [h,s,Math.max(0,Math.min(1,b*Number($('cap').value)/100))];
}
function zoneAt(t,d,role,i){
 let state=[225,.85,0],origin=state,start=0,duration=0;
 const blend=at=>{const f=duration?Math.max(0,Math.min(1,(at-start)/duration)):1;
 return [(origin[0]+((state[0]-origin[0]+540)%360-180)*f+360)%360,origin[1]+(state[1]-origin[1])*f,origin[2]+(state[2]-origin[2])*f]};
 for(const c of show.cues){const at=c.time+Number($('delay').value)/1000;if(at>t)break;if(c.roles&&!c.roles.includes(role))continue;
 origin=blend(at);state=zoneTarget(c,d,role,i);start=at;duration=c.fade/1000}
 return blend(t);
}

function hsv(h,s,v){const f=n=>{const k=(n+h/60)%6;return v-v*s*Math.max(0,Math.min(k,4-k,1))};return`rgb(${[f(5),f(3),f(1)].map(x=>Math.round(x*255)).join(',')})`}
function buildTimeline(){needsTimeline=false;const root=$('timeline');root.replaceChildren();timelineWordNodes=[];const step=span<=15?2:span<=30?5:10;for(let t=Math.ceil(windowStart/step)*step;t<windowStart+span;t+=step){const x=(t-windowStart)/span*100;const label=document.createElement('span');label.className='ruler-label';label.style.left=x+'%';label.textContent=fmt(t);const grid=document.createElement('div');grid.className='gridline';grid.style.left=x+'%';root.append(grid,label)}const lanes=[];for(let i=0;i<7;i++){const lane=document.createElement('div');lane.className='lane';lane.style.top=30+i*32+'px';root.append(lane);lanes.push(lane)}
function clip(lane,start,end,cls,title,onClick){if(end<=windowStart||start>=windowStart+span)return null;const el=document.createElement('button');el.className='timeline-clip '+cls;const visibleStart=Math.max(start,windowStart),visibleEnd=Math.min(end,windowStart+span);el.style.left=(visibleStart-windowStart)/span*100+'%';el.style.width=Math.max(.1,(visibleEnd-visibleStart)/span*100)+'%';el.title=title;el.setAttribute('aria-label',title);el.onclick=e=>{e.stopPropagation();$('cueDetail').textContent=title;onClick?onClick(e,el):seek(start)};lanes[lane].append(el);return el}
show.lines.forEach(l=>{const lane={'Professor':0,'Pip':1,'Private Perkins':1,'Safety Bot':2,'Ship':2,'Aliens':2,'Professor Vex':0,'Unit-7':2}[l.voice]??0;const el=clip(lane,l.time,l.end,'speech',`${l.voice} · ${precise(l.time)} — ${precise(l.end)} · ${l.text}`);if(el){el.textContent=l.text;timelineWordNodes.push({el,start:l.time,end:l.end})}});
const soundEvents=show.sound_events||show.events.map(e=>({time:e.effect_start,end:e.effect_end,name:e.title}));soundEvents.filter(e=>!e.bed).forEach(e=>{const el=clip(3,e.time,e.end,'sfx',`${e.id||'SFX'} · ${precise(e.time)} — ${precise(e.end)} · ${e.name}`);if(el)el.textContent=e.name});
const delay=Number($('delay').value)/1000;
['G','A','B'].forEach((role,r)=>{
 const cues=show.cues.filter(c=>!c.roles||c.roles.includes(role));
 cues.forEach((c,i)=>{const start=c.time+delay,end=(cues[i+1]?.time??show.duration)+delay;const el=clip(4+r,start,end,'light',`${role} · ${precise(start)} · ${c.name} · hue ${c.hue}° · ${Math.round(c.brightness*100)}% of cap · fade ${c.fade}ms`);if(el){el.style.background=hsv(c.hue,c.saturation,.38);el.textContent=c.name}})
})
}
function render(){if(!show)return;const t=audio.currentTime;$('seek').value=t;$('clock').textContent=precise(t)+' / '+fmt(show.duration);let scene=0;show.events.forEach((e,i)=>{if(e.start<=t)scene=i});if(scene!==lastScene){lastScene=scene;document.querySelectorAll('.scene').forEach((b,i)=>b.classList.toggle('active',i===scene));}let line=-1;show.lines.forEach((l,i)=>{if(l.time<=t)line=i});if(line!==lastLine){lastLine=line;scriptNodes.forEach((el,i)=>{el.classList.toggle('active',i===line);el.classList.toggle('past',i<line)});if(line>=0){const box=$('lines'),el=scriptNodes[line];box.scrollTo({top:el.offsetTop-box.offsetTop-12,behavior:'smooth'})}}for(const w of wordNodes){w.el.classList.toggle('current-word',w.start<=t&&w.end>t);w.el.classList.toggle('spoken-word',w.end<=t)}document.querySelectorAll('.zone-strip').forEach(strip=>{
 const d=deviceList.find(d=>d.mac===strip.dataset.mac),role=assignments[d.mac];
 [...strip.children].forEach((cell,i)=>{const state=zoneAt(t,d,role,i);cell.style.background=hsv(...state);cell.title='Zone '+(i+1)+' · '+Math.round(state[2]*100)+'%'});
 });const readouts=[];let cueName='Standby';for(const role of ['G','A','B']){const {state,active}=lightingAt(t,role);if(active)cueName=active.name;const f=document.querySelector(`.fixture[data-role="${role}"]`);if(f){f.style.setProperty('--light',hsv(...state));f.querySelector('.level').textContent=Math.round(state[2]*100)+'%'}readouts.push(`${role}: ${Math.round(state[2]*100)}%`)}$('effect').textContent=cueName;$('lightReadout').textContent=readouts.join(' · ');if(t<windowStart||t>windowStart+span*.85){windowStart=Math.max(0,t-span*.2);needsTimeline=true}if(needsTimeline)buildTimeline();const x=(t-windowStart)/span*100;$('playhead').style.left=x+'%';$('playhead').style.display=x<0||x>100?'none':'block';$('playheadTime').textContent=precise(t);for(const w of timelineWordNodes)w.el.classList.toggle('current',w.start<=t&&w.end>t)}
window.addEventListener('pagehide',()=>{if(session)navigator.sendBeacon('/api/stop',JSON.stringify({token}))});
async function init(){try{const d=await(await fetch('/api/show')).json();show=d.show;$('editionLabel').textContent=show.edition||'';words=d.words||{};token=d.token;audio.loop=true;$('seek').max=show.duration;const config=await(await fetch('/api/assignments')).json();assignments=config.assignments;roleInfo=config.roles;$('roleGuide').replaceChildren();for(const [role,info] of Object.entries(roleInfo)){const card=document.createElement('div');const name=document.createElement('strong');name.textContent=`${role} · ${info.name}`;const p=document.createElement('p');p.textContent=info.position+'. '+info.use;card.append(name,p);$('roleGuide').append(card)}devices(await(await fetch('/api/devices')).json());show.events.forEach((e,i)=>{const b=document.createElement('button');b.className='scene';const n=document.createElement('b');n.textContent=String(i+1).padStart(2,'0');const title=document.createElement('span');title.textContent=e.title;const at=document.createElement('small');at.textContent=fmt(e.start);b.append(n,title,at);b.onclick=()=>seek(e.start);$('scenes').append(b)});buildScript();render();setInterval(render,60);setInterval(()=>sync(),250);setInterval(async()=>{if(!session)return;try{const s=await(await fetch('/api/status')).json();if(!s.active){session=null;$('lightingNotice').hidden=true;lockSettings(false);$('mode').textContent='PREVIEW · NO LIGHT COMMANDS';status(s.error||'Lighting session ended',!!s.error)}}catch(e){status('Local server unavailable',true)}},2000)}catch(e){status(e.message,true)}}init();
