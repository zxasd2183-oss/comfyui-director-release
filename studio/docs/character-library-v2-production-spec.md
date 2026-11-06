# 《待回答事务所》Director Studio 角色库 V2：细粒度生产规格

状态：设计规格（Proposed）；不代表已部署。适用项目 WaitingOffice；可复用于其他项目。
版本：V2.0-Draft；基于已上线 V1 的角色档案、图片引用和人工母版审核。
核心目标：同一角色在角色卡、分镜、关键帧和视频片段中拥有可追溯、可复用、可冻结的身份特征与生产资产。

## 0. 不可突破的原则

1. 角色设定与美术制作以原创角色为主体。可以抽象提取对应模型官方品牌的色彩、节奏、组织和气质，但**正式立绘、资产图、角色卡、道具、分镜和视频均不得直接放置、描摹、重排、拼接或隐藏任何官方 Logo，也不能用近似形状冒充商标**。品牌依据仅作描述性文字；正式发布还须检查授权、商标和署名要求。
2. 同一角色只保留一个跨剧集的稳定 character_id；一套通过人工审核的角色资产包（Character Pack）可以被多个剧集和镜头引用。
3. **候选 ≠ 已批准 ≠ 镜头已使用**。图片入库/自动匹配不代表完成审核，ChatGPT 只可起草、关联、提出修改建议，不能自动批准正式母版。
4. 生产中不可暗中覆盖素材：批准版为不可变快照；修订产生新版本，旧版保留审计和引用。
5. 分镜与视频分别保存生成输入、参考资产、约束、产出及人工审核结果，能回答“这个镜头为什么长这样”。
6. 统一使用 **角色自身的左/右** 作为佩饰位置定义；画面左/右另存 screen_side，镜像翻转须重新核验。
7. 严格项目隔离；角色资产与关联只在相同 project_id 下复用。没有任何角色库操作应调用 GPU、电源、外部代理或绕过手机审批。
8. 保留并兼容 V1 的 character_profiles、character_visual_links、character_master_events 和 visual_media，增量升级，不搬移现有 EP01 原图。

## 1. Studio 信息架构（12 类资产）

| 编号 | 一级栏目 | 核心字段与素材（* 为必填） | 典型消费方 |
|---|---|---|---|
| 01 | **角色主档** | character_id*、display_name*、role*、story_function*、personality*、canonical_identity*、brand_basis_text、design_language、aliases、first_episode、locked_traits*、forbidden_rules* | 所有制作环节 |
| 02 | **批准母版** | asset_id*、category=master*、view_or_framing*、outfit_id*、hair_variant_id*、version*、approval_state*、source_sha256*；全身/半身/头像/站姿/坐姿 | 全制作链 |
| 03 | **八方向视图** | direction*（front、left、right、back、front_left_45、front_right_45、back_left_45、back_right_45）、body_proportion_id*、outfit_id*、accessory_map*、camera_elevation | 分镜、空间连续性 |
| 04 | **面部与口型** | expression_code*、intensity*、head_angle*、eye_shape、brow_shape、mouth_shape、viseme_code、eyeline、reference_view*；统一身份的多表情、视线与说话口型 | 近景分镜、对白视频 |
| 05 | **头发/五官结构** | hair_variant_id*、bang_partition*、length_boundary*、hair_flow_left/right/back、hair_color*、eye_color*、hair_ornament_position、face_landmarks | 头像、转头、运动 |
| 06 | **服装/配饰** | outfit_id*、piece_id*、layer_order*、material、color_ref*、silhouette_lock*、seam_map、fastener、front/back_detail、far_shot_simplification、closeup_keep | 立绘、分镜、动态画面 |
| 07 | **色板与材质** | palette_id*、swatch_key*、hex_srgb*、scope*（皮肤/发/眼/上衣/下装/配饰）、material、shadow_rule、highlight_rule、lighting_override_policy | 风格统一、视频调色 |
| 08 | **道具** | prop_id*、size_relative_to_body*、grip_hand*、attach_slot、state_model、front/side/back_views、usage_pose、continuity_notes；道具单独资产与姿态 | 道具镜头、人物动作 |
| 09 | **动作与运动** | action_id*、key_pose_start/mid/end*、motion_direction、foot_contact、hand_pose、speed_range、cloth_hair_reaction、loop_safe、camera_relative_orientation | 动作分镜、视频 |
| 10 | **关系/同框** | pair_or_group_id*、member_ids*、height_order*、preferred_spacing、eye_line、blocking、allowed_overlap、visual_priority、interaction_pose_refs | 多人镜头 |
| 11 | **镜头连续性** | project_id*、episode_id*、shot_id*、character_id*、character_pack_version*、outfit_id*、hair_variant_id*、pose_id、expression_id、direction、screen_side、prop_states、state_before/after、previous/next_shot、reference_asset_ids* | 31 镜头分镜与视频 |
| 12 | **禁止项与质量记录** | rule_id*、severity*、scope*、validation_type、rule_text*、evidence、review_status、reviewer、review_time、waiver_reason；五官、衣服、镜像、Logo 等硬约束 | 自动预检和人工终审 |

