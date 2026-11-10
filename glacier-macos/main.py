import json, os, re, socket, subprocess, sys, time, uuid
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote, quote_plus
from PySide6.QtCore import QUrl, QTimer
from PySide6.QtNetwork import QNetworkProxy
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
 QLineEdit, QTabWidget, QPushButton, QMessageBox, QInputDialog, QLabel)
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from features import GlacierFeatures
from ui08 import GlacierPrefs
from mac_ui08 import MacGlacierUI08
from ui09 import GlacierUI09
from mac_update import MacUpdateUI
from mac_platform import appdir, dpapi, get_link, core_path, xray_core_path
from ui12 import GlacierUI12
from tabtools13 import GlacierTabTools13
from mac_chrome_adapter import MacChrome14
from mac_desktop15 import MacDesktop15
from glacier_productivity16 import GlacierProductivity16
from glacier_workspaces17 import GlacierWorkspaces17
from glacier_downloads17 import GlacierDownloads17
from glacier_tabs19 import GlacierTabs19
from glacier_shell20 import GlacierShell20
from glacier_accounts22 import GlacierAccounts22
from glacier_sync23 import GlacierSync23
from glacier_account_center26 import GlacierAccountCenter26
from glacier_splash import show_glacier_splash
from mac_proxy_diagnostics import start_capture, latest_hint, classify
from mac_xray_reality import build_xray_reality_config

APP = "Glacier Browser"
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
  elif security=="reality":
   # REALITY generally expects a browser-shaped ClientHello; Xray share links
   # often omit fp even though matching clients default to chrome.
   tls["utls"]={"enabled":True,"fingerprint":"chrome"}
  if g("alpn"): tls["alpn"]=[v.strip() for v in g("alpn").split(",") if v.strip()]
  if security=="reality":
   if not g("pbk"): raise ValueError("REALITY 缺少 pbk")
   tls["reality"]={"enabled":True,"public_key":g("pbk"),"short_id":g("sid")}
  o["tls"]=tls
 transport=g("type","tcp").lower()
 if transport=="ws":
  t={"type":"ws","path":g("path","/")}
  if g("host"):t["headers"]={"Host":g("host")}
  # Xray WebSocket early data must be preserved or the tunnel handshake fails.
  ed=g("ed") or g("maxEarlyData")
  if ed:
   if not ed.isascii() or not ed.isdecimal() or not 0<=int(ed)<=65535:
    raise ValueError("WebSocket early data 参数无效")
   if int(ed):
    t["max_early_data"]=int(ed)
    t["early_data_header_name"]=g("eh") or "Sec-WebSocket-Protocol"
  o["transport"]=t
 elif transport=="grpc":
  o["transport"]={"type":"grpc","service_name":g("serviceName") or g("service_name") or g("path")}
 elif transport in ("httpupgrade","http-upgrade"):
  t={"type":"httpupgrade","path":g("path","/")}
  if g("host"):t["host"]=g("host")
  o["transport"]=t
 elif transport=="http":
  t={"type":"http","path":g("path","/")}
  if g("host"):t["host"]=[g("host")]
  o["transport"]=t
 elif transport not in ("","tcp","raw"):raise ValueError("暂不支持传输类型 "+transport)
 return o


def build_proxy_config(link,port):
 if not 1<=int(port)<=65535:raise ValueError("无效代理端口")
 outbound=parse_node(link)
 # sing-box 1.14 requires an explicit outbound dial-domain resolver.
 # This DNS is used only to resolve the actual node endpoint locally;
 # browser target names continue through the remote VLESS SOCKS5 connection.
 return {
  "log":{"level":"info"},
  "dns":{"servers":[{"type":"local","tag":"system-local"}],"final":"system-local"},
  "inbounds":[{"type":"mixed","tag":"in","listen":"127.0.0.1",
               "listen_port":int(port),"set_system_proxy":False}],
  "outbounds":[outbound],
  "route":{"final":"node","default_domain_resolver":"system-local"}
 }


def select_proxy_core(link,port):
 """Always use official Xray for REALITY; sing-box for other VLESS variants."""
 node=parse_node(link)
 if (node.get("tls") or {}).get("reality",{}).get("enabled"):
  core=xray_core_path()
  if not core:raise RuntimeError("应用包缺少用于 REALITY 的官方 Xray ARM64 内核")
  config=build_xray_reality_config(node,port)
  return core, config, "xray"
 core=core_path()
 if not core:raise RuntimeError("应用包内未找到 Apple Silicon sing-box")
 return core, build_proxy_config(link,port), "sing-box"


