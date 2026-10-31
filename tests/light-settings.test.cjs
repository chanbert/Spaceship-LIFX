const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('web/app.js','utf8');
const handler=source.slice(source.indexOf('async function openLightSettings(){'),source.indexOf("$('editLights').onclick="));
function harness(fail=false){
 const elements=Object.fromEntries(['lightSettings','mappingStatus','lightingNotice','mode'].map(id=>[id,{showModal(){this.open=true}}]));
 const events=[];
 const context=vm.createContext({busy:false,session:'active',audio:{currentTime:123,pause(){events.push('pause')}},$:id=>elements[id],lockSettings:on=>events.push(on?'lock':'unlock'),api:async path=>{events.push(path);if(fail)throw Error('Server unavailable')},status:()=>{}});
 vm.runInContext(handler,context);
 return {context,events,elements};
}
test('opening settings restores before unlocking and preserves playback position',async()=>{
 const {context,events,elements}=harness();
 await context.openLightSettings();
 assert.deepEqual(events,['lock','pause','stop','unlock']);
 assert.equal(context.session,null);assert.equal(context.busy,false);
 assert.equal(context.audio.currentTime,123);assert.equal(elements.lightSettings.open,true);
});
test('stop failure stays locked and explains retry',async()=>{
 const {context,events,elements}=harness(true);
 await context.openLightSettings();
 assert.equal(events.at(-1),'lock');assert.equal(context.session,'active');
 assert.match(elements.mappingStatus.textContent,/Close this menu and try again/);
 assert.equal(context.busy,false);
});
test('opening while another operation is pending does not race',async()=>{
 const {context,events}=harness();context.busy=true;
 await context.openLightSettings();assert.deepEqual(events,[]);
});
