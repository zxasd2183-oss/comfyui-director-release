# Director 视频生产流水线 · GPU 本地执行器 V0.7

这是独立的本地 ComfyUI 视频生产工具，不是吉皮提功能更新。先做批量任务准备、断点续作与结果回收，不自动生成视频。

## 现有功能

1. 校验 ComfyUI API 格式工作流，拒绝 UI 保存格式。
2. 明确按真实导出工作流的节点 ID / 输入名绑定 prompt、seed、frames、fps、image；不猜 H3 节点类型。
3. 支持 CSV/JSON 镜头表、《待回答事务所》的中文 CSV 列与逐镜头提示词 Markdown。
4. 按镜头构建独立 API prompt，按 24fps 等参数估算帧数。注意模型实际支持的分辨率/帧数需 GPU 实测。
5. SQLite 任务断点续作，状态含 pending、submitting、queued、done、rejected、failed、uncertain。计划变化将拒绝复用任务库。
6. 默认模拟、零网络。必须同时给出 --execute --acknowledge-gpu-cost 才对本机 127.0.0.1:8188 发送 /prompt。一次默认最多一条，状态不确定时禁止自动重发。
7. 查 ComfyUI /history/<prompt_id> 后按镜头归档 manifest.json，--download 时从本机 /view 下载产物并做 SHA-256、类型与路径校验。

## 接入真实 H3

GPU 开机、ComfyUI 可用后，在 UI 中载入原来的 T2V/I2V/R2V 工作流并选择 File → Export Workflow (API)。用导出的 API JSON 创建真实 bindings.json，例如下述映射 **仅演示文件格式，不代表 H3 实际节点编号或字段**：

    {
      "prompt": {"node": "6", "input": "text"},
      "frames": {"node": "9", "input": "num_frames"},
      "seed": {"node": "9", "input": "seed"}
    }

如果 H3 没有 frames 的字面量输入，就删掉该绑定。参考图需事先处于 ComfyUI 的受控输入目录，不自动上传本地任意文件。

## V0.7 增强：真实 H3 节点与队列预检查

此阶段新增明确的 **只读 preflight**：在已开机的 GPU 本地调用 ComfyUI 的每个节点 /object_info/{node_class}，逐一检查导出的 API 工作流中使用的节点是否实际安装；同时读取 /queue，只有运行与等待队列都为空时才允许提交。不会请求 /prompt，也不会导出模型、密钥或上传素材。

调用限制：只有 GPU 内部 127.0.0.1:8188，本工具不增加公网端口；禁用环境代理、拒绝 HTTP 重定向。不允许工作流的节点类名当作路径穿越或随意 URL。ComfyUI 队列检查和实际提交之间不是原子操作，如果其他客户端并发插入任务仍可能出现竞争，实际生产时建议同一 ComfyUI 实例只交给一个任务调度器。

**GPU 关机期间**只能执行 prepare/status；preflight 以及带 --execute 的 submit 必须在 GPU 开机、ComfyUI 已响应、H3 节点加载后运行。不应为了验证 CI 自动开机。

## V0.7 GPU 安装（不会启动或计费）

GPU 已关机时只需从 GitHub 拉取代码，**真正的安装应在 GPU 下次正常开机后执行**。把下述 /持久化目录/director-video 换成优云智算中已确认能跨开关机保存的路径，不要假定 /root 或容器临时盘会持久化。

    cd ~/comfyui-director-release
    git pull --ff-only
    bash video-pipeline/install-on-gpu.sh /持久化目录/director-video

安装器运行离线测试、复制本地 Python 执行器，不启动 ComfyUI、GPU、电源服务，也不开放任何端口。首次安装后用 GPU 本地文件导出 H3 的 API JSON，再执行 inspect 识别节点类型与映射字段：

    python3 /持久化目录/director-video/director_video.py inspect --workflow h3-api.json

inspect 只显示节点 ID、节点类型、输入字段名称和 link/literal 类型，自动隐藏实际提示词、种子和文件路径等字段值，不需要 GPU 在线。然后用真实节点 ID 填好 bindings.json，再运行下列 prepare、preflight、submit、collect、assemble 命令。

## 命令

规划已有 31 镜头（不联网）：

    python3 video-pipeline/director_video.py prepare --workflow h3-api.json --bindings bindings.json --shots shots.csv --prompts prompts.md --fps 24 --out work/plan.json

