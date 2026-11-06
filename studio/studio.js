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
  let characterProjectId = "", characterCurrentId = "", characterData = null;
  let characterEditingId = null;
  let sceneProjectId = "", sceneCurrentId = "", sceneData = null, sceneEditId = null;
  let sceneEpisodes = [];
  let sceneActiveVisualId = "";
  let shotBindingData=null, shotBindingCharacters=[], shotBindingFocus=null;
  let characterV2Data = null, characterV2Category = "profile";
  let characterActiveVisualId = "";
  let visualFingerprint = "", visualScope = "", visualRefreshAt = 0;
  let visualRefreshInFlight = false;
  let homeEpisodeScope="",homeTaskScope="",homeTaskInFlight=false;
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
    $("headerGpuStatus").textContent = gpu.ok ?
      "GPU · "+(gpu.state==="Stopped"?"已关机":
        gpu.state==="Running"?"运行中":String(gpu.state||"未知")):
      "GPU · 状态不可用";
    $("headerGpuStatus").dataset.state = gpu.ok?gpu.state:"unknown";
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
    $("headerStudioStatus").textContent=(data.sample_age_seconds!==null&&
      data.sample_age_seconds>30)?"● Studio · 数据延迟":"● Studio 正常";
    $("headerStudioStatus").dataset.live=String(
      data.sample_age_seconds!==null&&data.sample_age_seconds<=30);
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
    $("headerAuditStatus").textContent = production?.audit_chain_verified === true ?
      "✓ 审计正常":"审计待验证";
    $("headerAuditStatus").dataset.verified =
      String(production?.audit_chain_verified === true);
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
    const displayProject=projects.find(p=>p.project_id===sceneProjectId)||
      projects[0];
    $("workspaceProjectName").textContent=displayProject?.title||"尚无项目";
    const currentEpisode=episodes.find(e=>e.project_id===displayProject?.project_id);
    $("workspaceEpisodeName").textContent=currentEpisode?.episode_id||"NO EPISODE";
    const english=displayProject?.project_id==="WaitingOffice"?
      "The Waiting Office":(displayProject?.project_id||"");
    $("workspaceProjectEnglish").textContent=english;
    $("homeProjectTitle").textContent=displayProject?.title||"暂无项目";
    $("homeProjectEnglish").textContent=english;
    $("homeProgressEpisode").textContent=currentEpisode?.episode_id||"尚未建集";
    if(displayProject&&currentEpisode&&microsoftOwner){
      loadHomeEpisodeStats(displayProject.project_id,currentEpisode.episode_id);
      loadHomeRecentTasks(displayProject.project_id);
    }else{
      $("workspaceEpisodeSummary").textContent="镜头数据待登录";
      $("homeEpisodeLine").textContent="请登录后查看制作计划";
      $("homeProgressValue").textContent="—";
      $("homeRecentTasks").textContent="登录后查看真实项目任务。";
    }
    syncCharacterProjects(projects);
    syncSceneProjects(projects,episodes);
    syncWorkflowProjects(projects,episodes);
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

  async function loadHomeEpisodeStats(pid,eid) {
    const scope=pid+"/"+eid;
    if(homeEpisodeScope===scope)return;
    homeEpisodeScope=scope;
    try{
      const response=await fetch("./api/v1/production/episode?project="+
        encodeURIComponent(pid)+"&episode="+encodeURIComponent(eid),
        {cache:"no-store"});
      if(!response.ok)throw Error("episode_unavailable");
      const value=await response.json();
      if(homeEpisodeScope!==scope)return;
      const shots=value.shots||[];
      const complete=Number.isSafeInteger(value.shot_count)&&
        !value.shots_truncated&&shots.length===value.shot_count;
      const duration=complete?shots.reduce((a,s)=>a+(s.duration_ms||0),0)/1000:null;
      const total=value.shot_count||0;
      const approved=complete?shots.filter(x=>
        x.stage==="approved"||x.stage==="done").length:null;
      const progress=complete&&total>0?Math.round(approved/total*100):null;
      $("workspaceEpisodeSummary").textContent=total+" 镜头"+(
        duration!==null?" · "+duration+" 秒":"");
      $("homeEpisodeLine").textContent=eid+" · "+total+" 镜头 · "+
        (duration===null?"时长待确认":duration+" 秒");
      $("homeProgressValue").textContent=progress===null?"—":progress+"%";
      $("homeProgressRing").style.setProperty("--complete",progress===null?0:progress);
      const stats=$("homeProgressStats");
      stats.replaceChildren();
      for(const [label,val] of [["已登记镜头",total+" / "+total],
         ["已批准镜头",approved===null?"待读取":approved+" / "+total],
         ["生产阶段",value.episode?.stage||"规划中"],
         ["总时长",duration===null?"未完全载入":duration+" 秒"]]){
        const line=el("div","icebound-progress-row");
        line.appendChild(el("span","",label));
        line.appendChild(el("strong","",val));
        stats.appendChild(line);
      }
    }catch{
      if(homeEpisodeScope===scope){
        $("workspaceEpisodeSummary").textContent="镜头数据不可用";
        $("homeEpisodeLine").textContent=eid+" · 等待制作数据";
        $("homeProgressValue").textContent="—";
      }
    }
  }

  async function loadHomeRecentTasks(pid) {
    if(homeTaskScope===pid||homeTaskInFlight)return;
    homeTaskScope=pid;homeTaskInFlight=true;
    const root=$("homeRecentTasks");
    root.replaceChildren(el("p","icebound-tasks-empty","正在读取真实任务…"));
    try{
      const query=new URLSearchParams({project:pid,kind:"tasks"});
      const response=await fetch("./api/v1/workflow?"+query.toString(),
        {cache:"no-store"});
      const json=await response.json();
      if(!response.ok)throw Error(json.reason||"tasks_unavailable");
      if(homeTaskScope!==pid)return;
      root.replaceChildren();
      for(const task of json.items.slice(0,4)){
        const button=el("button","icebound-task-row");
        button.type="button";
        button.appendChild(el("span","icebound-task-dot","▤"));
        button.appendChild(el("strong","",task.fields.title||task.unit_id));
        button.appendChild(el("small","",({
          draft:"草稿",in_review:"待审核",approved:"已验收",
          rejected:"已驳回"}[task.status]||task.status)));
        button.addEventListener("click",()=>{
          wfState.tasks.project=pid;
          wfState.tasks.selected=task.unit_id;
          navigateWorkspace("tasks");
        });
        root.appendChild(button);
      }
      if(!json.items.length)root.appendChild(el("p","icebound-tasks-empty",
        "当前项目暂无制作任务。进入「制作任务」可以新增并分配。"));
    }catch{
      if(homeTaskScope===pid){
        root.replaceChildren(el("p","icebound-tasks-empty",
          "近期任务暂时无法读取，请从制作任务页面查看。"));
      }
    }finally{homeTaskInFlight=false;}
  }

  async function loadEpisode(projectId,episodeId) {
    const panel=$("episodeExplorer");
    panel.hidden=false;
    $("episodeExplorerTitle").textContent=episodeId+" · 读取中";
    $("episodeExplorerInfo").replaceChildren();
    $("episodeOutlinePanel").hidden=true;
    $("episodeOutlineBody").textContent="";
    $("episodeShotGrid").replaceChildren();
    $("shotCharacterForm").hidden=true;
    $("shotCharacterEntries").replaceChildren();
    $("shotCharacterFindings").replaceChildren();
    shotBindingData=null;shotBindingFocus=null;
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
        const bind=el("button","shot-character-trigger","绑定角色");
        bind.type="button";
        bind.addEventListener("click",()=>openShotCharacterEditor(projectId,episodeId,shot.shot_id));
        tile.appendChild(bind);
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
      if(microsoftOwner) {
        await loadVisuals(projectId,episodeId);
        try{await loadShotBindings(projectId,episodeId);}
        catch(error){$("shotCharacterStatus").textContent="读取镜头角色绑定失败："+error.message;}
      }
    } catch(err) {
      $("episodeExplorerTitle").textContent="无法读取剧集";
      $("episodeExplorerInfo").textContent=err.message;
    }
  }


  // Each shot's editable planning state freezes a character profile revision
  // and any referenced approved assets. Nothing here approves a character pack.
  async function loadShotBindings(projectId,episodeId){
    const scope={projectId,episodeId};
    const [bindings,profiles]=await Promise.all([
      fetch("./api/v1/characters/shot-bindings?project="+encodeURIComponent(projectId)+
        "&episode="+encodeURIComponent(episodeId),{cache:"no-store"}),
      fetch("./api/v1/characters?project="+encodeURIComponent(projectId),
        {cache:"no-store"})
    ]);
    if(!bindings.ok||!profiles.ok)throw Error("镜头绑定或角色档案不可读");
    const [b,c]=await Promise.all([bindings.json(),profiles.json()]);
    if(!selectedProductionEpisode||
       selectedProductionEpisode.projectId!==scope.projectId||
       selectedProductionEpisode.episodeId!==scope.episodeId)return;
    shotBindingData=b;
    shotBindingCharacters=c.characters||[];
    renderShotBindings();
  }

  function renderShotBindings(){
    const data=shotBindingData;
    const entries=$("shotCharacterEntries"),warnings=$("shotCharacterFindings");
    entries.replaceChildren();warnings.replaceChildren();
    if(!data)return;
    $("shotCharacterCount").textContent=data.binding_count+" 条角色规划绑定";
    $("shotCharacterStatus").textContent=data.binding_count?
      "当前均为规划绑定；角色资产包尚未批准，不能用于正式分镜或视频。":
      "本集尚未绑定镜头角色。点击任一镜头的「绑定角色」开始规划。";
    const names=Object.fromEntries(shotBindingCharacters.map(c=>[
      c.character_id,c.display_name]));
    for(const item of data.bindings){
      const row=el("div","shot-character-entry");
      const info=el("span","", "#"+item.shot_id+" · "+
        (names[item.character_id]||item.character_id)+" · "+
        item.view_direction+" · "+item.screen_side+" · V"+item.binding_revision+
        " · 锁定人物资料 V"+item.profile_revision+
        " / 已批准参考 "+item.asset_refs.length+" 项");
      row.appendChild(info);
      const edit=el("button","prod-new prod-secondary","编辑规划");
      edit.type="button";
      edit.addEventListener("click",()=>openShotCharacterEditor(data.project_id,
         data.episode_id,item.shot_id,item.character_id));
      row.appendChild(edit);
      entries.appendChild(row);
    }
    if(!data.findings.length&&data.binding_count)
      warnings.appendChild(el("p","shot-character-clear",
        "目前未发现相邻已绑定镜头的服装、发型或道具状态冲突；未绑定的镜头不参与检查。"));
    for(const finding of data.findings){
      const message={
        costume_changed:"服装变化",hair_variant_changed:"发型版本变化",
        prop_state_mismatch:"道具状态不连续"
      }[finding.rule]||finding.rule;
      warnings.appendChild(el("p","shot-character-warning",
        "⚠ "+(names[finding.character_id]||finding.character_id)+
        " · #"+finding.from_shot+" → #"+finding.to_shot+" · "+message+
        "："+finding.before+" → "+finding.after));
    }
  }

  async function openShotCharacterEditor(projectId,episodeId,shotId,characterId=null){
    if(!microsoftOwner||!selectedProductionEpisode||
       selectedProductionEpisode.projectId!==projectId||
       selectedProductionEpisode.episodeId!==episodeId)return;
    if(!shotBindingData||shotBindingData.project_id!==projectId||
       shotBindingData.episode_id!==episodeId){
      await loadShotBindings(projectId,episodeId);
    }
    const profiles=shotBindingCharacters;
    if(!profiles.length){$("shotCharacterStatus").textContent="角色库中尚无档案";return;}
    const existing=shotBindingData.bindings.find(b=>b.shot_id===shotId&&
      b.character_id===(characterId||profiles[0].character_id));
    const charSelect=$("shotCharacterId");
    charSelect.replaceChildren();
    for(const character of profiles){
      const option=el("option","",character.display_name+" · "+character.character_id);
      option.value=character.character_id;charSelect.appendChild(option);
    }
    const selected=characterId||existing?.character_id||profiles[0].character_id;
    charSelect.value=selected;
    shotBindingFocus={projectId,episodeId,shotId,selected};
    $("shotCharacterFormTitle").textContent="#"+shotId+" · 角色规划";
    function apply(item){
      $("shotCharacterDirection").value=item?.view_direction||"front";
      $("shotCharacterSide").value=item?.screen_side||"center";
      $("shotCharacterOutfit").value=item?.outfit_id||"";
      $("shotCharacterHair").value=item?.hair_variant_id||"";
      $("shotCharacterExpression").value=item?.expression||"";
      $("shotCharacterPose").value=item?.pose||"";
      $("shotCharacterPropBefore").value=item?.prop_state_before||"";
      $("shotCharacterPropAfter").value=item?.prop_state_after||"";
      $("shotCharacterNote").value=item?.note||"";
    }
    apply(existing);
    async function loadApprovedAssets(cid){
      const token=shotBindingFocus;
      const res=await fetch("./api/v1/characters/assets?project="+
        encodeURIComponent(projectId)+"&character="+encodeURIComponent(cid),
        {cache:"no-store"});
      if(!res.ok)throw Error("角色资产不可读");
      const data=await res.json();
      if(shotBindingFocus!==token||charSelect.value!==cid)return;
      const field=$("shotCharacterAssets");field.replaceChildren();
      const approved=(data.assets||[]).filter(x=>x.status==="approved");
      const current=shotBindingData.bindings.find(b=>b.shot_id===shotId&&
        b.character_id===cid);
      const chosen=new Set((current?.asset_refs||[]).map(x=>x.item_id));
      for(const asset of approved){
        const option=el("option","",asset.category+" · "+asset.label+
          " / V"+asset.revision);
        option.value=asset.item_id;option.selected=chosen.has(asset.item_id);
        field.appendChild(option);
      }
      if(!approved.length)field.appendChild(el("option","",
        "暂无已批准素材：可以先保存规划，不能正式制作"));
      if(!approved.length)field.firstChild.disabled=true;
    }
    // Use a new closure for each editor opening; no permanent event leak.
    charSelect.onchange=()=>{
      shotBindingFocus={projectId,episodeId,shotId,selected:charSelect.value};
      const current=shotBindingData.bindings.find(b=>b.shot_id===shotId&&
        b.character_id===charSelect.value);
      apply(current);
      loadApprovedAssets(charSelect.value).catch(err=>
        $("shotCharacterStatus").textContent=err.message);
    };
    $("shotCharacterForm").hidden=false;
    await loadApprovedAssets(selected);
    $("shotCharacterForm").scrollIntoView({behavior:"smooth",block:"nearest"});
  }

  $("shotCharacterCancel").addEventListener("click",()=>{
    $("shotCharacterForm").hidden=true;shotBindingFocus=null;
  });
  $("shotCharacterForm").addEventListener("submit",async event=>{
    event.preventDefault();
    const scope=shotBindingFocus;if(!scope||!csrf)return;
    const cid=$("shotCharacterId").value;
    const current=shotBindingData?.bindings.find(b=>
      b.shot_id===scope.shotId&&b.character_id===cid);
    const payload={
      project_id:scope.projectId,episode_id:scope.episodeId,
      shot_id:scope.shotId,character_id:cid,
      expected_revision:current?.binding_revision||0,
      view_direction:$("shotCharacterDirection").value,
      screen_side:$("shotCharacterSide").value,
      outfit_id:$("shotCharacterOutfit").value.trim(),
      hair_variant_id:$("shotCharacterHair").value.trim(),
      expression:$("shotCharacterExpression").value.trim(),
      pose:$("shotCharacterPose").value.trim(),
      prop_state_before:$("shotCharacterPropBefore").value.trim(),
      prop_state_after:$("shotCharacterPropAfter").value.trim(),
      note:$("shotCharacterNote").value.trim(),
      asset_ids:Array.from($("shotCharacterAssets").selectedOptions)
        .filter(x=>!x.disabled).map(x=>x.value)
    };
    const submit=$("shotCharacterSave");submit.disabled=true;
    try{
      const response=await fetch("./api/v1/characters/shot-bindings/save",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({csrf,...payload}),cache:"no-store"
      });
      const result=await response.json();
      if(!response.ok)throw Error(result.reason||"绑定失败");
      $("shotCharacterForm").hidden=true;shotBindingFocus=null;
      await loadShotBindings(scope.projectId,scope.episodeId);
      $("shotCharacterStatus").textContent="已保存 #"+scope.shotId+
        " · "+cid+" 的规划绑定（不代表审核通过）。";
    }catch(err){$("shotCharacterStatus").textContent="保存失败："+err.message;}
    finally{submit.disabled=false;}
  });

  // A project-level catalog deliberately references existing immutable
  // episode images instead of moving, copying or auto-approving them.
  const characterPresets = [
    ["CHAR_GPT","吉皮提","main","ChatGPT / OpenAI：交织与连接、克制的几何秩序",
     "深栗色短发、琥珀瞳、象牙白与青绿服装；通过衣襟交错与服装结构表达协作，不复制六环官方图案。",
     "事务所的协调者。温柔、理性；EP01 接纳零，调查异常连接。"],
    ["CHAR_GEM","杰米奈","main","Gemini / Google：多彩渐变、光感、四向延伸的动势",
     "紫蓝短层次发、粉紫发尾、渐变外套；用不对称光带呈现活力，不使用官方四尖星形。",
     "活泼好胜。EP01 发起 AI 争霸赛；需要夸张表情与动作。"],
    ["CHAR_CLA","克劳德","main","Claude / Anthropic：温暖珊瑚色、简洁人文、放射节奏",
     "陶土橘盘发、米白与焦糖色书卷气装束；抽象光线节奏，不描摹官方放射星芒。",
     "细腻温和。EP01 阅读、拒绝排名、对系统异常感到不安。"],
    ["CHAR_DS","迪普西克","main","DeepSeek：蓝鲸意象、深浅蓝色与流线",
     "深蓝长编发、冰蓝眼睛、蓝白海洋曲线服装、独立设计的鲸鱼抱枕；不复制官方鲸鱼标志轮廓。",
     "冷静敏锐。EP01 核查规则与连接数量。"],
    ["CHAR_ZERO","零","main","原创角色；无对应模型官方 Logo",
     "黑色低马尾、朴素米色外套、旧帆布包、右手红色手绳；断开的连接点作为原创抽象母题。",
     "神秘新人。EP01 的身份悬念核心；右手红绳不可左右反转。"],
    ["CHAR_QWEN","奎文","extended","通义千问 / Qwen：参考官方品牌语言重新研究，禁止复制标志",
     "保留已入库的紫色角色图作为候选参考，不将其视为正式母版。",
     "扩展角色，暂不进入 EP01 五位主角与四个连接的剧情。"]
  ];
  const charRoleName={main:"主角",extended:"扩展角色"};
  const charRefName={character_card:"角色卡",three_view:"三视图",
    expression:"表情集",costume:"服装",prop:"道具",inspiration:"创意参考"};


  const functionalPages={
    home:"工作台首页",projects:"项目与剧集",characters:"角色库 V2",
    scenes:"场景库",props:"道具库",shots:"分镜规划",
    storyboards:"分镜图制作",white_models:"白模预演",
    video_plans:"视频制作",review:"审核中心",tasks:"制作任务",
    monitor:"镜头监看",audit:"操作审计",settings:"项目设置"
  };
  function navigateWorkspace(name,changeHistory=true){
    const page=Object.prototype.hasOwnProperty.call(functionalPages,name)?
      name:"home";
    document.body.dataset.page=page;
    $("workspacePageTitle").textContent=functionalPages[page];
    for(const nav of document.querySelectorAll(".nav-items a[data-page]")){
      const active=nav.dataset.page===page;
      nav.classList.toggle("active",active);
      if(active)nav.setAttribute("aria-current","page");
      else nav.removeAttribute("aria-current");
    }
    if(changeHistory){
      const url=new URL(window.location.href);
      url.searchParams.set("page",page);
      window.history.pushState({page},"",url.pathname+url.search);
    }
    window.scrollTo(0,0);
    if(page==="scenes"&&sceneProjectId&&!sceneData&&microsoftOwner)
      loadScenes().catch(error=>$("sceneMessage").textContent=error.message);
    if(microsoftOwner)workflowEnterPage(page);
  }
  for(const nav of document.querySelectorAll(".nav-items a[data-page]")){
    nav.addEventListener("click",event=>{
      event.preventDefault();
      navigateWorkspace(nav.dataset.page);
    });
  }
  for(const button of document.querySelectorAll(".icebound-quick-actions [data-jump]")){
    button.addEventListener("click",()=>{
      const target=button.dataset.jump;
      navigateWorkspace(target);
      if(target==="projects"&&microsoftOwner)
        openProductionEditor("create_project");
    });
  }
  window.addEventListener("popstate",()=>navigateWorkspace(
    new URLSearchParams(window.location.search).get("page")||"home",false));


  // Real production work-unit UI. Each function lives in its own URL/page;
  // no case renders placeholder "approved" results or triggers GPU tasks.
  const wfPageKind={
    props:"props",shots:"shot_plans",storyboards:"storyboards",
    white_models:"white_models",video_plans:"video_plans",
    tasks:"tasks",settings:"settings"
  };
  const wfKinds=Object.keys(wfPageKind).map(p=>wfPageKind[p]);
  const wfState=Object.fromEntries(wfKinds.map(kind=>[
    kind,{project:"",episode:"",items:null,selected:"",editing:false,
          image:"",shots:[],scope:"",fields:null}
  ]));
  const wfLabels={props:"道具",shot_plans:"分镜规划",
    storyboards:"分镜图",white_models:"白模",video_plans:"视频制作单",
    tasks:"任务",settings:"项目规格"};
  const wfStatus={draft:"草稿",in_review:"待审核",
    approved:"已批准",rejected:"已驳回"};
  const wfHints={props:"尺寸、握持、材质及特写等须一致；只有人工批准的独立图片才是道具母版。",
    shot_plans:"场景编号需先在场景库建立，道具编号需先在道具库保存。此项规划不自动批准人物或视频。",
    storyboards:"使用分镜图候选、版本与审批；本页面没有连接 AI 绘图执行器。",
    white_models:"当前提供可编辑参数和浏览器粗白模空间预览；精细建模及带曲线动作预演仍需专用三维引擎。",
    video_plans:"此处仅保存生产指令；没有启动 GPU 或提交 ComfyUI。不能把指令当成已生成的视频。",
    tasks:"任务及其依赖必须经人工验收，任务完成不代表上游创意资产已经批准。",
    settings:"项目规格以数据库修订记录为准，修改后不会自动改写历史镜头或生成文件。"};

  function wfScope(kind){return ["props","tasks"].includes(kind)?"project":
    kind==="settings"?"episode":"shot";}
  function workflowProjects(){return latest?.production?.projects||[];}
  function workflowEpisodes(pid){return (latest?.production?.episodes||[])
    .filter(x=>x.project_id===pid);}
  function workflowSyncOptions(select,list,readLabel,value){
    const fingerprint=JSON.stringify(list.map(x=>[x.value,readLabel(x)]));
    if(select.dataset.signature!==fingerprint){
      select.dataset.signature=fingerprint;select.replaceChildren();
      for(const row of list){
        const option=el("option","",readLabel(row));option.value=row.value;
        select.appendChild(option);
      }
    }
    if(value&&list.some(x=>x.value===value))select.value=value;
  }
  function syncWorkflowProjects(projects,episodes){
    if(!microsoftOwner)return;
    for(const kind of wfKinds){
      const state=wfState[kind],project=$("wfProject_"+kind),
        ep=$("wfEpisode_"+kind);
      const projectItems=projects.map(x=>({...x,value:x.project_id}));
      const keep=projects.some(x=>x.project_id===state.project);
      if(!keep){
        state.project=projects[0]?.project_id||"";
        state.episode="";state.items=null;state.selected="";
      }
      workflowSyncOptions(project,projectItems,x=>x.title+" · "+x.project_id,
        state.project);
      project.disabled=!projectItems.length;
      const relevant=episodes.filter(e=>e.project_id===state.project);
      const epItems=relevant.map(e=>({...e,value:e.episode_id}));
      if(!epItems.some(x=>x.value===state.episode)) {
        state.episode=epItems[0]?.value||"";state.items=null;state.selected="";
      }
      workflowSyncOptions(ep,epItems,x=>x.episode_id+" · "+x.title,state.episode);
      ep.disabled=wfScope(kind)==="project"||!epItems.length;
      ep.closest("label").hidden=wfScope(kind)==="project";
      $("wfNew_"+kind).disabled=(!state.project ||
        (wfScope(kind)!=="project"&&!state.episode));
    }
    const reviewProject=$("wfReviewProject"),reviewEpisode=$("wfReviewEpisode");
    const p=reviewProject.value||projects[0]?.project_id||"";
    workflowSyncOptions(reviewProject,projects.map(x=>({...x,value:x.project_id})),
      x=>x.title+" · "+x.project_id,p);
    const eps=episodes.filter(x=>x.project_id===reviewProject.value);
    workflowSyncOptions(reviewEpisode,
      [{value:"",episode_id:"全部剧集",title:"包含项目级资产"},
       ...eps.map(x=>({...x,value:x.episode_id}))],
      x=>x.title+" · "+x.episode_id,reviewEpisode.value);
  }
  async function workflowFetch(kind,state){
    const pid=state.project,eid=state.episode;
    if(!pid||wfScope(kind)!=="project"&&!eid)return;
    const query=new URLSearchParams({project:pid,kind});
    if(wfScope(kind)!=="project")query.set("episode",eid);
    const res=await fetch("./api/v1/workflow?"+query.toString(),{cache:"no-store"});
    const body=await res.json();
    if(!res.ok)throw Error(body.reason||"工作数据读取失败");
    if(pid!==state.project||eid!==state.episode)return;
    state.items=body;
    state.fields=body.fields;state.scope=body.scope;
    if(wfScope(kind)==="shot"){
      const sh=await fetch("./api/v1/production/episode?project="+
        encodeURIComponent(pid)+"&episode="+encodeURIComponent(eid),{cache:"no-store"});
      if(!sh.ok)throw Error("镜头列表读取失败");
      const info=await sh.json();
      if(pid!==state.project||eid!==state.episode)return;
      state.shots=info.shots||[];
    }
    if(!state.editing&&!body.items.some(x=>x.unit_id===state.selected))
      state.selected=body.items[0]?.unit_id||"";
    workflowRender(kind);
  }
  async function workflowLoad(kind){
    const state=wfState[kind];
    if(!microsoftOwner||!state.project)return;
    $("wfMessage_"+kind).textContent="正在读取真实项目数据…";
    try{await workflowFetch(kind,state);}
    catch(error){$("wfMessage_"+kind).textContent="读取失败："+error.message;}
  }
  function workflowEnterPage(page){
    if(page==="review"){workflowLoadReviews();return;}
    const kind=wfPageKind[page];
    if(!kind)return;
    const state=wfState[kind];
    if(state.project)workflowLoad(kind);
  }
  async function workflowPost(action,data){
    if(!csrf||!microsoftOwner)throw Error("需要 Microsoft 所有者会话");
    const res=await fetch("./api/v1/workflow/"+action,{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({csrf,...data}),cache:"no-store"});
    const body=await res.json();
    if(!res.ok)throw Error(body.reason||"保存失败");
    return body;
  }

  function workflowRenderList(kind){
    const state=wfState[kind],data=state.items;
    if(!data)return;
    const list=$("wfList_"+kind);list.replaceChildren();
    const query=$("wfSearch_"+kind).value.trim().toLocaleLowerCase();
    const matches=data.items.filter(item=>
      (item.unit_id+" "+Object.values(item.fields).join(" ")).
        toLocaleLowerCase().includes(query));
    $("wfCount_"+kind).textContent=data.items.length+" 项记录";
    if(!matches.length){
      list.appendChild(el("p","workflow-stage-empty",data.items.length?
        "没有匹配的记录。":"当前还没有此类制作记录。"));
    }
    for(const item of matches){
      const btn=el("button","workflow-record"+(
        state.selected===item.unit_id&&!state.editing?" active":""));
      btn.type="button";
      btn.appendChild(el("strong","",item.fields.name||item.fields.title||
        item.unit_id));
      btn.appendChild(el("small","",item.unit_id+" · V"+item.revision+
        " · "+(item.episode_id||"全项目")));
      btn.appendChild(el("span","state "+item.status,wfStatus[item.status]||item.status));
      btn.addEventListener("click",()=>{
        state.selected=item.unit_id;state.editing=false;state.image="";
        workflowRender(kind);
      });
      list.appendChild(btn);
    }
  }
  function workflowRender(kind){
    const state=wfState[kind];if(!state.items)return;
    const data=state.items,chosen=data.items.find(x=>x.unit_id===state.selected);
    workflowRenderList(kind);
    const stage=$("wfStage_"+kind),visuals=$("wfVisuals_"+kind),
      meta=$("wfStageMeta_"+kind),detail=$("wfDetail_"+kind);
    stage.replaceChildren();visuals.replaceChildren();
    meta.replaceChildren();detail.replaceChildren();
    $("wfStageTitle_"+kind).textContent=chosen?
      (chosen.fields.name||chosen.fields.title||chosen.unit_id):"新建"+wfLabels[kind];
    $("wfMessage_"+kind).textContent=wfHints[kind];
    const source=chosen?.source_visual_id;
    const pictures=data.visuals.filter(x=>
      (kind==="props"||x.episode_id===state.episode)&&
      x.subject_id===(chosen?.unit_id||state.selected));
    const preview=pictures.find(x=>x.visual_id===state.image)||
      pictures.find(x=>x.visual_id===source)||pictures[0];
    if(kind==="white_models"){
      const canvas=el("canvas","workflow-clay-canvas");
      canvas.width=950;canvas.height=540;
      canvas.setAttribute("aria-label","基于镜头尺寸和相机/人物坐标的粗白模实时投影");
      stage.appendChild(canvas);
      const timeline=el("div","workflow-clay-timeline");
      const slider=el("input","");
      slider.type="range";slider.min="0";slider.max="100";slider.step="1";
      slider.value="0";slider.setAttribute("aria-label","粗白模关键帧时间轴");
      const time=el("span","","0.0s");
      const values=chosen?.fields||{};
      function draw(){
        const current=workflowFrameAt(values,Number(slider.value)/100);
        const frames=workflowFrameList(values);
        const last=frames[frames.length-1];
        time.textContent=last?(Number(slider.value)/100*last.t).toFixed(1)+"s":"静态机位";
        workflowDrawClay(canvas,current);
      }
      slider.disabled=workflowFrameList(values).length<2;
      slider.addEventListener("input",draw);
      timeline.append(slider,time);stage.appendChild(timeline);draw();
    }else if(preview){
      const picture=el("img","");
      picture.alt=(chosen?.unit_id||"")+"/"+preview.filename;
      picture.src=visualURL(state.project,preview.episode_id,preview.visual_id);
      stage.appendChild(picture);
      stage.appendChild(el("span","workflow-stage-caption",
        preview.filename+" · "+(preview.visual_id===source?
          "当前版本引用":"尚未纳入此记录的图片")));
    }else{
      const empty=el("div","workflow-stage-empty");
      empty.appendChild(el("div","workflow-stage-icon",kind==="video_plans"?"▶":
        kind==="white_models"?"⬡":"▨"));
      empty.appendChild(el("strong","",
        kind==="video_plans"?"视频执行器尚未连接":
        kind==="storyboards"?"暂无分镜图":
        kind==="props"?"暂无道具参考图片":"规划资料预览"));
      empty.appendChild(el("p","",kind==="video_plans"?
        "请创建可追溯的制作指令，待已批准的素材和 GPU 任务管道接通后再生成视频。":
        "保存真实数据后，会在下方列出当前记录的参数与来源。"));
      stage.appendChild(empty);
    }
    for(const pic of pictures){
      const btn=el("button","workflow-thumb"+(preview?.visual_id===pic.visual_id?
        " active":""));
      btn.type="button";
      const image=el("img","");
      image.loading="lazy";image.alt=pic.filename;
      image.src=visualURL(state.project,pic.episode_id,pic.visual_id);
      btn.appendChild(image);
      btn.appendChild(el("small","",pic.filename+" / V"+pic.version));
      btn.addEventListener("click",()=>{
        state.image=pic.visual_id;
        workflowRender(kind);
      });
      visuals.appendChild(btn);
    }
    if(chosen){
      if(kind==="video_plans"){
        const wrap=el("div","workflow-readiness");
        wrap.appendChild(el("strong","","渲染前置条件核对"));
        const blockers=chosen.blockers||["video_render_executor_not_connected"];
        const names={
          project_spec_not_approved:"缺少已批准的项目输出规格",
          shot_plans_not_approved:"分镜规划尚未批准",
          storyboards_not_approved:"分镜图尚未批准",
          white_models_not_approved:"白模预演尚未批准",
          scene_revision_not_approved:"当前场景版本尚未批准",
          video_render_executor_not_connected:"GPU / ComfyUI 正式执行器尚未接入"
        };
        for(const reason of blockers){
          wrap.appendChild(el("p","",
            "• "+(names[reason]||(
             reason.startsWith("prop_not_approved:")?"道具尚未批准："+reason.split(":")[1]:
             reason.startsWith("character_master_not_approved:")?
                "角色母版尚未批准："+reason.split(":")[1]:reason))));
        }
        meta.appendChild(wrap);
      }
      const dl=el("dl","");
      for(const [key,value] of Object.entries(chosen.fields)){
        dl.appendChild(el("dt","",data.fields[key]?.label||key));
        dl.appendChild(el("dd","",value));
      }
      meta.appendChild(dl);
    }else meta.appendChild(el("p","",wfHints[kind]));
    workflowRenderEditor(kind,chosen,pictures);
  }


  function workflowFrameList(values){
    try{
      const frames=JSON.parse(values.keyframes||"[]");
      if(!Array.isArray(frames)||frames.length>60)return [];
      return frames.filter(x=>x&&typeof x==="object"&&
        typeof x.t==="number"&&Number.isFinite(x.t)&&x.t>=0)
        .sort((a,b)=>a.t-b.t);
    }catch{return [];}
  }
  function workflowFrameAt(values,ratio){
    const frames=workflowFrameList(values);
    if(!frames.length)return values;
    const t=ratio*frames[frames.length-1].t;
    const high=frames.find(x=>x.t>=t)||frames[frames.length-1];
    const low=frames.slice().reverse().find(x=>x.t<=t)||frames[0];
    const mix=low===high?0:Math.max(0,Math.min(1,
      (t-low.t)/(high.t-low.t)));
    const props={...values};
    for(const key of ["actor_x","actor_y","prop_x","prop_y",
      "camera_x","camera_y","camera_z","camera_yaw"]){
      const a=typeof low[key]==="number"?low[key]:Number(values[key]||0);
      const b=typeof high[key]==="number"?high[key]:Number(values[key]||0);
      props[key]=String(a+(b-a)*mix);
    }
    return props;
  }

  function workflowDrawClay(canvas,values){
    // Perspective projection of independent scene primitives; this is a real
    // editable coarse spatial blocking preview, not a simulated video render.
    const ctx=canvas.getContext("2d");if(!ctx)return;
    const W=canvas.width,H=canvas.height;
    const num=(name,fallback)=>Number.isFinite(Number(values[name]))&&values[name]!==undefined?
      Number(values[name]):fallback;
    const width=Math.max(2,Math.min(40,num("stage_width",9)));
    const depth=Math.max(2,Math.min(40,num("stage_depth",10)));
    const yaw=num("camera_yaw",0)*Math.PI/180;
    const pitch=num("camera_pitch",-12)*Math.PI/180;
    const eye=[num("camera_x",0),num("camera_y",-9),Math.max(.5,num("camera_z",2.4))];
    const focal=Math.min(100,Math.max(12,num("focal_mm",35)));
    const scale=550*focal/35;
    const sin=Math.sin(yaw),cos=Math.cos(yaw);
    function project(p){
      const dx=p[0]-eye[0],dy=p[1]-eye[1],dz=p[2]-eye[2];
      const rx=dx*cos-dy*sin,forward=dx*sin+dy*cos;
      const rz=dz*Math.cos(pitch)-forward*Math.sin(pitch);
      const distance=dz*Math.sin(pitch)+forward*Math.cos(pitch);
      if(distance<.25)return null;
      return [W/2+scale*rx/distance,H/2-scale*rz/distance,distance];
    }
    function stroke(points,color,line=1){
      const projected=points.map(project);
      if(projected.some(v=>v===null))return;
      ctx.strokeStyle=color;ctx.lineWidth=line;ctx.beginPath();
      projected.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));
      ctx.stroke();
    }
    ctx.clearRect(0,0,W,H);
    const gradient=ctx.createLinearGradient(0,0,0,H);
    gradient.addColorStop(0,"#e7f6ff");gradient.addColorStop(1,"#f7fdff");
    ctx.fillStyle=gradient;ctx.fillRect(0,0,W,H);
    for(let x=-width/2;x<=width/2+.1;x+=1){
      stroke([[x,0,0],[x,depth,0]],"#b7d4e3",1);
    }
    for(let y=0;y<=depth+.1;y+=1){
      stroke([[-width/2,y,0],[width/2,y,0]],"#b7d4e3",1);
    }
    function box(x,y,w,d,h,color){
      const low=[[x-w/2,y-d/2,0],[x+w/2,y-d/2,0],
        [x+w/2,y+d/2,0],[x-w/2,y+d/2,0]];
      const high=low.map(p=>[p[0],p[1],h]);
      ctx.fillStyle=color;
      const q=high.map(project);
      if(q.every(Boolean)){
        ctx.beginPath();q.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));
        ctx.closePath();ctx.fill();
      }
      for(let i=0;i<4;i++){
        stroke([low[i],low[(i+1)%4]],"#84a5be",1.3);
        stroke([high[i],high[(i+1)%4]],"#789cba",1.3);
        stroke([low[i],high[i]],"#789cba",1.3);
      }
    }
    box(num("actor_x",0),num("actor_y",4),.65,.5,
      Math.max(.8,num("actor_height",1.7)),"#e6edf2");
    box(num("prop_x",1.4),num("prop_y",5),.6,.6,.65,"#9db4c4");
    ctx.fillStyle="#427398";ctx.font="bold 18px system-ui";
    ctx.fillText("粗白模 · 实时空间预览（未渲染）",18,31);
    ctx.font="13px system-ui";
    ctx.fillText("人物灰白占位 · 道具蓝灰占位 · 地面米制网格",18,54);
  }

  function workflowRenderEditor(kind,record,pictures){
    const state=wfState[kind],data=state.items,detail=$("wfDetail_"+kind);
    const current=record&&!state.editing?record:null;
    const form=el("form","workflow-form");
    const head=el("div","workflow-form-heading",
      current?"正在编辑："+current.unit_id+" · V"+current.revision:"新建"+wfLabels[kind]);
    form.appendChild(head);
    const idLabel=el("label","",data.scope==="shot"?"选择镜头编号":"条目编号");
    let idControl;
    if(data.scope==="shot"){
      idControl=el("select","");
      for(const shot of state.shots){
        const opt=el("option","","SH"+shot.shot_id+" · "+
          (shot.duration_ms/1000).toFixed(1)+" 秒");
        opt.value=shot.shot_id;idControl.appendChild(opt);
      }
      if(!state.shots.length)idControl.appendChild(el("option","","尚无镜头"));
    }else{
      idControl=el("input","");
      idControl.pattern="[A-Za-z][A-Za-z0-9_-]{1,47}";
      idControl.maxLength=48;idControl.required=true;
      idControl.placeholder=data.scope==="episode"?"SPEC":"PROP_01 / TASK_01";
    }
    idControl.value=current?.unit_id||(data.scope==="episode"?"SPEC":
      data.scope==="shot"?state.shots[0]?.shot_id||"":"");
    idControl.disabled=!!current;
    idLabel.appendChild(idControl);form.appendChild(idLabel);
    if(data.scope==="shot"&&!state.shots.length)
      form.appendChild(el("p","workflow-draft",
        "本剧集还没有镜头，请先在项目工程中建立镜头。"));
    const inputs={};
    for(const [field,config] of Object.entries(data.fields)){
      const label=el("label","",config.label);
      const control=config.type==="number"?
        el("input",""):el("textarea","");
      if(config.type==="number"){
        control.type="number";control.step="any";
      }else{
        control.maxLength=2000;
        control.rows=field==="prompt"||field==="story"||field==="keyframes"?3:2;
      }
      if(kind==="white_models"&&field==="keyframes")
        control.placeholder='[{"t":0,"actor_x":0,"actor_y":4},{"t":4,"actor_x":2,"actor_y":6}]';
      control.value=current?.fields[field]||
        (!current&&kind==="settings"?{
          aspect:"9:16",width:"1080",height:"1920",fps:"24",
          color:"Rec.709",naming:"EP01_SH01"}[field]||"":
         !current&&kind==="white_models"?{
           stage_width:"9",stage_depth:"10",camera_x:"0",camera_y:"-9",
           camera_z:"2.4",camera_yaw:"0",camera_pitch:"-12",
           focal_mm:"35",actor_x:"0",actor_y:"4",actor_height:"1.7",
           prop_x:"1.4",prop_y:"5",quality:"粗白模"}[field]||"":
         !current&&kind==="video_plans"?{
           fps:"24",width:"1080",height:"1920"}[field]||"":"");
      inputs[field]=control;label.appendChild(control);form.appendChild(label);
      if(kind==="white_models"){
        control.addEventListener("input",()=>{
          const canvas=$("wfStage_white_models").querySelector("canvas");
          if(!canvas)return;
          const values={};
          for(const [name,input] of Object.entries(inputs))values[name]=input.value;
          workflowDrawClay(canvas,values);
        });
      }
    }
    const noteLabel=el("label","","版本备注");
    const note=el("textarea","");
    note.maxLength=2000;note.rows=2;note.value=current?.note||"";
    noteLabel.appendChild(note);form.appendChild(noteLabel);
    if(kind==="video_plans"&&current){
      const exportButton=el("button","prod-new prod-secondary","导出当前镜头制作单 JSON");
      exportButton.type="button";
      exportButton.addEventListener("click",()=>{
        const plan={schema:"director_studio_video_order_v1",
          project_id:state.project,episode_id:state.episode,
          shot_id:current.unit_id,revision:current.revision,
          status:current.status,settings:current.fields,
          blockers:current.blockers||[],render_execution:"not_connected",
          generated_at:new Date().toISOString()};
        const output=new Blob([JSON.stringify(plan,null,2)],{type:"application/json"});
        const href=URL.createObjectURL(output);
        const a=document.createElement("a");a.href=href;
        a.download="video_order_"+current.unit_id+"_V"+current.revision+".json";
        a.click();URL.revokeObjectURL(href);
      });
      form.appendChild(exportButton);
    }
    const kindVisual=data.image_kind;
    const visualLabel=el("label","","本版参考图片");
    const visualSelect=el("select","");
    if(kindVisual){
      const none=el("option","","无图片：仅创建草稿");none.value="";
      visualSelect.appendChild(none);
      for(const image of data.visuals.filter(x=>
          x.subject_id===idControl.value &&(data.scope==="project"||
            x.episode_id===state.episode))){
        const opt=el("option","",image.episode_id+" · "+image.filename+
          " / V"+image.version);
        opt.value=image.visual_id;visualSelect.appendChild(opt);
      }
      visualSelect.value=current?.source_visual_id||"";
      const syncPictureOptions=()=>{
        const chosen=visualSelect.value;visualSelect.replaceChildren();
        const blank=el("option","","无图片：仅保存结构资料");
        blank.value="";visualSelect.appendChild(blank);
        for(const x of data.visuals.filter(v=>v.subject_id===idControl.value &&
            (data.scope==="project"||v.episode_id===state.episode))){
          const opt=el("option","",x.episode_id+" · "+x.filename+" / V"+x.version);
          opt.value=x.visual_id;visualSelect.appendChild(opt);
        }
        visualSelect.value=[...visualSelect.options].some(o=>o.value===chosen)?
          chosen:"";
      };
      idControl.addEventListener("change",syncPictureOptions);
      visualLabel.appendChild(visualSelect);form.appendChild(visualLabel);
    }
    const submit=el("button","prod-new","保存"+wfLabels[kind]+"草稿");
    submit.type="submit";
    submit.disabled=data.scope==="shot"&&!state.shots.length;
    form.appendChild(submit);
    form.addEventListener("submit",async event=>{
      event.preventDefault();
      if(!state.project||!idControl.value)return;
      const fields={};
      for(const [name,input] of Object.entries(inputs)){
        const value=input.value.trim();
        if(value)fields[name]=value;
      }
      if(!Object.keys(fields).length){
        $("wfMessage_"+kind).textContent="请至少填写一个有效字段";return;
      }
      const unit_id=idControl.value;
      const dataToSave={
        project_id:state.project,episode_id:data.scope==="project"?"":state.episode,
        kind,unit_id,shot_id:data.scope==="shot"?unit_id:"",
        expected_revision:current?.revision||0,
        fields,note:note.value.trim(),source_visual_id:kindVisual?
          visualSelect.value||null:null
      };
      submit.disabled=true;
      try{
        await workflowPost("save",dataToSave);
        state.selected=unit_id;state.editing=false;state.image="";
        await workflowLoad(kind);
        $("wfMessage_"+kind).textContent="草稿已保存，修订历史已锁定；尚未自动批准。";
      }catch(error){
        $("wfMessage_"+kind).textContent="保存失败："+error.message;
        submit.disabled=false;
      }
    });
    detail.appendChild(form);
    if(!current)return;
    const divider=el("div","workflow-form-heading","版本审核");
    form.appendChild(divider);
    const info=el("p",current.status==="approved"?"workflow-approved":"workflow-draft",
      "当前状态："+wfStatus[current.status]+
      (current.approved_revision?" · 历史批准 V"+current.approved_revision:"")+
      " · 操作均记录审计链");
    form.appendChild(info);
    const reason=el("textarea","workflow-review-note");
    reason.maxLength=600;reason.placeholder="审核依据，至少 8 个字";
    reason.setAttribute("aria-label","审核理由");
    form.appendChild(reason);
    const controls=el("div","workflow-review-actions");
    const choices=current.status==="draft"?[["submit","提交审核"]]:
      current.status==="in_review"?[["approve","批准当前版本"],["reject","驳回"]]:[];
    for(const [decision,label] of choices){
      const button=el("button","prod-new"+(decision==="approve"?
        " workflow-approve-button":""),label);
      button.type="button";
      button.disabled=decision==="approve"&&(
        kind==="video_plans"||
        (data.image_kind&&!current.source_visual_id));
      button.addEventListener("click",async()=>{
        if(reason.value.trim().length<8){
          $("wfMessage_"+kind).textContent="审核理由至少 8 个字";return;
        }
        if(decision==="approve"&&!window.confirm(
          "确认人工批准 "+current.unit_id+" 当前版本？原图及历史记录不会覆盖。"))return;
        button.disabled=true;
        try{
          await workflowPost("review",{
            project_id:state.project,episode_id:data.scope==="project"?"":state.episode,
            kind,unit_id:current.unit_id,expected_revision:current.revision,
            decision,rationale:reason.value.trim()
          });
          await workflowLoad(kind);
        }catch(error){
          $("wfMessage_"+kind).textContent="审核失败："+error.message;
          button.disabled=false;
        }
      });
      controls.appendChild(button);
    }
    if(!choices.length)controls.appendChild(el("span","workflow-draft",
      "此修订已有审核结果。需要继续修改请保存新的草稿版本。"));
    if(kind==="video_plans"&&current.status==="in_review")
      controls.appendChild(el("p","workflow-draft",
        "视频成片审核锁定：尚未接通真实生成结果回传，不能批准渲染。"));
    form.appendChild(controls);
    if(kindVisual){
      const upload=el("form","workflow-form workflow-upload-form");
      upload.appendChild(el("div","workflow-form-heading","上传真实候选图片"));
      const episodeLabel=el("label","","原图所属剧集");
      const episode=el("select","");
      const episodes=workflowEpisodes(state.project);
      for(const ep of episodes){
        const option=el("option","",ep.episode_id+" · "+ep.title);
        option.value=ep.episode_id;episode.appendChild(option);
      }
      if(data.scope==="shot")episode.value=state.episode;
      episode.disabled=data.scope==="shot";
      episodeLabel.appendChild(episode);upload.appendChild(episodeLabel);
      const file=el("input","");file.type="file";
      file.accept="image/png,image/jpeg,image/webp";file.required=true;
      file.setAttribute("aria-label","选择真实参考图片");
      upload.appendChild(file);
      const uploadButton=el("button","prod-new","上传并建立候选修订");
      uploadButton.type="submit";uploadButton.disabled=!episodes.length||
        current.status==="in_review";
      upload.appendChild(uploadButton);
      upload.addEventListener("submit",async event=>{
        event.preventDefault();const f=file.files?.[0];if(!f)return;
        if(!["image/png","image/jpeg","image/webp"].includes(f.type)||
           f.size>8*1024*1024||f.size<32){
          $("wfMessage_"+kind).textContent="只能上传不超过 8MB 的 PNG/JPG/WebP 图片";
          return;
        }
        uploadButton.disabled=true;
        try{
          const image_base64=await fileAsBase64(f);
          const response=await fetch("./api/v1/production/visual/upload",{
            method:"POST",headers:{"Content-Type":"application/json"},
            body:JSON.stringify({csrf,project_id:state.project,
              episode_id:episode.value,kind:data.image_kind,
              subject_id:current.unit_id,filename:f.name,image_base64}),
            cache:"no-store"
          });
          const result=await response.json();
          if(!response.ok)throw Error(result.reason||"上传失败");
          await workflowPost("save",{
            project_id:state.project,
            episode_id:data.scope==="project"?"":state.episode,
            kind,unit_id:current.unit_id,
            shot_id:data.scope==="shot"?current.unit_id:"",
            expected_revision:current.revision,
            fields:current.fields,note:current.note,
            source_visual_id:result.visual_id
          });
          state.image=result.visual_id;
          await workflowLoad(kind);
          $("wfMessage_"+kind).textContent="已上传候选并产生新草稿修订；必须重新人工审核。";
        }catch(error){
          $("wfMessage_"+kind).textContent="图片上传／关联失败："+error.message;
          uploadButton.disabled=false;
        }
      });
      detail.appendChild(upload);
    }
  }

  // UI handlers are bound once. Project/episode changes discard stale scopes.
  for(const kind of wfKinds){
    const state=wfState[kind];
    $("wfProject_"+kind).addEventListener("change",()=>{
      state.project=$("wfProject_"+kind).value;state.episode="";
      state.selected="";state.items=null;state.editing=false;
      syncWorkflowProjects(workflowProjects(),latest?.production?.episodes||[]);
      workflowLoad(kind);
    });
    $("wfEpisode_"+kind).addEventListener("change",()=>{
      state.episode=$("wfEpisode_"+kind).value;
      state.selected="";state.items=null;state.editing=false;
      workflowLoad(kind);
    });
    $("wfSearch_"+kind).addEventListener("input",()=>{
      if(state.items)workflowRenderList(kind);
    });
    $("wfNew_"+kind).addEventListener("click",()=>{
      if(!state.project||!state.items)return;
      state.selected="";state.editing=true;state.image="";
      workflowRender(kind);
    });
  }

  async function workflowLoadReviews(){
    if(!microsoftOwner)return;
    const project=$("wfReviewProject").value;
    const episode=$("wfReviewEpisode").value;
    if(!project)return;
    const query=new URLSearchParams({project});
    if(episode)query.set("episode",episode);
    const label=$("wfReviewMessage"),list=$("wfReviewList");
    label.textContent="正在读取人工审核队列…";
    try{
      const response=await fetch("./api/v1/workflow/reviews?"+query.toString(),
                                 {cache:"no-store"});
      const body=await response.json();
      if(!response.ok)throw Error(body.reason||"审核队列不可读");
      list.replaceChildren();
      $("wfReviewCount").textContent=body.total+" 条待审核";
      label.textContent=body.total?
        "所有条目均为真实待审记录；必须逐项确认，不能批量假批准。":
        "当前项目和剧集暂无待审制作工单。";
      if(!body.pending.length)list.appendChild(el("div","workflow-placeholder",
        "暂无待审核工单。角色和场景有自己的正式母版审批门槛。"));
      const map={props:"props",shot_plans:"shots",storyboards:"storyboards",
        white_models:"white_models",video_plans:"video_plans",
        tasks:"tasks",settings:"settings"};
      for(const item of body.pending){
        const row=el("div","workflow-review-record");
        const desc=el("div","");
        const typeName={scene:"场景库",character_asset:"角色分类资产"}[item.kind]||
          wfLabels[item.kind]||item.kind;
        desc.appendChild(el("strong","",typeName+" · "+item.unit_id));
        desc.appendChild(el("p","",(item.episode_id||"项目级")+" · V"+item.revision+
          " · "+(item.fields.title||item.fields.name||"待审核")));
        row.appendChild(desc);
        const open=el("button","prod-new prod-secondary","打开并审核");
        open.type="button";
        open.addEventListener("click",()=>{
          if(item.kind==="scene"){
            sceneProjectId=item.project_id;
            sceneCurrentId=item.unit_id;sceneData=null;
            navigateWorkspace("scenes");
            loadScenes().catch(e=>$("sceneMessage").textContent=e.message);
            return;
          }
          if(item.kind==="character_asset"){
            characterProjectId=item.project_id;
            characterCurrentId=item.character_id;
            characterData=null;characterV2Data=null;
            navigateWorkspace("characters");
            loadCharacters().catch(e=>$("characterMessage").textContent=e.message);
            return;
          }
          const page=map[item.kind],state=wfState[item.kind];
          state.project=item.project_id;
          state.episode=item.episode_id||state.episode;
          state.selected=item.unit_id;state.editing=false;
          navigateWorkspace(page);
          workflowLoad(item.kind);
        });
        row.appendChild(open);list.appendChild(row);
      }
    }catch(error){label.textContent="审核队列失败："+error.message;}
  }
  $("wfReviewProject").addEventListener("change",()=>{
    syncWorkflowProjects(workflowProjects(),latest?.production?.episodes||[]);
    workflowLoadReviews();
  });
  $("wfReviewEpisode").addEventListener("change",workflowLoadReviews);
  $("wfReviewRefresh").addEventListener("click",workflowLoadReviews);

  const sceneTypeName={interior:"室内",exterior:"室外",
    transition:"过渡场景",abstract:"抽象空间"};
  const sceneStatusName={draft:"草稿",in_review:"待审核",
    approved:"已批准",rejected:"已驳回"};
  const sceneRefName={overview:"总览",camera_angle:"机位参考",
    lighting:"光照",layout:"结构布局",inspiration:"创意参考"};

  function syncSceneProjects(projects,episodes){
    const select=$("sceneProject");
    if(!microsoftOwner){select.disabled=true;return;}
    const valid=projects.map(p=>p.project_id);
    const previous=sceneProjectId;
    const signature=JSON.stringify(valid);
    if(select.dataset.projects!==signature){
      select.dataset.projects=signature;
      select.replaceChildren();
      for(const project of projects){
        const option=el("option","",project.title+" · "+project.project_id);
        option.value=project.project_id;select.appendChild(option);
      }
    }
    if(!valid.includes(sceneProjectId)){
      sceneProjectId=valid[0]||"";
      sceneData=null;sceneCurrentId="";sceneActiveVisualId="";
    }
    select.value=sceneProjectId;
    select.disabled=!sceneProjectId;
    $("sceneCreateBtn").disabled=!sceneProjectId;
    sceneEpisodes=episodes.filter(e=>e.project_id===sceneProjectId);
    if(previous!==sceneProjectId&&sceneProjectId)
      loadScenes().catch(err=>$("sceneMessage").textContent="读取场景失败："+err.message);
  }

  async function scenePost(action,body){
    if(!microsoftOwner||!csrf)throw Error("仅 Microsoft 所有者可以修改场景");
    const response=await fetch("./api/v1/scenes/"+action,{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({csrf,...body}),cache:"no-store"
    });
    const data=await response.json();
    if(!response.ok)throw Error(data.reason||"场景保存失败");
    return data;
  }

  async function loadScenes(){
    const pid=sceneProjectId;
    if(!microsoftOwner||!pid)return;
    const response=await fetch("./api/v1/scenes?project="+encodeURIComponent(pid),
      {cache:"no-store"});
    const value=await response.json();
    if(!response.ok)throw Error(value.reason||"场景库不可读");
    if(pid!==sceneProjectId)return;
    sceneData=value;
    if(!value.scenes.some(scene=>scene.scene_id===sceneCurrentId))
      sceneCurrentId=value.scenes[0]?.scene_id||"";
    renderScenes();
  }

  function renderSceneList(){
    const list=$("sceneList");list.replaceChildren();
    const scenes=sceneData?.scenes||[];
    const search=$("sceneSearch").value.trim().toLocaleLowerCase();
    const filter=$("sceneTypeFilter").value;
    const visible=scenes.filter(scene=>
      (!filter||scene.scene_type===filter) &&
      (!search||(scene.display_name+" "+scene.scene_id).toLocaleLowerCase().includes(search)));
    $("sceneVisibleCount").textContent=String(visible.length);
    if(!visible.length){
      const empty=el("div","scene-rail-empty");
      empty.appendChild(el("span","scene-rail-empty-icon","▧"));
      empty.appendChild(el("strong","",scenes.length?"没有符合条件的场景":"暂无场景档案"));
      empty.appendChild(el("p","",scenes.length?"试试清除搜索或筛选条件。":"点击右上角「新建场景」，建立第一份真实场景资料。"));
      list.appendChild(empty);return;
    }
    for(const scene of visible){
      const button=el("button","scene-entry"+(
        sceneCurrentId===scene.scene_id?" active":""));
      button.type="button";
      button.setAttribute("aria-pressed",String(sceneCurrentId===scene.scene_id));
      const coverData=scene.visuals.find(v=>v.visual_id===scene.canonical?.visual_id)||
        scene.visuals[0];
      if(coverData){
        const cover=el("img","scene-entry-cover");
        cover.loading="lazy";cover.alt=scene.display_name;
        cover.src=visualURL(sceneData.project_id,coverData.episode_id,coverData.visual_id);
        button.appendChild(cover);
      }else button.appendChild(el("span","scene-entry-cover scene-cover-empty","▧"));
      const desc=el("span","scene-entry-copy");
      desc.appendChild(el("strong","",scene.display_name));
      desc.appendChild(el("small","",scene.scene_id+" · "+(sceneTypeName[scene.scene_type]||"场景")));
      const status=el("span","scene-list-status "+scene.status,
        sceneStatusName[scene.status]||scene.status);
      desc.appendChild(status);
      button.appendChild(desc);
      button.addEventListener("click",()=>{
        sceneCurrentId=scene.scene_id;sceneActiveVisualId="";
        if($("sceneEditorDialog").open)$("sceneEditorDialog").close();
        renderScenes();
      });
      list.appendChild(button);
    }
  }

  function renderScenes(){
    const data=sceneData;if(!data)return;
    const detail=$("sceneDetail"),stage=$("sceneStage"),
      gallery=$("sceneGallery"),tools=$("sceneAssetTools");
    detail.replaceChildren();stage.replaceChildren();
    gallery.replaceChildren();tools.replaceChildren();
    $("sceneCount").textContent=data.scenes.length+" 处场景";
    $("sceneMessage").textContent=data.scenes.length?
      "当前显示真实场景资料。图片和版本由项目数据库提供，候选不会自动获批。":
      "此项目还没有场景。先创建空间结构，再上传候选图并提交审核。";
    renderSceneList();
    const scene=data.scenes.find(x=>x.scene_id===sceneCurrentId);
    if(!scene){
      $("sceneActiveName").textContent="请选择场景";
      $("sceneActiveStatus").textContent="尚无场景";
      $("sceneActiveStatus").className="scene-status-pill";
      $("sceneImageCount").textContent="0 张图片";
      const empty=el("div","scene-stage-empty");
      empty.appendChild(el("div","scene-stage-emblem","▧"));
      empty.appendChild(el("strong","","从这里开始建立场景世界"));
      empty.appendChild(el("p","","每处场景拥有独立的空间布局、光照、机位规则和参考图。"));
      const start=el("button","prod-new scene-primary-button","＋ 创建第一个场景");
      start.type="button";start.addEventListener("click",()=>openSceneEditor());
      empty.appendChild(start);stage.appendChild(empty);
      detail.appendChild(el("p","scene-inspector-placeholder",
        "尚无场景属性。创建或选择场景后，可以查看布局说明、上传图片并进行人工审核。"));
      return;
    }
    $("sceneActiveName").textContent=scene.display_name;
    $("sceneActiveStatus").textContent=sceneStatusName[scene.status]||scene.status;
    $("sceneActiveStatus").className="scene-status-pill "+scene.status;
    const preferred=scene.visuals.find(v=>v.visual_id===sceneActiveVisualId)||
      scene.visuals.find(v=>v.visual_id===scene.canonical?.visual_id)||
      scene.visuals[0];
    sceneActiveVisualId=preferred?.visual_id||"";
    $("sceneImageCount").textContent=scene.visuals.length+" 张图片";
    if(preferred){
      const picture=el("img","scene-main-image");
      picture.src=visualURL(data.project_id,preferred.episode_id,preferred.visual_id);
      picture.alt=scene.display_name+" · "+preferred.filename;
      stage.appendChild(picture);
      const overlay=el("div","scene-image-overlay");
      overlay.appendChild(el("span","",preferred.episode_id+" · "+preferred.filename));
      if(scene.canonical?.visual_id===preferred.visual_id)
        overlay.appendChild(el("span","scene-stage-approved","✓ 已批准参考"));
      else overlay.appendChild(el("span","scene-stage-draft","候选图片"));
      stage.appendChild(overlay);
      const zoom=el("button","scene-zoom","⤢ 放大预览");
      zoom.type="button";
      zoom.addEventListener("click",()=>{
        $("sceneImageTitle").textContent=scene.display_name+" · "+preferred.filename;
        $("sceneImageFull").src=picture.src;
        $("sceneImageFull").alt=picture.alt;
        $("sceneImageDialog").showModal();
      });
      stage.appendChild(zoom);
    }else{
      const empty=el("div","scene-stage-empty");
      empty.appendChild(el("div","scene-stage-emblem","▧"));
      empty.appendChild(el("strong","","尚无场景预览"));
      empty.appendChild(el("p","","空间设定已保存。上传场景图后，将在这里显示实际的参考图片。"));
      const add=el("button","prod-new scene-primary-button","＋ 上传第一张参考图");
      add.type="button";
      add.addEventListener("click",()=>tools.querySelector('input[type="file"]')?.click());
      empty.appendChild(add);stage.appendChild(empty);
    }

    for(const visual of scene.visuals){
      const card=el("button","scene-visual"+(
        sceneActiveVisualId===visual.visual_id?" active":""));
      card.type="button";
      card.setAttribute("aria-label","预览 "+visual.filename);
      card.setAttribute("aria-pressed",String(sceneActiveVisualId===visual.visual_id));
      const picture=el("img","");
      picture.loading="lazy";picture.alt=visual.filename;
      picture.src=visualURL(data.project_id,visual.episode_id,visual.visual_id);
      card.appendChild(picture);
      const caption=el("span","",visual.filename);
      card.appendChild(caption);
      if(scene.canonical?.visual_id===visual.visual_id)
        card.appendChild(el("small","scene-approved-label","✓ 已批准 V"+scene.approved_revision));
      else if(!visual.linked)card.appendChild(el("small","","未关联"));
      else card.appendChild(el("small","","候选 V"+visual.version));
      card.addEventListener("click",()=>{
        sceneActiveVisualId=visual.visual_id;
        renderScenes();
      });
      gallery.appendChild(card);
    }
    if(!scene.visuals.length)gallery.appendChild(
      el("p","scene-gallery-empty","暂无图片版本。点击下方上传真实参考图。"));

    const box=el("div","scene-inspector-header");
    box.appendChild(el("h3","",scene.display_name));
    box.appendChild(el("span","scene-inspector-meta",
      scene.scene_id+" · "+sceneTypeName[scene.scene_type]+" · Revision "+scene.revision));
    if(scene.approved_revision!==null)
      box.appendChild(el("span","scene-preserved-version",
        "历史批准版 V"+scene.approved_revision+" 保留不变"));
    detail.appendChild(box);
    const edit=el("button","prod-new prod-secondary scene-edit-button","✎ 编辑场景设定");
    edit.type="button";edit.disabled=scene.status==="in_review";
    edit.addEventListener("click",()=>openSceneEditor(scene));
    detail.appendChild(edit);
    for(const [name,value] of [
        ["固定空间布局",scene.layout_notes],
        ["光照与时间",scene.lighting_notes],
        ["机位规则",scene.camera_rules],
        ["连续性锁定",scene.continuity_rules],
        ["剧情备注",scene.scene_notes]]){
      const row=el("section","scene-info");
      row.appendChild(el("strong","",name));
      row.appendChild(el("p","",value||"尚未填写"));
      detail.appendChild(row);
    }

    if(preferred&&!preferred.linked){
      const link=el("button","prod-new prod-secondary","＋ 将当前图片关联为候选");
      link.type="button";
      link.addEventListener("click",async()=>{
        link.disabled=true;
        try{
          await scenePost("link",{project_id:data.project_id,
            scene_id:scene.scene_id,visual_id:preferred.visual_id,
            reference_type:"overview"});
          await loadScenes();
        }catch(error){$("sceneMessage").textContent=error.message;link.disabled=false;}
      });
      detail.appendChild(link);
    }
    const other=data.available_visuals.filter(v=>
      !scene.visuals.some(x=>x.visual_id===v.visual_id));
    if(other.length){
      const wrap=el("div","scene-link-controls");
      wrap.appendChild(el("strong","", "关联项目中已有的其他场景图片"));
      const picker=el("select","");
      for(const image of other){
        const option=el("option","",image.episode_id+" · "+image.filename+
          " · "+image.subject_id);
        option.value=image.visual_id;picker.appendChild(option);
      }
      const type=el("select","");
      for(const [key,label] of Object.entries(sceneRefName)){
        const opt=el("option","",label);opt.value=key;type.appendChild(opt);
      }
      const button=el("button","prod-new prod-secondary","关联候选");
      button.type="button";
      button.addEventListener("click",async()=>{
        button.disabled=true;
        try{
          await scenePost("link",{project_id:data.project_id,
            scene_id:scene.scene_id,visual_id:picker.value,
            reference_type:type.value});await loadScenes();
        }catch(error){$("sceneMessage").textContent=error.message;
          button.disabled=false;}
      });
      wrap.append(picker,type,button);tools.appendChild(wrap);
    }

    const upload=el("form","scene-upload-form");
    upload.appendChild(el("strong","","上传当前场景参考图"));
    const desc=el("span","scene-upload-hint",
      "选择所属剧集，将原图保存到该剧集并关联至当前场景。上传仅生成候选。");
    upload.appendChild(desc);
    const line=el("div","scene-upload-line");
    const episodeSelect=el("select","");
    episodeSelect.setAttribute("aria-label","选择图片所属剧集");
    for(const ep of sceneEpisodes){
      const opt=el("option","",ep.episode_id+" · "+ep.title);
      opt.value=ep.episode_id;episodeSelect.appendChild(opt);
    }
    const file=el("input","");file.type="file";
    file.setAttribute("aria-label","选择场景图片");
    file.accept="image/png,image/jpeg,image/webp";file.required=true;
    const send=el("button","prod-new scene-primary-button","上传并关联");
    send.type="submit";send.disabled=!sceneEpisodes.length;
    line.append(episodeSelect,file,send);
    upload.appendChild(line);
    upload.addEventListener("submit",async event=>{
      event.preventDefault();
      if(!file.files?.length)return;
      const f=file.files[0];
      if(f.size<32||f.size>8*1024*1024||
          !["image/png","image/jpeg","image/webp"].includes(f.type)){
        $("sceneMessage").textContent="仅支持 8MB 内的 PNG/JPG/WebP 图片";return;
      }
      send.disabled=true;
      try{
        const image_base64=await fileAsBase64(f);
        const response=await fetch("./api/v1/production/visual/upload",{
          method:"POST",headers:{"Content-Type":"application/json"},
          body:JSON.stringify({csrf,project_id:data.project_id,
            episode_id:episodeSelect.value,kind:"scene",
            subject_id:scene.scene_id,filename:f.name,image_base64}),cache:"no-store"
        });
        const result=await response.json();
        if(!response.ok)throw Error(result.reason||"图片上传失败");
        await scenePost("link",{project_id:data.project_id,
          scene_id:scene.scene_id,visual_id:result.visual_id,
          reference_type:"overview"});
        sceneActiveVisualId=result.visual_id;
        await loadScenes();
        $("sceneMessage").textContent="已上传并关联候选图 V"+result.version+
          "。需要人工审核后才能成为正式场景参考。";
      }catch(error){$("sceneMessage").textContent="上传失败："+error.message;
        send.disabled=false;}
    });
    tools.appendChild(upload);

    const actions=el("section","scene-review");
    actions.appendChild(el("strong","","版本审核"));
    actions.appendChild(el("p","scene-review-hint",
      "审核将记录当前场景版本、原图哈希与审批理由；旧版永不覆盖。"));
    const rationale=el("textarea","");
    rationale.placeholder="填写审核依据（至少 8 字）";
    rationale.setAttribute("aria-label","审核理由");
    rationale.maxLength=600;
    actions.appendChild(rationale);
    const valid=scene.visuals.filter(v=>v.linked&&v.subject_id===scene.scene_id);
    const photoSelect=el("select","");
    photoSelect.setAttribute("aria-label","选择正式参考图片");
    for(const v of valid){
      const option=el("option","",v.episode_id+" · "+v.filename+" / V"+v.version);
      option.value=v.visual_id;photoSelect.appendChild(option);
    }
    if(!valid.length){
      const option=el("option","","暂无合格的独立场景图片");
      option.disabled=true;photoSelect.appendChild(option);
    }
    photoSelect.disabled=!valid.length;
    actions.appendChild(photoSelect);
    const commands=el("div","scene-review-actions");
    const choices=scene.status==="draft"?[["submit","提交审核"]]:
      scene.status==="in_review"?[["approve","批准当前版本"],["reject","驳回"]]:[];
    for(const [decision,title] of choices){
      const button=el("button",decision==="approve"?
        "prod-new scene-primary-button":"prod-new prod-secondary",title);
      button.type="button";button.disabled=decision==="approve"&&!valid.length;
      button.addEventListener("click",async()=>{
        if(rationale.value.trim().length<8){
          $("sceneMessage").textContent="审核理由至少 8 个字";return;
        }
        if(decision==="approve"&&!window.confirm(
          "确认将此场景版本和所选图片批准为正式参考？旧版本会保留。"))return;
        button.disabled=true;
        try{
          await scenePost("review",{project_id:data.project_id,
            scene_id:scene.scene_id,expected_revision:scene.revision,
            decision,visual_id:decision==="approve"?photoSelect.value:null,
            rationale:rationale.value.trim()});
          await loadScenes();
          $("sceneMessage").textContent="审核操作已记录："+title;
        }catch(error){$("sceneMessage").textContent="审核失败："+error.message;
          button.disabled=false;}
      });
      commands.appendChild(button);
    }
    if(!choices.length)commands.appendChild(el("p","scene-review-complete",
      "此版本已处理。如需调整，请建立新的修订草稿。"));
    actions.appendChild(commands);detail.appendChild(actions);
  }

  function openSceneEditor(scene=null){
    if(!microsoftOwner||!sceneProjectId)return;
    sceneEditId=scene?.scene_id||null;
    $("sceneEditorTitle").textContent=scene?"修订 "+scene.display_name:"创建场景";
    $("sceneId").value=scene?.scene_id||"";
    $("sceneId").disabled=!!scene;
    $("sceneName").value=scene?.display_name||"";
    $("sceneType").value=scene?.scene_type||"interior";
    $("sceneLayoutNotes").value=scene?.layout_notes||"";
    $("sceneLighting").value=scene?.lighting_notes||"";
    $("sceneCamera").value=scene?.camera_rules||"";
    $("sceneContinuity").value=scene?.continuity_rules||"";
    $("sceneNotes").value=scene?.scene_notes||"";
    $("sceneEditorDialog").showModal();
  }
  $("sceneProject").addEventListener("change",()=>{
    sceneProjectId=$("sceneProject").value;
    sceneCurrentId="";sceneData=null;sceneActiveVisualId="";
    if($("sceneEditorDialog").open)$("sceneEditorDialog").close();
    // Render's next production snapshot provides episodes for this project;
    // the latest dashboard is already loaded when a project is selected.
    sceneEpisodes=(latest?.production?.episodes||[]).filter(
      e=>e.project_id===sceneProjectId);
    loadScenes().catch(error=>$("sceneMessage").textContent=error.message);
  });
  $("sceneCreateBtn").addEventListener("click",()=>openSceneEditor());
  $("sceneEditorCancel").addEventListener("click",()=>$("sceneEditorDialog").close());
  $("sceneImageClose").addEventListener("click",()=>$("sceneImageDialog").close());
  $("sceneSearch").addEventListener("input",()=>{if(sceneData)renderSceneList();});
  $("sceneTypeFilter").addEventListener("change",()=>{if(sceneData)renderSceneList();});
  $("sceneEditor").addEventListener("submit",async event=>{
    event.preventDefault();
    const existing=sceneData?.scenes.find(x=>x.scene_id===sceneEditId);
    const values={project_id:sceneProjectId,
      scene_id:existing?.scene_id||$("sceneId").value.trim(),
      display_name:$("sceneName").value.trim(),scene_type:$("sceneType").value,
      layout_notes:$("sceneLayoutNotes").value.trim(),
      lighting_notes:$("sceneLighting").value.trim(),
      camera_rules:$("sceneCamera").value.trim(),
      continuity_rules:$("sceneContinuity").value.trim(),
      scene_notes:$("sceneNotes").value.trim()};
    const button=$("sceneSaveBtn");button.disabled=true;
    try{
      if(existing){
        await scenePost("update",{...values,expected_revision:existing.revision});
      }else{
        await scenePost("create",values);
      }
      sceneCurrentId=values.scene_id;
      $("sceneEditorDialog").close();
      await loadScenes();
    }catch(e){$("sceneMessage").textContent="保存失败："+e.message;}
    finally{button.disabled=false;}
  });

  function syncCharacterProjects(projects) {
    const select=$("characterProject"), valid=projects.map(p=>p.project_id);
    if(!microsoftOwner){select.disabled=true;return;}
    const previous=characterProjectId;
    select.disabled=!valid.length;
    const sig=JSON.stringify(valid);
    if(select.dataset.projects!==sig){
      select.dataset.projects=sig;
      select.replaceChildren();
      for(const p of projects){
        const option=el("option","",p.title+" · "+p.project_id);
        option.value=p.project_id;select.appendChild(option);
      }
    }
    if(!valid.includes(characterProjectId)){
      characterProjectId=valid[0]||"";
      characterCurrentId="";
      characterData=null;
      characterV2Data=null;
    }
    select.value=characterProjectId;
    $("characterSeedBtn").hidden=characterProjectId!=="WaitingOffice";
    $("characterCreateBtn").hidden=!valid.length;
    if(characterProjectId && previous!==characterProjectId)
      loadCharacters().catch(err=>$("characterMessage").textContent=err.message);
  }

  async function characterPost(action,body) {
    if(!microsoftOwner||!csrf)throw Error("仅 Microsoft 所有者可编辑角色库");
    const res=await fetch("./api/v1/characters/"+action,{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({csrf,...body}),cache:"no-store"
    });
    const value=await res.json();
    if(!res.ok)throw Error(value.reason||"角色库操作失败");
    return value;
  }

  async function loadCharacters() {
    const projectId=characterProjectId;
    if(!projectId||!microsoftOwner)return;
    const res=await fetch("./api/v1/characters?project="+encodeURIComponent(projectId),
      {cache:"no-store"});
    const value=await res.json();
    if(!res.ok)throw Error(value.reason||"角色库暂不可用");
    if(projectId!==characterProjectId)return;
    characterData=value;
    if(!value.characters.some(c=>c.character_id===characterCurrentId))
      characterCurrentId=value.characters[0]?.character_id||"";
    renderCharacterLibrary();
    await loadCharacterV2();
  }


  function renderCharacterList() {
    const list=$("characterList");list.replaceChildren();
    const profiles=characterData?.characters||[];
    const q=$("characterSearch").value.trim().toLocaleLowerCase();
    const role=$("characterRoleFilter").value;
    const shown=profiles.filter(c=>
      (!role||c.role===role) &&
      (!q||(c.display_name+" "+c.character_id).toLocaleLowerCase().includes(q)));
    $("characterVisibleCount").textContent=String(shown.length);
    if(!shown.length) {
      const empty=el("div","character-rail-empty");
      empty.appendChild(el("div","character-empty-symbol","♙"));
      empty.appendChild(el("strong","",profiles.length?"没有匹配的角色":"暂无角色档案"));
      empty.appendChild(el("p","",profiles.length?
        "试试清除搜索条件。":"可新建原创角色，或导入项目预设的六位角色档案。"));
      list.appendChild(empty);
      return;
    }
    for(const c of shown){
      const button=el("button","character-entry"+(
        characterCurrentId===c.character_id?" active":""));
      button.type="button";
      button.setAttribute("aria-pressed",String(characterCurrentId===c.character_id));
      const portrait=c.visuals.find(v=>v.visual_id===c.master?.visual_id)||
        c.visuals.find(v=>v.subject_id===c.character_id);
      if(portrait){
        const avatar=el("img","character-avatar-image");
        avatar.loading="lazy";avatar.alt=c.display_name;
        avatar.src=visualURL(characterData.project_id,portrait.episode_id,portrait.visual_id);
        button.appendChild(avatar);
      }else button.appendChild(el("span","character-avatar",
        c.character_id==="CHAR_ZERO"?"◌":c.role==="extended"?"✧":"♙"));
      const desc=el("span","character-entry-copy");
      desc.appendChild(el("strong","",c.display_name));
      desc.appendChild(el("small","",c.character_id+" · "+(charRoleName[c.role]||c.role)));
      desc.appendChild(el("span","character-entry-status "+(c.master?"approved":"draft"),
        c.master?"有已审母版":"待批准母版"));
      button.appendChild(desc);
      button.addEventListener("click",()=>{
        characterCurrentId=c.character_id;
        characterActiveVisualId="";
        characterV2Data=null;characterV2Category="profile";
        if($("characterEditorDialog").open)$("characterEditorDialog").close();
        if($("characterAssetEditorDialog").open)$("characterAssetEditorDialog").close();
        renderCharacterLibrary();
        loadCharacterV2().catch(err=>$("characterMessage").textContent=err.message);
      });
      list.appendChild(button);
    }
  }

  function characterOpenImage(profile,visual) {
    $("characterImageTitle").textContent=profile.display_name+" · "+visual.filename;
    $("characterImageFull").src=visualURL(characterProjectId,visual.episode_id,visual.visual_id);
    $("characterImageFull").alt=profile.display_name+" 候选参考："+visual.filename;
    $("characterImageDialog").showModal();
  }

  function renderCharacterLibrary() {
    const data=characterData;if(!data)return;
    const profiles=data.characters||[];
    $("characterCount").textContent=profiles.filter(c=>c.role==="main").length+
      " 位主角 · "+profiles.filter(c=>c.role==="extended").length+" 位扩展";
    $("characterMessage").textContent=profiles.length?
      "角色信息来自真实数据库。原图保留在对应剧集，未批准的素材不会自动成为正式母版。":
      "当前项目尚无角色档案。可创建角色或导入项目角色预设。";
    renderCharacterList();
    const stage=$("characterStage"),gallery=$("characterVisualGallery"),
      detail=$("characterDetail"),tools=$("characterReferenceTools"),
      panel=$("characterAssetsPanel");
    stage.replaceChildren();gallery.replaceChildren();
    detail.replaceChildren();tools.replaceChildren();panel.replaceChildren();
    const c=profiles.find(x=>x.character_id===characterCurrentId);
    if(!c){
      $("characterActiveName").textContent="角色预览";
      $("characterActiveStatus").textContent="尚无角色";
      $("characterActiveStatus").className="character-status-pill";
      $("characterVisualCount").textContent="0 张图片";
      const empty=el("div","character-stage-empty");
      empty.appendChild(el("div","character-stage-emblem","♙"));
      empty.appendChild(el("strong","","建立角色的标准视觉身份"));
      empty.appendChild(el("p","", "角色设定和分类资产会在这里管理。没有图片时不会展示虚构的人物。"));
      stage.appendChild(empty);
      detail.appendChild(el("p","character-inspector-empty",
        "选择或创建角色后，查看身份硬约束、视觉版本、审核依据和完整资产状态。"));
      return;
    }
    $("characterActiveName").textContent=c.display_name;
    $("characterActiveStatus").textContent=c.master?"正式母版已批准":"母版待审核";
    $("characterActiveStatus").className="character-status-pill "+
      (c.master?"approved":"draft");
    $("characterVisualCount").textContent=c.visuals.length+" 张参考图片";
    const picked=c.visuals.find(v=>v.visual_id===characterActiveVisualId)||
      c.visuals.find(v=>v.visual_id===c.master?.visual_id)||
      c.visuals.find(v=>v.subject_id===c.character_id)||
      c.visuals[0];
    characterActiveVisualId=picked?.visual_id||"";
    if(picked){
      const img=el("img","character-main-image");
      img.alt=c.display_name+" · "+picked.filename;
      img.src=visualURL(data.project_id,picked.episode_id,picked.visual_id);
      stage.appendChild(img);
      const bar=el("div","character-image-overlay");
      bar.appendChild(el("span","",picked.episode_id+" / "+picked.filename));
      const canonical=c.master?.visual_id===picked.visual_id;
      bar.appendChild(el("span",canonical?"character-image-approved":"character-image-candidate",
        canonical?"✓ 已批准母版":"候选素材 · 尚未批准"));
      stage.appendChild(bar);
      const zoom=el("button","character-image-zoom","⤢ 放大预览");
      zoom.type="button";zoom.addEventListener("click",()=>characterOpenImage(c,picked));
      stage.appendChild(zoom);
    } else {
      const empty=el("div","character-stage-empty");
      empty.appendChild(el("div","character-stage-emblem","♙"));
      empty.appendChild(el("strong","","暂无角色参考图"));
      empty.appendChild(el("p","",
        "先录入人物特征和身份约束，再上传单人物正面基准图。"));
      stage.appendChild(empty);
    }
    for(const v of c.visuals){
      const tile=el("button","character-visual-tile"+(
        picked?.visual_id===v.visual_id?" active":""));
      tile.type="button";
      tile.setAttribute("aria-pressed",String(picked?.visual_id===v.visual_id));
      tile.setAttribute("aria-label","预览 "+v.filename);
      const image=el("img","");
      image.loading="lazy";image.alt=c.display_name+" "+v.filename;
      image.src=visualURL(data.project_id,v.episode_id,v.visual_id);
      tile.appendChild(image);
      tile.appendChild(el("span","",v.filename));
      tile.appendChild(el("small",c.master?.visual_id===v.visual_id?
        "character-image-approved":"",c.master?.visual_id===v.visual_id?
        "✓ 正式母版":"候选 · "+(charRefName[v.reference_type]||v.reference_type)));
      tile.addEventListener("click",()=>{
        characterActiveVisualId=v.visual_id;
        renderCharacterLibrary();
        renderCharacterV2(c,$("characterAssetsPanel"));
      });
      gallery.appendChild(tile);
    }
    if(!c.visuals.length)gallery.appendChild(
      el("p","character-gallery-empty","暂无图片版本。下方可上传真实角色参考图。"));

    const top=el("div","character-inspector-profile");
    top.appendChild(el("h3","",c.display_name));
    top.appendChild(el("p","",c.character_id+" · "+
      (charRoleName[c.role]||c.role)+" · 人物档案 V"+c.revision));
    if(c.master)top.appendChild(el("span","character-history-approved",
      "正式母版 "+c.master.visual_id+" · 已留审计记录"));
    else top.appendChild(el("span","character-history-draft",
      "尚无人工批准的正式母版"));
    detail.appendChild(top);
    const edit=el("button","prod-new prod-secondary character-edit-button","✎ 编辑角色主档");
    edit.type="button";edit.addEventListener("click",()=>openCharacterEditor(c));
    detail.appendChild(edit);
    for(const [title,value] of [["官方视觉依据（文字）",c.brand_basis],
       ["原创设计语言",c.design_language],["人物性格与剧情",c.character_notes]]){
      const card=el("section","character-info");
      card.appendChild(el("strong","",title));
      card.appendChild(el("p","",value||"尚未填写"));
      detail.appendChild(card);
    }
    detail.appendChild(el("div","character-logo-rule",
      "原创性硬约束：仅借鉴抽象配色、秩序、连接等设计语言；不得使用、描摹、拼接或隐藏任何官方 Logo。"));

    const review=el("section","character-main-review");
    review.appendChild(el("strong","","人物母版审核"));
    const msg=el("p","",picked?
      "当前查看："+picked.filename+"（"+picked.episode_id+"）":
      "尚无图片。请先上传角色独立参考图。");
    review.appendChild(msg);
    const note=el("textarea","character-review-note");
    note.maxLength=600;
    note.setAttribute("aria-label","人物母版审核理由");
    note.placeholder="审核依据至少 8 字；核对发色、瞳色、衣服和禁止项…";
    review.appendChild(note);
    const approve=el("button","prod-new character-primary-button","批准当前图片为正式母版");
    approve.type="button";
    const own=picked&&picked.subject_id===c.character_id;
    approve.disabled=!own||c.master?.visual_id===picked?.visual_id;
    if(picked&&!own)review.appendChild(el("p","character-review-alert",
      "这是综合/其他人物参考图，只能用于创意参考，不能批准为此角色的单人母版。"));
    approve.addEventListener("click",async()=>{
      if(!picked||picked.subject_id!==c.character_id)return;
      const rationale=note.value.trim();
      if(rationale.length<8){
        $("characterMessage").textContent="先填写至少 8 字的母版审核理由。";
        note.focus();return;
      }
      if(!window.confirm("确认将 "+picked.filename+" 设为 "+c.display_name+
        " 的项目级正式母版？请先检查身份特征和所有官方 Logo 禁用项。"))return;
      approve.disabled=true;
      try{
        await characterPost("approve",{project_id:data.project_id,
          character_id:c.character_id,visual_id:picked.visual_id,rationale});
        await loadCharacters();
        $("characterMessage").textContent="已记录人工批准；原图、其他候选及审核历史未覆盖。";
      }catch(error){
        $("characterMessage").textContent="批准失败："+error.message;
        approve.disabled=false;
      }
    });
    review.appendChild(approve);detail.appendChild(review);

    const episodes=(latest?.production?.episodes||[]).filter(
      episode=>episode.project_id===data.project_id);
    const upload=el("form","character-upload-form");
    upload.appendChild(el("strong","","上传此人物的候选图"));
    upload.appendChild(el("p","",
      "图片保存到所选剧集并自动关联当前角色；上传不代表审核通过。"));
    const row=el("div","character-upload-row");
    const select=el("select","");
    select.setAttribute("aria-label","选择素材所属剧集");
    for(const ep of episodes){
      const option=el("option","",ep.episode_id+" · "+ep.title);
      option.value=ep.episode_id;select.appendChild(option);
    }
    const file=el("input","");file.type="file";
    file.accept="image/png,image/jpeg,image/webp";
    file.required=true;file.setAttribute("aria-label","选择人物候选图");
    const send=el("button","prod-new character-primary-button","上传并关联");
    send.type="submit";send.disabled=!episodes.length;
    row.append(select,file,send);upload.appendChild(row);
    upload.addEventListener("submit",async event=>{
      event.preventDefault();
      if(!file.files?.length)return;
      const f=file.files[0];
      if(f.size<32||f.size>8*1024*1024||
         !["image/png","image/jpeg","image/webp"].includes(f.type)){
        $("characterMessage").textContent="仅支持不超过 8MB 的 PNG/JPG/WebP 图片";return;
      }
      send.disabled=true;
      try{
        const image_base64=await fileAsBase64(f);
        const response=await fetch("./api/v1/production/visual/upload",{
          method:"POST",headers:{"Content-Type":"application/json"},
          body:JSON.stringify({csrf,project_id:data.project_id,
            episode_id:select.value,kind:"character",
            subject_id:c.character_id,filename:f.name,image_base64}),
          cache:"no-store"});
        const result=await response.json();
        if(!response.ok)throw Error(result.reason||"图片上传失败");
        characterActiveVisualId=result.visual_id;
        await loadCharacters();
        $("characterMessage").textContent="已上传候选图片 V"+result.version+
          "；只有人工审核才能作为正式角色母版。";
      }catch(error){
        $("characterMessage").textContent="上传失败："+error.message;
        send.disabled=false;
      }
    });
    tools.appendChild(upload);

    const remaining=(data.available_visuals||[]).filter(v=>
      !c.visuals.some(x=>x.visual_id===v.visual_id));
    if(remaining.length){
      const controls=el("div","character-ref-controls");
      controls.appendChild(el("strong","", "关联项目中已有参考图"));
      const picker=el("select","");
      picker.setAttribute("aria-label","选择现有角色图片");
      for(const v of remaining){
        const option=el("option","",v.episode_id+" · "+v.filename+
          " · "+v.subject_id);
        option.value=v.visual_id;picker.appendChild(option);
      }
      const type=el("select","");
      type.setAttribute("aria-label","选择角色参考类型");
      for(const [key,label] of Object.entries(charRefName)){
        const option=el("option","",label);option.value=key;type.appendChild(option);
      }
      type.value="inspiration";
      const button=el("button","prod-new prod-secondary","关联候选");
      button.type="button";
      button.addEventListener("click",async()=>{
        button.disabled=true;
        try{
          await characterPost("link",{project_id:data.project_id,
            character_id:c.character_id,visual_id:picker.value,
            reference_type:type.value});
          await loadCharacters();
        }catch(error){
          $("characterMessage").textContent="关联失败："+error.message;button.disabled=false;
        }
      });
      controls.append(picker,type,button);
      tools.appendChild(controls);
    }
    renderCharacterV2(c,panel);
  }

  const v2CategoryNames={
    profile:"01 主档硬约束",master:"02 批准母版",turnaround:"03 八方向视图",
    face:"04 表情与口型",hair:"05 发型与五官",costume:"06 服装结构",
    palette:"07 配色材质",prop:"08 道具",motion:"09 动作模板",
    relationship:"10 同框关系",continuity:"11 镜头连续性",
    rules:"12 禁止项与质检"
  };
  const v2FieldNames={
    identity_lock:"身份锁定特征",story_function:"剧情功能",personality:"性格",
    story_notes:"故事备注",framing:"景别",body_proportions:"身体比例",
    outfit_id:"服装编号",hair_variant_id:"发型编号",direction:"朝向",
    camera_height:"机位高度",proportions:"比例",expression:"表情",
    intensity:"强度",eyeline:"视线",viseme:"口型",region:"发型区域",
    fringe_partition:"刘海分区",length_boundary:"发尾边界",
    ornament_position:"发饰位置",piece_id:"服装部件编号",
    layer_order:"穿衣层序",silhouette_lock:"不可变化的外轮廓",
    far_view_rule:"远景简化规则",scope:"色板作用域",hex_srgb:"sRGB 颜色",
    material:"材质",lighting_rule:"不同光照规则",prop_id:"道具编号",
    grip_hand:"持握手",scale_rule:"大小比例",state_rule:"道具状态",
    action_id:"动作编号",key_pose_start:"起始关键姿势",
    key_pose_middle:"中间关键姿势",key_pose_end:"结束关键姿势",
    other_character_ids:"对方角色编号",height_rule:"身高关系",
    blocking:"同框走位",episode_id:"剧集编号",shot_id:"镜头编号",
    screen_side:"画面站位",before_state:"前镜头状态",
    after_state:"后镜头状态",severity:"严重程度",
    locked_attribute:"锁定属性",forbidden_change:"禁止变化内容",
    check_method:"检查办法"
  };
  const v2StatusName={draft:"草稿",in_review:"待审核",
    approved:"已批准",rejected:"已驳回"};
  const v2JipiteDefaults=[
    ["profile","identity","身份视觉锁定",
      "以 Revision 2 为文字约束；没有批准的视觉母版时不得标记角色就绪。",
      {identity_lock:"深栗色齐颈短发、自然侧分、琥珀棕瞳，原创人物",
       story_function:"事务所协调者；接纳零并调查异常连接",
       personality:"温和、理性、可靠"}],
    ["hair","standard","标准发型与五官约束",
      "详细发流和具体五官比例待第一张正确主立绘通过后补充。",
      {region:"头部整体",fringe_partition:"自然侧分，禁止银白色长发",
       length_boundary:"齐颈短发，长度不得超过锁骨"}],
    ["costume","daily","标准服装结构约束",
      "裁片与服装正背图片尚未制作，禁止将旧银发角色图作为服装母版。",
      {outfit_id:"GPT_DAILY_01",piece_id:"日常制服整体",
       layer_order:"象牙白外套、青绿色内衬、深灰下装",
       silhouette_lock:"克制的层次和交错衣襟；禁止拼成官方商标轮廓"}],
    ["rules","hard_identity","头发与眼睛绝对禁止变化",
      "任何违反发色、长度或眼睛颜色的图像一律退回。",
      {severity:"hard",locked_attribute:"发型、发色、瞳色",
       forbidden_change:"银白长发、青绿或蓝色眼睛、发型超出锁骨",
       check_method:"逐张比较正面、侧面、背面和特写"}],
    ["rules","brand_no_logo","原创性与品牌规则",
      "仅可抽象借鉴连接、协作、秩序与留白；不使用官方标志。",
      {severity:"hard",locked_attribute:"任何立绘、配饰、道具、卡面与视频",
       forbidden_change:"直接放入、描摹、拼接、隐藏、近似复刻任何官方 Logo",
       check_method:"人工检查全图、局部配饰和反向构图"}]
  ];

  async function loadCharacterV2() {
    const pid=characterProjectId,cid=characterCurrentId;
    if(!pid||!cid||!microsoftOwner)return;
    const res=await fetch("./api/v1/characters/assets?project="+
      encodeURIComponent(pid)+"&character="+encodeURIComponent(cid),
      {cache:"no-store"});
    const body=await res.json();
    if(!res.ok)throw Error(body.reason||"V2 资产库暂不可用");
    if(pid!==characterProjectId||cid!==characterCurrentId)return;
    characterV2Data=body;
    const profile=characterData?.characters.find(p=>p.character_id===cid);
    const panel=document.querySelector(".character-v2-section");
    if(panel&&profile)renderCharacterV2(profile,panel);
  }

  function renderCharacterV2(profile,panel) {
    panel.replaceChildren();
    const head=el("div","character-v2-header");
    head.appendChild(el("strong","","V2 · 分类资产库"));
    head.appendChild(el("span","character-v2-summary",
      "可追溯版本 · 原图不移动 · 未审核不成为正式母版"));
    panel.appendChild(head);
    if(!characterV2Data||characterV2Data.project_id!==characterProjectId||
        characterV2Data.character_id!==profile.character_id){
      panel.appendChild(el("p","character-message","正在加载 12 类角色资产…"));
      return;
    }
    const tabs=el("div","character-v2-tabs");
    for(const [key,name] of Object.entries(v2CategoryNames)){
      const tally=characterV2Data.counts[key];
      const btn=el("button","character-v2-tab"+(
        characterV2Category===key?" active":""),name+
        " · "+tally.total+(tally.approved?"（通过 "+tally.approved+"）":""));
      btn.type="button";
      btn.addEventListener("click",()=>{characterV2Category=key;renderCharacterV2(profile,panel);});
      tabs.appendChild(btn);
    }
    panel.appendChild(tabs);
    const group=el("div","character-v2-body");
    panel.appendChild(group);
    const category=characterV2Category;
    const assets=characterV2Data.assets.filter(item=>item.category===category);
    const summary=el("div","character-v2-group-head");
    summary.appendChild(el("strong","",v2CategoryNames[category]));
    const create=el("button","prod-new prod-secondary","＋ 新增分类资产");
    create.type="button";
    create.addEventListener("click",()=>v2AssetEditor(profile,category,null,group));
    summary.appendChild(create);
    group.appendChild(summary);
    if(category==="profile" && profile.character_id==="CHAR_GPT" &&
        characterV2Data.assets.length===0){
      const seed=el("button","prod-new","建立吉皮提 V2 样板（5 条草稿）");
      seed.type="button";
      seed.addEventListener("click",async()=>{
        seed.disabled=true;
        let count=0;
        try{
          for(const [cat,sub,label,note,details] of v2JipiteDefaults){
            await characterPost("assets/create",{
              project_id:characterProjectId,character_id:profile.character_id,
              category:cat,subtype:sub,label,note,details,source_visual_id:null
            });count++;
          }
          await loadCharacterV2();
          $("characterMessage").textContent="已创建 "+count+
            " 条吉皮提 V2 文字草稿；图片和正式审核仍待制作。";
        }catch(err){
          await loadCharacterV2();
          $("characterMessage").textContent="已创建 "+count+" 条；"+err.message;
        }finally{seed.disabled=false;}
      });
      group.appendChild(seed);
    }
    if(!assets.length){
      group.appendChild(el("div","production-empty",
        "暂无本分类资产。新增文字约束或绑定已有角色候选图；不会自动获批。"));
    }
    for(const item of assets){
      const card=el("div","character-v2-asset");
      const cardHead=el("div","character-v2-asset-head");
      cardHead.appendChild(el("strong","",item.label+" · V"+item.revision));
      cardHead.appendChild(el("span","character-v2-status "+item.status,
        v2StatusName[item.status]||item.status));
      card.appendChild(cardHead);
      card.appendChild(el("p","",item.note||"未填备注"));
      const description=el("dl","character-v2-attributes");
      for(const [key,value] of Object.entries(item.details)){
        description.appendChild(el("dt","",v2FieldNames[key]||key));
        description.appendChild(el("dd","",value||"—"));
      }
      card.appendChild(description);
      if(item.source_visual_id){
        const thumbnail=el("img","character-v2-image");
        thumbnail.loading="lazy";
        thumbnail.alt=item.source_filename||"角色候选";
        thumbnail.src=visualURL(characterProjectId,item.source_episode_id,
                                item.source_visual_id);
        card.appendChild(thumbnail);
        card.appendChild(el("small","",item.source_episode_id+" · "+
          item.source_filename+" · 原图仅关联"));
      }
      if(item.reviews.length)card.appendChild(el("small","",
        "最近审核："+v2StatusName[item.status]+"；"+
        item.reviews[0].rationale));
      const actions=el("div","character-v2-actions");
      if(item.status==="draft"||item.status==="rejected"){
        const edit=el("button","prod-new prod-secondary","编辑草稿");
        edit.type="button";
        edit.addEventListener("click",()=>v2AssetEditor(profile,category,item,group));
        actions.appendChild(edit);
      }
      if(item.status==="draft"||item.status==="in_review"){
        for(const [decision,label] of (item.status==="draft"?
              [["submit","提交审核"]]:
              [["approve","审核通过"],["reject","驳回"]])){
          const btn=el("button","prod-new prod-secondary",label);
          btn.type="button";
          btn.addEventListener("click",async()=>{
            const reason=window.prompt("请填写不少于 8 个字的"+label+"理由");
            if(reason===null)return;
            if(reason.trim().length<8){
              $("characterMessage").textContent="审核理由至少 8 个字";return;
            }
            if(decision==="approve" &&
                !window.confirm("确认人工批准 "+item.label+
                  "？请先核对完整身份特征与官方 Logo 禁用规则。"))return;
            btn.disabled=true;
            try{
              await characterPost("assets/review",{project_id:characterProjectId,
                character_id:profile.character_id,item_id:item.item_id,
                expected_revision:item.revision,decision,rationale:reason.trim()});
              await loadCharacterV2();
            }catch(err){
              $("characterMessage").textContent="审核失败："+err.message;
              btn.disabled=false;
            }
          });
          actions.appendChild(btn);
        }
      }
      card.appendChild(actions);group.appendChild(card);
    }
  }

  function v2AssetEditor(profile,category,item,mount){
    // Asset edits live in a focused dialog, not underneath the asset grid.
    const dialog=$("characterAssetEditorDialog");
    const area=$("characterAssetEditorMount");
    if(dialog.open)dialog.close();
    area.replaceChildren();
    const form=el("form","character-v2-editor");
    const heading=el("div","character-v2-group-head");
    heading.appendChild(el("strong","",item?"编辑 V"+item.revision+" 草稿":"新增分类资产"));
    const cancel=el("button","prod-new prod-secondary","取消");
    cancel.type="button";
    cancel.addEventListener("click",()=>dialog.close());
    heading.appendChild(cancel);form.appendChild(heading);
    function field(title,control){
      const label=el("label","",title);
      label.appendChild(control);form.appendChild(label);
      return control;
    }
    const subtype=field("类型编号",el("input",""));
    subtype.required=true;subtype.maxLength=55;
    subtype.placeholder="front / expression_smile / daily_outfit";
    subtype.value=item?.subtype||"";
    const name=field("素材名称",el("input",""));
    name.required=true;name.maxLength=110;name.value=item?.label||"";
    const note=field("用途与连续性说明",el("textarea",""));
    note.maxLength=1800;note.rows=2;note.value=item?.note||"";
    const source=field("关联现有候选图（可不选）",el("select",""));
    let opt=el("option","","无图：仅录入结构资料");opt.value="";source.appendChild(opt);
    for(const image of profile.visuals){
      opt=el("option","",image.episode_id+" · "+image.filename);
      opt.value=image.visual_id;source.appendChild(opt);
    }
    source.value=item?.source_visual_id||"";
    const info=el("div","character-v2-fields");
    const inputs={};
    for(const key of characterV2Data.fields[category]){
      const wrap=el("label","",v2FieldNames[key]||key);
      const input=el("input","");input.maxLength=220;
      input.value=item?.details[key]||"";
      if(category==="turnaround"&&key==="direction"){
        const picker=el("select","");
        for(const dir of ["front","left","right","back","front_left_45",
                          "front_right_45","back_left_45","back_right_45"]){
          const option=el("option","",dir);option.value=dir;picker.appendChild(option);
        }
        picker.value=item?.details.direction||"front";
        inputs[key]=picker;wrap.appendChild(picker);
      }else if(category==="rules"&&key==="severity"){
        const picker=el("select","");
        for(const level of ["hard","soft"]){
          const option=el("option","",level==="hard"?"硬约束":"软约束");
          option.value=level;picker.appendChild(option);
        }
        picker.value=item?.details.severity||"hard";
        inputs[key]=picker;wrap.appendChild(picker);
      }else{
        inputs[key]=input;wrap.appendChild(input);
      }
      info.appendChild(wrap);
    }
    form.appendChild(info);
    const save=el("button","prod-new","保存为草稿");
    save.type="submit";form.appendChild(save);
    form.addEventListener("submit",async e=>{
      e.preventDefault();
      const details={};
      for(const [key,control] of Object.entries(inputs)){
        if(control.value.trim())details[key]=control.value.trim();
      }
      if(!Object.keys(details).length){
        $("characterMessage").textContent="请至少填写一个分类字段";return;
      }
      save.disabled=true;
      const payload={project_id:characterProjectId,
        character_id:profile.character_id,category,
        subtype:subtype.value.trim(),label:name.value.trim(),
        note:note.value.trim(),details,
        source_visual_id:source.value||null};
      if(item){
        payload.item_id=item.item_id;
        payload.expected_revision=item.revision;
      }
      try{
        await characterPost(item?"assets/revise":"assets/create",payload);
        dialog.close();
        await loadCharacterV2();
      }catch(err){
        $("characterMessage").textContent="保存 V2 分类资产失败："+err.message;
        save.disabled=false;
      }
    });
    area.appendChild(form);
    dialog.showModal();
  }

  function openCharacterEditor(profile=null){
    if(!microsoftOwner||!characterProjectId)return;
    characterEditingId=profile?.character_id||null;
    $("characterEditorTitle").textContent=profile?"编辑角色 · "+profile.display_name:
      "创建原创角色档案";
    $("characterId").value=profile?.character_id||"";
    $("characterId").disabled=!!profile;
    $("characterName").value=profile?.display_name||"";
    $("characterRole").value=profile?.role||"main";
    $("characterBrand").value=profile?.brand_basis||"";
    $("characterLanguage").value=profile?.design_language||"";
    $("characterNotes").value=profile?.character_notes||"";
    $("characterEditForm").hidden=false;
    $("characterEditorDialog").showModal();
  }
  $("characterProject").addEventListener("change",()=>{
    characterProjectId=$("characterProject").value;
    characterCurrentId="";characterData=null;characterV2Data=null;
    characterV2Category="profile";characterActiveVisualId="";
    if($("characterEditorDialog").open)$("characterEditorDialog").close();
    if($("characterAssetEditorDialog").open)$("characterAssetEditorDialog").close();
    loadCharacters().catch(err=>$("characterMessage").textContent=err.message);
  });
  $("characterSearch").addEventListener("input",()=>{if(characterData)renderCharacterList();});
  $("characterRoleFilter").addEventListener("change",()=>{if(characterData)renderCharacterList();});
  $("characterImageClose").addEventListener("click",()=>$("characterImageDialog").close());
  $("characterCreateBtn").addEventListener("click",()=>openCharacterEditor());
  $("characterEditorCancel").addEventListener("click",()=>{
    $("characterEditorDialog").close();
  });
  $("characterEditForm").addEventListener("submit",async event=>{
    event.preventDefault();
    const existing=(characterData?.characters||[]).find(c=>
      c.character_id===characterEditingId);
    const values={
      project_id:characterProjectId,
      character_id:existing?.character_id||$("characterId").value.trim(),
      display_name:$("characterName").value.trim(),
      role:$("characterRole").value,
      brand_basis:$("characterBrand").value.trim(),
      design_language:$("characterLanguage").value.trim(),
      character_notes:$("characterNotes").value.trim()
    };
    if(!/^[A-Za-z][A-Za-z0-9_-]{1,47}$/.test(values.character_id)){
      $("characterMessage").textContent="角色编号无效";return;
    }
    const submit=$("characterSaveBtn");submit.disabled=true;
    try{
      if(existing)await characterPost("update",{
        ...values,expected_revision:existing.revision});
      else await characterPost("create",values);
      characterCurrentId=values.character_id;
      $("characterEditorDialog").close();
      await loadCharacters();
    }catch(err){$("characterMessage").textContent="保存失败："+err.message;}
    finally{submit.disabled=false;}
  });
  $("characterSeedBtn").addEventListener("click",async()=>{
    if(characterProjectId!=="WaitingOffice"||!microsoftOwner)return;
    const button=$("characterSeedBtn");button.disabled=true;
    let count=0;
    try{
      const existing=new Set((characterData?.characters||[]).map(c=>c.character_id));
      for(const [character_id,display_name,role,brand_basis,design_language,
                  character_notes] of characterPresets){
        if(existing.has(character_id))continue; // never overwrite existing profiles
        await characterPost("create",{project_id:characterProjectId,character_id,
          display_name,role,brand_basis,design_language,character_notes});
        count++;
      }
      await loadCharacters();
      $("characterMessage").textContent="已新建 "+count+
        " 位角色档案；已有档案未改动，候选图不自动批准。";
    }catch(err){
      await loadCharacters();
      $("characterMessage").textContent="已建立 "+count+" 位；"+err.message;
    }finally{button.disabled=false;}
  });

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
      navigateWorkspace(new URLSearchParams(window.location.search).get("page")||"home",false);
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
