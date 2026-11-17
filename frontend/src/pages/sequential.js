import {store,load} from '../stores/research.js';
import {sequential} from '../api/research.js';
import {studySelect} from '../components/common/study-select.js';
import {table} from '../components/common/table.js';
import {esc,fmt} from '../utils/format.js';
import {bindForm} from '../hooks/forms.js';

const PLAN_STATUS={active:'进行中 · 可依次揭盲',stopped:'已停试 · 仅诊断'};
const STOP_LABELS={significant:'达显著停试',looks_exhausted:'查看次数与额度耗尽'};

function planRows(){
  return table(['编号 / 方案','状态','查看次数','额度 已用/上限','停试依据'],
    store.plans.map(p=>[
      {html:`<a href="#sequential/${p.id}">#${p.id} ${esc(p.name)}</a>`},
      {html:`<span class="status ${p.status}">${PLAN_STATUS[p.status]||p.status}</span>`},
      `${p.looks.length} 次 · 已揭盲 ${p.unblinded_count??0} 次`,
      `${fmt(p.alpha_spent_value)} / ${fmt(p.alpha_total_value)}（剩 ${fmt(p.alpha_remaining_value)}）`,
      p.stop_reason?`${STOP_LABELS[p.stop_reason]||p.stop_reason} · 第${p.stop_stage}次`: '—',
    ]));
}

export async function render(id){
  await load();
  const writable=localStorage.getItem('research-role')!=='viewer';
  if(!id) return listView(writable);
  const p=await sequential.get(id);
  return detailView(p,writable);
}

function listView(writable){
  return `<div class="eyebrow">06 / PRE-REGISTERED SEQUENTIAL TEST</div>
  <h1>预注册分阶段检验</h1>
  <p class="lead">开始前锁定各次查看的双组累计触达门槛与显著性额度，各次额度合计不得超过研究上限；达门槛才可依次揭盲，按当次额度作双侧两比例检验。并发揭盲与重试不重复扣额，数据更正只作诊断、已揭盲额度不退、原结论保留。</p>
  <div class="method-note">一旦显著或用完查看次数即停试；迟归结果只能走更正诊断，不得重开研究。显著性额度按百万分位整数记账，杜绝浮点漂移超额。</div>
  ${writable?`<details ${store.plans.length?'':'open'}><summary>注册新的分阶段方案（锁定后不可修改）</summary>
  <form id="plan-form" class="worksheet">
    ${studySelect()}
    <label>方案名称<input name="name" required minlength="2" value="榆灯·分阶段预注册 ${new Date().toISOString().slice(0,10)}"></label>
    <div class="inline-form">
      <label>研究显著性上限 α (0–1]<input name="alpha_total" type="number" step="any" min="0.000001" max="1" value="0.05" required></label>
      <label>查看次数 (1–20)<input name="look_count" type="number" step="1" min="1" max="20" value="3" required></label>
    </div>
    <div id="look-rows"></div>
    <p id="alpha-sum" class="checksum"></p>
    <button type="submit">锁定门槛与额度并注册 →</button>
  </form></details>`:''}
  <h2>已注册方案</h2>${planRows()}`;
}

function lookEditor(count){
  const defaults=[[4000,4000,0.01],[8000,8000,0.015],[12000,12000,0.025]];
  let html='<div class="table-wrap"><table><thead><tr><th>查看次序</th><th>A组累计触达门槛</th><th>B组累计触达门槛</th><th>当次显著性额度 αₖ</th></tr></thead><tbody>';
  for(let i=1;i<=count;i++){
    const d=defaults[i-1]||[4000*i,4000*i,0.01];
    html+=`<tr><td>第 ${i} 次</td>
      <td><input name="reach_a_${i}" type="number" step="1" min="1" value="${d[0]}" required></td>
      <td><input name="reach_b_${i}" type="number" step="1" min="1" value="${d[1]}" required></td>
      <td><input name="alpha_${i}" type="number" step="any" min="0.000001" max="1" value="${d[2]}" required></td></tr>`;
  }
  return html+'</tbody></table></div>';
}

