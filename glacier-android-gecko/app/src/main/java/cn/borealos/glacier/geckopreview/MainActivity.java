package cn.borealos.glacier.geckopreview;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.mozilla.geckoview.GeckoResult;
import org.mozilla.geckoview.GeckoRuntimeSettings;
import org.mozilla.geckoview.GeckoRuntime;
import org.mozilla.geckoview.GeckoSession;
import org.mozilla.geckoview.GeckoSessionSettings;
import org.mozilla.geckoview.GeckoView;

import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Glacier GeckoView network experiment v0.1.2.
 * A REAL, app-bundled VLESS core may feed Gecko through a loopback SOCKS5 proxy.
 * No credential vault, automatic login or cloud sync exists yet.
 *
 * Profile isolation is provided by GeckoSessionSettings.contextId, NOT UI only.
 * Each tab retains the contextId with which it was created for its entire life.
 */
public final class MainActivity extends Activity {
    private static final String PRIVATE = "private";
    private static final String WORK = "work";
    private static final int INK = Color.rgb(41, 57, 70);
    private static final int MUTED = Color.rgb(110, 128, 140);
    private static final int ICE = Color.rgb(235, 245, 251);
    private static final String START_URL = "https://example.com/";

    // GeckoRuntime is process-scoped, and must only be created once.
    private static GeckoRuntime runtime;
    private static boolean proxyMode = false;

    private final List<Tab> tabs = new ArrayList<>();
    private GeckoView web;
    private EditText address;
    private TextView identity;
    private TextView tabCounter;
    private TextView engineLabel;
    private Button backButton;
    private Button forwardButton;
    private Tab active;
    private String selectedProfile = PRIVATE;

    private static class Tab {
        final GeckoSession session;
        final String profile;
        String url = START_URL;
        String title = "新标签页";
        boolean canBack = false;
        boolean canForward = false;

