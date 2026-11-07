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

## 07:00 后追加进展

- Windows/macOS D03：账号卡片只对当前活动标签页展示，后台加载不弹；切回标签页时弹出一次，同一网站访问不重复提示；已补模拟回归。
- Windows/macOS D03：账号名称大小写/空格归一化去重；编辑与失败回滚回归、测试夹具信号修正。
- Android M05：正式签名 Release 不再带 `--prerelease`；客户端 `BrowserUpdater.findLatest` 排除 draft/prerelease。
- Android M05：增加 `StableReleaseFilteringTest` 两项 instrumentation 测试，更新 CI 为至少 9 项通过，并修复 grep 正则。
- GitHub commit 已写入；工作流是否实际成功、正式签名 Secret 是否存在仍待真实 CI 检查。**未宣称发布或真机验证完成。**

## 17:30 后补充：移动版门禁通过，继续桌面主线

- 用户已确认 Android M05 本轮构建与测试全部通过；这是来自 GitHub Actions 的用户验收反馈，尚未等同于正式稳定签名 Release 发布。
- Android M05 独立固定签名 Release 仍需手动触发 `workflow_dispatch: publish_signed=true`，并通过仓库签名 Secrets 和证书 SHA-256 校验。当前工具无法读取 Secrets 或证明 Release 已存在。
- Windows/macOS D03：新增“管理全部网站账号”可搜索目录，按域名和备注过滤、逐网站查看/编辑/删除；不索引密码、用户名或其他密文。
- 新增纯函数 `account_site_summary22` 和跨平台单元测试；相关 CI 未在本轮报告为已运行通过。