核对 GPU 上已安装的 H3 节点和空闲队列（只读，不生成）：

    python3 video-pipeline/director_video.py preflight --plan work/plan.json

查看队列（本地 SQLite，不生成）：

    python3 video-pipeline/director_video.py status --plan work/plan.json --db work/queue.sqlite

模拟提交（默认不联网）：

    python3 video-pipeline/director_video.py submit --plan work/plan.json --db work/queue.sqlite

在 GPU 已经由用户授权启动、通过 preflight 且队列空闲后，明确提交一个镜头（可能产生 GPU 费用；提交时会再次自动预检查）：

    python3 video-pipeline/director_video.py submit --plan work/plan.json --db work/queue.sqlite --execute --acknowledge-gpu-cost --max-jobs 1

只读检查已经生成的镜头，并下载真实产物：

    python3 video-pipeline/director_video.py collect --plan work/plan.json --db work/queue.sqlite --out work/results --download

校验每个镜头已下载 MP4 的 SHA-256、字节数和音视频编码/尺寸/帧率，按镜头表顺序无损拼接（不再使用 GPU）：

    python3 video-pipeline/director_video.py assemble --plan work/plan.json --results work/results --movie work/final.mp4

assemble 依赖本地 ffprobe/ffmpeg。每个镜头必须有且只有一个已下载 MP4；格式不兼容时**拒绝拼接**，不会默默裁剪、丢音轨或转码。最终电影文件不得预先存在，防止覆盖已有作品。所有输入必须在本机结果归档目录内，检验失败不会发布最终文件。


## 整集自动渲染（GPU 上一次启动，逐镜头断点续跑）

已审核完成的 Studio 整集制作包，使用 \`prepare-studio-batch\` 生成计划。
在 **GPU 主机本地** ComfyUI/H3 实际运行、节点预检查通过后，执行：

\`\`\`bash
python3 director_video.py run-episode \
  --plan /safe/work/episode-plan.json \
  --db /safe/work/episode-runs.sqlite \
  --results /safe/work/collected-videos \
  --delivery /safe/work/StudioDelivery_EP01 \
  --execute --acknowledge-gpu-cost
\`\`\`

该命令会实际调用本机 ComfyUI \`/prompt\`，逐条等待 \`/history\` 任务成功，
将 \`/view\` 中的真实 MP4 下载并做 SHA-256、字节数与唯一视频检查，
再提交下一条。全部完成后生成一个可在 Studio 网页中选择文件夹
批量导入的素材包。默认每 10 秒查询一次，单镜头超时 7200 秒，
可使用 \`--poll-seconds\` 和 \`--shot-timeout\` 调整。

SQLite 中 \`queued\`/ \`done\` 状态重启后继续；不重提已提交的任务。
\`uncertain\`、\`failed\`、\`rejected\` 和 \`submitting\` 必须人工核查，**绝不
在可能已产生 GPU 费用的情况下自动重试**。OS 独占锁阻止两个执行器
同时提交。同一 GPU 的其他 ComfyUI 客户端应暂停，避免抢占队列。
已存在的交付目录不会覆盖；导出到该目录并不代表自动网络回传。
此命令不会执行 GPU 云端开关机；真实输入仍需要已批准 H3 工作流、
正确模型节点映射、获批镜头和角色/场景素材。


## 当前边界

GPU 当前关机，因此没有真实 H3 运行、真实模型兼容性或成片验收。Director V3 MCP 仍然只读；此脚本不是已经开放生成 MCP 接口。不执行 GPU 开关机、审批或其他辅助 App 更新。现阶段没有自动审片、角色一致性优化或配音合成。

离线检查（不需要模型/GPU/网络）：

    python3 -m unittest discover -s video-pipeline/tests -p 'test_*.py' -v

## Studio V2 → 本地执行器：安全单镜头导入（新增）

Studio 的「视频制作」页面提供按真实素材版本导出的制作单 JSON。
该文件包含完整上游版本引用、当前阻塞项与规范化 SHA-256 校验值。
`prepare-studio` 仅把**满足前置批准条件**的制作单转为本机 ComfyUI
计划，不联网、不提交任务，也不代替影片成品审核：

```sh
python3 video-pipeline/director_video.py prepare-studio \
  --package studio_handoff_EP01_SH01_V1.json \
  --workflow h3-api.json --bindings bindings.json \
  --out work/studio-shot01-plan.json
