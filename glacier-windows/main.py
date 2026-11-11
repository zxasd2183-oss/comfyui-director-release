import ctypes, json, os, re, socket, subprocess, sys, uuid
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote, quote_plus
from PySide6.QtCore import QUrl, QTimer
from PySide6.QtNetwork import QNetworkProxy
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
 QLineEdit, QTabWidget, QPushButton, QMessageBox, QInputDialog, QLabel)
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from features import GlacierFeatures
from ui08 import GlacierUI08, GlacierPrefs
from ui09 import GlacierUI09
from update_ui import GlacierUpdateUI
from ui12 import GlacierUI12
from tabtools13 import GlacierTabTools13
from chrome14 import GlacierChrome14
from windows_desktop15 import WindowsDesktop15
from glacier_productivity16 import GlacierProductivity16
from glacier_workspaces17 import GlacierWorkspaces17
from glacier_downloads17 import GlacierDownloads17
from glacier_tabs19 import GlacierTabs19
from glacier_shell20 import GlacierShell20
from glacier_chrome_ui30 import GlacierChromeUI30
from glacier_desktop_ui32 import GlacierDesktopUI32
from glacier_chrome_shell33 import GlacierChromeShell33
from glacier_site_diagnostic31 import GlacierSiteDiagnostic31
from glacier_input21 import GlacierInput21
from glacier_accounts22 import GlacierAccounts22
from glacier_sync23 import GlacierSync23
from glacier_account_center26 import GlacierAccountCenter26
from glacier_splash import show_glacier_splash, reveal_browser_after_splash
from glacier_proxy_health29 import (ephemeral_proxy_config, await_proxy_ready,
                                    proxy_status_text)

APP = "Glacier Browser"
def appdir():
 p=Path(os.getenv("LOCALAPPDATA",str(Path.home()))) / "GlacierBrowser"
 p.mkdir(parents=True,exist_ok=True)
 return p
def parse_node(link):
 p=urlsplit(link.strip())
 if p.scheme.lower()!="vless" or not p.hostname or not p.port: raise ValueError("只支持完整的 vless:// 分享链接")
 try: uuid.UUID(unquote(p.username or ""))
 except Exception: raise ValueError("VLESS UUID 无效")
 q=parse_qs(p.query,keep_blank_values=True)
 g=lambda k,d="": q.get(k,[d])[0]
 if g("encryption","none")!="none": raise ValueError("不支持此 encryption")
 if g("allowInsecure","0").lower() in ("true","1") or g("insecure","0").lower() in ("true","1"): raise ValueError("不接受禁用 TLS 校验")
 o={"type":"vless","tag":"node","server":p.hostname,"server_port":p.port,"uuid":unquote(p.username)}
 if g("flow"): o["flow"]=g("flow")
 security=g("security","none").lower()
 if security not in ("none","tls","reality"): raise ValueError("不支持安全类型 "+security)
 if security!="none":
  tls={"enabled":True,"server_name":g("sni") or p.hostname}
  if g("fp"): tls["utls"]={"enabled":True,"fingerprint":g("fp")}
  if g("alpn"): tls["alpn"]=g("alpn").split(",")
  if security=="reality":
   if not g("pbk"): raise ValueError("REALITY 缺少 pbk")
   tls["reality"]={"enabled":True,"public_key":g("pbk"),"short_id":g("sid")}
  o["tls"]=tls
 transport=g("type","tcp").lower()
 if transport=="ws":
  t={"type":"ws","path":g("path","/")}
  if g("host"):t["headers"]={"Host":g("host")}
  o["transport"]=t
 elif transport=="grpc":o["transport"]={"type":"grpc","service_name":g("serviceName")}
 elif transport not in ("","tcp","raw"):raise ValueError("暂不支持传输类型 "+transport)
 return o
class Blob(ctypes.Structure):
 _fields_=[("size",ctypes.c_ulong),("data",ctypes.POINTER(ctypes.c_byte))]
def dpapi(data,decrypt=False):
 raw=ctypes.create_string_buffer(data)
 src=Blob(len(data),ctypes.cast(raw,ctypes.POINTER(ctypes.c_byte)))
 out=Blob()
 f=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
 f.restype=ctypes.c_int
 f.argtypes=([ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong,ctypes.POINTER(Blob)] if decrypt else [ctypes.POINTER(Blob),ctypes.c_wchar_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong,ctypes.POINTER(Blob)])
 if not f(ctypes.byref(src),None,None,None,None,1,ctypes.byref(out)):raise ctypes.WinError()
 try:return ctypes.string_at(out.data,out.size)
 finally:
  ctypes.windll.kernel32.LocalFree.argtypes=[ctypes.c_void_p]
  ctypes.windll.kernel32.LocalFree(ctypes.cast(out.data,ctypes.c_void_p))
