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
  let microsoftOwner = false, selectedProductionEpisode = null, productionAction = null;
  let currentVisual = null;
  let visualFingerprint = "", visualScope = "", visualRefreshAt = 0;
  let visualRefreshInFlight = false;
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
      (microsoftOwner?"已验证所有者 · 可编辑项目":"制作数据 · 只读") : "制作数据不可用";
    $("createEpisodeBtn").disabled=!microsoftOwner ||
      !(production?.projects||[]).length;

    const list=$("projectList");
    list.replaceChildren();
    const projects=production?.projects || [];
    const episodes=production?.episodes || [];
    if(!projects.length) {
      list.appendChild(el("div","production-empty",
        microsoftOwner?"尚未建立项目。点击「新建项目」，开始第一部作品。":
        "尚未建立项目。请使用受保护的 Microsoft 网页登录创建。"));
      return;
    }
    for(const p of projects) {
      const wrap=el("div","project-entry");
      const row=el("div","project-item");
      const info=el("div","");
      info.appendChild(el("strong","",p.title));
      const related=episodes.filter(x=>x.project_id===p.project_id);
      info.appendChild(el("small","",related.length+" 集已登记 · 点击剧集查看分镜与资产"));
      row.appendChild(info);
      row.appendChild(el("span","project-id",p.project_id));
      wrap.appendChild(row);
      if(related.length) {
        const group=el("div","project-episodes");
        for(const e of related) {
          const button=el("button","project-episode-button",e.episode_id+" · "+e.title);
          button.type="button";
          button.setAttribute("aria-label","查看剧集 "+e.title);
          button.addEventListener("click",()=>loadEpisode(p.project_id,e.episode_id));
          group.appendChild(button);
        }
        wrap.appendChild(group);
      }
      list.appendChild(wrap);
    }
  }
  async function loadEpisode(projectId,episodeId) {
    const panel=$("episodeExplorer");
    panel.hidden=false;
    $("episodeExplorerTitle").textContent=episodeId+" · 读取中";
    $("episodeExplorerInfo").replaceChildren();
    $("episodeOutlinePanel").hidden=true;
    $("episodeOutlineBody").textContent="";
    $("episodeShotGrid").replaceChildren();
    $("episodeAssetSummary").replaceChildren();
    $("visualLibraryPanel").hidden=true;
    $("visualGallery").replaceChildren();
    visualScope = ""; visualFingerprint = "";
    try {
      const url="./api/v1/production/episode?project="+encodeURIComponent(projectId)
        +"&episode="+encodeURIComponent(episodeId);
      const response=await fetch(url,{cache:"no-store"});
      if(!response.ok)throw Error(response.status===401?
        "登录会话已过期，请重新登录":"剧集数据无法读取");
      const data=await response.json();
      selectedProductionEpisode={projectId,episodeId};
      const episode=data.episode||{};
      $("episodeExplorerTitle").textContent=(episode.title||episodeId)
        +" · "+episodeId;
      $("episodeExplorerStage").textContent=episode.stage==="planning"?
        "策划中":episode.stage||"制作中";
      const summary=$("episodeExplorerInfo");
      const duration=(data.shots||[]).reduce((acc,s)=>acc+s.duration_ms,0);
      summary.appendChild(el("span","", "镜头 "+data.shot_count));
      summary.appendChild(el("span","", "已登记时长 "+(duration/1000).toFixed(1)+" 秒"
        +(data.shots_truncated?"（部分展示）":"")));
      summary.appendChild(el("span","", "关联资产 "+data.assets.length
        +(data.assets_truncated?"+":"")));
      summary.appendChild(el("span","", "连续性异常 "+data.finding_count));
      const outline=data.outline||{};
      if(Number.isSafeInteger(outline.revision)&&outline.revision>0
          && typeof outline.body==="string") {
        $("episodeOutlinePanel").hidden=false;
        $("episodeOutlineRevision").textContent="DRAFT · V"+outline.revision;
        // Never interpret AI-provided content as HTML; no script execution.
        $("episodeOutlineBody").textContent=outline.body;
      }
      const shotGrid=$("episodeShotGrid");
      if(!data.shots.length)shotGrid.appendChild(
        el("div","production-empty","尚未导入分镜。可以在 VPS 使用审核后的 V0.7 计划安全导入。"));
      for(const shot of data.shots) {
        const tile=el("div","episode-shot-tile");
        tile.setAttribute("role","listitem");
        tile.appendChild(el("strong","","#"+shot.shot_id));
        tile.appendChild(el("span","", (shot.duration_ms/1000).toFixed(1)+"秒"));
        tile.appendChild(el("small","", stages[shot.stage]||shot.stage));
        shotGrid.appendChild(tile);
      }
      const assets=$("episodeAssetSummary");
      assets.appendChild(el("strong","", "已绑定视听资产版本"));
      if(!data.assets.length)assets.appendChild(
        el("span","","尚无角色、声线或场景资产绑定"));
      for(const asset of data.assets) {
        assets.appendChild(el("span","asset-chip",
          asset.kind+" · "+asset.subject_id+" · V"+asset.version));
      }
      if(microsoftOwner) await loadVisuals(projectId,episodeId);
    } catch(err) {
      $("episodeExplorerTitle").textContent="无法读取剧集";
      $("episodeExplorerInfo").textContent=err.message;
    }
  }

  function visualURL(projectId,episodeId,id) {
    return "./api/v1/production/visual?project="+encodeURIComponent(projectId)
      +"&episode="+encodeURIComponent(episodeId)+"&id="+encodeURIComponent(id);
  }

  async function loadVisuals(projectId,episodeId,{automatic=false}={}) {
    const panel=$("visualLibraryPanel"), gallery=$("visualGallery");
    if(!microsoftOwner){panel.hidden=true;return;}
    if(visualRefreshInFlight || (automatic && $("visualUploadBtn").disabled))return;
    visualRefreshInFlight=true;
    try {
    const response=await fetch("./api/v1/production/visuals?project="
      +encodeURIComponent(projectId)+"&episode="+encodeURIComponent(episodeId),
      {cache:"no-store"});
    if(!response.ok) {
      if(!automatic)$("visualMessage").textContent="素材库暂时不可用，请检查登录状态或服务版本。";
      return;
    }
    const data=await response.json(), visuals=data.visuals||[];
    if(!selectedProductionEpisode ||
       selectedProductionEpisode.projectId!==projectId ||
       selectedProductionEpisode.episodeId!==episodeId)return;
    const scope=projectId+"/"+episodeId;
    const fingerprint=JSON.stringify(visuals.map(v=>
      [v.visual_id,v.version,v.selected,v.source,v.sha256]));
    if(!panel.hidden && visualScope===scope && visualFingerprint===fingerprint)return;
    visualScope=scope;visualFingerprint=fingerprint;
    panel.hidden=false;
    gallery.replaceChildren();
    $("visualCount").textContent=visuals.length+(data.truncated?"+":"")+" 张图片";
    $("visualMessage").textContent=visuals.length?
      "点击图片可放大，并将确认的版本设为正式参考。":
      "本集暂无已上传图片。请先把之前生成的 PNG/JPG 图片上传一次；不会触发 GPU。";
    if(!visuals.length)gallery.appendChild(el("p","production-empty","暂无图片：角色、场景、分镜图可以从上方上传。"));
    const kindName={character:"角色",scene:"场景",storyboard:"分镜"};
    for(const v of visuals) {
      const button=el("button","visual-card"+(v.selected?" selected":""));
      button.type="button";
      button.setAttribute("aria-label","预览 "+v.filename+" 版本"+v.version);
      const preview=el("img","visual-thumb");
      preview.loading="lazy";preview.alt=v.filename;
      preview.src=visualURL(projectId,episodeId,v.visual_id);
      button.appendChild(preview);
      button.appendChild(el("strong","",v.subject_id+" · V"+v.version));
      button.appendChild(el("small","",(kindName[v.kind]||v.kind)+" · "+(v.source||"Studio")));
      button.appendChild(el("span","visual-status",v.selected?"★ 正式参考":"候选版本"));
      button.addEventListener("click",()=>{
        currentVisual={...v,projectId,episodeId};
        $("visualPreviewTitle").textContent=v.filename;
        $("visualPreviewImg").src=visualURL(projectId,episodeId,v.visual_id);
        $("visualPreviewInfo").textContent=
          (kindName[v.kind]||v.kind)+" / "+v.subject_id+" / V"+v.version;
        $("visualApproveBtn").disabled=v.selected;
        $("visualApproveBtn").textContent=v.selected?"当前正式参考":"设为正式参考图";
        $("visualPreviewDialog").showModal();
      });
      gallery.appendChild(button);
    }
    } finally {visualRefreshInFlight=false;}
  }
  $("visualKind").addEventListener("change",()=>{
    const byKind={character:"CHAR_GEM",scene:"SCN_HALL",storyboard:"SH01"};
    $("visualSubject").value=byKind[$("visualKind").value]||"CHAR_GEM";
  });
  $("visualPreviewClose").addEventListener("click",()=>{
    $("visualPreviewDialog").close();
    $("visualPreviewImg").removeAttribute("src");
  });
  $("visualApproveBtn").addEventListener("click",async()=>{
    const v=currentVisual;
    if(!v||!microsoftOwner||!csrf||v.selected)return;
    $("visualApproveBtn").disabled=true;
    try {
      const response=await fetch("./api/v1/production/visual/select",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({csrf,project_id:v.projectId,episode_id:v.episodeId,
                             visual_id:v.visual_id}),cache:"no-store"});
      const out=await response.json();
      if(!response.ok)throw Error(out.reason||"无法保存正式参考");
      $("visualPreviewDialog").close();
      $("visualPreviewImg").removeAttribute("src");
      await loadVisuals(v.projectId,v.episodeId);
    } catch(err) {
      $("visualPreviewInfo").textContent="保存失败："+err.message;
      $("visualApproveBtn").disabled=false;
    }
  });
  function fileAsBase64(file) {
    return new Promise((resolve,reject)=>{
      const reader=new FileReader();
      reader.onerror=()=>reject(Error("读取文件失败"));
      reader.onload=()=>resolve(String(reader.result).split(",")[1]||"");
      reader.readAsDataURL(file);
    });
  }
  $("visualUploadForm").addEventListener("submit",async event=>{
    event.preventDefault();
    const ref=selectedProductionEpisode;
    if(!microsoftOwner||!csrf||!ref)return;
    const subject=$("visualSubject").value.trim();
    if(!/^[A-Za-z][A-Za-z0-9_-]{1,47}$/.test(subject)){
      $("visualMessage").textContent="编号须使用字母开头的字母、数字、下划线或连字符。";
      return;
    }
    const files=Array.from($("visualFiles").files||[]);
    if(!files.length)return;
    const btn=$("visualUploadBtn");
    btn.disabled=true;
    let uploaded=0;
    try {
      for(let i=0;i<files.length;i++){
        const f=files[i];
        if(f.size<32||f.size>8*1024*1024)
          throw Error(f.name+"：仅支持 8MB 以内的图片");
        if(!["image/png","image/jpeg","image/webp"].includes(f.type))
          throw Error(f.name+"：不支持此格式");
        $("visualMessage").textContent="上传中 "+(i+1)+"/"+files.length+" · "+f.name;
        const image_base64=await fileAsBase64(f);
        const response=await fetch("./api/v1/production/visual/upload",{
          method:"POST",headers:{"Content-Type":"application/json"},
          body:JSON.stringify({csrf,project_id:ref.projectId,
            episode_id:ref.episodeId,kind:$("visualKind").value,
            subject_id:subject,filename:f.name,image_base64}),cache:"no-store"});
        const out=await response.json();
        if(!response.ok)throw Error(f.name+"："+(out.reason||"上传失败"));
        uploaded++;
      }
      $("visualFiles").value="";
      await loadVisuals(ref.projectId,ref.episodeId);
      $("visualMessage").textContent="成功上传 "+uploaded+" 张；原有版本和正式参考均未覆盖。";
    } catch(err) {
      $("visualMessage").textContent="已上传 "+uploaded+" 张；"+err.message;
      await loadVisuals(ref.projectId,ref.episodeId);
      $("visualMessage").textContent="已上传 "+uploaded+" 张；"+err.message;
    } finally {btn.disabled=false;}
  });

  function openProductionEditor(action,projectId=null) {
    if(!microsoftOwner||!csrf)return;
    productionAction=action;
    const episode=action==="create_episode";
    const projects=latest?.production?.projects||[];
    if(episode&&!projects.length)return;
    $("productionDialogTitle").textContent=episode?"添加剧集":"创建新项目";
    $("productionDialogDescription").textContent=episode?
      "为现有短剧项目建立一集。你可以之后安全导入已审核分镜计划。":
      "创建正式项目档案。所有项目和剧集更改都会写入审计链。";
    $("productionIdLabel").textContent=episode?"剧集编号":"项目编号";
    $("productionIdInput").value=episode?"EP01":"";
    $("productionIdInput").placeholder=episode?"例如 EP01":"例如 WaitingOffice";
    $("productionTitleInput").value="";
    $("productionTitleInput").placeholder=episode?"例如 第一集":"例如 待回答事务所";
    $("productionParentFields").hidden=!episode;
    $("productionFormError").textContent="";
    const selector=$("productionProjectSelect");
    selector.replaceChildren();
    for(const p of projects) {
      const option=document.createElement("option");
      option.value=p.project_id;option.textContent=p.title+" ("+p.project_id+")";
      selector.appendChild(option);
    }
    if(projectId&&projects.some(x=>x.project_id===projectId))
      selector.value=projectId;
    $("productionOrdinalInput").value=episode?
      String((latest?.production?.episodes||[]).filter(
        e=>e.project_id===selector.value).length+1):"";
    $("productionSubmit").disabled=false;
    $("productionDialog").showModal();
    $("productionIdInput").focus();
  }
  $("createProjectBtn").addEventListener("click",()=>openProductionEditor("create_project"));
  $("createEpisodeBtn").addEventListener("click",()=>openProductionEditor("create_episode"));
  $("productionCancel").addEventListener("click",()=>$("productionDialog").close());
  $("productionProjectSelect").addEventListener("change",()=>{
    $("productionOrdinalInput").value=String((latest?.production?.episodes||[])
      .filter(e=>e.project_id===$("productionProjectSelect").value).length+1);
  });
  $("productionForm").addEventListener("submit",async event=>{
    event.preventDefault();
    if(!microsoftOwner||!productionAction||!csrf)return;
    const inputId=$("productionIdInput").value.trim();
    const title=$("productionTitleInput").value.trim();
    const error=$("productionFormError");
    const validId=/^[A-Za-z][A-Za-z0-9_-]{1,47}$/;
    if(!validId.test(inputId)) {
      error.textContent="编号必须以英文字母开头，且为 2–48 位字母、数字、下划线或连字符";
      return;
    }
    if(!title||title.length>160||/[\u0000-\u001f]/.test(title)) {
      error.textContent="请输入 1–160 字的项目或剧集名称";return;
    }
    let data={action:productionAction,csrf,title};
    if(productionAction==="create_project")data.project_id=inputId;
    else {
      const ordinal=Number($("productionOrdinalInput").value);
      if(!Number.isInteger(ordinal)||ordinal<1||ordinal>1000) {
        error.textContent="剧集序号必须在 1–1000 之间";return;
      }
      data={...data,project_id:$("productionProjectSelect").value,
            episode_id:inputId,ordinal};
    }
    $("productionSubmit").disabled=true;
    error.textContent="";
    try {
      const response=await fetch("./api/v1/production/action",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(data),cache:"no-store"
      });
      const result=await response.json();
      if(!response.ok)throw Error(response.status===401?"会话已过期，请重新登录":
        ({already_exists_or_invalid_parent:"编号或剧集序号已存在，请更换",
          invalid_identifier:"编号不符合要求",
          invalid_text:"名称不能为空",
          audit_integrity_failure:"审计链校验失败，已禁止写入；需要管理员检查备份"
        }[result.reason]||result.reason||"无法保存制作工程"));
      $("productionDialog").close();
      await refresh();
      if(productionAction==="create_project")
        openProductionEditor("create_episode",result.project_id);
      else await loadEpisode(result.project_id,result.episode_id);
    }catch(err) {
      error.textContent=err.message;
    }finally {$("productionSubmit").disabled=false;}
  });

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
      microsoftOwner=b.mode==="microsoft_owner";
      $("createProjectBtn").hidden=!microsoftOwner;
      $("createEpisodeBtn").hidden=!microsoftOwner;
      if(microsoftOwner){
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
        // The browser gallery is separate from the V0.9 assets ledger.
        // Poll its owner-only index at most every 4s while the EP is visible.
        // Repaint only if the actual image/version inventory changed.
        if(microsoftOwner && selectedProductionEpisode &&
           document.visibilityState!=="hidden" &&
           Date.now()-visualRefreshAt>=4000){
          visualRefreshAt=Date.now();
          const {projectId,episodeId}=selectedProductionEpisode;
          loadVisuals(projectId,episodeId,{automatic:true}).catch(()=>{});
        }
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
