# Director Studio V0.8 — 实时可视化监制工作台（首个可安装版本）

这不是单纯的 ComfyUI 状态页。V0.8 开始建设独立的导演/制片操作台，供项目负责人持续观察、留痕、暂停未来调度和发起返工。UI 是真实可运行的本地网页，含 GPU/ComfyUI 实时状态、镜头列表、审片面板、操作审计和交互确认。适合从 EP01 镜头计划开始导入数据。

## 权限边界（重点）

- **监控是真实的**：每 5 秒经过本地 Director Hub MCP 的两个白名单工具查询 CompShare GPU 电源状态和 ComfyUI 队列。网页通过 Server-Sent Events 约每 2 秒收到最新快照；离线/不可用显示异常，不伪造数值。
- **人工决策是真实写入的**：镜头暂停/释放、要求返工、备注、暂停或放行未来调度，原子写入单独 SQLite 和审计事件；镜头使用乐观版本号防止过时审批。
- **当前还没有控制 GPU 中正在执行的 ComfyUI 任务**：这个版本不调用 /prompt、/interrupt、/queue 删除，也不负责手机审批、不启动/关闭 GPU。暂停是未来派单许可，GPU 端 V0.7 CLI 目前尚未接入这个许可源。只有后续完成安全的调度 Worker 与指令执行链路后，才能把“人工介入”扩展为真实取消或重做生成。
- **当前不提供视频实况画面**：预览区明确显示 NOT CONNECTED。后续需要具备身份保护、私密素材地址、支持缩略图/视频的媒体代理，不能用假画面冒充 GPU 输出。
- **审核通过受保护**：尚未验证的镜头产物不允许批准。当前版本只提供人工备注和返工账本，真实通过需后续接入产物校验。
- **独立低权限**：Director Studio 由独立系统用户 directorstudio 运行，不是 directorpower，不读取审批数据库/API 密钥，MCP 只能调用 get_gpu_power_status、get_queue_summary。只监听 VPS 127.0.0.1:8900，**不对公网开放、不修改 Nginx、无独立弱口令登录页面**。
- ChatGPT 原 Director Hub V0.6 的 13 个工具、URL/token、吉皮提指纹审批、APK/DMG、OIDC、GPU SSH 回连全都不变。

## 1. VPS 一次安装（无需打开 GPU）

在自有 VPS 私人终端：

    cd ~/comfyui-director-release
    git pull --ff-only
    sudo bash studio/install-v08.sh

安装器会先跑离线测试、复制前端和后端到 /opt/director-studio，新增 director-studio.service（状态库 /var/lib/director-studio/studio.sqlite）。工作台只监听 localhost 8900。脚本检查旧 Hub 服务正常，不触碰云平台的开关机功能。

## 2. 通过 SSH 安全打开可视化工作台

在自己的电脑打开终端（不是 VPS 终端），用平时连接 VPS 的 SSH 配置别名替换 YOUR_VPS_SSH_ALIAS：

    ssh -N -L 8900:127.0.0.1:8900 YOUR_VPS_SSH_ALIAS

保持此 SSH 会话开启。在本机浏览器访问：

    http://127.0.0.1:8900

这一页不需要提供任何 Hub 令牌，也不需要在公网开放 8900。SSH 自己负责身份认证和加密。如果本机 8900 已被占用，可改用 ssh -N -L 18900:127.0.0.1:8900 ...，但 V0.8 对管理页 Host/Origin 限制严格，暂不支持浏览器使用 18900 端口访问，因此**建议优先腾出本机 8900**，避免安全误配置。

## 3. 将已有镜头计划导入（不保存提示词）

导入的是 V0.7 的 plan.json 文件，仅存储镜头 ID、顺序、时长和数据指纹，不保存 prompt、工作流图、模型路径、MCP 密钥。先通过可信 SSH/SCP 将本地计划放进 VPS 的安全目录，再执行：

    sudo install -o directorstudio -g directorstudio -m 0600 /你已确认的安全位置/plan.json /var/lib/director-studio/plan.json
    sudo -u directorstudio /usr/bin/python3 /opt/director-studio/manage.py import-plan --plan /var/lib/director-studio/plan.json

浏览器的镜头列表会自动刷新显示。默认全局调度为“已暂停”；修改排程需在界面人工确认。计划不一致时拒绝覆盖原数据库，避免与历史审计错位；新的剧集应该用新的数据库或后续项目多租户机制。

可选地从 GPU 视频执行器的 SQLite 导出只读快照，复制到 VPS，再同步镜头状态（这不是实时同步）：

    sudo install -o directorstudio -g directorstudio -m 0600 /安全路径/queue-copy.sqlite /var/lib/director-studio/queue-copy.sqlite
    sudo -u directorstudio /usr/bin/python3 /opt/director-studio/manage.py sync-runner --runner-db /var/lib/director-studio/queue-copy.sqlite

不要直接复制正在被 GPU SQLite 写入的数据库文件；先使用 SQLite backup API 获取一致快照，再通过 SSH 安全传输。实时的 GPU 生产任务事件上报与素材代理属于下一阶段。

## 4. 验证

在 VPS：

    sudo systemctl status director-studio
    curl -fsS http://127.0.0.1:8900/api/v1/snapshot
    sudo ss -ltn | grep ':8900'

必须只有 127.0.0.1:8900 本地监听，不应有 0.0.0.0:8900。状态结果包含 live.gpu_power、live.comfy_queue、shots、events、capabilities。GPU 已关机时，ComfyUI 状态不可用是预期行为。

离线 CI：

    python3 -m unittest discover -s studio/tests -p 'test_*.py' -v
    bash -n studio/install-v08.sh

## 后续生产级工作台

- V0.9：计划/资产多项目数据库、GPU 本地安全调度代理、可验证的取消与中断指令、排程门禁与已提交任务状态关联、自动异常告警；
- V1.0：真实视频帧预览与双屏审片、参考角色一致性/动作/字幕质检、标注返工区域、版本对比、人工逐镜头审批；
- V1.1：Microsoft 个人账号登录与设备会话权限、正式自有域名 HTTPS、操作者审计身份、审批分层，以及跨设备管理；
- 此后：制片成本预算、GPU 资源配额、镜头优先级和多集自动编排。

**不要将当前 SSH-only 工作台未经身份保护直接通过 Nginx 对外发布。**
