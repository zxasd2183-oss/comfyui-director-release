# GamePilot Mac: 111 VPS 代理镜像（免费 WineCX + DXMT）

只镜像 **WineCX 24.0.7、DXMT 0.74 与 Wine 11.0 支持库**这三个固定的开源归档。所有文件仍按 GitHub Release 原始长度与 SHA-256 校验。GamePilot 新版本优先从 `sync.borealos.cn` 下载，404、网络失败时再尝试官方 GitHub；即便服务器被替换了文件，Mac 端最终 SHA-256 不匹配也拒绝安装。

## 111 VPS 一次性启用

从有 sudo 权限的 Ubuntu 111 VPS shell 执行：

```bash
cd /home/ubuntu/comfyui-director-release
HTTPS_PROXY=http://127.0.0.1:1081 HTTP_PROXY=http://127.0.0.1:1081 git pull --ff-only
sudo bash vps-control/install-gamepilot-dxmt-mirror.sh
```

脚本要求本地已有 `/etc/nginx/snippets/glacier-preview-downloads.conf` 和既有 GamePilot ZIP 路由，确认 Git 分支是 `main`，只访问现有 HTTP 代理 `127.0.0.1:1081`，绝不将该代理公开。

1. 顺序从 **官方 GitHub Releases** 通过 VPS 的本地代理下载三个已固定哈希的压缩包。
2. 完整验证大小、SHA-256 后原子地写入 `/var/lib/glacier-preview-downloads/gamepilot-dxmt/`。
3. 使用另一个审阅过的 Nginx 文件，仅注册三个**精确匹配**且只允许 GET/HEAD 的 HTTPS 文件路径；不修改原 Glacier 或 GamePilot 的签名清单与 URL。
4. `nginx -t` 和 reload 后，对三个**公网 HTTPS 下载文件的完整内容重新计算 SHA-256**。旧 Nginx worker 的瞬时 404 会有限重试。
5. 失败时只回滚此次添加的 Nginx include/片段，已通过 SHA-256 的静态压缩包缓存继续保留，方便重跑。备份保留在原目录的 `.dxmt.*.backup`。

该操作不触及 GPU、电源、Glacier 自动更新、GamePilot 签名密钥、登录、Wine 前缀，也不创建公网代理。

## 对外固定下载地址

- `https://sync.borealos.cn/downloads/gamepilot-dxmt/winecx-24.0.7_7.tar.xz`
- `https://sync.borealos.cn/downloads/gamepilot-dxmt/dxmt-0.74-builtin.tar.gz`
- `https://sync.borealos.cn/downloads/gamepilot-dxmt/wine-stable-11.0_1-libs.tar.xz`

客户端从 **GamePilot Mac v0.4.6** 开始自动使用 VPS 优先下载。不需要用户填写代理，也不需要手工改地址。v0.4.5 正在进行的下载不会自动切换到新服务器；不应在两份进程之间同时修改同一 `.part` 文件。

## 检查结果

脚本成功时显示：

```
HTTPS PASS: winecx-24.0.7_7.tar.xz (172348356 bytes) SHA256
HTTPS PASS: dxmt-0.74-builtin.tar.gz (18990005 bytes) SHA256
HTTPS PASS: wine-stable-11.0_1-libs.tar.xz (185303032 bytes) SHA256
PASS: Three immutable FOSS DXMT assets available via existing owner VPS HTTPS, every byte SHA256 checked.
```

**CI 的静态配置测试或脚本提交不代表 111 VPS 已执行安装**。只有在 111 上完成上述命令并得到三个 HTTPS PASS，才可以对用户声明 VPS 镜像正式可用。