        Tab(GeckoSession session, String profile) {
            this.session = session;
            this.profile = profile;
        }
    }

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(Color.rgb(238, 244, 248));
        getWindow().setNavigationBarColor(Color.rgb(248, 251, 253));
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR
                | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        // Do not let Gecko create network requests until the user has chosen
        // an explicit mode and its runtime preferences are in place.
        if (runtime == null) {
            NativeProxy.deleteStaleFiles(this);
            showNetworkGate();
        } else {
            buildChrome();
            openTab(PRIVATE, START_URL);
        }
    }

    private int dp(float size) {
        return Math.round(getResources().getDisplayMetrics().density * size);
    }

    private GradientDrawable surface(int color, int radius) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(color);
        shape.setCornerRadius(dp(radius));
        return shape;
    }

    private Button button(String text) {
        Button b = new Button(this);
        b.setText(text);
        b.setAllCaps(false);
        b.setTextSize(17);
        b.setTextColor(INK);
        b.setMinWidth(0);
        b.setMinimumWidth(0);
        b.setPadding(dp(7), 0, dp(7), 0);
        b.setBackground(surface(ICE, 12));
        return b;
    }

    private LinearLayout horizontal() {
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.HORIZONTAL);
        l.setGravity(Gravity.CENTER_VERTICAL);
        l.setPadding(dp(10), dp(6), dp(10), dp(6));
        return l;
    }

    private void buildChrome() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.WHITE);
        setContentView(root);

        LinearLayout header = horizontal();
        header.setBackgroundColor(Color.rgb(247, 250, 252));

        TextView brand = new TextView(this);
        brand.setText("❄  Glacier");
        brand.setTextSize(19);
        brand.setTypeface(null, Typeface.BOLD);
        brand.setTextColor(Color.rgb(55, 116, 149));
        header.addView(brand, new LinearLayout.LayoutParams(0, dp(40), 1));

        identity = new TextView(this);
        identity.setTextSize(12);
        identity.setTextColor(INK);
        identity.setGravity(Gravity.CENTER);
        identity.setPadding(dp(11), dp(7), dp(11), dp(7));
        identity.setBackground(surface(ICE, 12));
        identity.setOnClickListener(v -> chooseProfile());
        header.addView(identity);
        root.addView(header);

        LinearLayout nav = horizontal();
        backButton = button("‹");
        backButton.setContentDescription("后退");
        backButton.setOnClickListener(v -> {
            if (active != null && active.canBack) active.session.goBack();
        });
        nav.addView(backButton, new LinearLayout.LayoutParams(dp(38), dp(43)));
        forwardButton = button("›");
        forwardButton.setContentDescription("前进");
        forwardButton.setOnClickListener(v -> {
            if (active != null && active.canForward) active.session.goForward();
        });
        LinearLayout.LayoutParams front = new LinearLayout.LayoutParams(dp(38), dp(43));
        front.setMargins(dp(4), 0, dp(7), 0);
        nav.addView(forwardButton, front);

        address = new EditText(this);
        address.setSingleLine(true);
        address.setTextSize(13);
        address.setTextColor(INK);
        address.setHintTextColor(MUTED);
        address.setHint("搜索或输入网址");
        address.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        address.setSelectAllOnFocus(true);
        address.setPadding(dp(12), 0, dp(12), 0);
        address.setBackground(surface(Color.rgb(242, 246, 249), 14));
        address.setImeOptions(android.view.inputmethod.EditorInfo.IME_ACTION_GO);
        address.setOnEditorActionListener((v, actionId, event) -> {
            navigate(address.getText().toString());
            return true;
        });
        nav.addView(address, new LinearLayout.LayoutParams(0, dp(43), 1));

        Button go = button("→");
        go.setContentDescription("打开网址");
        go.setOnClickListener(v -> navigate(address.getText().toString()));
        LinearLayout.LayoutParams end = new LinearLayout.LayoutParams(dp(40), dp(43));
        end.setMargins(dp(6), 0, 0, 0);
        nav.addView(go, end);
        root.addView(nav);

        // Testing banner makes the network security limitation explicit.
        engineLabel = new TextView(this);
        engineLabel.setText(proxyMode
                ? "VLESS → 本地 SOCKS5 → GeckoView · 实验连接"
                : "直连网络 · 已明确选择（无代理保护）");
        engineLabel.setTextColor(Color.rgb(111, 91, 49));
        engineLabel.setTextSize(11);
        engineLabel.setGravity(Gravity.CENTER);
        engineLabel.setBackgroundColor(Color.rgb(255, 247, 222));
        engineLabel.setPadding(dp(4), dp(4), dp(4), dp(4));
        root.addView(engineLabel);

        web = new GeckoView(this);
        root.addView(web, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1));

        LinearLayout bottom = horizontal();
        bottom.setBackgroundColor(Color.rgb(247, 250, 252));

        Button refresh = button("⟳");
        refresh.setContentDescription("刷新");
        refresh.setOnClickListener(v -> {
            if (active != null) active.session.reload();
        });
        bottom.addView(refresh, new LinearLayout.LayoutParams(dp(52), dp(44)));

        TextView space = new TextView(this);
        space.setText("  内核兼容性实验  ");
        space.setGravity(Gravity.CENTER);
        space.setTextColor(MUTED);
        space.setTextSize(12);
        bottom.addView(space, new LinearLayout.LayoutParams(0, dp(44), 1));

        Button plus = button("+");
        plus.setContentDescription("新建标签页");
        plus.setOnClickListener(v -> openTab(selectedProfile, START_URL));
        bottom.addView(plus, new LinearLayout.LayoutParams(dp(43), dp(44)));

        tabCounter = new TextView(this);
        tabCounter.setTextSize(15);
        tabCounter.setGravity(Gravity.CENTER);
        tabCounter.setTextColor(INK);
        tabCounter.setBackground(surface(ICE, 12));
        tabCounter.setOnClickListener(v -> showTabs());
        LinearLayout.LayoutParams countParams = new LinearLayout.LayoutParams(dp(43), dp(44));
        countParams.setMargins(dp(8), 0, 0, 0);
        bottom.addView(tabCounter, countParams);

        Button menu = button("⋮");
        menu.setContentDescription("内核测试菜单");
        menu.setOnClickListener(v -> new AlertDialog.Builder(this)
                .setTitle("Glacier · GeckoView 内核")
                .setItems(new String[]{
                    "打开 Gecko 内核信息", "打开 ChatGPT", "打开 GitHub",
                    "切换账号空间", "网络连接信息", "测试说明"
                }, (dialog, index) -> {
                    if (index == 0) navigate("about:buildconfig");
                    if (index == 1) navigate("https://chatgpt.com/");
                    if (index == 2) navigate("https://github.com/");
                    if (index == 3) chooseProfile();
                    if (index == 4) showNetworkStatus();
                    if (index == 5) showLabWarning();
                }).show());
        LinearLayout.LayoutParams dots = new LinearLayout.LayoutParams(dp(43), dp(44));
        dots.setMargins(dp(8), 0, 0, 0);
        bottom.addView(menu, dots);
        root.addView(bottom);
        updateChrome();
    }

    private GeckoSession createSession(final String profile) {
        GeckoSessionSettings settings = new GeckoSessionSettings.Builder()
                .contextId("glacier-" + profile)
                .usePrivateMode(false)
                .build();
        GeckoSession session = new GeckoSession(settings);
        session.setContentDelegate(new GeckoSession.ContentDelegate() {});
        session.setNavigationDelegate(new GeckoSession.NavigationDelegate() {
            @Override
            public void onLocationChange(GeckoSession source, String url,
                                         List<GeckoSession.PermissionDelegate.ContentPermission> perms,
                                         Boolean userGesture) {
                Tab t = findBySession(source);
                if (t != null && url != null) {
                    t.url = url;
                    t.title = url.length() > 40 ? url.substring(0, 40) + "…" : url;
                    if (t == active) updateChrome();
                }
            }

            @Override
            public void onCanGoBack(GeckoSession source, boolean value) {
                Tab t = findBySession(source);
                if (t != null) {
                    t.canBack = value;
                    if (t == active) updateChrome();
                }
            }

            @Override
            public void onCanGoForward(GeckoSession source, boolean value) {
                Tab t = findBySession(source);
                if (t != null) {
                    t.canForward = value;
                    if (t == active) updateChrome();
                }
            }

            @Override
            public GeckoResult<GeckoSession> onNewSession(GeckoSession source, String url) {
                // Popup pages inherit the source profile, never cross identities.
                Tab parent = findBySession(source);
                String owner = parent == null ? profile : parent.profile;
                Tab child = createTab(owner);
                switchTo(child);
                return GeckoResult.fromValue(child.session);
            }
        });
        session.open(runtime);
        return session;
    }

    private Tab createTab(String profile) {
        Tab t = new Tab(createSession(profile), profile);
        tabs.add(t);
        return t;
    }

    private Tab findBySession(GeckoSession session) {
        for (Tab t : tabs) {
            if (t.session == session) return t;
        }
        return null;
    }

    private void openTab(String profile, String url) {
        Tab t = createTab(profile);
        switchTo(t);
        t.session.loadUri(url);
    }

    private void switchTo(Tab next) {
        if (next == active) return;
        if (web.getSession() != null) web.releaseSession();
        active = next;
        selectedProfile = next.profile;
        web.setSession(next.session);
        updateChrome();
    }

    private void updateChrome() {
        if (address == null) return;
        identity.setText(WORK.equals(selectedProfile) ? "工作空间  ▾" : "私人空间  ▾");
        tabCounter.setText(Integer.toString(tabs.size()));
        if (engineLabel != null) {
            if (proxyMode) {
                boolean connected = NativeProxy.alive();
                engineLabel.setText(connected
                        ? "VLESS 本地代理运行中 · 可测试出口 IP"
                        : "代理已断开 · Gecko SOCKS 不会自动改为直连");
            }
        }
        if (active != null) {
            if (!address.hasFocus()) address.setText(active.url);
            backButton.setEnabled(active.canBack);
            forwardButton.setEnabled(active.canForward);
        } else {
            backButton.setEnabled(false);
            forwardButton.setEnabled(false);
        }
    }

    private void chooseProfile() {
        new AlertDialog.Builder(this)
                .setTitle("选择独立账号空间")
                .setItems(new String[]{"私人空间 · 独立 Cookie", "工作空间 · 独立 Cookie"},
                        (d, which) -> {
                            String newProfile = which == 0 ? PRIVATE : WORK;
                            Tab target = null;
                            for (int i = tabs.size() - 1; i >= 0; i--) {
                                if (tabs.get(i).profile.equals(newProfile)) {
                                    target = tabs.get(i);
                                    break;
                                }
                            }
                            if (target == null) {
                                openTab(newProfile, START_URL);
                            } else {
                                switchTo(target);
                            }
                        })
                .show();
    }

    private void showTabs() {
        if (tabs.isEmpty()) return;
        String[] choices = new String[tabs.size() + 2];
        for (int i = 0; i < tabs.size(); i++) {
            Tab t = tabs.get(i);
            choices[i] = (t == active ? "● " : "○ ")
                    + (WORK.equals(t.profile) ? "工作" : "私人")
                    + " · " + t.title;
        }
        choices[tabs.size()] = "＋ 新建标签页";
        choices[tabs.size() + 1] = "× 关闭当前标签页";
        new AlertDialog.Builder(this).setTitle("标签页")
                .setItems(choices, (d, which) -> {
                    if (which < tabs.size()) {
                        switchTo(tabs.get(which));
                    } else if (which == tabs.size()) {
                        openTab(selectedProfile, START_URL);
                    } else {
                        closeActiveTab();
                    }
                }).show();
    }

    private void closeActiveTab() {
        if (active == null) return;
        Tab closing = active;
        if (web.getSession() != null) web.releaseSession();
        active = null;
        tabs.remove(closing);
        closing.session.close();
        if (tabs.isEmpty()) {
            openTab(selectedProfile, START_URL);
        } else {
            switchTo(tabs.get(tabs.size() - 1));
        }
    }

    private void navigate(String raw) {
        if (active == null) return;
        String q = raw == null ? "" : raw.trim();
        if (q.isEmpty()) return;
        String url;
        if (q.startsWith("https://") || q.startsWith("about:")) {
            url = q;
        } else if (q.startsWith("http://")) {
            // The app itself prohibits cleartext in the manifest. Do not
            // silently downgrade or promise insecure HTTP compatibility.
            url = "https://" + q.substring("http://".length());
        } else if (!q.contains(" ") && (q.contains(".") || q.equals("localhost"))) {
            url = "https://" + q;
        } else {
            try {
                url = "https://www.google.com/search?q="
                        + URLEncoder.encode(q, "UTF-8");
            } catch (Exception e) {
                return;
            }
        }
        active.session.loadUri(url);
        address.clearFocus();
        InputMethodManager imm =
                (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
        if (imm != null) imm.hideSoftInputFromWindow(address.getWindowToken(), 0);
    }

    /**
     * Safety gate. The browser never implicitly chooses DIRECT when node
     * configuration fails. Starting a DIRECT test requires a deliberate tap.
     */
    private void showNetworkGate() {
        new AlertDialog.Builder(this)
                .setTitle("Glacier · 选择网络测试方式")
                .setMessage("内核测试版支持导入 VLESS（TLS/REALITY），经内置 sing-box 和本地 SOCKS5 访问网页。\n\n也可以明确选择直连模式进行基础对照。\n\nVLESS 配置失败时不会自动切换直连。")
                .setCancelable(false)
                .setPositiveButton("导入 VLESS 节点", (d, w) -> askForNode())
                .setNegativeButton("明确使用直连", (d, w) -> startDirectMode())
                .show();
    }

    private void askForNode() {
        final EditText input = new EditText(this);
        input.setSingleLine(false);
        input.setLines(3);
        input.setTextSize(14);
        input.setHint("粘贴 vless://UUID@服务器:端口?... ");
        input.setInputType(InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        LinearLayout wrapper = new LinearLayout(this);
        wrapper.setPadding(dp(20), dp(8), dp(20), dp(8));
        wrapper.addView(input, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
        new AlertDialog.Builder(this)
                .setTitle("导入 VLESS · 仅本次运行")
                .setMessage("支持 TLS / REALITY、TCP / WS。节点链接不会上传或写入日志；代理运行时会创建应用私有临时配置。")
                .setView(wrapper)
                .setNegativeButton("返回", (d, w) -> showNetworkGate())
                .setPositiveButton("启动代理", (d, w) -> {
                    String value = input.getText().toString().trim();
                    input.setText("");
                    startVlessMode(value);
                })
                .setCancelable(false)
                .show();
    }

    private void startDirectMode() {
        try {
            proxyMode = false;
            String yaml = NativeProxy.prepareGecko(this, false);
            initializeEngine(yaml);
        } catch (Exception e) {
            showNetworkError("无法初始化直连 GeckoView 内核");
        }
    }

    private void startVlessMode(String value) {
        final VlessLink node;
        try {
            node = VlessLink.parse(value);
        } catch (Exception e) {
            showNetworkError(e.getMessage());
            return;
        }
        android.app.ProgressDialog loading = android.app.ProgressDialog.show(this,
                "Glacier 网络实验", "正在初始化 sing-box 核心和 SOCKS5 代理...",
                true, false);
        new Thread(() -> {
            try {
                NativeProxy.start(getApplicationContext(), node);
                String yaml = NativeProxy.prepareGecko(getApplicationContext(), true);
                runOnUiThread(() -> {
                    loading.dismiss();
                    proxyMode = true;
                    initializeEngine(yaml);
                });
            } catch (Exception e) {
                NativeProxy.stop();
                runOnUiThread(() -> {
                    loading.dismiss();
                    // Errors must not include node UUID, host, keys, or URL.
                    String detail = e.getMessage();
                    if (detail == null || detail.length() > 120) detail = "代理启动失败";
                    showNetworkError(detail);
                });
            }
        }, "glacier-vless-start").start();
    }

    private void initializeEngine(String configPath) {
        try {
            if (runtime == null) {
                GeckoRuntimeSettings settings = new GeckoRuntimeSettings.Builder()
                        .configFilePath(configPath)
                        .build();
                runtime = GeckoRuntime.create(getApplicationContext(), settings);
            }
            buildChrome();
            openTab(PRIVATE, START_URL);
        } catch (Exception ex) {
            NativeProxy.stop();
            showNetworkError("GeckoView 无法使用当前网络配置初始化");
        }
    }

    private void showNetworkError(String message) {
        new AlertDialog.Builder(this)
                .setTitle("网络未连接")
                .setMessage(message + "\n\n网页未启动，不会自动回退到直连。")
                .setCancelable(false)
                .setPositiveButton("重新配置", (d, w) -> showNetworkGate())
                .show();
    }

    private void showNetworkStatus() {
        new AlertDialog.Builder(this)
                .setTitle("Glacier 网络诊断")
                .setMessage(proxyMode
                        ? ("内置 sing-box: " + (NativeProxy.alive() ? "本地 SOCKS5 正在运行" : "已断开")
                           + "\n网页代理：127.0.0.1:" + NativeProxy.PORT
                           + "\nDNS：SOCKS5 远端解析"
                           + "\nWebRTC：暂时关闭（降低 IP 泄漏风险）"
                           + "\n\n本地 SOCKS5 启动不代表远端 VLESS 已验证。请在网页里测试出口 IP、断网后是否失败以及 DNS。")
                        : "当前是主动选择的直连测试模式，没有 VLESS 保护。")
                .setPositiveButton("知道了", null).show();
    }

    private void showLabWarning() {
        new AlertDialog.Builder(this)
                .setTitle("这是内核实验版")
                .setMessage("已集成 GeckoView 真正的网页内核，可比较网页显示、导航、账号空间隔离和兼容性。"
                        + "\n\n已接入内置 VLESS/本地 SOCKS5 实验网络；该模式不是 Android 系统级 VPN，也未经过独立审计。"
                        + "\n\n目前尚未提供账号保险箱、验证码 API、云同步、完整权限管理。"
                        + "\n\n直连模式仅用于对照测试；VLESS 模式必须验证真实出口。请勿输入关键账号。")
                .setPositiveButton("知道了", null)
                .show();
    }

    @Override
    public void onBackPressed() {
        if (active != null && active.canBack) {
            active.session.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        if (isFinishing()) {
            if (web != null && web.getSession() != null) web.releaseSession();
            for (Tab t : tabs) t.session.close();
            tabs.clear();
        }
        super.onDestroy();
        if (isFinishing()) {
            NativeProxy.stop();
            // GeckoRuntime is single-instance per process. For experimental
            // proxy-vs-direct comparisons, a clean restart is essential.
            if (runtime != null) runtime.shutdown();
            runtime = null;
            android.os.Process.killProcess(android.os.Process.myPid());
        }
    }
}