def get_link(app):
 path=appdir()/"node.dpapi"
 if path.exists():
  try:
   link=dpapi(path.read_bytes(),True).decode()
   parse_node(link)
   return link
  except Exception as e: QMessageBox.warning(None,APP,"已有线路无法读取："+str(e))
 clip=app.clipboard().text().strip()
 proposal=clip if clip.lower().startswith("vless://") else ""
 link,ok=QInputDialog.getMultiLineText(None,"冰川浏览器首次导入",
  "从 v2rayN 复制 VLESS 分享链接并粘贴：\n仅在本机使用 Windows DPAPI 加密保存。",proposal)
 if not ok or not link.strip():return ""
 try:
  parse_node(link)
  path.write_bytes(dpapi(link.strip().encode()))
  return link.strip()
 except Exception as e:
  QMessageBox.warning(None,APP,"导入失败："+str(e))
  return ""
def core_path():
 roots=[Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parent)),Path(sys.executable).parent]
 for root in roots:
  for part in ("bin/sing-box.exe","_internal/bin/sing-box.exe"):
   candidate=root/part
   if candidate.is_file():return candidate
 return None
def proxy_start(link,port):
 if not link:return None
 core=core_path()
 if not core:raise RuntimeError("安装包内未找到 sing-box.exe")
 config={"log":{"level":"warn"},"inbounds":[{"type":"mixed","tag":"in","listen":"127.0.0.1","listen_port":port,"set_system_proxy":False}],"outbounds":[parse_node(link)],"route":{"final":"node"}}
 flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
 # The persistent VLESS link stays DPAPI-encrypted. Only a temporary JSON
 # is provided to sing-box while the core verifies and loads configuration.
 # After local listener readiness this JSON is deleted even if startup fails.
 with ephemeral_proxy_config(appdir(),config) as configfile:
  result=subprocess.run([str(core),"check","-c",str(configfile)],
   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
   timeout=15,creationflags=flags)
  if result.returncode:raise RuntimeError("VLESS 核心无法识别该线路配置")
  proc=subprocess.Popen([str(core),"run","-c",str(configfile)],
   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags)
  try:
   await_proxy_ready(proc,port,timeout=12)
  except Exception:
   if proc.poll() is None:
    try:proc.terminate()
    except OSError:pass
   raise
 # Delete any stale plaintext config left by the old v0.20.x client.
 # It is never necessary for the verified, running sing-box core.
 legacy=appdir()/"runtime.json"
 try:legacy.unlink(missing_ok=True)
 except OSError:pass
 return proc

class Page(QWebEngineView):
 def __init__(self,win):
  super().__init__(win)
  self.win=win
  self.setPage(QWebEnginePage(win.profile,self))
  self.win.prepare_page_input21(self)
 def createWindow(self,typ):return self.win.new_tab()
