# UE 5.8 · EP01 五位主角的独立 Blueprint 造型候选 V1.0.0

制作路线：Director Studio → VPS Director Hub → Windows Unreal Engine 5.8 UE Worker（无 H3）。

## 为什么必须是候选，不是直接宣布成片角色

Studio 有 5 位主角的详细形象约束（吉皮提、杰米奈、迪普西克、克劳德、零），但五位角色 **均未批准唯一母版**，设计卡是视觉参考，并不是 UE 骨骼模型。因此本版不会冒充 MetaHuman、自动导入网络人脸、用灰模宣称已制作动画或直接修改 Approved 目录。

## 新增可实际执行的 UE 工作

- Hub 工具：enqueue_ue_cast_blueprints(project_id="WaitingOffice", episode_id="EP01")
- Worker Job：build_ep01_cast_blueprints
- 仅从 Studio 读取冻结的 31 镜头、24fps、160 秒，以及严格的 5 个 main character ID。调用者不能提供可执行代码、外部文件、路径、Logo 或其他输入。
- Unreal 原生创建五个**独立 Blueprint Actor**。每位演员有真实可单独选择的 StaticMeshComponents：脸、眼睛、耳朵、手、衣服、外套、鞋、发束、附件等，基于引擎基础网格构成原创风格化造型。
- 角色外观硬约束：吉皮提深栗齐颈侧分短发、琥珀眼、象牙白/青绿色外套；杰米奈紫蓝短层次发、粉紫细节；迪普西克深蓝长编发、冰蓝眼和蓝白服装；克劳德陶土橘盘发、米白焦糖系；零黑色低马尾、朴素米色外套、旧帆布包以及 **右手红绳（角色局部Y负方向）**。绝不描摹任何官方 Logo。
- 输出 18 份 UE 原生原创材质，独立预览 World，五位角色各自有可用 Actor root transform（后续可做 Sequencer 角色走位）。

所有资产保存在 job-ID 隔离目录，绝不覆盖既有 V03/09 场景、候选人物或 Approved 正式母版：

    /Game/Director/Candidates/EP01/CastBuilds/J<job-id>/Blueprints/BP_CHAR_GPT
    /Game/Director/Candidates/EP01/CastBuilds/J<job-id>/Blueprints/BP_CHAR_GEM
    /Game/Director/Candidates/EP01/CastBuilds/J<job-id>/Blueprints/BP_CHAR_DS
    /Game/Director/Candidates/EP01/CastBuilds/J<job-id>/Blueprints/BP_CHAR_CLA
    /Game/Director/Candidates/EP01/CastBuilds/J<job-id>/Blueprints/BP_CHAR_ZERO
    /Game/Director/Candidates/EP01/CastBuilds/J<job-id>/Maps/EP01_Five_Cast_Review

## 验收与后续阻塞

任务成功后，真实回执必须列明上述5个Blueprint路径、每位角色组件数、18种材质、1个预览地图、右手红绳与吉皮提身份锁定信息。所有结果明确设置：

- studio_character_approval_verified=false
- skeletal_rig_bound=false
- metahuman_bound=false
- facial_performance_ready=false
- render_ready=false
- gpu_render_submitted=false

这些 Blueprint **不是最终高精度雕刻或绑定骨骼的模型**，不能自动完成口型/身体动作。必须由导演审核造型，再导入/建设正式可驱动骨骼角色，并将其绑定到已有的 EP01 Sequencer。

这是生产资产向前迈出的一步，不会虚报最终成片已制作。自动签名发布和版本更新必须在完整 CI 后执行，实机成功与否则以 Windows UE Editor 的返回和资产读取为准。
