'use strict';
// Presentation and navigation only. All actual start actions use existing APIs/gates.
window.Guidance=(()=>{
 let env=null, mode='daily', bank=null, banks=[], prefs={}, busy=0, lastStatus=null, next=null, lastProject=null, draft=false;
 const calculated=new Set();
 const settingIds={dpi:'dpi',sensitivity:'sensitivity',ads_sensitivity:'ads',fov:'fov',game_build:'build'};
 const nativeSteps=new Set(['record_response','record_train','record_validation']);
 function settings(){return{dpi:+$('dpi').value,sensitivity:+$('sensitivity').value,ads_sensitivity:+$('ads').value,zoom:+$('zoom').value,resolution:[+$('width').value,+$('height').value],fov:+$('fov').value,game_build:$('build').value};}
 async function remember(patch){prefs={...prefs,...await api('preferences',{patch})};}
 function useSettings(s){for(const[k,id]of Object.entries(settingIds))$(id).value=s[k];$('width').value=s.resolution[0];$('height').value=s.resolution[1];$('settingsConfirmed').checked=true;settingsLabel();}
 function settingsLabel(){$('settingsSummary').textContent=$('settingsConfirmed').checked?`已记住本机设置：${$('dpi').value} DPI · ${$('width').value}×${$('height').value} · 灵敏度 ${$('sensitivity').value} / 开镜 ${$('ads').value}。游戏内改过后需更新。`:'首次请展开本机设置，核对真实值；不能从截图推断。';}
 function changeMode(m){mode=m;tab(m==='daily'?'daily':m==='teach'?'teach':'setup');$('guide').hidden=m!=='tune';for(const[id,which]of [['homeButton','daily'],['tuneButton','tune'],['teachButton','teach']])$(id).classList.toggle('primary',m===which);refresh();}
 function showStep(){if(!next)return;tab(next.tab);if(next.focus){$(next.focus)?.focus();if(next.focus==='settingsConfirmed')$('settingsPanel').open=true;}}
 function model(){
  if(draft&&$('settingsConfirmed').checked)return{tab:'setup',title:'保存这份新配装',hint:'只改本次要测试的条件；旧配置和原有结果会保留。',button:'保存并开始调教',action:'create'};
  if(!current||draft)return{tab:'setup',title:'先选一套配装',hint:'选枪械和配件，负重只是手动标签。首次核对本机设置，之后可复用。',button:'去设置配装',focus:'weapon'};
  const p=current.workflow||{},c=p.counts||{};
  const map={
   record_response:{tab:'capture',action:'recordResponse',hint:'回到目标窗口，按住 F7＋右键；这一步不要开火，也不要移动鼠标。',button:`开始第 ${Math.min((c.response||0)+1,2)} / 2 次标定`},
   response:{tab:'calibrate',action:'response',hint:'不需要再切回游戏。程序计算本机鼠标输入与画面移动的关系。',button:'计算并保存标定'},
   record_train:{tab:'capture',action:'batchTrain',hint:'一次准备补齐未补偿试射。每轮松开 F7 和左右键，换弹并回到起点，再按下试射；不自动点击，不输出鼠标移动。',button:`一次准备，补齐 ${Math.max(1,3-(c.train||0))} 轮试射`},
   fit:{tab:'calibrate',action:'fit',hint:'根据你刚才的试射生成补偿。无需手填鼠标位移或时间参数。',button:'生成这套配装的补偿'},
   record_validation:{tab:'capture',action:'recordValidation',hint:'现在检查刚生成的版本。重新采集，按住 F7＋右键＋左键；旧版本的检查不会算进来。',button:`开始第 ${Math.min((c.validation_current||0)+1,3)} / 3 次效果检查`},
   validate:{tab:'calibrate',action:'validate',hint:'检查完整过程，而不只看最后落点。通过后才可用于受控运行。',button:'计算本版检查结果'},
   ready:{tab:'teach',hint:'补偿已通过实测回放检查。接下来教程序识别这套配置，或回到日常入口。',button:'教程序识别这套配置'},
   demo:{tab:'calibrate',hint:'这是软件合成演示，不可用于实际输出。真实配置仍需你自己调教。',button:'查看演示结果'},
   review:{tab:'calibrate',hint:'先看下方结果。可以追加新的试射后微调，或恢复一个此前通过的版本；不自动覆盖旧记录。',button:'查看结果与调整入口'}
  };
  let result={...(map[p.step]||map.review),title:p.title||'继续调教'};
  if(nativeSteps.has(p.step)){
   if(!env?.native_available)return{...result,title:'当前系统只支持离线分析',hint:'窗口采集需要在 Windows 便携版进行；你仍可导入已有数据。',action:null,button:'查看导入入口'};
   if(!$('windows').value)return{tab:'capture',title:'先选目标窗口',hint:'读取窗口列表后，核对目标名称。分辨率必须与当前配置一致。',action:'listwindows',button:'读取窗口列表'};
   if(!image)return{tab:'capture',title:'取一张画面，框选墙面',hint:'先勾选本次采集授权，再点击。5秒内切到目标窗口；回来后框选有纹理的静态墙面。',action:'preview',button:'5秒后取得画面'};
   if(!roi)return{tab:'capture',title:'在预览里框出一块静态墙面',hint:'不要框枪、准星、HUD或会移动的物体。框好后，下一步会变为采集。',button:'查看预览并框选',focus:'previewCanvas'};
  }
  return result;
 }
 function refresh(){
  if(!env)return;
  next=model();$('guideTitle').textContent=next.title;$('guideHint').textContent=next.hint;$('guideNext').textContent=busy?'正在处理，请稍候…':next.button;$('guideNext').disabled=busy>0||!!poll;
  const c=current?.workflow?.counts;$('guideProgress').textContent=c?`不射击标定 ${c.response}/2　未补偿试射 ${c.train}/3　当前版本检查 ${c.validation_current}/3 · 每次成功都会保存`:'完成一次就保存一次；不用重头开始。';
  const ready=current?.workflow?.can_request_execution===true;
  $('dailyTitle').textContent=current?current.name:'先准备第一套配置';
  $('dailyState').textContent=current?`${current.demo?'合成演示，不可实际运行':(current.workflow?.title||'还未调教')}\n${current.context.weapon} · ${current.context.pose==='standing'?'站立':current.context.pose==='crouching'?'蹲下':'卧倒'} · ${current.context.zoom}× · 负重 ${current.context.weight_label||'未记录'}`:'选配装、按提示试射、教它识别。日常使用不用再经过全部步骤。';
  const checks=[['配置已选择',!!current],['本版效果检查',ready],['识别样本检查',bank?.validation?.passed===true],['目标窗口',!!$('windows').value]];
  $('dailyChecklist').replaceChildren();for(const[label,ok]of checks){const el=document.createElement('span');el.textContent=(ok?'✓ ':'○ ')+label;el.className=ok?'pass':'pending';$('dailyChecklist').append(el);}
  const base=!!env.native_available&&!!bank&&!!$('windows').value&&busy===0&&!poll;
  $('dailyMonitor').disabled=!base;$('dailyRun').disabled=!base||!ready||bank?.validation?.passed!==true||bank.samples.some(s=>s.demo);
  $('dailyWindows').disabled=!env.native_available||busy>0||!!poll;
  $('dailyWhy').textContent=!env.native_available?'当前不是Windows，仍可设置配装、导入和分析。':!bank?'先教它识别并保存参考，再使用自动选档。':!$('windows').value?'请选择本次目标窗口。':!ready?'当前补偿尚未通过实测检查。可以先只看识别结果。':bank?.validation?.passed!==true?'补偿已准备好，但识别样本还需检查。':'开始前服务会再次核验识别库和所有关联曲线；不会只信界面的通过标记。';
  $('quickRollback').disabled=!current?.workflow?.recommended_rollback_id||busy>0||!!poll;
  for(const id of ['duplicateConfig','dailyExport','dailyTeach','reviewEffect'])$(id).disabled=!current||busy>0||!!poll;
  if(lastStatus){const name=bank?.samples.find(s=>s.project_id===lastStatus.selected_project)?.name;$('dailyLive').textContent=lastStatus.message+(name?'\n当前识别：'+name:'')+'\n'+(lastStatus.actual_output_enabled?'本次已允许受监督输出':'未启用自动输出');}
  if(mode==='tune'&&!draft&&busy===0&&!poll&&lastStatus?.state!=='ERROR'&&$('autoCalculate').checked&&['response','fit','validate'].includes(current?.workflow?.step)){
   const key=[current.id,current.workflow.step,current.active_profile,...current.trials.map(t=>t.id)].join(':');
   if(!calculated.has(key)){calculated.add(key);const action=current.workflow.step;queueMicrotask(()=>{if(busy===0&&!poll&&mode==='tune')$(action).click();else calculated.delete(key);});}
  }
 }
 function windowsChanged(){const selected=$('windows').value;$('dailyWindow').replaceChildren();for(const x of $('windows').options)option($('dailyWindow'),x.value,x.textContent);$('dailyWindow').value=selected;refresh();}
 function banksChanged(event){bank=event.detail.bank;banks=event.detail.banks||banks;if(env&&bank&&prefs.last_bank_id!==bank.id)remember({last_bank_id:bank.id}).catch(()=>{});const sel=$('dailyBank');sel.replaceChildren();option(sel,'','选择识别库');for(const b of banks)option(sel,b.id,b.name);sel.value=bank?.id||'';
  const weight=$('dailyWeight').value;const weights=new Set(['未记录','轻装','中装','重装',...(bank?.weights||[])]);$('dailyWeight').replaceChildren();for(const w of weights)option($('dailyWeight'),w,w);$('dailyWeight').value=weights.has(weight)?weight:'未记录';$('teachWeight').value=$('dailyWeight').value;refresh();}
 async function dailyStart(modeName){
  if(!$('dailyConsent').checked)throw Error('请先勾选本次窗口采集与受控使用授权');
  $('teachLiveConsent').checked=true;$('teachWeight').value=$('dailyWeight').value;
  await TeachingUI.live(modeName);refresh();
 }
 async function nextAction(){
  refresh();showStep();if(next?.action==='batchTrain'){await CaptureHelp.startBatch();return;}if(next?.action){if($(next.action).disabled)throw Error('这一步当前不可用，请按页面提示准备');$(next.action).click();}
  if(next?.tab==='teach'){mode='teach';$('guide').hidden=true;}
 }
 async function init(e){env=e;prefs=await api('preferences');
  if(prefs.settings)useSettings(prefs.settings);
  if(prefs.weight_label){optionIfMissing($('dailyWeight'),prefs.weight_label);$('dailyWeight').value=prefs.weight_label;}
  $('teachSession').value=prefs.teach_session||newCaptureSession();if(!prefs.teach_session)await remember({teach_session:$('teachSession').value});
  await TeachingUI.refresh(prefs.last_bank_id||'');if(!bank&&banks.length===1)await TeachingUI.refresh(banks[0].id);
  if(prefs.last_project_id&&[...$('projects').options].some(x=>x.value===prefs.last_project_id))await openProject(prefs.last_project_id);
  changeMode('daily');refresh();
 }
 function optionIfMissing(el,value){if(![...el.options].some(o=>o.value===value))option(el,value,value);}
 async function beforeCreate(){if(!$('settingsConfirmed').checked){$('settingsPanel').open=true;throw Error('首次先核对本机设置；确认后保存，下次无需重填');}
  if(!$('name').value.trim())$('name').value=`${catalog.weapons[$('weapon').value].name} · ${$('pose').selectedOptions[0].textContent} · ${$('zoom').value}× · ${$('weightLabel').value}`.slice(0,80);
  await remember({settings:settings()});
 }
 function copied(){draft=true;$('settingsConfirmed').checked=true;settingsLabel();changeMode('tune');tab('setup');}
 for(const[id,m]of [['homeButton','daily'],['tuneButton','tune'],['teachButton','teach']])$(id).addEventListener('click',()=>changeMode(m));
 $('expertMode').addEventListener('change',()=>$('expertNav').hidden=!$('expertMode').checked);
 bind('continueTune',()=>{draft=false;changeMode('tune');showStep();});bind('newConfig',()=>{draft=true;$('name').value='';changeMode('tune');tab('setup');});bind('dailyTeach',()=>changeMode('teach'));bind('dailyWindows',async()=>{$('listwindows').click();});
 bind('guideNext',nextAction);bind('guideDetails',showStep);
 bind('dailyMonitor',()=>dailyStart('recognize'));bind('dailyRun',()=>dailyStart('auto_execute'));
 bind('duplicateConfig',async()=>{$('copySetup').click();});bind('dailyExport',async()=>{$('export').click();});
 bind('reviewEffect',()=>{changeMode('tune');tab('calibrate');});
 bind('quickRollback',async()=>{const id=current?.workflow?.recommended_rollback_id;if(!id)throw Error('请在高级版本列表中选择此前通过检查的版本');render(await api('select',{profile_id:id}));say('已恢复通过检查的版本；没有启用输出');});
 $('dailyWindow').addEventListener('change',()=>{$('windows').value=$('dailyWindow').value;invalidatePreview();refresh();});
 $('dailyBank').addEventListener('change',async()=>{try{await TeachingUI.refresh($('dailyBank').value||'');await remember({last_bank_id:$('dailyBank').value});}catch(e){say(e.message,true);}refresh();});
 $('dailyWeight').addEventListener('change',async()=>{$('teachWeight').value=$('dailyWeight').value;try{await remember({weight_label:$('dailyWeight').value});}catch(e){say(e.message,true);}refresh();});
 for(const id of [...Object.values(settingIds),'width','height'])$(id).addEventListener('input',()=>{$('settingsConfirmed').checked=false;settingsLabel();});
 $('settingsConfirmed').addEventListener('change',()=>{settingsLabel();refresh();});$('autoCalculate').addEventListener('change',refresh);
 window.addEventListener('lab-bank',banksChanged);window.addEventListener('lab-windows',windowsChanged);
 window.addEventListener('lab-busy',e=>{busy=e.detail;document.body.classList.toggle('busy',busy>0);refresh();});
 window.addEventListener('lab-status',e=>{lastStatus=e.detail;refresh();});
 window.addEventListener('lab-project',()=>{if(env&&current?.id!==lastProject){lastProject=current?.id;draft=false;if(lastProject)remember({last_project_id:lastProject}).catch(()=>{});}refresh();});
 for(const id of ['previewCanvas','windows','consent'])$(id).addEventListener('pointerup',()=>setTimeout(refresh,0));
 $('windows').addEventListener('change',windowsChanged);
 $('teachSession').addEventListener('change',()=>remember({teach_session:$('teachSession').value}).catch(e=>say(e.message,true)));
 $('teachNewSession').addEventListener('click',()=>setTimeout(()=>remember({teach_session:$('teachSession').value}).catch(()=>{}),0));
 return{init,refresh,beforeCreate,copied};
})();

if(window.labInitialized)Guidance.init(window.labEnvironment).catch(e=>say(e.message,true));else window.addEventListener('lab-ready',()=>Guidance.init(window.labEnvironment).catch(e=>say(e.message,true)),{once:true});