主档包括独立的“故事设定”与“视觉锁定”字段；不要把所有信息混成一个超长备注。
每个栏目提供：候选、待审、已批准、已废弃历史四种状态，并按视角、表情、服装、版本和镜头可筛选。

## 2. 建议统一素材元数据（所有图片/参考帧共享）

每张素材都必须挂载独立 asset_id，不能仅靠文件名区分：

| 字段 | 要求 |
|---|---|
| asset_id, project_id, character_id, category, subtype | 必填，可机器查询 |
| pack_version, asset_revision, status | 必填；status: draft / in_review / approved / superseded / rejected |
| source_visual_id | 可选：指向 V1 不可变 episode 图，引用而非复制 |
| storage_ref, sha256, mime, width, height | 新上传角色级素材必填；源文件与生成缩略图分别追踪 |
| facing, camera_angle, framing, mirror_policy | 视图/镜头素材必填；镜像策略必须显式 |
| outfit_id, hair_variant_id, palette_id | 人物主体素材必填 |
| expression_id, action_id, prop_ids, hand_occupancy | 有关时必填 |
| source_asset_ids, generator, workflow_revision, seed, prompts, negative_constraints | 生成资产必填；记录来源和可复现信息，不存访问令牌 |
| reviewer, approved_at, approval_reason, review_event_id | 人工批准时必填；追加记录而非覆盖 |
| notes, tag_set, applicable_episodes | 可选，服务检索与复用 |

**原图只存一次；项目级资产不应强制归属 EP01。** 仍可引用原 V1 visual_id；未来新增素材落在独立的项目级角色资产存储。重复字节 SHA-256 去重，保持来源与授权记录。

## 3. 角色资产包（Character Pack）与状态机

Character Pack = 某个 character_id 在指定 pack_version 下冻结的一套**结构化资产引用及规则快照**；它不是一张“大拼贴图”。

- draft（草稿）：可编辑资料、上传和关联候选；不能用于“正式分镜”默认参考包。
- review（待审核）：冻结待审内容，显示缺项及硬规则冲突。
- approved（已批准）：由 Microsoft Studio 所有者逐类审核后正式批准；不可原地替换，锁定引用哈希。
- superseded（被新版替代）：仍可用于旧镜头还原，但新镜头默认选择新的批准版。
- rejected（驳回）：保留审计与退回理由，不进入生产导出。

类别审批与整包审批分开：一张正面母版批准，不意味着侧面、表情或视频一致性已经通过。
**允许按生产阶段逐步就绪**，避免要求 12 类全部完成才能开始绘制分镜：

| 就绪级别 | 最低证据 | 允许用途 |
|---|---|---|
| identity_locked | 标准全身正面+头像+角色身份硬约束+禁用项人工批准 | 生成人物候选草图 |
| storyboard_ready | 前/侧/后 + 45°常用机位、至少 8 个基础表情、1 套主服装细节、基础色板、主要道具、比例规则获批 | 正式分镜图与关键帧 |
| video_ready | 至少 8 方位、口型/面部运动规则、动作关键姿态、头发和布料动态规则、道具持握、连续性检查通过 | 连续视频镜头 |

不足条件给出缺项清单，并禁止 UI 把“部分通过”显示成“全包已批准”。

## 4. 分镜与视频引用合约

镜头生产时先读取该镜头**锁定的角色包版本与素材 ID**，由系统生成一份 Camera/Character Continuity Bundle：