function detailView(p,writable){
  const stopBlock=p.status==='stopped'
    ?`<div class="method-note"><strong>停试依据：${esc(STOP_LABELS[p.stop_reason]||p.stop_reason)}（第 ${p.stop_stage} 次查看）</strong><p>${esc(p.stop_note)}</p><small>研究已关闭，迟归结果不得重开；数据更正仅生成诊断。</small></div>`
    :`<div class="method-note">研究进行中，下一次可揭盲：第 ${p.next_stage} 次查看。必须依次揭盲，不得跳次。</div>`;
  const lookTable=table(['查看','A组门槛','B组门槛','当次额度','状态'],
    p.looks.map(l=>[`第${l.stage}次`,fmt(l.reach_a),fmt(l.reach_b),fmt(l.alpha_k_value),
      l.unblinded?{html:'<span class="status completed">已揭盲 · 已扣额</span>'}:{html:'<span class="status">待揭盲</span>'}]));
  const unblindTable=table(['查看','采用数据版本 (A触达/A点击/B触达/B点击)','数据校验','额度','z','p 值','当次临界 z','结论'],
    p.unblindings.map(u=>[
      `第${u.stage}次`,
      `${fmt(u.data_version.reach_a)} / ${fmt(u.data_version.click_a)} / ${fmt(u.data_version.reach_b)} / ${fmt(u.data_version.click_b)}`,
      u.data_checksum.slice(0,16),
      fmt(u.result.alpha_k),
      fmt(u.result.z),
      fmt(u.result.p_value),
      fmt(u.result.critical_z),
      u.significant?{html:'<span class="status completed">显著 · 停试</span>'}:{html:'<span class="status">不显著 · 继续</span>'},
    ]));
  const corrTable=p.corrections.length?table(['更正编号','查看','更正后数据','诊断 p 值','诊断结论','说明','操作人 / 时间'],
    p.corrections.map((c,i)=>[
      `#${c.id}`,
      `第${c.stage}次`,
      `${fmt(c.corrected_version.reach_a)}/${fmt(c.corrected_version.click_a)} · ${fmt(c.corrected_version.reach_b)}/${fmt(c.corrected_version.click_b)}`,
      fmt(c.diagnostic.p_value),
      c.diagnostic.significant?'诊断显著（不改变原结论）':'诊断不显著',
      esc(c.note||'—'),
      `${esc(c.author)} · ${esc(c.created_at)}`,
    ])):'';
  const forms=writable?p.looks.map(l=>{
    if(!l.unblinded){
      if(p.status!=='active'||l.stage!==p.next_stage) return '';
      return `<form id="unblind-form" class="worksheet" data-stage="${l.stage}">
        <h2>第 ${l.stage} 次查看 · 录入实际累计触达与点击并揭盲</h2>
        <div class="inline-form">
          <label>A组累计触达（门槛 ${fmt(l.reach_a)}）<input name="reach_a" type="number" step="1" min="0" value="${l.reach_a}" required></label>
          <label>A组累计点击<input name="click_a" type="number" step="1" min="0" required></label>
          <label>B组累计触达（门槛 ${fmt(l.reach_b)}）<input name="reach_b" type="number" step="1" min="0" value="${l.reach_b}" required></label>
          <label>B组累计点击<input name="click_b" type="number" step="1" min="0" required></label>
        </div>
        <p>揭盲按当次额度 <strong>${fmt(l.alpha_k_value)}</strong> 作双侧检验；扣额与结论同时生效，重试同版数据不重复扣额。</p>
        <button type="submit">达门槛，揭盲并检验 →</button>
      </form>`;
    }
    return `<details><summary>第 ${l.stage} 次查看数据更正（诊断重算，不退额、不改原结论）</summary>
      <form class="worksheet correction-form" data-stage="${l.stage}">
        <div class="inline-form">
          <label>A组累计触达<input name="reach_a" type="number" step="1" min="0" value="${l.reach_a}" required></label>
          <label>A组累计点击<input name="click_a" type="number" step="1" min="0" required></label>
          <label>B组累计触达<input name="reach_b" type="number" step="1" min="0" value="${l.reach_b}" required></label>
          <label>B组累计点击<input name="click_b" type="number" step="1" min="0" required></label>
        </div>
        <label>更正说明（可选）<input name="note" maxlength="2000" placeholder="如：上游修订点击口径 / 迟归补录"></label>
        <button type="submit">提交更正诊断 →</button>
      </form></details>`;
  }).join(''):'';
  return `<div class="eyebrow">06 / SEQUENTIAL PLAN #${p.id}</div>
  <h1>${esc(p.name)} <span class="status ${p.status}">${PLAN_STATUS[p.status]||p.status}</span></h1>
  <div class="checksum">研究上限 α=${fmt(p.alpha_total_value)} · 已扣额度=${fmt(p.alpha_spent_value)} · 剩余额度=${fmt(p.alpha_remaining_value)} · 注册人 ${esc(p.created_by)} · ${esc(p.created_at)}</div>
  ${stopBlock}
  <h2>预注册锁定的查看门槛与额度</h2>${lookTable}
  ${forms}
  <h2>各次揭盲采用的数据与检验结论</h2>${p.unblindings.length?unblindTable:'<p class="method-note">尚无揭盲记录。</p>'}
  <h2>数据更正诊断 <small>原结论与已扣额度始终保留</small></h2>${corrTable||'<p class="method-note">暂无更正。</p>'}
  <div class="toolbar"><a class="button secondary" href="#sequential">← 返回方案列表</a></div>`;
}

