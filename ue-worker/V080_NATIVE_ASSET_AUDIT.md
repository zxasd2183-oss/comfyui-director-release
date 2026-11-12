# UE 5.8 · EP01 正式资产核查 V0.8.0

目标：沿着已确定的 **Director Studio → 私有 VPS → Windows UE 5.8** 主线推进《待回答事务所》，不再接 H3/ComfyUI，也不复做 V03/V04 灰模。

## 新增真实功能

Director Hub \`enqueue_ue_asset_audit("WaitingOffice", "EP01")\` 提交
**只读的 Unreal Editor 资产登记核查任务**。Worker 通过已存在的私有 SSH
反向隧道接收一个从 Studio 31 镜头计划派生的固定 job，不接受调用方传入
脚本、UE 资产路径、命令、URL、文件名或渲染选项。

在已有的 UE 5.8 项目中，Unreal Python 使用 \`EditorAssetLibrary\`
检查目标资产是否真实存在、能否载入，以及 Unreal 原生资产类型：

| 组 | 固定 Unreal Content 路径 | 类型校验 |
|---|---|---|
| 五人角色 | \`/Game/Director/Approved/Characters/CHAR_GPT\`, \`CHAR_GEM\`, \`CHAR_DS\`, \`CHAR_CLA\`, \`CHAR_ZERO\` | \`Blueprint\` 或 \`SkeletalMesh\` |
| 两处场景 | \`/Game/Director/Approved/Scenes/SCN_HALL\`, \`SCN_ENTRANCE\` | \`World\` |
| 31 镜头 | \`/Game/Director/Approved/EP01/Shots/SH01\` … \`SH31\` | \`LevelSequence\` |

这 **38 个位置**是正式制作资产目录，故意与旧 V03 灰模路径不同。
不会把既有 V03 代理方块、V04 四帧 PNG、文字场景档案视为正式资产。

成功返回 \`state=succeeded\` 的 job 只说明**资产清单扫描成功**，不代表
38 个资产都存在，更不代表角色母版通过审核。实际结果位于
\`get_ue_episode_job_status(job_id).result\`：

- \`asset_audit.{characters,scenes,shots}\`: 每项 \`id\`、\`exists\`、\`type_valid\`
- \`all_assets_present_and_class_valid\`: 所有位置都找到正确类型
- \`studio_approval_verified=false\`：此工具不能替导演批准母版
- \`animation_binding_verified=false\`：此工具不能证明 Sequencer 中有有效表演、口型或灯光
- \`render_ready=false\`、\`gpu_render_submitted=false\`：不能拿它冒充渲染/成片

未发现任何正式角色/场景/镜头时，**返回缺失清单也是正确进度**：
真实揭示应该导入哪组经批准的资产，而不是浪费 GPU 再生成灰模。

## 已有制作基线

- 正式 EP01 规划：31 镜头、160 秒、24fps、3,840 帧，禁止重排或改时长。
- UE Worker V0.7.3 已实机完成 V02 时间线、V03 31 摄影机、V04/V071 四帧技术预演；这些都不是正式成片。
- Studio 两处场景 \`SCN-HALL\`、\`SCN-ENTRANCE\` 已创建为 **draft**，没有批准的场景母版；五位主角也尚未审批为唯一母版。
- 31段正式 MP4 与混音 WAV 均缺失。不得跳过这个事实。

## 部署与调用

这次变更只修改固定签名包内的文件：Worker 的
\`agent.py\`、\`ue_jobs.py\`、\`unreal_build_stage.py\`；
Hub 的 \`hub_app.py\`、\`ue_worker_rpc.py\`。
GitHub 现有自动签名发布只从主分支已通过的 UE Worker CI 签署九文件/两文件包。
签名升级器只允许受信任版本自动更新；此文档和 CI 通过 **不等于实例已升级**。

升级回执实际显示 Worker/Hub 均为 V0.8.0 后：

1. \`get_ue_worker_status()\`、\`get_ue_worker_capabilities()\` 验证新版本和 \`audit_ep01_assets\`。
2. \`enqueue_ue_asset_audit(project_id="WaitingOffice", episode_id="EP01")\` 提交一次核查（会启动 UE 编辑器，占用计费 Windows GPU，但不渲染、不改 UE 项目）。
3. 用返回的 \`job_id\` 查询状态及固定 38 项清单。
4. 从 Studio 审核五人造型与两处场景后，由独立受控导入流程将 **真正批准的** 模型/场景/镜头资产放入上述目录；必须避免覆盖已批准内容。
5. 后续版本才允许在角色、场景、Sequencer 表演、声音与镜头审批通过后加入正式 MP4 导出动作。

禁止把任何代码审核通过、signed feed 升级成功或者灰模 PNG 当作可播放的整集成品。