def proxy_start(link,port):
 if not link:return None
 core,config,engine=select_proxy_core(link,port)
 # Credential-bearing config remains strictly local in a user-private directory.
 configfile=appdir()/"runtime.json"
 fd=os.open(str(configfile),os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
 with os.fdopen(fd,"w",encoding="utf-8") as handle:json.dump(config,handle)
 flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
 # Xray and sing-box have different validation command forms.
 check_args=([str(core),"run","-test","-config",str(configfile)]
             if engine=="xray" else [str(core),"check","-c",str(configfile)])
 result=subprocess.run(check_args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                       timeout=15,creationflags=flags)
 if result.returncode:
  hint=classify(result.stdout.decode("utf-8",errors="replace")) or (engine+" 配置不受支持")
  raise RuntimeError("VLESS 内核配置校验失败："+hint)
 run_args=([str(core),"run","-config",str(configfile)]
           if engine=="xray" else [str(core),"run","-c",str(configfile)])
 process=subprocess.Popen(run_args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                          creationflags=flags)
 start_capture(process)
 # The process may exit or fail to bind even when config validation succeeds.
 # Do not advertise a working core until its local SOCKS5 port accepts traffic.
 for _ in range(30):
  if process.poll() is not None:
   raise RuntimeError(engine+" 启动后退出："+(latest_hint(process) or "内核初始化失败"))
  try:
   with socket.create_connection(("127.0.0.1",port),timeout=0.3):
    return process
  except OSError:
   time.sleep(0.1)
 process.terminate()
 raise RuntimeError(engine+" 未监听本地代理端口，已禁止直连")
class Page(QWebEngineView):
 def __init__(self,win):
  super().__init__(win)
  self.win=win
  self.setPage(QWebEnginePage(win.profile,self))
 def createWindow(self,typ):return self.win.new_tab()
class Browser(GlacierAccountCenter26, GlacierSync23, GlacierAccounts22, GlacierShell20, GlacierTabs19, GlacierWorkspaces17, GlacierDownloads17, GlacierProductivity16, MacDesktop15, MacChrome14, GlacierTabTools13, GlacierUI12, MacUpdateUI, GlacierUI09, MacGlacierUI08, GlacierFeatures, QMainWindow):
 def __init__(self,process,port):
  super().__init__()
  self.proc=process
  self.proxy_port=port
  self.prefs=GlacierPrefs(appdir()/"settings.json")
  self.setWindowTitle("❄ Glacier Browser · macOS v0.20.14")
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
  self.proxy_label=QLabel("● 本地代理已启动，正在验证外网…" if process else "● 未连接（禁止直连）");bar.addWidget(self.proxy_label)
  self.tabs=QTabWidget();self.tabs.setTabsClosable(True);self.tabs.tabCloseRequested.connect(self.close_tab);self.tabs.currentChanged.connect(self.sync_url);self.tabs.currentChanged.connect(lambda _idx:self.queue_session_save())
  lay.addWidget(self.tabs);self.connect_tabbar13();self.new_tab()
  self.setStyleSheet("QMainWindow,QWidget{background:#eef7fc;color:#365b72} QPushButton,QLineEdit{background:white;border:1px solid #cce1ef;border-radius:8px;padding:7px} QTabBar::tab{padding:9px;background:#d9edf8} QTabBar::tab:selected{background:white}")
  self.setup_ui08(lay,bar)
  self.setup_updater(bar, appdir())
  self.setup_windows_ui12(bar)
  self.setup_chrome14(lay,bar)
  self.restore_startup_session()
  self.setup_desktop15()
  self.setup_productivity16(bar,mac=True)
  self.setup_workspaces17(bar,appdir(),dpapi)
  self.setup_downloads17(bar,appdir(),dpapi)
  self.setup_tabs19()
  self.setup_shell20(bar)
  self.setup_accounts22(appdir(), lambda data: dpapi(data), lambda data: dpapi(data, True))
  self.setup_sync23(appdir(), lambda data: dpapi(data), lambda data: dpapi(data, True))
  self.setup_account_center26(bar)
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
 # Chromium reads QTWEBENGINE_CHROMIUM_FLAGS during Qt startup on macOS.
 # Reserve a per-process local port and set fail-closed proxy flags BEFORE QApplication.
 with socket.socket() as listener:
  listener.bind(("127.0.0.1",0));port=listener.getsockname()[1]
 os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]=f"--proxy-server=socks5://127.0.0.1:{port} --disable-quic --force-webrtc-ip-handling-policy=disable_non_proxied_udp"
 app=QApplication(sys.argv);app.setApplicationName(APP)
 splash=show_glacier_splash("macOS v0.20.14")
 link=get_link(app,parse_node)
 proc=None
 try:proc=proxy_start(link,port)
 except Exception as e:QMessageBox.warning(None,APP,"代理未启动，禁止直连："+str(e))
 # The proxy remains configured even when the core is unavailable: fail closed.
 QNetworkProxy.setApplicationProxy(QNetworkProxy(QNetworkProxy.ProxyType.Socks5Proxy,"127.0.0.1",port))
 try:
  win=Browser(proc,port)
 except Exception as exc:
  splash.close()
  # Expose a startup error instead of a silent macOS .app exit.
  # Never write VLESS credentials or raw traceback values to logs.
  import traceback
  frames=traceback.extract_tb(exc.__traceback__)
  last=frames[-1] if frames else None
  location=(str(Path(last.filename).name)+":"+str(last.lineno)) if last else "startup"
  safe_error=f"{type(exc).__name__} at {location}"
  try:
   (appdir()/"startup-error.txt").write_text(safe_error+"\\n",encoding="utf-8")
  except OSError:pass
  QMessageBox.critical(None,APP,"Mac 浏览器初始化失败：\\n"+safe_error+"\\n请保留 startup-error.txt 以便排查。")
  if proc and proc.poll() is None:proc.terminate()
  return 1
 win.show()
 # Actually probe VLESS HTTPS connectivity on startup, rather than equating
 # sing-box process existence with a working internet connection.
 if proc:
  QTimer.singleShot(1400, win.start_connection_check)
 QTimer.singleShot(1100, lambda: splash.finish(win))
 code=app.exec()
 if proc and proc.poll() is None:proc.terminate()
 return code
if __name__=="__main__":sys.exit(main())
