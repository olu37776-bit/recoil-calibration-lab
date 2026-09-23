'use strict';
window.TeachingUI=(()=>{
 let banks=[],bank=null,picture=null,encoded=null,boxes=[],start=null;
 function draw(){const c=$('teachCanvas'),x=c.getContext('2d');x.clearRect(0,0,c.width,c.height);if(picture){x.drawImage(picture,0,0,c.width,c.height);x.strokeStyle='#66d6b9';x.lineWidth=2;for(const [a,b,w,h] of boxes)x.strokeRect(a/picture.width*c.width,b/picture.height*c.height,w/picture.width*c.width,h/picture.height*c.height);}$('teachRegions').textContent=boxes.length?'原图区域：'+boxes.map(b=>b.join(',')).join('；'):'首次在图上拖框；之后自动复用。';}
 function showBank(next){bank=next;window.dispatchEvent(new CustomEvent('lab-bank',{detail:{bank,banks}}));boxes=next?next.rois.map(x=>x.slice()):[];draw();$('teachSamples').replaceChildren();if(!next){$('teachReport').textContent='尚未建立识别库';return;}
  $('teachName').value=next.name;const old=$('teachWeight').value;$('teachWeight').replaceChildren();for(const w of new Set(['未记录','轻装','中装','重装',...next.weights]))option($('teachWeight'),w,w);$('teachWeight').value=[...$('teachWeight').options].some(o=>o.value===old)?old:'未记录';
  const r=next.validation;$('teachReport').textContent=r?`${r.passed?'识别样本检查通过':'识别样本检查未通过'}；${r.scope}\n${r.missing.join('\n')}\n误判 ${r.trace.filter(x=>!x.passed).length} 张`:'未检查；参考图与独立验证图须分开采集。';
  const table=document.createElement('table');for(const s of next.samples){const row=table.insertRow();for(const text of [s.name,s.weight,s.phase==='reference'?'参考':'独立验证',s.session_id])row.insertCell().textContent=text;const b=document.createElement('button');b.textContent='移除';b.onclick=async()=>{try{showBank(await api('teach_remove',{bank_id:bank.id,sample_id:s.id}));await refresh(bank.id);}catch(e){say(e.message,true);}};row.insertCell().append(b);}$('teachSamples').append(table);
 }
 async function refresh(selected){banks=(await api('teach_list')).banks;const id=selected===undefined?bank?.id:selected;$('teachBanks').replaceChildren();option($('teachBanks'),'','新建识别库');for(const b of banks)option($('teachBanks'),b.id,b.name);if(id)$('teachBanks').value=id;showBank(banks.find(b=>b.id===id)||null);}
 async function loadImage(value){encoded=value;picture=await new Promise((ok,no)=>{const i=new Image();i.onload=()=>ok(i);i.onerror=()=>no(Error('无法读取图片'));i.src='data:image/png;base64,'+value;});const c=$('teachCanvas');c.width=Math.min(900,picture.width);c.height=Math.round(picture.height/picture.width*c.width);draw();if(bank&&$('teachAutoQuery').checked)await query();}
 async function query(){if(!bank||!encoded)throw Error('先选择识别库与待测截图');const r=await api('teach_query',{bank_id:bank.id,image:encoded,weight:$('teachWeight').value});$('teachReport').textContent=`${r.reason} · 分数 ${r.score.toFixed(3)}（不是准确率）\n${r.project_name||'未知：未选择任何配置'}\n${r.recognition_checked?'已检查识别样本':'识别样本尚未通过检查'}；此操作不会输出鼠标。`;if(r.project_id){await openProject(r.project_id);say('已识别并选中：'+r.project_name+'；未启用输出');}else say('未知或歧义：未应用配置',true);}
 async function add(phase,unknown=false){if(!bank&&phase!=='reference')throw Error('先加入一张当前项目参考图建立识别库');if(!encoded)throw Error('先导入截图');if(!unknown)requireProject();const r={project_id:unknown?null:current.id,image:encoded,phase,session_id:$('teachSession').value,weight:$('teachWeight').value,consent:$('teachConsent').checked};const result=bank?await api('teach_add',{...r,bank_id:bank.id}):await api('teach_create',{...r,name:$('teachName').value,rois:boxes});showBank(result);await refresh(result.id);say('已保存裁剪与标签到本机；没有预设负重系数');}
 function point(e){const r=$('teachCanvas').getBoundingClientRect();return[Math.round(Math.max(0,Math.min(1,(e.clientX-r.left)/r.width))*picture.width),Math.round(Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))*picture.height)];}
 $('teachCanvas').addEventListener('pointerdown',e=>{if(!picture||bank)return;start=point(e);e.target.setPointerCapture(e.pointerId);});
 $('teachCanvas').addEventListener('pointerup',e=>{if(!start)return;const p=point(e),r=[Math.min(start[0],p[0]),Math.min(start[1],p[1]),Math.abs(start[0]-p[0]),Math.abs(start[1]-p[1])];start=null;if(boxes.length>=3||Math.min(r[2],r[3])<8||Math.max(r[2],r[3])>512){say('最多3块区域，每块宽高8至512原图像素',true);return;}boxes.push(r);draw();});
 $('teachImage').addEventListener('change',async()=>{try{const f=$('teachImage').files[0];if(f&&f.size>6*1024*1024)throw Error('截图最多6MiB');await loadImage(await file64(f));}catch(e){say(e.message,true);}});
 document.addEventListener('paste',async e=>{if($('teach').hidden)return;const f=[...(e.clipboardData?.files||[])].find(x=>x.type.startsWith('image/'));if(!f)return;e.preventDefault();try{await loadImage(await file64(f));}catch(x){say(x.message,true);}});
 $('teachBanks').addEventListener('change',()=>showBank(banks.find(b=>b.id===$('teachBanks').value)||null));
 bind('teachNew',async()=>{showBank(null);$('teachBanks').value='';});
 bind('teachClearRegions',async()=>{if(bank)throw Error('已有库区域已冻结；用“新建识别库”建立另一布局');boxes=[];draw();});
 bind('teachNewSession',async()=>{$('teachSession').value=newCaptureSession();say('请实际开始一次新的采集；同一录像不能仅改会话名称');});
 bind('teachPreview',async()=>{if(!image)throw Error('先在第02页读取窗口预览');await loadImage(image.src.split(',')[1]);});
 bind('teachReference',()=>add('reference'));bind('teachPositive',()=>add('validation'));bind('teachNegative',()=>add('validation',true));bind('teachQuery',query);
 bind('teachCheck',async()=>{if(!bank)throw Error('先建立识别库');showBank(await api('teach_verify',{bank_id:bank.id}));await refresh(bank.id);});
 async function live(mode){if(!bank)throw Error('先建立识别库');const r=await api('native',{mode,bank_id:bank.id,weight:$('teachWeight').value,hwnd:+$('windows').value,consent:$('teachLiveConsent').checked});$('teachLiveStatus').textContent=r.message;if(poll)clearInterval(poll);poll=setInterval(checkNative,750);say(r.message);}
 bind('teachMonitor',()=>live('recognize'));bind('teachRun',()=>live('auto_execute'));
 function status(s){if(!['recognize','auto_execute'].includes(s.mode))return;const name=bank?.samples.find(x=>x.project_id===s.selected_project)?.name;$('teachLiveStatus').textContent=`${s.message}\n当前识别：${name||'未选中'}\n手动负重：${s.weight}；${s.actual_output_enabled?'已允许受监督输出':'只识别、不输出'}`;}
 return{refresh,status,live};
})();

if(token&&catalog)TeachingUI.refresh().catch(e=>say(e.message,true));