class Browser(GlacierChromeShell33, GlacierDesktopUI32, GlacierSiteDiagnostic31, GlacierChromeUI30, GlacierAccountCenter26, GlacierSync23, GlacierAccounts22, GlacierInput21, GlacierShell20, GlacierTabs19, GlacierWorkspaces17, GlacierDownloads17, GlacierProductivity16, WindowsDesktop15, GlacierChrome14, GlacierTabTools13, GlacierUI12, GlacierUpdateUI, GlacierUI09, GlacierUI08, GlacierFeatures, QMainWindow):
 def __init__(self,process,port):
  super().__init__()
  self.proc=process
  self.proxy_port=port
  self.prefs=GlacierPrefs(appdir()/"settings.json")
  self.setWindowTitle("❄ Glacier Browser · Windows v0.20.22")
  self.resize(1260,850)
  self.profile=QWebEngineProfile("Glacier",self)
  self.profile.setPersistentStoragePath(str(appdir()/"profile"))
  self.profile.setCachePath(str(appdir()/"cache"))
  self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
  self.initialize_workspace_profiles17(appdir(),dpapi)
  root=QWidget();lay=QVBoxLayout(root);self.setCentralWidget(root)
  bar=QHBoxLayout();lay.addLayout(bar)
  for label,cb in [("←",lambda:self.current().back()),("→",lambda:self.current().forward()),("↻",lambda:self.current().reload()),("＋",self.new_tab)]:
   b=QPushButton(label);b.clicked.connect(cb);bar.addWidget(b)
  self.address=QLineEdit();self.address.setPlaceholderText("输入网址或搜索");self.address.returnPressed.connect(self.navigate);bar.addWidget(self.address,1)
  self.init_features(bar)
  self.init_ui09(bar, lambda data: dpapi(data), lambda data: dpapi(data, True), appdir())
  self.setup_tabtools13(lay,bar)
  self.proxy_label=QPushButton("● 正在检查代理状态",self)
  self.proxy_label.setObjectName("GlacierProxyHealth29")
  self.proxy_label.setToolTip("这里只检测本地 VLESS 端口。检测 Gemini HTTPS：打开 ▦ 工具中心 → Gemini 连接诊断")
  self.proxy_label.clicked.connect(self.reconnect_saved_proxy29)
  bar.addWidget(self.proxy_label)
  self._proxy_health_timer29=QTimer(self)
  self._proxy_health_timer29.timeout.connect(self.refresh_proxy_status29)
  self._proxy_health_timer29.start(3500)
  self.refresh_proxy_status29()
  self.tabs=QTabWidget();self.tabs.setTabsClosable(True);self.tabs.tabCloseRequested.connect(self.close_tab);self.tabs.currentChanged.connect(self.sync_url);self.tabs.currentChanged.connect(lambda _idx:self.queue_session_save())
  lay.addWidget(self.tabs);self.connect_tabbar13();self.new_tab()
  self.setStyleSheet("QMainWindow,QWidget{background:#eef7fc;color:#365b72} QPushButton,QLineEdit{background:white;border:1px solid #cce1ef;border-radius:8px;padding:7px} QTabBar::tab{padding:9px;background:#d9edf8} QTabBar::tab:selected{background:white}")
  self.setup_ui08(lay,bar)
  self.setup_updater(bar, appdir())
  self.setup_windows_ui12(bar)
  self.setup_chrome14(lay,bar)
  self.restore_startup_session()
  self.setup_desktop15()
  self.setup_productivity16(bar,mac=False)
  self.setup_workspaces17(bar,appdir(),dpapi)
  self.setup_downloads17(bar,appdir(),dpapi)
  self.setup_tabs19()
  self.setup_shell20(bar)
  self.setup_accounts22(appdir(), lambda data: dpapi(data), lambda data: dpapi(data, True))
  self.setup_sync23(appdir(), lambda data: dpapi(data), lambda data: dpapi(data, True))
  self.setup_account_center26(bar)
  self.setup_ui30(bar)
  self.setup_desktop_ui32(lay,bar)
  self.setup_chrome_shell33()
 def refresh_proxy_status29(self):
  status, ready=proxy_status_text(self.proc,self.proxy_port)
  if getattr(self, "_desktop_ui_ready32", False):
   # Chrome toolbar: visible 42px connection indicator, long diagnostic in
   # tooltip. This must not masquerade as a remote Gemini HTTPS check.
   badge = "●" if ready else "○"
   if self.proxy_label.text()!=badge:self.proxy_label.setText(badge)
   self.proxy_label.setToolTip(status+"\n点击重连已保存线路；这里只检测本地代理端口。"
                              "\n远端 Gemini HTTPS 可通过工具中心单独诊断。")
   self.proxy_label.setStyleSheet(
    "QPushButton#GlacierProxyHealth29{background:#f2f7fa;"
    "border:1px solid #d8e3eb;border-radius:16px;"
    "padding:3px;color:"+("#188261" if ready else "#b35043")+";"
    "font-size:17px;min-height:30px;}")
  else:
   if self.proxy_label.text()!=status:self.proxy_label.setText(status)
   self.proxy_label.setStyleSheet(
    "QPushButton#GlacierProxyHealth29 {border:1px solid #dce6ec;"
    "border-radius:9px;background:#f5f9fb;padding:6px 9px;"
    "color:"+("#177956" if ready else "#a04d41")+";}")

 def reconnect_saved_proxy29(self):
  # Deliberately reconnect only the stored DPAPI-encrypted VLESS line.
  # The Qt and Chromium proxies remain locked to 127.0.0.1 at all times:
  # a failed reconnect NEVER falls back to the machine's direct connection.
  state,ready=proxy_status_text(self.proc,self.proxy_port)
  if ready:
   self.statusBar().showMessage("本地 VLESS 代理已在运行",4500)
   return True
  link=get_link(QApplication.instance())
  if not link:return False
  previous=self.proc
  if previous is not None and previous.poll() is None:
   try:
    previous.terminate()
    previous.wait(timeout=5)
   except (OSError,subprocess.TimeoutExpired):
    QMessageBox.warning(self,APP,"旧代理尚未退出。为避免端口冲突，已取消重新连接。")
    self.refresh_proxy_status29()
    return False
  self.proc=None
  self.refresh_proxy_status29()
  try:
   self.proc=proxy_start(link,self.proxy_port)
  except Exception:
   QMessageBox.warning(self,APP,"VLESS 重新连接失败，已继续禁止直连。请检查线路或代理内核。")
   self.refresh_proxy_status29()
   return False
  self.refresh_proxy_status29()
  self.statusBar().showMessage("本地代理端口已就绪；公网连通性尚未验证",5500)
  return True

 def current(self):return self.tabs.currentWidget()
 def new_tab(self):
  v=Page(self);i=self.tabs.addTab(v,"新标签");self.tabs.setCurrentIndex(i)
  self.attach_tab13(v)
  v.titleChanged.connect(lambda _title: self.refresh_tabs14())
  v.iconChanged.connect(lambda _icon: self.refresh_tabs14())
  v.urlChanged.connect(lambda _url,view=v:self.sync_url() if view is self.current() else None)
  v.loadFinished.connect(lambda ok,view=v:self.on_page_loaded(view,ok))
  self.attach_page_security(v)
  v.setHtml(self.home_markup(),QUrl("about:blank"));self.open_startup_home(v)
  self.refresh_tabs14()
  self._workspace_register17(v)
  self.register_account_tab22(v)
  return v
 def close_tab(self,i):
  v=self.tabs.widget(i)
  if v is None:return
  self._workspace_forget17(v)
  self.unregister_account_tab22(v)
  self.remember_recent15(v.url().toString())
  self.remember_closed_tab(v.url().toString())
  self.cleanup_closed13(v)
  self.tabs.removeTab(i);v.deleteLater()
  self.refresh_tabs14()
  if not self.tabs.count():self.new_tab()
 def sync_url(self):
  v=self.current()
  if v:self.address.setText(v.url().toString() if v.url().scheme() in ("http","https") else "")
  self.refresh_bookmark_icon()
 def navigate(self):
  text=self.address.text().strip()
  if not text:return
  if re.match(r"^https?://",text,re.I):url=text
  elif re.match(r"^[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?::\d+)?(?:/\S*)?$",text):url="https://"+text
  else:url=self.search_url(text)
  self.current().setUrl(QUrl(url))
 def closeEvent(self,event):
  self._proxy_health_timer29.stop()
  self.close_satellite_windows()
  self.flush_workspaces17()
  self.flush_downloads17()
  self._autosave_timer15.stop()
  self.session_timer.stop();self.save_session()
  if self.proc and self.proc.poll() is None:self.proc.terminate()
  try:(appdir()/"runtime.json").unlink(missing_ok=True)
  except OSError:pass
  super().closeEvent(event)
