'use strict';
// Preparation and recovery UI only. No persisted permission or automatic retry.
window.CaptureHelp=(()=>{
 let running=false;
 function batchCount(){
  const c=current?.workflow?.counts||{};
  const done=current?.active_profile?(c.new_train||0):(c.train||0);
  return Math.max(1,Math.min(3,3-done));
 }
 function refresh(){
  const button=$('batchTrain');
  button.textContent=`一次准备，补录 ${batchCount()} 轮未补偿试射`;
  button.disabled=!window.labEnvironment?.native_available||!current||current.demo||!!poll||running;
  $('checkPreparation').disabled=!!poll||running;
  $('exportDiagnostic').disabled=!!poll||running;
 }
 function mode(){return {record_response:'response',record_train:'train',record_validation:'validation'}[current?.workflow?.step]||'train';}
 async function prepare(){
  const r=await api('preflight',{mode:mode(),hwnd:+$('windows').value,consent:$('consent').checked,roi,duration_s:+$('duration').value});
  const box=$('preflightResult');box.replaceChildren();
  const title=document.createElement('strong');title.textContent=r.ready?'准备项已齐；还未启动，也没有发送输入。':'先处理下面未完成的项目：';box.append(title);
  for(const item of r.checks){const p=document.createElement('p');p.textContent=(item.passed?'✓ ':'○ ')+item.name+'：'+item.hint;box.append(p);}
 }
 async function batch(){
  requireProject();
  await native('train_batch',{count:batchCount(),sound:$('captureSound').checked});
 }
 function status(s){
  const box=$('recoveryPanel');
  box.hidden=!s.recovery;
  if(s.recovery){
   $('recoveryTitle').textContent=s.recovery.title;
   $('recoveryHint').textContent=s.recovery.hint;
   $('savedRounds').textContent=`本组已保存 ${s.completed||0}/${s.total||1} 轮。无效轮次不计数；不会自行重试。`;
  }
  if(s.mode==='train_batch'||s.countdown_s){
   const detail=s.countdown_s?`准备倒计时 ${s.countdown_s} 秒`:`已保存 ${s.completed||0}/${s.total||1} 轮${s.waiting?' · 等待你准备下一轮':''}`;
   $('captureProgress').textContent=detail+'\n'+s.message;
  }else $('captureProgress').textContent=s.message;
  refresh();
 }
 bind('batchTrain',batch);
 bind('checkPreparation',prepare);
 bind('exportDiagnostic',async()=>{
  const r=await api('diagnostic');
  download('RecoilLab-诊断摘要.txt',JSON.stringify(r,null,2),'text/plain;charset=utf-8');
  say('已导出无图片诊断；不含窗口标题、路径、账号或原始错误，不会自动上传。');
 });
 bind('retryPreparation',async()=>{
  if(poll)throw Error('请等待停止完成后再检查');
  tab('capture');await prepare();
  say('已重新检查准备项；请主动点击需要的采集按钮，不会自动续录。');
 });
 window.addEventListener('lab-project',refresh);
 window.addEventListener('lab-ready',refresh);
 window.addEventListener('lab-status',e=>status(e.detail));
 window.addEventListener('lab-busy',e=>{running=e.detail>0;refresh();});
 return{refresh,status,startBatch:batch};
})();
