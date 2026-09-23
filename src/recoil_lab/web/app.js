'use strict';
const $=id=>document.getElementById(id);
const labels={AR:'突击步枪',SMG:'冲锋枪',LMG:'轻机枪'};
const slotLabels={sight:'瞄准镜',muzzle:'枪口',underbarrel:'握把 / 脚架',magazine:'弹匣'};
const modifierLabels={vertical:'垂直后坐',horizontal:'水平后坐',spread:'散布',aim_time:'开镜耗时'};
let cat,token,weapon='galil',category='all',slots={},ammo='556-FMJ',mode='pattern';
let revision=0;
let images=[],imageNames=[],preview=null,aim=null,points=[],measurement=null,activePreset=null;
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function money(n){return n===null||n===undefined?'待核验':'$'+n.toLocaleString('en-US');}
function unlock(item){const u=item.unlock;return u.level===null?'解锁条件待核验':(u.role==='initial'?'初始开放':cat.roles[u.role]+' '+u.level+' 级')+' · 解锁 '+money(u.fee);}
function message(text){$('message').textContent=text;}
function changed(){revision++;activePreset=null;measurement=null;$('calibration-state').textContent='当前配装：未测量；修改配置后必须使用匹配的新证据。';$('fingerprint').textContent='';$('download-result').disabled=true;$('result').textContent='配置已变化，旧结果已失效；请重新分析。';}
async function api(path,payload){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':token},body:JSON.stringify(payload)});const data=await r.json();if(!r.ok)throw Error(data.error||'请求失败');return data;}
function renderWeapons(){
 $('weapons').replaceChildren();const query=$('search').value.trim().toLowerCase();
 for(const w of Object.values(cat.weapons)){if(category!=='all'&&w.category!==category)continue;if(!(`${w.name} ${w.id}`).toLowerCase().includes(query))continue;
 const b=node('button',undefined,'weapon'+(w.id===weapon?' active':''));b.dataset.weapon=w.id;b.append(node('strong',w.name),node('small',cat.calibers[w.caliber]+' · '+money(w.price)),node('small',unlock(w)));b.onclick=()=>selectWeapon(w.id);$('weapons').append(b);}
}
function selectWeapon(id){weapon=id;const w=cat.weapons[id];const old=slots;slots={};
 for(const slot of cat.slots){const options=w.compatibility[slot];slots[slot]=options.includes(old[slot])?old[slot]:(slot==='magazine'?options[0]:null);}
 if(!cat.ammo[ammo]||cat.ammo[ammo].caliber!==w.caliber)ammo=w.caliber+'-FMJ';
 // Preserve actual zoom only for unchanged optics; selecting an optic prompts a new measurement.
 if(old.sight!==slots.sight)$('zoom').value=slots.sight?cat.parts[slots.sight].zoom:1;
 changed();renderWeapons();renderBuild();
}
function renderBuild(){const w=cat.weapons[weapon];$('weapon-name').textContent=w.name;$('weapon-category').textContent=labels[w.category];$('weapon-info').textContent=cat.calibers[w.caliber]+' · '+(w.rpm===null?'射速待核验':w.rpm+' 发 / 分')+' · '+unlock(w)+' · 枪价 '+money(w.price);
 $('fitment-note').textContent=w.fitment_status==='partial-pending'?'这把枪部分槽位缺少可靠兼容列表；未开放推断配件，不代表游戏里不能装。':'仅列入已核对的社区兼容子集；不是完整配件库或游戏内认证。';
 $('weapon-source').href=w.sources[0];$('slots').replaceChildren();
 for(const slot of cat.slots){const label=node('label',slotLabels[slot]);const select=node('select');select.dataset.slot=slot;select.setAttribute('aria-label',slotLabels[slot]);
 if(slot!=='magazine'){const none=node('option',w.compatibility[slot].length?'不安装':'待核验 / 暂无已收录选项');none.value='';select.append(none);}
 for(const id of w.compatibility[slot]){const p=cat.parts[id],option=node('option',p.name+' · '+money(p.price));option.value=id;select.append(option);}
 select.value=slots[slot]||'';select.onchange=()=>{slots[slot]=select.value||null;if(slot==='sight')$('zoom').value=select.value?cat.parts[select.value].zoom:1;if(slot==='underbarrel')$('bipod').checked=false;changed();renderDetails();};label.append(select);$('slots').append(label);}
 $('ammo').replaceChildren();for(const a of Object.values(cat.ammo).filter(a=>a.caliber===w.caliber)){const o=node('option',a.name+' · '+money(a.price)+' / 数据库单位');o.value=a.id;$('ammo').append(o);}$('ammo').value=ammo;renderDetails();
}
function renderDetails(){const w=cat.weapons[weapon];const selected=Object.values(slots).filter(Boolean).map(id=>cat.parts[id]);let total=w.price||0;const missing=w.price===null?[w.name]:[];$('part-detail').replaceChildren();
 for(const part of [...selected,cat.ammo[ammo]]){const box=node('div',undefined,'detail');box.append(node('strong',part.name),node('p',unlock(part)+' · 购买 '+money(part.price)));
 if(part.modifiers){const mods=Object.entries(part.modifiers).map(([k,v])=>modifierLabels[k]+' '+(v>0?'+':'')+v+'%');box.append(node('p',mods.length?mods.join(' / '):'未收录完整修正；不把缺失属性当作零。'));}
 if(part.kind)box.append(node('p','弹药包装数量待核验；不据此换算每发价格。'));
 $('part-detail').append(box);}
 for(const p of selected){if(p.price===null)missing.push(p.name);else total+=p.price;}$('total').textContent=money(total)+(missing.length?' + 未知项':'');
}
function settings(){return {dpi:+$('dpi').value,sensitivity:+$('sensitivity').value,ads_sensitivity:+$('ads_sensitivity').value,zoom:+$('zoom').value,resolution:[+$('width').value,+$('height').value],fov:+$('fov').value,pose:$('pose').value,game_build:$('game_build').value.trim(),bipod_deployed:$('bipod').checked};}
function payload(){return {weapon,slots:{...slots},ammo,settings:settings()};}
async function preset(){const started=revision;const p=await api('/api/preset',payload());if(revision!==started)throw Error('配装已变化，请重试');activePreset=p;$('fingerprint').textContent='配置指纹 '+p.context_id;$('calibration-state').textContent='配置已保存 / 尚未完成校准与独立验证';return p;}
function download(data,name,type='application/json'){const blob=new Blob([data],{type}),url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function importPreset(p){const verified=await api('/api/preset',p);weapon=verified.weapon;slots=verified.slots;ammo=verified.ammo;const s=verified.settings;
 for(const k of ['dpi','sensitivity','ads_sensitivity','zoom','fov','pose','game_build'])$(k).value=s[k];$('width').value=s.resolution[0];$('height').value=s.resolution[1];$('bipod').checked=s.bipod_deployed;
 changed();renderWeapons();renderBuild();message('配装已载入。历史测量状态没有跟随导入；请确认当前游戏配置。');}
async function guard(fn){try{message('');await fn();}catch(e){message(e.message||String(e));}}
function dataURL(file){return new Promise((resolve,reject)=>{if(file.size>6*1024*1024)return reject(Error('每张图片最多 6 MiB'));const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=()=>reject(Error('读取图片失败'));r.readAsDataURL(file);});}
async function setImages(files){revision++;if(!files.length)return;if(files.length>120)throw Error('最多 120 张截图');if(mode==='pattern'&&files.length!==1)throw Error('单张模式请选择一张图片');if(mode==='pair'&&files.length!==2)throw Error('前后模式请正好选择两张图片');
 const started=revision;const loaded=await Promise.all(files.map(dataURL));if(started!==revision)return;images=loaded;imageNames=files.map(f=>f.name);aim=null;points=[];measurement=null;$('download-result').disabled=true;
 $('file-list').textContent=imageNames.map((n,i)=>`${i+1}. ${n}`).join('\n');$('file-list').style.whiteSpace='pre-line';
 preview=await new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=()=>reject(Error('图片不能显示'));im.src=images[0];});
 if(preview.width*preview.height>12000000)throw Error('图片像素数过大');$('canvas').width=preview.width;$('canvas').height=preview.height;draw();$('result').textContent='截图已载入。请确认原始分辨率和分析模式。';
}
function draw(){const c=$('canvas'),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);if(!preview)return;ctx.drawImage(preview,0,0);
 ctx.lineWidth=Math.max(2,c.width/700);if(mode==='pattern'){if(aim){ctx.strokeStyle='#ffc65c';ctx.beginPath();ctx.moveTo(aim[0]-12,aim[1]);ctx.lineTo(aim[0]+12,aim[1]);ctx.moveTo(aim[0],aim[1]-12);ctx.lineTo(aim[0],aim[1]+12);ctx.stroke();}for(let i=0;i<points.length;i++){const p=points[i];ctx.strokeStyle='#72e1cb';ctx.beginPath();ctx.arc(p[0],p[1],Math.max(5,c.width/200),0,2*Math.PI);ctx.stroke();}}
 else{ctx.strokeStyle='#ffc65c';const r=roi();ctx.strokeRect(...r);}}
