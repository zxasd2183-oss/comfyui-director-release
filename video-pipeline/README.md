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


## 当前边界

GPU 当前关机，因此没有真实 H3 运行、真实模型兼容性或成片验收。Director V3 MCP 仍然只读；此脚本不是已经开放生成 MCP 接口。不执行 GPU 开关机、审批或其他辅助 App 更新。现阶段没有自动审片、角色一致性优化或配音合成。

离线检查（不需要模型/GPU/网络）：

    python3 -m unittest discover -s video-pipeline/tests -p 'test_*.py' -v
