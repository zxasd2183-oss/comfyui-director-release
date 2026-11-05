# Director Studio V0.9.3 — ChatGPT 大脑 ↔ Director Hub ↔ Studio 安全闭环

## 正确的系统角色

- ChatGPT（大脑）：根据用户的创作意图规划项目、剧集、剧情大纲、镜头时长；使用 MCP 工具把确认需要保存的制作数据提交到 Studio。
- Director Hub（工具与安全中枢）：向当前 ChatGPT 连接提供 6 个 Studio 工具，并将请求通过本机 HMAC 签名通道转交 Studio。它不能直接访问 Studio SQLite。
- Director Studio（项目事实来源）：验证 HMAC、时间戳与一次性 nonce，按工具白名单写入 production.sqlite 和审计链。
- Studio 网页（工作室）：读取真实项目和剧集，可查看 ChatGPT 保存的大纲草稿和修订版本；网页不调用当前 ChatGPT 会话。
- GPU/ComfyUI（执行器）：与新读写路径隔离，仍须按原有吉皮提生物识别审批。

流程：
ChatGPT → MCP → Director Hub (127.0.0.1:8896)
→ HMAC-SHA256 签名 POST → Studio (127.0.0.1:8900/api/v1/brain)
→ production.sqlite → https://jipite.borealos.cn/studio/

## 新增 6 个 ChatGPT MCP 工具

| 工具 | 用途 |
| --- | --- |
| get_production_dashboard | 查询真实项目、剧集与资产计数 |
| get_production_episode(project_id,episode_id) | 读取剧集分镜、资产和大纲草稿 |
| create_production_project(project_id,title) | 创建并审计项目 |
| create_production_episode(project_id,episode_id,title,ordinal) | 创建并审计剧集 |
| add_production_shot(project_id,episode_id,shot_id,ordinal,duration_ms) | 登记一条计划镜头的 ID、顺序、时长 |
| save_production_outline(project_id,episode_id,body,expected_revision) | 保存待审核的创作大纲，首次 expected_revision=0；更新须使用最新版本号 |

现有 13 个 GPU/VPS/电源工具保持不变，合计 19 个。草稿默认 draft；修订历史保存在版本表，审计事件只保留内容哈希及版本，不在事件日志里放剧本文本。保存大纲或登记镜头绝不意味着视频已经生成。

## VPS 单条部署命令

前提：director-studio、director-hub-mcp、director-hub-bridge、director-power-mcp、director-mobile-v06 和 nginx 均 active；V0.9.1 Microsoft Web 登录后端以及原受保护的 Nginx 路由已配置。不需要开启 GPU 或生成新的微软客户端密码。

在 VPS 私人 SSH 终端执行：

    cd ~/comfyui-director-release
    git pull --ff-only
    sudo bash studio/install-brain-link.sh

安装器将：
1. 检查现有服务及 Nginx Microsoft 登录保护；
2. 运行 Studio 与 VPS 离线测试；
3. 通过原安装器更新 Studio；
4. 创建 root 独占 0600 的独立随机密钥 /etc/director-studio/brain-link.key（如已存在则校验复用，不默默更改）；
5. 使用 systemd LoadCredential 向 Hub 与 Studio 分别提供密钥，不交出数据库权限、微软凭据或云 GPU 密钥；
6. 安装 6 个新的 Hub 工具，保留其原来的 13 个工具；
7. 本机进行一次经签名的只读项目总览验证、审计链检查和 19 工具注册检查，不调用任何生产写操作或 GPU；
8. 为 Hub 提供独立 root-only 代码备份，失败时尝试恢复。Studio 升级由既有安装器备份/回滚。

安装会重启 Studio，网页当前登录会话可能失效；刷新页面重新登录即可。不得将密钥、微软客户端密码、含授权码的回调 URL 或私有 MCP token 上传 GitHub、发给 ChatGPT。

## 在 ChatGPT 中启用新工具

重要：GitHub 代码和 VPS 服务升级不一定会立即更新 ChatGPT 当前对话内已加载的工具清单。

安装后，请在 ChatGPT 的 Director Hub 连接设置中刷新工具列表；如果仍只看到原来的 13 个工具，尝试重新连接同一个已有 Director Hub。无需重新生成原有连接 URL 或 token。

可在这里说：

“先读取 Director Studio 现有项目。如果没有《待回答事务所》，创建 WaitingOffice 项目和 EP01，保存一份待审核的大纲，不要使用 GPU。”

助手应先通过 get_production_dashboard 核对数据库，避免重名后再按用户指示调用写工具。随后在 https://jipite.borealos.cn/studio/ 的「全剧制作工程」打开 EP01，看到「AI 导演 · 剧集大纲草稿」以及修订版本。镜头只有通过登记后才增加。

## 安全边界与验收

- Studio 仅监听 VPS 127.0.0.1:8900；匿名浏览器请求、错误签名、nonce 重放、反向代理伪装、任意脚本/运行命令及越权 GPU 工具都被拒绝。
- Hub 不持有 Studio 的 SQLite 文件权限或 Microsoft Web Secret。
- 所有写入由 Studio 原服务身份执行，带审计；大纲更新有 optimistic revision 防止覆盖。
- 操作不会影响 GPU、电源、生物识别审批或现有手机 API。
- 当前 ChatGPT 只能在对话中通过工具调用完成这些任务，不等于自动全天候后台代理。
- 网页不会直接调用当前这段 ChatGPT 会话；如果未来想在网页里聊天，需要额外的 OpenAI API 方案及独立计费。
- 目前不提供完整剧本结构化编辑、自动视频生成或 GPU 自动调度，也不允许 AI 直接批准艺术例外。