function roi(){return ['roi-x','roi-y','roi-w','roi-h'].map(id=>+$(id).value);}
function setMode(m){revision++;mode=m;images=[];imageNames=[];preview=null;aim=null;points=[];measurement=null;$('images').value='';$('file-list').textContent='';$('download-result').disabled=true;$('result').textContent='请重新选择此模式的截图。';draw();
 for(const b of $('modes').querySelectorAll('button'))b.classList.toggle('active',b.dataset.mode===m);
 $('pattern-controls').hidden=m!=='pattern';$('pattern-controls').style.display=m==='pattern'?'flex':'none';$('roi-controls').hidden=m==='pattern';$('sequence-controls').hidden=m!=='sequence';$('declaration').hidden=m==='pattern';$('stationary').checked=false;
 $('mode-help').textContent={pattern:'单张图：手动标注弹孔，测偏移与散布；不能恢复逐发时间或生成补偿曲线。',pair:'两张图：按选择列表依次为射击前、射击后。只测静态背景总位移，不生成补偿曲线。',sequence:'连续截图：按列出的文件顺序填写时间戳，通过质量门禁后导出标准 Trial；后续拟合还需要独立输入响应标定。'}[m];}
async function analyze(){const started=revision;if(!images.length)throw Error('请先选择截图');const p=await preset();let body={preset:p};let route;
 if(mode==='pattern'){route='pattern';body={...body,image:images[0],aim,points};}
 else if(mode==='pair'){if(images.length!==2)throw Error('需要两张图片');route='pair';body={...body,before:images[0],after:images[1],roi:roi(),stationary:$('stationary').checked};}
 else{route='sequence';const text=$('times').value.trim();if(!text)throw Error('需要逐帧时间戳');const timestamps=text.split(/[,，\s]+/).map(Number);body={...body,images,timestamps,roi:roi(),run_id:'screenshot-burst',capture_session:$('capture_session').value.trim(),uncompensated:$('stationary').checked};}
 $('analyze').disabled=true;try{const received=await api('/api/'+route,body);if(started!==revision)throw Error('输入已变化，丢弃旧请求结果，请重新分析');measurement=received;const visible={...measurement};delete visible.zip_base64;$('result').textContent=JSON.stringify(visible,null,2);$('download-result').disabled=false;message('测量完成。测量结果不等于已经验证的压枪曲线。');}finally{$('analyze').disabled=false;}}
