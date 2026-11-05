# Director 视频生产流水线 · 离线优先 V0

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

## 命令

规划已有 31 镜头（不联网）：

    python3 video-pipeline/director_video.py prepare --workflow h3-api.json --bindings bindings.json --shots shots.csv --prompts prompts.md --fps 24 --out work/plan.json

查看队列（本地 SQLite，不生成）：

    python3 video-pipeline/director_video.py status --plan work/plan.json --db work/queue.sqlite

模拟提交（默认不联网）：

    python3 video-pipeline/director_video.py submit --plan work/plan.json --db work/queue.sqlite

在 GPU 已经由用户授权启动、工作流节点实际检查通过后，明确提交一个镜头（有 GPU 费用）：

    python3 video-pipeline/director_video.py submit --plan work/plan.json --db work/queue.sqlite --execute --acknowledge-gpu-cost --max-jobs 1

只读检查已经生成的镜头，并下载真实产物：

    python3 video-pipeline/director_video.py collect --plan work/plan.json --db work/queue.sqlite --out work/results --download

## 当前边界

GPU 当前关机，因此没有真实 H3 运行、真实模型兼容性或成片验收。Director V3 MCP 仍然只读；此脚本不是已经开放生成 MCP 接口。不执行 GPU 开关机、审批或其他辅助 App 更新。现阶段没有自动审片、角色一致性优化或配音合成。

离线检查（不需要模型/GPU/网络）：

    python3 -m unittest discover -s video-pipeline/tests -p 'test_*.py' -v
