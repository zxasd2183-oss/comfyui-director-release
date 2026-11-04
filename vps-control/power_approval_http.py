"""Standalone 2FA human-approval page, accessible only through separately
configured HTTPS ingress. Never bind directly to a public interface.

The secret route prevents casual discovery; TOTP and a typed confirmation
are independent of ChatGPT. Request submissions do NOT execute GPU actions.
"""
import hmac
import html
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from power_ops import read_env_file, read_systemd_credential_env
from power_v03 import DB_DEFAULT, approve_request, request_status

MAX_FORM = 2048

def build_handler(path_key: str, seed: str, config_path: str,
                  db_path: str = DB_DEFAULT):
    target = "/approve/" + path_key

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            # The URL contains an authorization factor: never print request paths.
            pass

        def respond(self, code: int, body: str):
            data = body.encode("utf-8")
            self.send_response(code)
            for name, val in (
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", str(len(data))),
                ("Cache-Control", "no-store"),
                ("Referrer-Policy", "no-referrer"),
                ("X-Frame-Options", "DENY"),
                ("X-Content-Type-Options", "nosniff"),
                ("Content-Security-Policy",
                 "default-src 'none'; style-src 'unsafe-inline'; "
                 "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"),
                ("Connection", "close"),
            ):
                self.send_header(name, val)
            self.end_headers()
            self.wfile.write(data)

        def page(self, body: str, status: int = 200):
            self.respond(status, "<!doctype html><html lang='zh-CN'>"
                         "<meta charset='utf-8'><meta name='viewport' "
                         "content='width=device-width,initial-scale=1'>"
                         "<title>Director GPU 二次审批</title>"
                         "<style>body{font:16px system-ui;max-width:640px;"
                         "margin:50px auto;padding:16px;line-height:1.6}"
                         "input{padding:9px;width:100%;box-sizing:border-box}"
                         "button{margin-top:15px;padding:12px 18px}"
                         "p{word-wrap:break-word}</style><body>"
                         "<h2>Director GPU · 独立审批</h2>"
                         "<p>这里不接受 ChatGPT 发送的验证码。"
                         "请在浏览器中用自己手机的动态验证码完成审批。</p>"
                         + body + "</body></html>")

        def valid_route(self):
            p = urlsplit(self.path)
            return hmac.compare_digest(p.path.encode(), target.encode())

        def do_GET(self):
            if not self.valid_route():
                return self.page("<p>Not found</p>", 404)
            parsed = urlsplit(self.path)
            args = parse_qs(parsed.query, keep_blank_values=False)
            rid = args.get("id", [""])[0][:80]
            if not rid:
                return self.page(
                    "<form method='get'><label>输入 ChatGPT 给出的申请编号"
                    "<input name='id' required maxlength='80'></label>"
                    "<button>查询申请</button></form>")
            status = request_status(rid, db_path)
            if status.get("state") != "pending":
                return self.page("<p>申请不存在、已处理或已过期。"
                                 "请在 ChatGPT 中查询状态或重新申请。</p>", 404)
            action = status["action"]
            phrase = "START GPU" if action == "start" else "STOP GPU"
            meaning = "启动 GPU（可能产生租赁费用）" if action == "start" else (
                "关闭 GPU（检查输出已保存到持久化存储）")
            e = html.escape
            return self.page(
                f"<p><strong>申请类型：{e(meaning)}</strong></p>"
                f"<p>编号：<code>{e(rid)}</code></p>"
                f"<p>这一步将实际调用优云智算电源 API。"
                f"VPS 会重新检查实例状态，关机还会再次验证任务队列。</p>"
                f"<form method='post' action='{e(target)}'>"
                f"<input type='hidden' name='id' value='{e(rid)}'>"
                "<label>手机验证器 6 位动态码"
                "<input type='text' name='otp' inputmode='numeric'"
                " autocomplete='one-time-code' pattern='[0-9]{6}'"
                " maxlength='6' required></label>"
                f"<label>输入确认短语 <strong>{e(phrase)}</strong>"
                "<input name='phrase' autocomplete='off' required></label>"
                "<label><input type='checkbox' name='ack' value='yes'"
                " required style='width:auto'>我已确认该操作的费用或数据风险"
                "</label><button type='submit'>批准并提交电源操作</button></form>")

        def do_POST(self):
            if not self.valid_route() or urlsplit(self.path).query:
                return self.page("<p>Not found</p>", 404)
            if self.headers.get("Transfer-Encoding"):
                return self.page("<p>Invalid request</p>", 400)
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                size = 0
            if not 0 < size <= MAX_FORM:
                return self.page("<p>Invalid form size</p>", 413)
            if "application/x-www-form-urlencoded" not in self.headers.get(
                    "Content-Type", "").lower():
                return self.page("<p>Invalid form encoding</p>", 415)
            form = parse_qs(self.rfile.read(size).decode("utf-8", "replace"))
            rid = form.get("id", [""])[0]
            otp = form.get("otp", [""])[0]
            phrase = form.get("phrase", [""])[0]
            if form.get("ack") != ["yes"]:
                return self.page("<p>未确认风险。未执行任何操作。</p>", 400)
            try:
                directory = os.environ.get("CREDENTIALS_DIRECTORY")
                config = (read_systemd_credential_env(config_path, directory)
                          if directory else read_env_file(config_path))
                result = approve_request(rid, otp, phrase, seed, config, db_path)
            except Exception:
                return self.page("<p>审批服务异常。未确认云平台最终状态，"
                                 "请通过只读工具查询。</p>", 500)
            if result.get("ok"):
                return self.page("<p>云平台已接受电源请求。"
                                 "请在 ChatGPT 的只读 Director VPS 插件里"
                                 "重新查询最终电源状态。</p>")
            reason = html.escape(result.get("reason", result.get("result", "unknown")))
            return self.page(f"<p>申请未执行或无法确认：{reason}</p>"
                             "<p>如果是网络异常，不要直接重复提交。"
                             "请先查询 GPU 状态。</p>", 400)

        def do_PUT(self): self.page("<p>Method not allowed</p>", 405)
        def do_DELETE(self): self.page("<p>Method not allowed</p>", 405)

    return Handler


def main():
    cred = os.environ.get("CREDENTIALS_DIRECTORY", "")
    config = os.environ.get("DIRECTOR_POWER_CONFIG",
                            os.path.join(cred, "directorenv"))
    otpfile = os.environ.get("DIRECTOR_POWER_TOTP", os.path.join(cred, "otp"))
    keyfile = os.environ.get("DIRECTOR_POWER_WEB_KEY", os.path.join(cred, "webkey"))
    seed = open(otpfile, encoding="ascii").read().strip()
    key = open(keyfile, encoding="ascii").read().strip()
    if len(key) < 48 or not re.fullmatch(r"[0-9a-f]+", key):
        raise SystemExit("Invalid secret approval route")
    db = os.environ.get("DIRECTOR_POWER_DB", DB_DEFAULT)
    srv = ThreadingHTTPServer(("127.0.0.1", 8893),
                              build_handler(key, seed, config, db))
    srv.daemon_threads = True
    print("Director independent OTP approval: loopback-only port 8893", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