- **Identity Lock**：角色编号、稳定头身比例、脸型、发色、瞳色、发型长度、禁止变化项。
- **Appearance Lock**：具体 outfit_id、layer_order、palette_id、配饰位置和不应消失的细节。
- **Pose/Camera Lock**：景别、机位、人物朝向、动作关键姿态、视线和银幕站位；区分人物左/右与画面左/右。
- **Emotion/Dialogue Lock**：表情/强度、嘴型和对白阶段（视频）。
- **Prop Continuity**：上一镜头结尾、当前镜头开始/结束的持握手和道具状态；镜头之间自动比较冲突。
- **Style Lock**：EP01 指定画风、光线及可允许的色偏；不允许光源导致“换发色/换眼色”。
- **Asset Provenance**：批准母版 asset_ids、角色包版本、模型/workflow 版本和提示词快照、输出图/视频 SHA-256。

输出分两种：
1. 分镜包：人设母版 + 角度视图 + 表情 + 服装细节 + 镜头姿态 + 显式负面约束 + 预检报告。
2. 视频包：分镜包加前后关键帧、表情过渡、口型规则、动作片段、道具状态时间线、连续性验收报告。

默认只从 approved 快照构建**正式**生产包；候选试验可手动使用 draft，但必须带水印/标识，不覆盖正式镜头。新角色包批准后，已开工镜头不自动切换版本，需明确的升级和差异复核。

## 5. 数据库模型与 API 迭代

### V1 保留（无需破坏性迁移）
- character_profiles：当前 6 位人物基本档案（吉皮提现为 Revision 2）。
- character_visual_links：原 EP01 角色候选图的跨角色参考关系。
- character_master_events：既有单张母版批准事件，保留历史，映射 V2 legacy_main_master 状态，不推断其他类别获批。
- visual_media：现有 7 张 EP01 图全部原位保留。

### V2 新表（建议增量创建）
| 表 | 责任与约束 |
|---|---|
| character_packs | project_id + character_id + version；状态、规范 JSON 快照、冻结哈希、创建者、审核时间 |
| character_asset_entries | 每张图/视频/局部细节的分类、文件哈希、视角、配色、服装、表情、素材追溯；project_id 隔离 |
| character_asset_revisions | 不可变修订历史，每次变更生成新 revision |
| character_category_review_events | 逐类批准/拒绝事件，人工身份、理由和哈希；只追加 |
| character_pack_review_events | 整包批准/替代事件，人工身份、理由和哈希；只追加 |
| character_canonical_slots | 当前有效 canonical 资产槽位，例如 front_full、back_full、neutral_face；来源于最新批准事件 |
| character_components | 发型、服装分件、色板、配饰、禁止项等结构化子对象 |
| character_motion_presets | 关键姿势、动作转移、头发/布料约束 |
| character_group_rules | 身高次序、多人站位、交互模板，引用多名同项目角色 |
| shot_character_bindings | project_id+episode_id+shot_id+character_id；锁定 pack_version 和状态快照 |
| character_continuity_events | 镜头前后姿态、物品、表情变化及相邻镜头冲突 |
| character_generation_manifests | 每次图像/视频生产的原始输入资产、提示词、workflow、版本、种子、输出及 QC 结果 |

建议分模块 POST/GET API；Web UI 保持当前 owner + CSRF + Origin 验证；ChatGPT 脑连接可先有**只读查询、建立候选、关联候选、构建镜头包**，**不开放任何正式母版/整包自动批准动作**。
所有写入使用项目校验、字段白名单、修订冲突检测、审计链和事务；拒绝跨项目引用、无来源覆盖、绕过状态流转和直接删除已使用资产。

## 6. 《待回答事务所》实际角色样板：吉皮提 CHAR_GPT