def main():
 # Chromium must read the locked SOCKS5 proxy BEFORE QApplication initializes.
 # QtWebEngine must not have an opportunity to start a DIRECT renderer.
 with socket.socket() as s:
  s.bind(("127.0.0.1",0));port=s.getsockname()[1]
 os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]=f"--proxy-server=socks5://127.0.0.1:{port} --disable-quic --force-webrtc-ip-handling-policy=disable_non_proxied_udp"
 app=QApplication(sys.argv);app.setApplicationName(APP)
 splash=show_glacier_splash("Windows v0.20.22")
 link=get_link(app)
 proc=None
 try:proc=proxy_start(link,port)
 except Exception as e:QMessageBox.warning(None,APP,"代理未启动，禁止直连："+str(e))
 # The proxy remains configured even when the core is unavailable: fail closed.
 QNetworkProxy.setApplicationProxy(QNetworkProxy(QNetworkProxy.ProxyType.Socks5Proxy,"127.0.0.1",port))
 try:
  win=Browser(proc,port)
 except Exception as exc:
  splash.close()
  # Avoid exposing proxy links, account entries or saved credentials in dialogs.
  import traceback
  frames=traceback.extract_tb(exc.__traceback__)
  last=frames[-1] if frames else None
  location=(str(Path(last.filename).name)+":"+str(last.lineno)) if last else "startup"
  safe_error=f"{type(exc).__name__} at {location}"
  try:
   (appdir()/"startup-error.txt").write_text(safe_error+"\\n",encoding="utf-8")
  except OSError:pass
  QMessageBox.critical(None,APP,"Windows 浏览器初始化失败：\\n"+safe_error+"\\n请保留 startup-error.txt。")
  if proc and proc.poll() is None:proc.terminate()
  return 1
 # Main window was built hidden; show it only after splash is gone.
 reveal_browser_after_splash(splash, win)
 code=app.exec()
 if proc and proc.poll() is None:proc.terminate()
 return code
if __name__=="__main__":sys.exit(main())
