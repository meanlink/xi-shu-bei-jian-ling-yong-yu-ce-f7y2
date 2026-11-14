import {datasets,quarantines} from '../api/entities.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {status} from '../components/common/status.js';

const isAdmin=()=>session.user.role==='admin';

function progressBlock(q){
 const steps=q.progress?.steps||[];
 return '<div class="progress-steps">'+steps.map(s=>'<div class="'+(s.done?'done':'')+(s.key===q.progress.current?' current':'')+'"><span>'+esc(s.label)+'</span><small>'+(s.done?'已处置':s.key===q.progress.current?'进行中':'待办')+'</small></div>').join('')+'</div>';
}

function affectedBlock(q){
 const jobsList=q.affected?.jobs||[],reportList=q.affected?.reports||[],deliveryList=q.affected?.deliveries||[];
 return '<div class="affected-grid"><div><h3>受影响试算</h3>'+(jobsList.length?jobsList.map(j=>'<div class="affected-row"><div><strong>'+esc(j.name)+'</strong><small>'+status(j.status)+' · '+(j.approved?'已批准':'已撤销批准')+'</small></div><small>#'+j.id+'</small></div>').join(''):'<p class="empty">无关联试算</p>')+'</div>'+
 '<div><h3>受影响计划</h3>'+(reportList.length?reportList.map(r=>'<div class="affected-row"><div><strong>'+esc(r.name)+'</strong><small>'+esc(r.destination)+' · '+(r.enabled?'仍启用':'已停用')+'</small></div><small>#'+r.id+'</small></div>').join(''):'<p class="empty">无关联分发计划</p>')+'</div>'+
 '<div><h3>受影响归档</h3>'+(deliveryList.length?deliveryList.map(d=>'<div class="affected-row"><div><strong>'+esc(d.filename)+'</strong><small>'+date(d.created_at)+' · 保留追查</small></div><small>#'+d.id+'</small></div>').join(''):'<p class="empty">无关联归档</p>')+'</div></div>';
}

function replacementBlock(q){
 const r=q.replacement;
 if(!r)return '<p class="hint">修正日历应另建数据批次，再在下方关联为处置去向；原批次不会恢复。</p>';
 return '<div class="replacement-note"><p><strong>关联去向</strong> '+esc(r.dataset_name||('批次 #'+r.dataset_id))+'</p><p>'+(r.approved_job_id?'新结果已重新批准（#'+r.approved_job_id+'）':'等待负责人重新批准修正批次的分析结果')+'</p><p>'+(r.report_id?'新分发计划已重新启用（#'+r.report_id+'），后续归档可下载':'尚未启用新的分发计划')+'</p></div>';
}

export async function quarantinePage(){
 const list=await quarantines.list();
 const batches=await datasets.list();
 const openBatches=batches.filter(d=>!d.quarantined);
 const replacementOptions=batches.filter(d=>!d.quarantined);
 const form='<section class="panel"><div class="section-title"><h2>隔离问题批次</h2><span>仅业务负责人</span></div>'+
  (isAdmin()?
   '<form id="quarantine-form"><label>问题数据批次<select name="dataset_id" required>'+openBatches.map(d=>'<option value="'+d.id+'">'+esc(d.name)+' · '+d.rows+' 条</option>').join('')+'</select></label>'+
   '<label>失真原因<textarea name="reason" rows="3" minlength="5" maxlength="500" required placeholder="例如：领用日历缺失零需求日，日均领用被系统性高估"></textarea></label>'+
   '<label>修正批次（可选，须在隔离后另建）<select name="replacement_dataset_id"><option value="">稍后关联</option>'+replacementOptions.map(d=>'<option value="'+d.id+'">'+esc(d.name)+'</option>').join('')+'</select></label>'+
   '<button type="submit" class="primary" '+(openBatches.length?'':'disabled')+'>确认隔离并停用下游 ↗</button>'+
   '<p class="hint">隔离生效后拒绝该批次的新试算、批准与分发；已有归档保留追查但停止下载。重试不会重复记账。</p></form>'
  :'<p class="empty">观察员与分析员只能查看处置进度，隔离操作需业务负责人执行。</p>')+'</section>';
 const items=list.length?list.map(q=>'<article class="quarantine-card panel"><div class="section-title"><h2>'+esc(q.dataset_name||('批次 #'+q.dataset_id))+'</h2><span>隔离于 '+date(q.effective_at)+' · '+esc(q.created_by)+'</span></div>'+
   '<p class="quarantine-reason">原因：'+esc(q.reason)+'</p>'+
   progressBlock(q)+
   '<div class="quarantine-counts"><span>'+q.counts.jobs+' 个试算</span><span>'+q.counts.reports+' 个计划</span><span>'+q.counts.deliveries+' 份归档</span></div>'+
   affectedBlock(q)+
   replacementBlock(q)+
   (isAdmin()&&!q.replacement_dataset_id&&replacementOptions.filter(d=>d.id!==q.dataset_id).length?'<form class="replacement-form" data-replacement="'+q.id+'"><label>关联修正批次<select name="dataset_id" required>'+replacementOptions.filter(d=>d.id!==q.dataset_id).map(d=>'<option value="'+d.id+'">'+esc(d.name)+'</option>').join('')+'</select></label><button type="submit" class="button small">登记去向</button></form>':'')+
   '</article>').join(''):'<section class="panel empty">还没有隔离处置。先选择失真批次并填写原因。</section>';

 return heading('06 / QUARANTINE','问题批次隔离处置','隔离失真的领用日历批次，阻断新试算、批准与分发，并保留受影响结果的追查线索。')+form+items;
}

export function bindQuarantine(refresh){
 const form=document.querySelector('#quarantine-form');
 if(form)submit(form,async f=>{
  const replacement=f.get('replacement_dataset_id');
  const result=await quarantines.create({dataset_id:Number(f.get('dataset_id')),reason:f.get('reason')});
  if(replacement&&result.replacement_dataset_id==null)await quarantines.replacement(result.id,Number(replacement));
  notify('隔离已生效，下游试算、批准与分发已停用');await refresh();
 });
 document.querySelectorAll('[data-replacement]').forEach(f=>submit(f,async data=>{
   const datasetId=f.getAttribute('data-replacement'),batchId=Number(data.get('dataset_id'));
   await quarantines.replacement(datasetId,batchId);
   notify('已登记修正批次去向');await refresh();
 }));
}
