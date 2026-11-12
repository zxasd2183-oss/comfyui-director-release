# UE 5.8 · EP01 原创场景候选建造 V0.9.0

主线：Director Studio → VPS Hub → Windows UE 5.8 Worker。原 H3/ComfyUI 已退役。

## 真正创建的候选场景

新的 Hub 工具 enqueue_ue_scene_candidates("WaitingOffice","EP01") 调用 Windows 的 build_ep01_scene_candidates 固定任务。Worker 先验证 Studio 已存在场景档案 SCN-HALL、SCN-ENTRANCE，以及冻结31镜、160秒、24fps、3840帧的剧集计划。

- SCN_HALL：暖色办公室大厅，奶白薄荷色墙面、原创木质长桌、桌椅、沙发、茶几、书架、多色书、盆栽、杯子、书本与纸张、无字控制终端、玻璃门与窗户、真实 UE 灯光和构图相机。
- SCN_HALL_ALERT：布局、门窗及道具几何完全相同的大厅警报版本，额外开启暖红色警报点光源。
- SCN_ENTRANCE：与大厅同一门轴坐标的玻璃门入口、地垫、长椅、衣架、无商标低多边形城市轮廓与入门/反打参考相机。

每次 job 独立生成不可覆盖的 UE 资产目录：

    /Game/Director/Candidates/EP01/SceneBuilds/J<32hex-job-id>/
        Materials/M_Milk ... M_Slate    (10个 UE 原生 Material)
        Maps/SCN_HALL
        Maps/SCN_HALL_ALERT
        Maps/SCN_ENTRANCE

所有 World/Material 是真实 UE 可编辑资产，不是生成图或标为完成的灰模代理。使用引擎自带形体和新创建的高粗糙度彩色材质，不下载外部资源、品牌 Logo 或其他未知代码。

## 权限、保护与真实状态

- 本版只写新 Candidates 下的独立 job 目录，绝不覆盖 V02、V03、V04 已有成果或 Approved 正式母版；如果已批准的场景存在则拒绝新建候选。
- 失败不掩盖中途创建的草稿；换 job ID 另建新版本而不是覆盖失败产物。
- 返回三个真实 World 路径、道具/灯光/相机数量与材质数，严格校验。studio_scene_approval_verified=false、character_models_bound=false、render_ready=false、gpu_render_submitted=false。
- 本阶段只做场景候选，正式人物模型、Rig、动作、口型、正式 Sequencer 和 MRQ MP4 仍未完成。可编辑场景不等于已审核母版，也不等于可播放成片。
- 脚本无任意 shell、路径、网址、用户输入代码的执行能力。所有控制仍经私有 SSH 和已签名受限 Worker。
- Job 会实际启动按小时计费的 UE Editor，在 Windows RTX4090 上运行；发布/CI 不等于已经执行场景建造。

## 发布

更新 Worker 固定签名九文件包中的 agent.py、ue_jobs.py、unreal_build_stage.py 和 Hub 固定签名两文件包中的 hub_app.py、ue_worker_rpc.py。两端版本升至 V0.9.0。

正式执行需 Worker/Hub 均实测升级到 V0.9.0，Worker 无活跃任务。提交一次 enqueue_ue_scene_candidates，再用 get_ue_episode_job_status(job_id) 查验是否成功。

之后在 UE/Studio 审核候选场景，再走严格的正式母版版本化流程。场景和角色审核绝不由这项构建自动批准。
