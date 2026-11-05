# Director Studio V0.9.2 — 项目、剧集及视听分镜工作台

**状态：代码与 CI 已完成；须执行 VPS 升级并验收后才算在线。** 本阶段支持已验证的 Microsoft 所有者在网页中真实创建短剧项目与剧集、查看已登记分镜及声音/画面资产版本。

## 主要能力

- 创建短剧项目，填写固定项目编号和显示名称。
- 为已存在的项目创建剧集，填写剧集 ID、名称和剧集顺序。
- 创建项目后可直接进入添加剧集的表单。
- 展开某一剧集，查看其已登记镜头的序号、时长、制作阶段，关联的角色、声音、道具和场景资产版本以及连续性风险数量。
- 未导入镜头/资产时，明确显示空状态；不会伪造视频已经制作完成。
- 成功写入均保存到 production.sqlite 并追加审计链。操作员 ID 基于已验证 Microsoft 所有者身份的不可逆哈希标识生成，网页不能指定操作员。
- 浏览器写操作需验证 Microsoft owner 会话、Origin 与会话 CSRF。旧 SSH 本地监管入口不能调用这个新写接口。重复 ID 或剧集序号会拒绝覆盖。审计链遭修改则拒绝继续写入。
- 网页没有 GPU 开关机、ComfyUI 提交/中断、艺术例外批准、声音克隆、媒体文件上传等能力。吉皮提现有指纹审批不变。

## VPS 安装

要求 V0.9.1 的 Microsoft 个人账号网页登录已正常部署。VPS 私人 SSH 终端执行：

    cd ~/comfyui-director-release
    git pull --ff-only
    sudo bash studio/install-microsoft-web.sh

该安装器自动调用已有备份升级流程，重新运行测试、复制代码/样式并重启独立 Studio 服务。已保存的 Web Client Secret 会复用，**不需要新建或发送密码**。不会修改 GPU、手机审批或其他现有域名路由。

安装后浏览器打开：

https://jipite.borealos.cn/studio/

成功登录后在「全剧制作工程」区域看到「＋ 新建项目」和「＋ 添加剧集」。若还没登录，会显示 Director Studio 自己的冰川风格登录页。点击作品内某剧集可展开真实已登记镜头和关联资产。

## 真实 EP01 操作建议

1. 如果数据库里还没有《待回答事务所》，点击「新建项目」；编号可设为 WaitingOffice，名称设为 待回答事务所。已经存在的话不必重建。
2. 添加 EP01，剧集名称使用你真正已批准的名字，顺序为 1。
3. 点击 EP01 展开镜头。尚未导入分镜时为空是正常的，创建项目不等于自动生产视频。
4. 如果已有私人 V0.7 plan.json，按同仓库 studio/V09_PRODUCTION.md 提供的 VPS 私有导入方式，将镜头元数据一次性导入。导入过程不保存完整提示词、密钥或 ComfyUI 节点数据。
5. 验证审计链：

       sudo -u directorstudio /usr/bin/python3 /opt/director-studio/production_manage.py verify-audit

   返回 ok=true 代表当前事件链自洽。更强防管理员篡改保证仍需要外部签名存证。
6. 检查 GPU 依旧保持原来的电源状态，新建项目不会启动 GPU。

## API 范围

- GET /studio/api/v1/production — 原有制作概览。
- GET /studio/api/v1/production/episode?project=WaitingOffice&episode=EP01 — Microsoft 所有者限定的镜头/资产元数据；不返回媒体字节、提示词、授权凭据或绝对文件路径。
- POST /studio/api/v1/production/action — Microsoft 所有者限定的制作写接口，仅允许 create_project 和 create_episode，要求登录会话 CSRF、HTTPS 同源 Origin 与精确字段。
- 400：参数错误；401：未登录；403：无权操作；409：已有记录或审计冲突；503：数据存储故障。

## 后续

下一阶段推进安全的剧本、角色、场景、声音圣经编辑及版本管理，再发展视听连续性检查与导演艺术例外，随后实现受控 ComfyUI GPU 任务执行、媒体预览、剪辑与成片交付。