**当前有效信息**：吉皮提是温和、理性、可靠的协调者；EP01 接纳零、调查连接警报。当前 V1 Revision 2 已明确的视觉锁定特征：
- 发型：深栗色**齐颈短发**、自然侧分；不允许变成银白长发。
- 瞳色：**琥珀棕**；不允许变成青绿色眼睛。
- 服装：**象牙白外套**、青绿色内衬与结构点缀、深灰色下装、舒适短靴；衣襟层次与交错缝线只是原创连接意象，不得形成商标图形。
- 气质：年轻、克制、友善，偏理性与协调；不擅自变成浮夸的“元气少女”。
- 8 种基础表情：自然微笑、认真、思考、惊讶、安慰、疑惑、苦笑、坚定。
- 官方品牌的字形、图案和 Logo：**禁止出现在任何角色成品图中**。
- 道具可候选：记录本、工作终端；以审核后的外观和大小为准。
- **尚待测量**：精准色号、身高、标准头身比、五官比例、服装裁片尺寸与每个配件的位置；不可把失败生成图中出现的“166cm、银发、蓝眼”当成已锁定设定。

建议先填如下独立资产槽位（全部候选起步，绝不自动批准）：
| 编号 | 类别 | 素材与交付 |
|---|---|---|
| GPT-M01 | 母版 | 正面无背景全身基准、同人物头像、半身 |
| GPT-T01~08 | 视图 | 八方向，同发型同外套同鞋靴 |
| GPT-E01~08 | 表情 | 8 种基础表情；统一面部结构，附嘴型与视线 |
| GPT-H01 | 头发 | 刘海分区、左/右/后发流、发尾长度 |
| GPT-C01 | 服装 | 正反裁片、衣领/袖口/腰部/鞋靴细节与穿脱层序 |
| GPT-P01 | 配色 | 明确的 sRGB 色板与不同照明状态示例 |
| GPT-R01 | 道具 | 记录本/终端两种候选、与手部相对尺寸 |
| GPT-A01 | 动作 | 中立站姿、走路、坐姿、回头、示意、安慰手势 |
| GPT-X01 | 禁止项 | 长银发、青绿瞳、官方 Logo、商标仿制、配件镜像 |

图像制作流程必须改为 **单张正面身份锁定 → 审核 → 由该参考生成其他方向 → 审核 → 表情/动作/衣物局部素材 → 程序化角色卡布局**；不得再次一键重绘整张集合图并冒充通过一致性检查。

## 7. 页面交互：避免“很详细但使用费力”

角色库默认显示六位档案（5 主角、1 扩展），每张角色概览显示：
- 角色头像、姓名、状态、当前批准包、就绪率、最近修改、剧集引用数。
- 进入角色后有 12 个分类 Tab；各 Tab 的“规范信息、资产网格、审核差异、历史版本”四栏固定一致。
- 页面顶部固定“角色身份硬约束”和“当前用于 EP01 的包版本”，避免跨 Tab 丢失语境。
- 提供“生成本镜头参考包”入口：从镜头选择角色、角度/姿势/情绪/服装，自动带出已批准素材，减少手工查图。
- 新角色可克隆**空白结构模板**，但不克隆另一人的身份/脸/配饰，不会自动设置通过。
- 支持一个角色的各类素材完成度和阻塞项列表；无需翻遍数十张图查缺什么。

## 8. 开发顺序与验收（先 V2 结构，再制作资产）

**P0 · 不破坏旧数据**：项目级新表、唯一 ID、来源、状态、目录与审核事件；V1 六角色和 EP01 7 张原素材原封不动；读回哈希一致。

**P1 · 吉皮提样板**：完整 12 分类结构、表单字段与审核规则、原有候选图跨分类只做 reference；禁止直接使用官方 Logo。真实素材尚未制作/获批时，页面如实标记缺项。

**P2 · 分镜集成**：每镜头绑定角色包版本、姿态/服装/表情/道具状态；多镜头差异报告；支持为 EP01 31 镜头逐一构建参考包，不改原计划。

**P3 · 视频集成**：视频输入/输出 manifest、关键帧、动作与口型约束、道具连续性、人工 QC；不把“参考图绑定成功”当作模型的一致性保证。

**回归验收最低要求**：
- 任意一次版本升级，不得改变 EP01 的 31 镜头、160 秒、Revision 2 和既有 7 张原图。
- 没有 owner 审核，任一候选均不得自动进入正式母版或正式镜头参考包。
- 已绑定 V1 的镜头，在 V2 新版本批准后依旧可重放相同资产版本。
- 阻止跨项目读写、非法引用、镜像导致零右手红绳变左手以及官方 Logo 违例。
- 所有修改有操作记录，保留 SHA-256、版本号和人工审核理由。
- 全流程不启动 GPU；视频生成必须走后续单独授权的制作流程。
