# 一次性启用签名自动更新（无需重新上传 ZIP）

## 已经完成
- `V3 0.3.0` 已在优云智算实例的 **8790** 运行，ChatGPT Plus 通过新 MCP 连接已验证读取。
- GitHub V3 bootstrap 归档已发布，SHA256 校验固定。
- `ci.yml` 已在真实 GitHub Actions 上通过离线测试。
- `publish.yml` 可生成 **Ed25519 签名** `manifest.json`、`manifest.json.sig` 和 release ZIP。

## 一次性配置签名与 Pages（在你自己的可信电脑执行，**不要在 GPU 上运行**）

**前提：** 已安装 [GitHub CLI](https://cli.github.com/) 并运行过 `gh auth login`；Python 3.10+ 可用。

在 macOS 电脑终端（不是优云智算）：

```bash
# 没装 gh 时，可以先运行：brew install gh
gh auth login
python3 -m venv ~/.comfyui-director-release-venv
~/.comfyui-director-release-venv/bin/python -m pip install cryptography
curl -fsSL https://raw.githubusercontent.com/zxasd2183-oss/comfyui-director-release/main/scripts/setup_signed_release.py -o ~/setup_signed_release.py
# 可以先查看脚本，确认安全行为
~/.comfyui-director-release-venv/bin/python ~/setup_signed_release.py
```

脚本会：
1. **在你的电脑**生成 Ed25519 密钥对（原本就存在则复用，禁止静默轮换）。
2. 通过你自己的 GitHub CLI 授权，把**私钥**安全写入仓库 Actions Secret：`DIRECTOR_SIGNING_PRIVATE_HEX`。
3. 把**公钥**提交到公开仓库 `bootstrap/trusted_public_key.hex`（公钥可公开）。
4. 创建/切换 GitHub Pages 为 **GitHub Actions** 构建模式。
5. 触发 `publish.yml` 生成 `0.3.0` 的首份签名发布。

**不要把签名私钥发给 ChatGPT、加入 GitHub 文件或上传 GPU。**

## 确认首份签名版本生成

在 [GitHub Actions 发布页](https://github.com/zxasd2183-oss/comfyui-director-release/actions/workflows/publish.yml) 查看最新运行是否成功。

完成后应该能访问：
- [签名清单](https://zxasd2183-oss.github.io/comfyui-director-release/manifest.json)
- [签名](https://zxasd2183-oss.github.io/comfyui-director-release/manifest.json.sig)

如果 Actions 失败，查看运行日志；在确认发布成功前不要配置 GPU 更新源。

## 将公钥绑定到 GPU（**发布成功后**，在优云智算 GPU 终端运行）

```bash
curl -fsSL https://raw.githubusercontent.com/zxasd2183-oss/comfyui-director-release/main/bootstrap/trusted_public_key.hex \
  -o ~/.comfyui-director/director_signing.pub.hex

python3 ~/.comfyui-director/controller/configure_updates.py \
  --manifest-url 'https://zxasd2183-oss.github.io/comfyui-director-release/manifest.json' \
  --public-key-file ~/.comfyui-director/director_signing.pub.hex
```

这会在实例中固定公钥，保留现有 MCP 密钥、**8790** 端口等配置。需安全重启 Director Supervisor 后才会读取新配置：**只重启 Director Supervisor，不重启 ComfyUI，也不要停止 Slink（8765）**。重启方法请按实际守护方式操作；如果是最初脚本启动，可使用：

```bash
~/.comfyui-director/controller/stop.sh
~/.comfyui-director/controller/start.sh
curl -fsS http://127.0.0.1:8790/health
```

然后回到 ChatGPT 询问 `ComfyUI Director V3` 的 `get_upgrade_readiness`，确认 `trusted_release_manifest_configured: true`。**已发布版本 0.3.0 与当前版本相同，所以不会升级；只有以后发布更高版本才会自动下载与切换。**

重要：该方案自动更新**网关程序**，但 Supervisor 本身仍是固定可信控制器，不会远程自我替换；GPU 停机期间也不会自动执行更新。

## 出错处理

- `gh: command not found`：先安装 [GitHub CLI](https://cli.github.com/)。
- `gh auth status` 失败：执行 `gh auth login`。
- `404 Not Found`（Pages）：等发布 Actions 成功再访问。
- 同一公钥文件已存在但不匹配：脚本会拒绝静默换钥，避免破坏现有的信任链。