export function bind(refresh){
  const countInput=document.querySelector('[name=look_count]');
  const rows=document.getElementById('look-rows');
  const sum=document.getElementById('alpha-sum');
  if(countInput&&rows){
    const paint=()=>{
      const n=Math.max(1,Math.min(20,parseInt(countInput.value||'1',10)));
      rows.innerHTML=lookEditor(n);
      const total=Array.from(rows.querySelectorAll('input[name^=alpha_]'))
        .reduce((s,x)=>s+(parseFloat(x.value)||0),0);
      const cap=parseFloat(document.querySelector('[name=alpha_total]').value)||0;
      sum.textContent=`各次额度合计 ${total.toFixed(6)} / 研究上限 ${cap} —— ${total<=cap?'未超额，可以锁定':'已超额，必须下调额度'}`;
      sum.style.color=total<=cap?'':'oklch(45% .16 25)';
    };
    countInput.onchange=paint;
    document.querySelector('[name=alpha_total]').onchange=paint;
    paint();
    rows.addEventListener('input',e=>{if(e.target.name&&e.target.name.startsWith('alpha_'))paint();});
  }
  bindForm('plan-form',async data=>{
    const n=Math.max(1,Math.min(20,parseInt(data.look_count,10)));
    const looks=[];
    for(let i=1;i<=n;i++){
      looks.push({stage:i,reach_a:+data[`reach_a_${i}`],reach_b:+data[`reach_b_${i}`],alpha_k:+data[`alpha_${i}`]});
    }
    const p=await sequential.create({study_id:+data.study_id,name:data.name,alpha_total:+data.alpha_total,looks});
    await load();location.hash='sequential/'+p.id;
  });
  bindForm('unblind-form',async data=>{
    const id=Number(location.hash.split('/')[1]);
    const stage=Number(document.getElementById('unblind-form').dataset.stage);
    await sequential.unblind(id,stage,{reach_a:+data.reach_a,click_a:+data.click_a,reach_b:+data.reach_b,click_b:+data.click_b});
    await load();refresh();
  });
  document.querySelectorAll('.correction-form').forEach(form=>{
    form.onsubmit=async e=>{
      e.preventDefault();
      try{
        const id=Number(location.hash.split('/')[1]);
        const d=Object.fromEntries(new FormData(form));
        await sequential.correct(id,+form.dataset.stage,
          {reach_a:+d.reach_a,click_a:+d.click_a,reach_b:+d.reach_b,click_b:+d.click_b,note:d.note||''});
        await load();refresh();
      }catch(err){document.getElementById('notice').textContent=err.message;}
    };
  });
}
