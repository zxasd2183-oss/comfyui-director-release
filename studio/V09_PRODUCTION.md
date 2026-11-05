# Director Studio V0.9（第一交付阶段）：全剧制作工程底座

本阶段已经实现可升级的软件代码和离线测试，但未自动部署到 VPS。它是 V0.9 的 **production foundation**，不是完整 V0.9 的 Microsoft Web SSO 或 GPU 自动派单。

## 已实现

- 项目、剧集、镜头三层关系，允许数字形式的镜头编号（如 01–31）。
- 视听资产登记：人物形象、人物声线、服装、场景、道具、对白、声音环境、音效、音乐、生成视频/音频版本、剪辑时间线版本。
- 所有资产通过 SHA-256 指纹和递增版本号引用，不在 SQLite 储存大容量原始媒体。
- 声线、对白、音乐、音效、音频候选必须提供权利/同意记录引用（字段存在不代表系统独立核实授权真实性）。
- 镜头与资产精确绑定，禁止跨项目引用。
- 连续性异常登记：作用于具体项目、剧集、镜头和属性（如 voice.timbre、costume.identity）。
- 艺术例外草案：精确到毫秒时间窗、异常属性、证据哈希、原因和目标镜头实际引用的资产版本。
- 例外批准/撤销：**只能通过 VPS 本地受控 CLI 且需要显式证据确认**；禁止过期资产版本获批。新版本资产会使关联的已批准例外变为 stale。
- 逐事件追加哈希链审计、审计验证；它能检测普通记录篡改，但**不等同于防 root 修改的独立外部签名存证**。
- V0.7 plan.json 整集导入，只保留镜头 ID、顺序、毫秒时长及源文件哈希，绝不在制作数据库写入完整 ComfyUI 工作流或视频 prompt。
- 工作台增加「全剧制作工程」面板，SSE 只读提供项目、剧集、视听资产、异常/例外统计和审计校验状态；**网页没有新增修改或审批接口**。

## 升级（只在 VPS，本轮无 GPU 开机）

已安装 V0.8 的 VPS 私有 SSH 终端：

    cd ~/comfyui-director-release
    git pull --ff-only
    sudo bash studio/upgrade-v09.sh

升级程序运行离线测试，对已安装文件建立 root-only 备份，并使用 SQLite 在线备份 API 归档旧 studio.sqlite，再复制并启动 V0.9 模块。新 production.sqlite 位于 /var/lib/director-studio，不覆盖旧监管数据库。失败时尝试恢复旧代码与服务，保留备份供手动排查。

**不会更改 Nginx**：如果你已部署 /studio/，沿用当前原有的 HTTPS Basic Auth；如果你还没有部署，继续通过 SSH 端口转发访问，不要为此取消登录保护。

升级成功后（VPS）：

    curl -fsS http://127.0.0.1:8900/api/v1/production
    curl -fsS http://127.0.0.1:8900/api/v1/snapshot
    sudo ss -ltn | grep ':8900'

新的数据状态应显示 version=0.9.0、mode=read_only_production_summary、audit_chain_verified=true。空数据库时项目与剧集数量为零，这是正常的。

## 创建正式项目与 EP01 镜头计划（示例）

这里的项目名沿用你的《待回答事务所》，但**命令只有在你确实有已审核的 V0.7 plan.json 时才执行**。CLI 本身不能臆造分镜或人物/声音素材。

    sudo -u directorstudio /usr/bin/python3 /opt/director-studio/production_manage.py \
      create-project --id WaitingOffice --title '待回答事务所'

    sudo -u directorstudio /usr/bin/python3 /opt/director-studio/production_manage.py \
      create-episode --project WaitingOffice --id EP01 \
      --title '谁才是真正的AI？' --ordinal 1

将真实 V0.7 计划通过 SSH 安全保存到 /var/lib/director-studio/ep01-plan.json，设置 owner=directorstudio、mode 0600 后：

    sudo -u directorstudio /usr/bin/python3 /opt/director-studio/production_manage.py \
      import-plan --project WaitingOffice --episode EP01 \
      --plan /var/lib/director-studio/ep01-plan.json

该命令可以一次导入全部镜头，无需逐条录入。重复提交相同文件安全无改动；源文件变更则拒绝覆盖，必须走新的已审核版本流程。

查询：

    sudo -u directorstudio /usr/bin/python3 /opt/director-studio/production_manage.py dashboard
    sudo -u directorstudio /usr/bin/python3 /opt/director-studio/production_manage.py verify-audit

## 注册角色声音和艺术例外（约束说明）

1. 为角色声音标准资产生成真实 SHA-256，并在获得有效授权后登记 character_voice，提供 rights_ref 指向你保管的同意/许可证明。
2. 将资产绑定到实际使用的镜头，purpose 可写 voice_reference。
3. 登记 voice.timbre / voice.emotion / audio.effect 等属性的检测异常，并保存证据文件的 SHA-256。
4. 创建针对异常的 draft 例外，必须给出精确起止毫秒、艺术意图以及镜头引用的资产版本。
5. 在 VPS 私有终端人工核对原音频和证据后，使用 decide-exception --decision approve --expected-revision 1 --i-reviewed-evidence 批准。撤销要提交新的操作，不能覆盖历史。
6. 以后更新声音参考资产时，历史相关的批准自动标记 stale 并禁止重新使用。

**重要边界**：目前这个引擎只管理元数据与人为裁决，并未自动提取声纹、评价音色或音画同步。没有真实音频证据时，不要声称声音已经验证通过。

## 不在本轮范围内

- Microsoft 个人账号 Web OIDC、角色权限分级与网页上的真实审批者身份：尚需安全设计、Microsoft App 注册重定向 URI和可验证的会话。
- 真实的视频/音频缩略图及播放、时间线编辑和媒体存储：尚待受控资产服务。
- 自动视觉/声音检测器：当前异常需要人工或其他检测流程创建，不能把数量为 0 误当成没有问题。
- GPU 任务提交、中断、取消或电源操作：均未接入；吉皮提原有生物识别审批保持独立。

下一阶段目标是 Microsoft 登录和受控项目编辑 API，之后再接入 GPU 本地代理、媒体预览、真实视听质检与导演裁决 UI。
