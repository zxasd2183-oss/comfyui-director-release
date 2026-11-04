# 吉皮提 V0.10.3：不触发 GPU 的真实指纹签名自检

## 功能说明

吉皮提已经在小米国行真机上完成 Microsoft 登录、本机 TEE 强生物识别安全检查和 VPS 设备绑定后的待审批查询。当前没有待审批 GPU 操作，而且控制中心为 `read_only`。无需制造任何真实 GPU 开机或关机申请，就可以验证**手机签名 → VPS 验证**是否真实可用。

本版本增加两条**独立且要求 Microsoft ID Token 认证**的 VPS API：

- `POST /api/v1/mobile/selftest_challenge`：仅已绑定设备可以获取随机数和 90 秒有效的一次性挑战。
- `POST /api/v1/mobile/selftest_verify`：只接受已绑定设备同一个挑战对应的 P-256/ECDSA 签名；挑战只能消费一次。

认证信息、设备 ID、随机挑战和签名通过 HTTPS 发送；服务端不会输出任何配对码或私钥，也不会创建 GPU 请求、调用电源 API、读取 GPU 云平台的凭据或更改已有申请状态。为了阻止重放，会在原 SQLite 数据库内使用**独立**的 `mobile_selftest_nonce` 表记录短时随机数，这是本功能唯一的持久状态变化。

**这是对已登记公钥的所有权/使用权证明，并不是服务端远程硬件证明。** Android App 仍在本机要求 TEE/StrongBox、仅强生物识别、每次使用验证并通过 `BiometricPrompt.CryptoObject(Signature)` 才发送签名；服务端只验证签名是否来自曾绑定的密钥。

## 服务器只需升级一次 API

已经部署并成功验收 `jipite.borealos.cn` 现有 Microsoft 审批 API、VPS APK 镜像和发布 OIDC 通知后，**仅在自己的 VPS SSH** 执行：

```bash
cd ~/comfyui-director-release
git pull --ff-only
sudo bash vps-control/install-jipite-selftest.sh
```

这不是原来的首次安装脚本。它只备份并替换既有 VPS 的 `mobile_v06_api.py`，添加独立的 `mobile_v06_selftest.py`，对现有 Python 环境进行语法/导入检查，然后重启 **director-mobile-v06**。它不会改 Nginx、Microsoft 应用注册、配对码、TOTP、Mi Push、APK 同步工作流或 GPU 电源权限；启动或匿名 HTTPS 验证失败会自动恢复旧版服务代码。

预期会看到：

```text
Selftest challenge without Microsoft token: HTTP 401 (401 expected)
Selftest verification without Microsoft token: HTTP 401 (401 expected)
Original pending API without Microsoft token: HTTP 401 (401 expected)
[4/4] Selftest API ready; no GPU power operation was performed.
```

可以自行进一步只读确认：

```bash
sudo systemctl is-active director-mobile-v06
sudo systemctl is-active director-power-approval
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST -H 'Content-Type: application/json' --data '{}' \
  https://jipite.borealos.cn/api/v1/mobile/selftest_challenge
```

**不提供真实 Microsoft Token、配对码或 GPU 凭据**；无认证状态必须返回 401。没有任何“允许匿名自检”的兼容模式。

## 手机完成全链路验收

V0.10.3 经同一签名证书发布并可从自己的 VPS 通过应用内升级。

1. 打开吉皮提 → 设置 → 检查更新，升级至 **V0.10.3**。不卸载现有版本，不清除 App 数据，不重新生成审批密钥。
2. 确认上面的 VPS 自检 API 已部署。在小米手机 →「审批」找到**安全审批链路自检**卡片。
3. 点击「开始指纹安全自检」，核对确认提示，然后在系统安全窗口使用指纹。
4. 手机上的结果应显示：**“安全自检通过 ✓ Microsoft、设备绑定、指纹签名、VPS 验签与防重放均正常；未操作 GPU”**。
5. 如果没有通过，复制/截图**错误代码或状态文字**（不要提供 Microsoft Token、VPS 配对码、设备 ID、原始签名或私钥）。如果显示 `not_found`，先检查 VPS 部署，不能通过修改客户端绕过服务端校验。

### CI 安全验收

新增的测试覆盖：匿名 401、无效 Microsoft 身份、未绑定/错误设备、有效 P256 签名、无效签名消费、重复签名拒绝、过期挑战、替换挑战、并发重放、JSON 内夹带 GPU 操作字段无法触发任何云平台行为。核心测试只模拟身份/签名、不联外网，且刻意让 GPU provider 配置加载函数抛异常，以确认自检路径绝不会使用它。

## 当前限制

- 服务端用注册过的公钥验证签名，**不进行 Android Key Attestation 的远程安全硬件真实性证明**；本地检查和真实签名属于分开的证据。
- 本功能**不能**完成真实 GPU 开关机审批业务验收。正式操作仍需用户主动确认并受现有 VPS 控制开关限制，当前继续保持 `read_only`。
- 自检与国行 Mi Push 无关，不需要第三方推送服务，也无需审批网站。