```

若绑定的 H3 工作流需要图像输入，还须先将已批准的原图放入 ComfyUI
本地受控 input 目录，并传 `--image 已确认的文件名.png`。
非法路径、未经批准的场景/道具/分镜/粗白模、制作规格不符或被篡改的
JSON 都会被拒绝。SHA-256 是防误修改校验，**不是数字签名**。

真实提交仍必须遵循上述独立的本地 `preflight`、空队列确认及
`--execute --acknowledge-gpu-cost` 双重明确授权。VPS Studio 部署**不会**
自动更新关机中的 GPU 本地执行器。生成结果自动回传 Studio、成片 MP4
可视化审核与一致性质检仍未接通，不能因为准备了计划就宣称成片完成。

技术契约与当前边界见
[`studio/docs/studio-gpu-handoff.md`](../studio/docs/studio-gpu-handoff.md)。

## 整集批量导入（一次准备所有已审核镜头）

Studio 视频制作页新增「导出整集版本锁定制作包」。将文件保存到 GPU
受控目录后，在 GPU **本地**执行（准备阶段不需要 GPU 在线）：

```sh
python3 director_video.py prepare-studio-batch \
  --package /safe/inbox/studio_episode_EP01_handoff.json \
  --workflow /safe/local/h3-api.json \
  --bindings /safe/local/bindings.json \
  --out /safe/work/episode-plan.json
```

只有整集所有镜头已有经人工提交的视频制作单，且所有场景、分镜、粗白模、
道具、角色引用的批准条件全部满足时，才允许生成完整离线计划。某一个
镜头缺版本或素材、镜头总数不符、SHA-256 被篡改、帧率不统一或时长不符
都会拒绝，**不会只准备一部分而假装整集完成**。

I2V/R2V 等含本地图片输入的工作流，可增加
`--images /safe/local/images.json`，内容为镜头编号到 ComfyUI 受控
input 目录内图片**安全文件名**的映射。不可传 URL 或路径穿越。

Studio 已支持独立的 Microsoft owner MP4 分块回传（单片最大 250MB、
严格 SHA-256 + ffprobe 规格检查、版本锁定、审片、返工和浏览器播放）。
当前传输需由已登录的 Studio owner 选择真实 MP4；不存在隐藏的自动
GPU 调度或自动生成回传。播放/批准是对实际产物的独立审查门槛，不是
对制作单的批准。详情：
[`studio/docs/studio-gpu-handoff.md`](../studio/docs/studio-gpu-handoff.md)。

## GPU 自动回传 Studio（免逐镜头人工上传）

在 Studio 视频制作页先选择项目/剧集，点击「下载 GPU 自动回传密钥」。
仅 Microsoft 所有者可签发；有效期 48 小时、单剧集作用域、只允许导入
\`in_review\` 视频；新密钥使原凭据失效。GPU 持久化目录上的私有
\`.token\` 文件必须为 \`chmod 600\`，不要将内容发送到聊天/GitHub。

在 GPU 本地使用安装后的最新版 \`director_video.py\`：
\`\`\`bash
python3 director_video.py run-episode \
  --plan /safe/work/episode-plan.json \
  --db /safe/work/episode-runs.sqlite \
  --results /safe/work/collected-videos \
  --studio-return-token /safe/secrets/gpu-return-WaitingOffice-EP01.token \
  --execute --acknowledge-gpu-cost
\`\`\`

每个 H3 镜头由 ComfyUI 确认成功、真正下载 MP4 后，执行 HTTPS
\`/studio/api/v1/gpu-return/start|chunk|finish\` 的定长 SHA-256
分块断点续传。Studio 使用现有受控的 FFprobe/版本锁机制保存结果，
状态为「待审片」，不能自动变为“审核通过”。断网时执行器拒绝继续
提交新任务；重启后会接着回传已有真实镜头，避免重复 GPU 计费。

需统一部署新的 Studio 服务和单独 Nginx 返回代理（1.2MB 请求大小，
只将 Authorization 转发给 GPU 返回通道；普通 Microsoft 登录仍清空它）。
代码提交成功并不代表已部署、已开机或已产生真实视频。
