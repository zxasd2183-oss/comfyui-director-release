"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const names = {
    pause_dispatch:"暂停后续调度",resume_dispatch:"恢复后续调度",
    hold_shot:"暂停镜头",release_shot:"解除镜头暂停",
    request_rework:"要求返工",approve_shot:"审核通过",add_note:"添加导演备注",
    plan_imported:"导入制作计划"
  };
  const stages = {planned:"待制作",queued:"已排队",rendering:"生成中",
    review:"待审片",approved:"审核通过",failed:"生成失败",done:"已完成"};
  let latest = null, selectedId = null, csrf = null, pending = null;
  const clock = () => {
    $("clock").textContent = new Date().toLocaleTimeString("zh-CN",{hour12:false});
  };
  setInterval(clock,1000); clock();

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if(className) node.className = className;
    if(text!==undefined) node.textContent = String(text);
    return node;
  }
  function render(data) {
    latest=data;
    const live=data.live||{}, gpu=live.gpu_power||{}, queue=live.comfy_queue||{};
    const active = gpu.ok===true && gpu.state==="Running";
    $("gpuValue").textContent=gpu.ok?String(gpu.state):"连接异常";
    $("gpuValue").className=active?"on":gpu.ok?"off":"error";
    $("gpuSub").textContent=gpu.ok?"CompShare · "+(gpu.gpu_type||"GPU"):"只读电源状态暂不可读";
    $("queueValue").textContent=queue.ok?
      String((queue.running??queue.queue_running??0)+(queue.pending??queue.queue_pending??0)):"—";
    $("queueSub").textContent=queue.ok?
      "运行 "+(queue.running??queue.queue_running??0)+" · 等待 "+(queue.pending??queue.queue_pending??0):
      (gpu.state==="Stopped"?"GPU 关机，工作室未运行":"GPU ComfyUI 后端不可用");
    const shots=data.shots||[], hold=shots.filter(x=>x.held).length;
    const rework=shots.filter(x=>x.review==="rework").length;
    $("shotCount").textContent=String(shots.length);
    $("shotSub").textContent=shots.length?"按生产计划顺序排列":"暂无计划，可从 CLI 导入";
    $("reviewCount").textContent=String(rework)+" / "+String(hold);
    $("dispatchState").textContent=data.dispatch_paused?"调度状态：已暂停":"调度状态：已放行";
    $("dispatchToggle").textContent=data.dispatch_paused?"▶ 允许后续调度":"Ⅱ 暂停后续调度";
    $("dispatchToggle").disabled=false;
    $("shotsTotal").textContent=shots.length+" SHOTS";
    renderShots(shots); renderInspector(shots); renderEvents(data.events||[]);
    renderProduction(data.production);
    $("streamLabel").textContent=(data.sample_age_seconds!==null&&data.sample_age_seconds>30)?
      "GPU 状态延迟 "+data.sample_age_seconds+"s":"实时已连接";
    $("streamDot").className="dot "+((data.sample_age_seconds===null||data.sample_age_seconds>30)?"bad":"good");
  }
  function renderProduction(production) {
    const counts = production?.counts || {};
    const num = key => Number.isSafeInteger(counts[key]) && counts[key] >= 0 ? counts[key] : 0;
    const totalAssets = num("assets");
    const audio = Number.isSafeInteger(production?.audio_asset_count) ?
      production.audio_asset_count : 0;
    $("productionCount").textContent = [
      num("projects"), num("episodes"), num("production_shots")
    ].join(" / ");
    $("visualAssets").textContent = String(Math.max(0, totalAssets-audio));
    $("audioAssets").textContent = String(audio);
    $("continuityCount").textContent = num("findings")+" / "+num("exceptions");
    const exceptionCounts = production?.exception_status || {};
    $("exceptionBrief").textContent = "待审 "+(exceptionCounts.draft||0)+
      " · 已批准 "+(exceptionCounts.approved||0)+
      " · 已过期 "+(exceptionCounts.stale||0);
    $("productionAudit").textContent = production?.audit_chain_verified === true ?
      "✓ 审计事件链校验通过" : "⚠ 审计链未通过验证或尚未加载";
    const kinds = production?.asset_kinds || {};
    $("productionAssetKinds").textContent = Object.keys(kinds).length ?
      "资产类型："+Object.keys(kinds).sort().join(" · ") : "资产类型：尚无已登记资产";
    $("productionMode").textContent=production?.mode==="read_only_production_summary" ?
      "正式制作台账 · 只读" : "制作数据不可用";

    const list=$("projectList");
    list.replaceChildren();
    const projects=production?.projects || [];
    const episodes=production?.episodes || [];
    if(!projects.length) {
      list.appendChild(el("div","production-empty",
        "尚未建立项目。可通过 VPS 本地管理命令创建项目和剧集。"));
      return;
    }
    for(const p of projects) {
      const row=el("div","project-item");
      const info=el("div","");
      info.appendChild(el("strong","",p.title));
      const related=episodes.filter(x=>x.project_id===p.project_id);
      const names=related.map(e=>e.episode_id+" "+e.title).join(" · ");
      info.appendChild(el("small","",names||"尚未建立剧集"));
      row.appendChild(info);
      row.appendChild(el("span","project-id",p.project_id));
      list.appendChild(row);
    }
  }
  function renderShots(shots) {
    const parent=$("shotList");
    parent.replaceChildren();
    if(!shots.length) {
      parent.appendChild(el("div","empty-state","暂无镜头数据。将 V0.7 plan.json 导入工作台后会出现逐镜头监控列表。"));
      return;
    }
    if(!shots.some(s=>s.id===selectedId))selectedId=shots[0].id;
    for(const s of shots) {
      const button=el("button","shot-item"+(s.id===selectedId?" selected":""));
      button.type="button";button.setAttribute("role","listitem");
      const count=el("span","shot-ordinal",String(s.position).padStart(2,"0"));
      const info=el("span","shot-info");
      info.appendChild(el("strong","", "镜头 "+s.id));
      info.appendChild(el("small","",s.seconds+" 秒 · "+(stages[s.stage]||s.stage)));
      const label=s.review==="rework"?"需返工":s.held?"已暂缓":
        s.review==="approved"?"已批准":"待制作";
      const state=el("span","shot-state "+(s.review==="rework"?"rework":s.held?"hold":
        s.review==="approved"?"approved":""),label);
      button.append(count,info,state);
      button.addEventListener("click",()=>{selectedId=s.id;renderShots(shots);renderInspector(shots);});
      parent.appendChild(button);
    }
  }
  function renderInspector(shots) {
    const s=shots.find(x=>x.id===selectedId);
    $("selectedShot").textContent=s?"#"+s.id:"—";
    $("selectedStage").textContent=s?
      (stages[s.stage]||s.stage)+" / "+(s.review==="rework"?"需返工":s.review==="approved"?"已批准":"待审"):"—";
    $("selectedRevision").textContent=s?"r"+s.revision:"—";
    $("viewerMain").textContent=s?"镜头 "+s.id:"未选择镜头";
    $("viewerSub").textContent=s?"预览桥尚未连接；目前可先记录导演决策":"选择左侧镜头，开始监管";
    $("holdBtn").disabled=!s; $("reworkBtn").disabled=!s;
    $("noteBtn").disabled=!s; $("approveBtn").disabled=!s||s.stage!=="review";
    $("holdBtn").textContent=s&&s.held?"▶ 解除镜头暂停":"Ⅱ 暂停当前镜头";
  }
  function renderEvents(events) {
    const parent=$("eventList"); parent.replaceChildren();
    if(!events.length){parent.appendChild(el("div","empty-state","尚无导演介入记录"));return;}
    for(const event of events){
      const item=el("div","event"),badge=el("span","event-icon","✧"),center=el("div","");
      center.appendChild(el("strong","",(names[event.action]||event.action)+
        (event.target?" · 镜头 "+event.target:"")));
      center.appendChild(el("p","",event.detail||"已记录操作"));
      const t=el("time","",new Date(event.at*1000).toLocaleString("zh-CN",{hour12:false}));
      item.append(badge,center,t);parent.appendChild(item);
    }
  }
  function openAction(action,shot) {
    pending={action,shot_id:shot?shot.id:null,revision:shot?shot.revision:null};
    $("dialogTitle").textContent=names[action]||"确认操作";
    const copy={
      pause_dispatch:"仅暂停工作台后续派单许可，不会中断已经提交到 ComfyUI 的任务。",
      resume_dispatch:"仅将未来派单许可改为放行。当前 V0.8 尚未连接自动 GPU 调度器。",
      hold_shot:"阻止此镜头被未来支持该账本的调度器选中，不影响已在 GPU 执行的任务。",
      release_shot:"解除此镜头的排程冻结，不会立即提交生成任务。",
      request_rework:"记录返工需求并冻结当前镜头，之后由制片调度器安排重新生成。",
      approve_shot:"确认已实际审阅的镜头产物，并保留版本审核记录。",
      add_note:"为当前镜头留下一条可追溯的监制意见。"
    };
    $("dialogDescription").textContent=copy[action]||"操作将记入工作台审计日志";
    $("reasonInput").value=""; $("dialogError").textContent="";
    $("reasonInput").required=["request_rework","add_note"].includes(action);
    $("dialogConfirm").disabled=false;
    $("actionDialog").showModal();
  }
  $("dispatchToggle").addEventListener("click",()=>{
    if(latest)openAction(latest.dispatch_paused?"resume_dispatch":"pause_dispatch",null);
  });
  const selected = ()=>latest?.shots?.find(x=>x.id===selectedId);
  $("holdBtn").addEventListener("click",()=>{
    const s=selected();if(s)openAction(s.held?"release_shot":"hold_shot",s);
  });
  $("reworkBtn").addEventListener("click",()=>{const s=selected();if(s)openAction("request_rework",s);});
  $("noteBtn").addEventListener("click",()=>{const s=selected();if(s)openAction("add_note",s);});
  $("approveBtn").addEventListener("click",()=>{const s=selected();if(s)openAction("approve_shot",s);});
  $("dialogCancel").addEventListener("click",()=>$("actionDialog").close());
  $("actionForm").addEventListener("submit",async event=>{
    event.preventDefault(); if(!pending||!csrf)return;
    $("dialogConfirm").disabled=true;
    const request={...pending,reason:$("reasonInput").value.trim(),csrf};
    if(!request.shot_id){delete request.shot_id;delete request.revision;}
    try{
      const response=await fetch("./api/v1/action",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(request),cache:"no-store"});
      const result=await response.json();
      if(!response.ok)throw Error(result.reason||"操作被拒绝");
      $("actionDialog").close();
      await refresh();
    }catch(error){
      const messages={stale_shot_revision:"镜头状态已变化，请重新选中镜头操作",
        review_artifact_not_verified:"尚未验证真实视频，不能直接审核通过",
        reason_required:"请填写介入原因"};
      $("dialogError").textContent=messages[error.message]||error.message;
    }finally{$("dialogConfirm").disabled=false;}
  });

  async function refresh() {
    const res=await fetch("./api/v1/snapshot",{cache:"no-store"});
    if(!res.ok)throw Error("snapshot_unavailable");
    render(await res.json());
  }
  async function start(){
    try{
      const r=await fetch("./api/v1/bootstrap",{cache:"no-store"});
      if(!r.ok)throw Error("No operator access");
      const b=await r.json(); csrf=b.csrf;
      if(b.mode==="microsoft_owner"){
        $("logoutMicrosoft").hidden=false;
        $("logoutMicrosoft").addEventListener("click",async()=>{
          if(!csrf)return;
          try{
            const result=await fetch("./auth/logout",{
              method:"POST",headers:{"X-CSRF-Token":csrf},cache:"no-store"});
            if(result.status===204)window.location.assign("./");
          }catch(_error){$("streamLabel").textContent="退出登录失败，请刷新页面";}
        });
      }
      await refresh();
      const es=new EventSource("./api/v1/stream");
      es.addEventListener("snapshot",event=>{
        try{render(JSON.parse(event.data));}catch(_error){/* next tick will recover */}
      });
      es.addEventListener("error",()=>{
        $("streamDot").className="dot bad";
        $("streamLabel").textContent="流断开，自动重连中";
      });
    }catch(_error){
      $("streamDot").className="dot bad";
      $("streamLabel").textContent="无法连接工作台服务";
    }
  }
  start();
})();