async function init(){const [bootstrap,catalog]=await Promise.all([fetch('/api/bootstrap').then(r=>r.json()),fetch('/api/catalog').then(r=>r.json())]);token=bootstrap.token;cat=catalog;
 $('catalog-count').textContent=Object.keys(cat.weapons).length+' 把枪械 / '+Object.keys(cat.parts).length+' 个配件\n'+Object.keys(cat.ammo).length+' 种弹药选项 · 社区资料子集';$('source-note').textContent='资料核对：'+cat.reviewed_on+' · '+cat.notice;
 for(const [id,name] of Object.entries({all:'全部',...labels})){const b=node('button',name,id==='all'?'active':'');b.onclick=()=>{category=id;for(const x of $('categories').children)x.classList.remove('active');b.classList.add('active');renderWeapons();};$('categories').append(b);}
 slots={sight:'tricon15',muzzle:null,underbarrel:null,magazine:'galil35'};selectWeapon('galil');setMode('pattern');
 $('search').oninput=renderWeapons;$('ammo').onchange=()=>{ammo=$('ammo').value;changed();renderDetails();};
 for(const k of ['dpi','sensitivity','ads_sensitivity','zoom','width','height','fov','pose','game_build','bipod'])$(k).addEventListener('input',changed);
 $('save').onclick=()=>guard(async()=>download(JSON.stringify(await preset(),null,2),weapon+'-preset.json'));
 $('remember').onclick=()=>guard(async()=>{localStorage.setItem('recoil-lab-preset',JSON.stringify(await preset()));message('配装已保存到本机浏览器，不含图片。');});
 $('restore').onclick=()=>guard(async()=>{const stored=localStorage.getItem('recoil-lab-preset');if(!stored)throw Error('没有已保存配装');await importPreset(JSON.parse(stored));});
 $('import').onchange=()=>guard(async()=>{const f=$('import').files[0];if(f.size>1024*1024)throw Error('配装文件过大');await importPreset(JSON.parse(await f.text()));});
 $('images').onchange=()=>guard(()=>setImages([...$('images').files]));
 document.addEventListener('paste',e=>{if(mode!=='pattern')return;const file=[...(e.clipboardData?.items||[])].find(i=>i.type.startsWith('image/'))?.getAsFile();if(file){e.preventDefault();guard(()=>setImages([file]));}});
 $('canvas').onclick=e=>{if(!preview||mode!=='pattern')return;const r=$('canvas').getBoundingClientRect(),p=[(e.clientX-r.left)*preview.width/r.width,(e.clientY-r.top)*preview.height/r.height];if(!aim)aim=p;else points.push(p);revision++;measurement=null;$('download-result').disabled=true;draw();};
 $('undo').onclick=()=>{if(points.length)points.pop();else aim=null;revision++;measurement=null;$('download-result').disabled=true;draw();};$('clear').onclick=()=>{points=[];aim=null;revision++;measurement=null;$('download-result').disabled=true;draw();};
 $('use-resolution').onclick=()=>{if(!preview)return;$('width').value=preview.width;$('height').value=preview.height;changed();message('分辨率已更新；确认游戏实际设置与该截图一致。');};
 for(const b of $('modes').querySelectorAll('button'))b.onclick=()=>setMode(b.dataset.mode);
 for(const id of ['roi-x','roi-y','roi-w','roi-h'])$(id).oninput=()=>{revision++;measurement=null;$('download-result').disabled=true;draw();};
 $('times').oninput=$('capture_session').oninput=$('stationary').onchange=()=>{revision++;measurement=null;$('download-result').disabled=true;};
 $('analyze').onclick=()=>guard(analyze);$('download-result').onclick=()=>{if(!measurement)return;if(measurement.zip_base64){const bytes=Uint8Array.from(atob(measurement.zip_base64),c=>c.charCodeAt(0));download(bytes,'screenshot-trial.zip','application/zip');}else download(JSON.stringify(measurement,null,2),'screenshot-measurement.json');};
}
guard(init);
