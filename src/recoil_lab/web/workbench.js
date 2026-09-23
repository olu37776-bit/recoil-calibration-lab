'use strict';
const $=id=>document.getElementById(id);
let token='', catalog=null, current=null, roi=null, image=null, dragging=null, poll=null;
function newCaptureSession(){return 'session-'+Array.from(crypto.getRandomValues(new Uint32Array(3)),n=>n.toString(16).padStart(8,'0')).join('');}
function say(text,error=false){$('message').textContent=text;$('message').className=error?'error':'';}
async function api(action,extra={}){
 const r=await fetch('/api/product',{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':token},body:JSON.stringify({action,project_id:current?.id,...extra})});
 const v=await r.json();if(!r.ok)throw Error(v.error||'本机服务错误');return v;
}
function option(select,value,text){const e=document.createElement('option');e.value=value;e.textContent=text;select.append(e);}
function price(v){return v===null?'待核验':'$'+v.toLocaleString();}
function describeDetail(item){const u=item.unlock;return `${item.name}｜${catalog.roles[u.role]}${u.level??'?'}级 / 解锁${price(u.fee)} / 购买${price(item.price)}`;}
function describe(item){return item.name;}
function slots(){const w=catalog.weapons[$('weapon').value];for(const key of catalog.slots){const e=$(key);e.replaceChildren();if(key!=='magazine')option(e,'','不安装');for(const id of w.compatibility[key])option(e,id,describe(catalog.parts[id]));}
 $('ammo').replaceChildren();Object.values(catalog.ammo).filter(a=>a.caliber===w.caliber).forEach(a=>option($('ammo'),a.id,describe(a)));
 if(w.id==='galil')$('sight').value='tricon15'; zoom();cost();}
function zoom(){const p=catalog.parts[$('sight').value];if(p?.zoom)$('zoom').value=p.zoom;}
function cost(){let sum=catalog.weapons[$('weapon').value].price;for(const key of catalog.slots)if($(key).value)sum+=(catalog.parts[$(key).value].price||0);$('cost').textContent=`已知武器/配件单次成本：${price(sum)}；不含弹药。数据为社区核对目录，不决定实测补偿力度。`+'\n'+[catalog.weapons[$('weapon').value],...catalog.slots.map(k=>catalog.parts[$(k).value]).filter(Boolean)].map(describeDetail).join('\n');}
function preset(){return{weapon:$('weapon').value,slots:Object.fromEntries(catalog.slots.map(k=>[k,$(k).value||null])),ammo:$('ammo').value,settings:{dpi:+$('dpi').value,sensitivity:+$('sensitivity').value,ads_sensitivity:+$('ads').value,zoom:+$('zoom').value,resolution:[+$('width').value,+$('height').value],fov:+$('fov').value,pose:$('pose').value,game_build:$('build').value,bipod_deployed:$('bipodState').value==='true',weight_label:$('weightLabel').value}};}
function tab(id){document.querySelectorAll('.pane').forEach(e=>e.hidden=e.id!==id);document.querySelectorAll('[data-tab]').forEach(e=>e.classList.toggle('selected',e.dataset.tab===id));}
async function projects(){const data=await api('projects');$('projects').replaceChildren();for(const p of data.projects)option($('projects'),p.id,p.name);if(current)$('projects').value=current.id;}
function requireProject(){if(!current)throw Error('请先创建或选择一个项目');}
function drawCurve(data){const c=$('chart'),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);if(!data)return;const {t_s,uy_counts}=data;const lo=Math.min(0,...uy_counts),hi=Math.max(1,...uy_counts);ctx.strokeStyle='#65d5bc';ctx.lineWidth=2;ctx.beginPath();for(let i=0;i<t_s.length;i++){const x=35+t_s[i]/t_s[t_s.length-1]*(c.width-60),y=200-(uy_counts[i]-lo)/(hi-lo)*160;i?ctx.lineTo(x,y):ctx.moveTo(x,y);}ctx.stroke();ctx.fillStyle='#b8cadd';ctx.font='14px system-ui';ctx.fillText('累计垂直输入（不是每发伤害，也不是游戏已验证）',30,24);ctx.fillText(`0 → ${t_s[t_s.length-1].toFixed(2)} 秒`,30,230);}
function render(data){current=data;$('summary').replaceChildren();let p=document.createElement('p');p.textContent=`当前：${data.name}\n${data.demo?'合成演示':'真实采样项目'}\n配置：${data.context.weapon} / ${data.context.pose} / 负重：${data.context.weight_label||'未记录'}`;$('summary').append(p);
 const counts={response:0,train:0,validation:0};data.trials.forEach(t=>counts[t.phase]++);p=document.createElement('p');p.textContent=`响应 ${counts.response}/2　训练 ${counts.train}/3　验证 ${counts.validation}/3`;$('summary').append(p);
 const table=document.createElement('table');const head=table.insertRow();['记录','阶段','时长','最低质量'].forEach(text=>{const cell=head.insertCell();cell.textContent=text;});for(const t of data.trials){const row=table.insertRow();[t.run_id.slice(0,19),t.phase,t.duration_s.toFixed(2)+'s',t.confidence.toFixed(2)].forEach(text=>row.insertCell().textContent=text);}$('trials').replaceChildren(table);
 $('profiles').replaceChildren();for(const v of data.profiles)option($('profiles'),v.id,`${v.id.slice(0,10)} · ${v.duration_s.toFixed(2)}秒 · ${v.report?.evidence_kind||'未验证'}`);$('profiles').value=data.active_profile||'';
 const active=data.profiles.find(v=>v.id===data.active_profile);$('report').textContent=active?.report?`${active.report.passed?'门禁通过':'未通过'} / ${active.report.evidence_kind} / 游戏实测：未认证`:'尚无验证报告';$('details').textContent=JSON.stringify(active?.report||data.response||{message:'先采集响应与训练数据'},null,2);drawCurve(data.curve);$('projects').value=data.id;window.dispatchEvent(new Event('lab-project'));
}
async function openProject(id){render(await api('open',{project_id:id}));roi=null;image=null;drawPreview();}
async function refreshCurrent(){if(current)render(await api('open'));}
function download(name,data,type){const url=URL.createObjectURL(new Blob([data],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);}
function bytes64(b64){return Uint8Array.from(atob(b64),c=>c.charCodeAt(0));}
async function file64(f){if(!f)throw Error('请选择数据包');if(f.size>12*1024*1024)throw Error('数据包最多12MiB');return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=reject;r.readAsDataURL(f);});}
function drawPreview(){const c=$('previewCanvas'),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);if(image){ctx.drawImage(image,0,0,c.width,c.height);if(roi){ctx.strokeStyle='#62f2ba';ctx.lineWidth=3;ctx.strokeRect(roi[0]/image.width*c.width,roi[1]/image.height*c.height,roi[2]/image.width*c.width,roi[3]/image.height*c.height);}}$('roi').textContent=roi?'原图区域：'+roi.join(', '):'尚未选择区域';}
function point(e){const r=$('previewCanvas').getBoundingClientRect();return[Math.max(0,Math.min(image.width,Math.round((e.clientX-r.left)/r.width*image.width))),Math.max(0,Math.min(image.height,Math.round((e.clientY-r.top)/r.height*image.height)))];}
$('previewCanvas').addEventListener('pointerdown',e=>{if(!image)return;dragging=point(e);e.target.setPointerCapture(e.pointerId);});
$('previewCanvas').addEventListener('pointermove',e=>{if(!dragging)return;const q=point(e);roi=[Math.min(q[0],dragging[0]),Math.min(q[1],dragging[1]),Math.abs(q[0]-dragging[0]),Math.abs(q[1]-dragging[1])];drawPreview();});
$('previewCanvas').addEventListener('pointerup',()=>{dragging=null;if(roi&&(roi[2]<32||roi[3]<32)){roi=null;say('区域至少32×32原图像素',true);drawPreview();}});
async function native(mode){requireProject();const consent=mode==='execute'?$('executeConsent').checked:$('consent').checked;const status=await api('native',{mode,consent,hwnd:+$('windows').value,roi,duration_s:+$('duration').value});$('nativeStatus').textContent=status.message;say(status.message);if(poll)clearInterval(poll);poll=setInterval(checkNative,750);if(window.Guidance)Guidance.refresh();}
let polling=false;
async function checkNative(){if(polling)return;polling=true;try{const s=await api('status');$('nativeStatus').textContent=`${s.message} ${Math.round((s.progress||0)*100)}%`;if(window.TeachingUI)TeachingUI.status(s);window.dispatchEvent(new CustomEvent('lab-status',{detail:s}));if(s.state!=='RUNNING'){clearInterval(poll);poll=null;say(s.message,s.state==='ERROR');if(s.preview){const next=new Image();next.onload=()=>{image=next;const c=$('previewCanvas');c.width=Math.min(900,image.width);c.height=Math.round(image.height/image.width*c.width);roi=null;drawPreview();if(window.Guidance)Guidance.refresh();};next.src='data:image/png;base64,'+s.preview.image;}await refreshCurrent();if(window.Guidance)Guidance.refresh();}}catch(e){say(e.message,true);}finally{polling=false;}}
let actionBusy=0;
function bind(id,fn){$(id).addEventListener('click',async()=>{const b=$(id);b.disabled=true;actionBusy++;window.dispatchEvent(new CustomEvent('lab-busy',{detail:actionBusy}));try{await fn();}catch(e){say(e.message,true);}finally{b.disabled=false;actionBusy--;window.dispatchEvent(new CustomEvent('lab-busy',{detail:actionBusy}));}});}
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>tab(b.dataset.tab)));
$('weapon').addEventListener('change',slots);for(const k of catalog?.slots||[])$(k).addEventListener('change',cost);
$('projects').addEventListener('change',()=>openProject($('projects').value).catch(e=>say(e.message,true)));
bind('refresh',async()=>{await projects();await refreshCurrent();});
bind('create',async()=>{if(window.Guidance)await Guidance.beforeCreate();render(await api('create',{name:$('name').value,preset:preset()}));await projects();tab('capture');say('项目已保存；请核对目标窗口与分辨率');});
bind('demo',async()=>{say('正在运行全流程合成演示…');render(await api('demo'));await projects();tab('calibrate');say('合成全流程完成；不是游戏校准结果');});
bind('import',async()=>{requireProject();render(await api('import',{zip_base64:await file64($('trialzip').files[0])}));say('导入完成');});
bind('listwindows',async()=>{const r=await api('windows');$('windows').replaceChildren();for(const w of r.windows)option($('windows'),w.handle,`${w.title} · ${w.resolution.join('×')}`);say('按实际窗口尺寸创建项目；采集前需切到该窗口');window.dispatchEvent(new Event('lab-windows'));});
for(const [id,mode] of [['preview','preview'],['recordResponse','response'],['recordTrain','train'],['recordValidation','validation'],['executeButton','execute']])bind(id,()=>native(mode));
for(const action of ['response','fit','refine','validate'])bind(action,async()=>{requireProject();say('正在计算…');const r=await api(action);if(action==='validate')say(`${r.passed?'通过':'未通过'}：${r.evidence_kind}`);else say('计算完成并保存新记录');await refreshCurrent();});
bind('selectProfile',async()=>{requireProject();render(await api('select',{profile_id:$('profiles').value}));say('已切换版本；没有启用输出');});
bind('export',async()=>{requireProject();const r=await api('export');download(r.filename,bytes64(r.zip_base64),'application/zip');say('项目导出到浏览器下载目录');});
bind('stop',async()=>{await api('stop');say('已请求停止；F8/Esc也可直接停止');});
window.addEventListener('keydown',e=>{if(e.key==='Escape'||e.key==='F8')api('stop').catch(()=>{});});
async function init(){token=(await(await fetch('/api/bootstrap')).json()).token;catalog=await(await fetch('/api/catalog')).json();Object.values(catalog.weapons).forEach(w=>option($('weapon'),w.id,describe(w)));$('weapon').value='galil';slots();for(const k of catalog.slots)$(k).addEventListener('change',()=>{if(k==='sight')zoom();cost();});const env=await api('environment');$('notice').textContent=env.notice;$('environment').textContent=`${env.platform} · ${env.version} · 数据只存本机`;
 if(!env.native_available){for(const id of ['listwindows','preview','recordResponse','recordTrain','recordValidation','executeButton'])$(id).disabled=true;$('notice').textContent+=' 当前系统只开放离线工作流。';}
 await projects();if(window.TeachingUI)await TeachingUI.refresh();window.labEnvironment=env;window.labInitialized=true;window.dispatchEvent(new Event('lab-ready'));say('准备就绪。先选已有项目或创建配装。');}
init().catch(e=>say('初始化失败：'+e.message,true));

bind('copySetup',async()=>{requireProject();if(!current.preset)throw Error('合成演示不是可复用的游戏配装');const p=current.preset;$('weapon').value=p.weapon;slots();for(const k of catalog.slots)$(k).value=p.slots[k]||'';$('ammo').value=p.ammo;const x=current.context;for(const [k,id] of [['dpi','dpi'],['sensitivity','sensitivity'],['ads_sensitivity','ads'],['zoom','zoom'],['fov','fov'],['pose','pose'],['game_build','build']])$(id).value=x[k];$('width').value=x.resolution[0];$('height').value=x.resolution[1];$('bipodState').value=String(x.bipod_deployed||false);$('weightLabel').value=x.weight_label||'未记录';$('name').value=current.name+' 副本';cost();tab('setup');say('修改所需条件后建立新项目；不会覆盖旧校准');if(window.Guidance)Guidance.copied();});
