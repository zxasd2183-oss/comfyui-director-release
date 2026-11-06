# Glacier Browser · 2026-11-06 交接状态

## 路线

- Android M01–M04 作为历史 Debug 测试版本，已从 M05 正式发布门禁中剔除。
- Android M05 v0.2.1 是新固定签名基线；保留 GeckoView、sing-box/VLESS、Android 15 模拟器及 fail-closed 回归。
- **M05 未声称正式发布成功**：必须具有 Glacier 独立长期签名证书和 GitHub Actions Secrets/变量，且真实 CI/签名检查通过。不得在 CI 或仓库中自动生成并公开私钥。
- 直接回归 Windows/macOS 桌面主线。

## 本轮完成的桌面代码 (D03)

Windows 分支 `fix/glacier-browser-windows-v0201-input`：
- `glacier-windows/glacier_accounts22.py`：按 HTTPS 域名精准匹配账号卡片；本机 DPAPI 加密；新增、查看、编辑、手动复制与确认删除；拒绝仅大小写或空格不同的重复名称。
- `glacier-windows/main.py` / `windows_desktop15.py`：接入现有标签页与菜单；不自动填表、自动登录或上传凭据。
- `glacier-windows/test_accounts22.py`：主机匹配、非法站点、存储加密、编辑与删除、重复名称拦截及失败回滚。
- `.github/workflows/glacier-browser-windows-v0201-input.yml`：将新代码及测试加入 CI，使用独立不可覆盖预览 tag，不更新已签名自动更新源。

macOS 分支 `build/glacier-browser-v0-20-ui-refresh`：
- 同步账号卡片模块、编辑与删除、菜单、标签页监听与测试；复用 macOS Keychain / Fernet 密钥存储。
- `.github/workflows/glacier-browser-macos-arm64.yml`：加入测试，采用独立不可覆盖 D03 预览 tag，取消预览构建自动触发正式签名 feed。

## 未完成 / 不得假报通过

- 无法从当前 GitHub 工具取得 GitHub Actions 最新运行结果；已提交 CI，但尚未证明真实 Windows EXE/macOS DMG 构建成功。
- M05 正式签名 Secret/证书配置与真实 Release APK 发布尚未验证；不应绕过签名。
- D02 多账号完全隔离、D04 验证码 API、D05 账号保险箱完整管理功能、Windows/macOS 现场验收、跨设备同步均尚未完整交付。
- D03 为最小初版：只按 HTTPS 主机精确匹配并手动复制；用户应在真实设备检查弹窗与删除体验。

## 接下来

1. 查看 D03 两平台 CI 结果，修复构建/运行错误再发布预览。
2. 完成 D02 多账号空间隔离与 D03 资料管理交互，再开始 D04 可选验证码 API。
3. 继续 D05–D07 桌面功能与双平台统一验收，避免回头为 M04 添加兼容阻塞。

此文档是代码状态记录，不代表应用已实际安装测试成功。
