package cn.borealos.glacier.geckopreview;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
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
import android.widget.CheckBox;
import android.widget.FrameLayout;
import android.widget.GridLayout;
import android.widget.ScrollView;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.mozilla.geckoview.GeckoResult;
import org.mozilla.geckoview.GeckoRuntimeSettings;
import org.mozilla.geckoview.GeckoRuntime;
import org.mozilla.geckoview.GeckoSession;
import org.mozilla.geckoview.GeckoSessionSettings;
import org.mozilla.geckoview.GeckoView;
import org.mozilla.geckoview.WebResponse;

import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Glacier Android mobile browser v0.2.0: M02 Chrome-inspired light UI.
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
    private static final int PALE = Color.rgb(247, 251, 254);
    private static final int GLACIER_BLUE = Color.rgb(62, 145, 187);
    private static final int HAIRLINE = Color.rgb(222, 233, 241);
    private static final String START_URL = "https://example.com/";

    // GeckoRuntime is process-scoped, and must only be created once.
    private static GeckoRuntime runtime;
    private static boolean proxyMode = false;

    private final List<Tab> tabs = new ArrayList<>();
    private GeckoView web;
    private BrowserTransfers transfers;
    private EditText address;
    private TextView identity;
    private TextView tabCounter;
    private TextView engineLabel;
    private View newTabPage;
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
        transfers = new BrowserTransfers(this);
        getWindow().setStatusBarColor(Color.rgb(238, 244, 248));
        getWindow().setNavigationBarColor(Color.rgb(248, 251, 253));
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR
                | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        // Do not let Gecko create network requests until the user has chosen
        // an explicit mode and its runtime preferences are in place.
        if (runtime == null) {
            NativeProxy.deleteStaleFiles(this);
            // An intentionally non-working SOCKS5 port is CI's fail-closed
            // sentinel. Only a debug APK and an explicit adb launch can enter
            // this path. Never open a direct runtime when it is requested.
            String ciNetwork = getIntent().getStringExtra("glacier.ci.network");
            if (debugBuild() && ("offline-socks".equals(ciNetwork)
                    || "mock-socks".equals(ciNetwork))) {
                // Synthetic CI-only SOCKS service. There is never a DIRECT
                // fallback or a real account/node in these test modes.
                proxyMode = true;
                try {
                    String config = NativeProxy.prepareGecko(this, true);
                    android.util.Log.i("GlacierSmoke", "PROXY_TEST="
                            + ("mock-socks".equals(ciNetwork)
                            ? "MOCK_SOCKS_CONFIGURED" : "OFFLINE_SOCKS_CONFIGURED"));
                    initializeEngine(config);
                } catch (Exception e) {
                    showNetworkError("代理测试初始化失败");
                }
            } else if (SavedVlessNode.autoConnectEnabled(this)) {
                // Start the proxy on a worker before creating GeckoRuntime.
                // A failed restoration never starts the DIRECT runtime.
                startSavedVlessMode();
            } else {
                showNetworkGate();
            }
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

    private GradientDrawable surfaceBorder(int color, int radius, int border) {
        GradientDrawable shape = surface(color, radius);
        shape.setStroke(dp(1), border);
        return shape;
    }

    private Button button(String text) {
        Button b = new Button(this);
        b.setText(text);
        b.setAllCaps(false);
        b.setTextSize(20);
        b.setTypeface(Typeface.create("sans-serif", Typeface.NORMAL));
        b.setTextColor(INK);
        b.setGravity(Gravity.CENTER);
        b.setMinWidth(0);
        b.setMinimumWidth(0);
        b.setMinHeight(0);
        b.setMinimumHeight(0);
        b.setPadding(0, 0, 0, 0);
        b.setBackground(surface(PALE, 15));
        b.setElevation(0);
        return b;
    }

    private LinearLayout horizontal() {
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.HORIZONTAL);
        l.setGravity(Gravity.CENTER_VERTICAL);
        l.setPadding(dp(12), dp(5), dp(12), dp(5));
        return l;
    }

    private void buildChrome() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.WHITE);
        if (android.os.Build.VERSION.SDK_INT >= 35) {
            root.setOnApplyWindowInsetsListener((view, insets) -> {
                android.graphics.Insets bars = insets.getInsets(
                        android.view.WindowInsets.Type.systemBars());
                view.setPadding(bars.left, bars.top, bars.right, bars.bottom);
                if (debugBuild()) {
                    android.util.Log.i("GlacierSmoke",
                            "SYSTEM_BAR_INSETS top=" + bars.top
                                    + " bottom=" + bars.bottom);
                }
                return insets;
            });
        }
        setContentView(root);

        // Android Chrome-style compact toolbar: no persistent logo, profile
        // badge, diagnostic banner, or second row of navigation buttons.
        LinearLayout toolbar = horizontal();
        toolbar.setPadding(dp(7), dp(6), dp(7), dp(6));
        toolbar.setBackgroundColor(PALE);

        Button home = button("⌂");
        home.setTextSize(22);
        home.setContentDescription("主页");
        home.setOnClickListener(v -> showNewTabInCurrentTab());
        toolbar.addView(home, new LinearLayout.LayoutParams(dp(39), dp(47)));

        LinearLayout omnibox = new LinearLayout(this);
        omnibox.setOrientation(LinearLayout.HORIZONTAL);
        omnibox.setGravity(Gravity.CENTER_VERTICAL);
        omnibox.setBackground(surface(Color.rgb(235, 243, 250), 25));

        TextView siteIcon = new TextView(this);
        siteIcon.setText("⌕");
        siteIcon.setTextSize(25);
        siteIcon.setTextColor(MUTED);
        siteIcon.setGravity(Gravity.CENTER);
        siteIcon.setContentDescription("搜索");
        omnibox.addView(siteIcon, new LinearLayout.LayoutParams(dp(38), dp(47)));

        address = new EditText(this);
        address.setSingleLine(true);
        address.setTextSize(14);
        address.setTextColor(INK);
        address.setHintTextColor(MUTED);
        address.setHint("搜索或输入网址");
        address.setContentDescription("Glacier 地址栏");
        address.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        address.setSelectAllOnFocus(true);
        address.setPadding(0, 0, dp(9), 0);
        address.setBackgroundColor(Color.TRANSPARENT);
        address.setImeOptions(android.view.inputmethod.EditorInfo.IME_ACTION_GO);
        address.setOnEditorActionListener((v, actionId, event) -> {
            navigate(address.getText().toString());
            return true;
        });
        omnibox.addView(address, new LinearLayout.LayoutParams(0, dp(47), 1));

        LinearLayout.LayoutParams addressParams =
                new LinearLayout.LayoutParams(0, dp(47), 1);
        addressParams.setMargins(dp(4), 0, dp(8), 0);
        toolbar.addView(omnibox, addressParams);

        tabCounter = new TextView(this);
        tabCounter.setTextSize(14);
        tabCounter.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        tabCounter.setGravity(Gravity.CENTER);
        tabCounter.setTextColor(INK);
        tabCounter.setContentDescription("标签页");
        tabCounter.setBackground(surfaceBorder(Color.WHITE, 10, INK));
        tabCounter.setOnClickListener(v -> showTabs());
        toolbar.addView(tabCounter, new LinearLayout.LayoutParams(dp(34), dp(34)));

        Button menu = button("⋮");
        menu.setTextSize(23);
        menu.setContentDescription("更多选项");
        menu.setOnClickListener(v -> showBrowserMenu());
        LinearLayout.LayoutParams menuParams =
                new LinearLayout.LayoutParams(dp(36), dp(47));
        menuParams.setMargins(dp(5), 0, 0, 0);
        toolbar.addView(menu, menuParams);
        root.addView(toolbar);

        // Keep existing navigation delegates working; backward/forward/reload
        // live in the overflow menu and Android system back gesture.
        backButton = button("‹");
        forwardButton = button("›");
        identity = new TextView(this);
        engineLabel = null;

        FrameLayout viewport = new FrameLayout(this);
        web = new GeckoView(this);
        web.setBackgroundColor(Color.WHITE);
        viewport.addView(web, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));

        newTabPage = createNewTabPage();
        viewport.addView(newTabPage, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));
        root.addView(viewport, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1));

        View separator = new View(this);
        separator.setBackgroundColor(HAIRLINE);
        root.addView(separator, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(1)));
        updateChrome();
    }

    private View createNewTabPage() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(Color.WHITE);
        LinearLayout page = new LinearLayout(this);
        page.setGravity(Gravity.CENTER_HORIZONTAL);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setPadding(dp(22), dp(68), dp(22), dp(30));

        TextView symbol = new TextView(this);
        symbol.setText("❄");
        symbol.setTextSize(35);
        symbol.setGravity(Gravity.CENTER);
        symbol.setTextColor(GLACIER_BLUE);
        page.addView(symbol, new LinearLayout.LayoutParams(dp(65), dp(65)));

        TextView brand = new TextView(this);
        brand.setText("Glacier");
        brand.setTextSize(30);
        brand.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        brand.setTextColor(INK);
        brand.setGravity(Gravity.CENTER);
        page.addView(brand);

        TextView search = new TextView(this);
        search.setText("⌕   搜索或输入网址");
        search.setTextSize(16);
        search.setTextColor(MUTED);
        search.setGravity(Gravity.CENTER_VERTICAL);
        search.setPadding(dp(22), 0, dp(15), 0);
        search.setBackground(surfaceBorder(PALE, 28, HAIRLINE));
        search.setContentDescription("新标签页搜索");
        search.setOnClickListener(v -> {
            address.requestFocus();
            InputMethodManager keyboard = (InputMethodManager)
                    getSystemService(Context.INPUT_METHOD_SERVICE);
            if (keyboard != null) keyboard.showSoftInput(address,
                    InputMethodManager.SHOW_IMPLICIT);
        });
        LinearLayout.LayoutParams searchParams =
                new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(56));
        searchParams.setMargins(0, dp(32), 0, dp(30));
        page.addView(search, searchParams);

        TextView caption = new TextView(this);
        caption.setText("常用网站");
        caption.setTextSize(14);
        caption.setTextColor(MUTED);
        caption.setGravity(Gravity.START);
        page.addView(caption, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(40)));

        LinearLayout shortcuts = horizontal();
        shortcuts.setPadding(0, 0, 0, 0);
        String[] labels = {"Google", "GitHub", "ChatGPT"};
        String[] hosts = {"google.com", "github.com", "chatgpt.com"};
        String[] glyphs = {"G", "⌘", "✦"};
        for (int i = 0; i < labels.length; i++) {
            final String url = "https://" + hosts[i] + "/";
            LinearLayout item = new LinearLayout(this);
            item.setGravity(Gravity.CENTER_HORIZONTAL);
            item.setOrientation(LinearLayout.VERTICAL);

            TextView icon = new TextView(this);
            icon.setText(glyphs[i]);
            icon.setTextSize(24);
            icon.setTextColor(GLACIER_BLUE);
            icon.setGravity(Gravity.CENTER);
            icon.setBackground(surface(ICE, 26));
            item.addView(icon, new LinearLayout.LayoutParams(dp(53), dp(53)));

            TextView label = new TextView(this);
            label.setText(labels[i]);
            label.setTextSize(12);
            label.setGravity(Gravity.CENTER);
            label.setTextColor(INK);
            LinearLayout.LayoutParams lp =
                    new LinearLayout.LayoutParams(
                            LinearLayout.LayoutParams.MATCH_PARENT, dp(28));
            item.addView(label, lp);
            item.setContentDescription("打开 " + labels[i]);
            item.setOnClickListener(v -> navigate(url));
            shortcuts.addView(item, new LinearLayout.LayoutParams(0, dp(95), 1));
        }
        page.addView(shortcuts, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));

        scroll.addView(page, new ScrollView.LayoutParams(
                ScrollView.LayoutParams.MATCH_PARENT,
                ScrollView.LayoutParams.WRAP_CONTENT));
        return scroll;
    }

    private void showNewTabInCurrentTab() {
        if (active == null) return;
        active.session.loadUri("about:blank");
        active.url = "about:blank";
        active.title = "新标签页";
        updateChrome();
    }

    private boolean debugBuild() {
        return (getApplicationInfo().flags
                & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0;
    }

    private void showBrowserMenu() {
        final List<String> actions = new ArrayList<>();
        actions.add("新建标签页");
        actions.add("刷新");
        actions.add("后退");
        actions.add("前进");
        actions.add("切换账号空间");
        actions.add("网络连接信息");
        actions.add("打开 ChatGPT");
        actions.add("打开 GitHub");
        actions.add("打开 Gecko 内核信息");
        actions.add("测试说明");
        if (debugBuild() && !proxyMode) {
            actions.add("隔离自测：私人写入");
            actions.add("隔离自测：工作检查");
            actions.add("隔离自测：私人复查");
            actions.add("传输自测：打开测试页面");
        }
        new AlertDialog.Builder(this)
                .setTitle("Glacier · 更多选项")
                .setItems(actions.toArray(new String[0]), (dialog, index) -> {
                    String item = actions.get(index);
                    if ("新建标签页".equals(item)) {
                        openTab(selectedProfile, "about:blank");
                    } else if ("刷新".equals(item)) {
                        if (active != null) active.session.reload();
                    } else if ("后退".equals(item)) {
                        if (active != null && active.canBack) active.session.goBack();
                    } else if ("前进".equals(item)) {
                        if (active != null && active.canForward) active.session.goForward();
                    } else if ("切换账号空间".equals(item)) {
                        chooseProfile();
                    } else if ("网络连接信息".equals(item)) {
                        showNetworkStatus();
                    } else if ("打开 ChatGPT".equals(item)) {
                        navigate("https://chatgpt.com/");
                    } else if ("打开 GitHub".equals(item)) {
                        navigate("https://github.com/");
                    } else if ("打开 Gecko 内核信息".equals(item)) {
                        navigate("about:buildconfig");
                    } else if ("测试说明".equals(item)) {
                        showLabWarning();
                    } else if ("隔离自测：私人写入".equals(item)
                            || "隔离自测：工作检查".equals(item)
                            || "隔离自测：私人复查".equals(item)) {
                        // CI fixture never appears in the production menu.
                        String phase = item.contains("私人写入") ? "seed"
                                : item.contains("工作检查") ? "work" : "return";
                        if (debugBuild() && !proxyMode && active != null)
                            active.session.loadUri("http://127.0.0.1:18765/profile?phase=" + phase);
                    } else if ("传输自测：打开测试页面".equals(item)
                            && debugBuild() && !proxyMode && active != null) {
                        active.session.loadUri("http://127.0.0.1:18765/transfer");
                    }
                }).show();
    }

    private GeckoSession createSession(final String profile) {
        GeckoSessionSettings settings = new GeckoSessionSettings.Builder()
                .contextId("glacier-" + profile)
                .usePrivateMode(false)
                .build();
        GeckoSession session = new GeckoSession(settings);
        session.setContentDelegate(new GeckoSession.ContentDelegate() {
            @Override
            public void onTitleChange(GeckoSession source, String title) {
                if (!debugBuild() || title == null || !title.startsWith("GLACIER_TEST_")) return;
                if ("mock-socks".equals(getIntent().getStringExtra("glacier.ci.network"))
                        && "GLACIER_TEST_PROXY_ROUTE_OK".equals(title)) {
                    android.util.Log.i("GlacierSmoke", "PROXY_TEST=MOCK_SOCKS_PAGE_RENDERED");
                }
                Tab tab = findBySession(source);
                if (tab != null && (tab.url.startsWith("http://127.0.0.1:18765/profile")
                        || tab.url.startsWith("http://127.0.0.1:18765/transfer"))) {
                    // The value is a fixed fixture marker, never account data.
                    android.util.Log.i("GlacierSmoke", "ISOLATION_STATE=" + title);
                }
            }
            @Override
            public void onExternalResponse(GeckoSession source, WebResponse response) {
                transfers.onExternalResponse(response);
            }
        });
        session.setPromptDelegate(new GeckoSession.PromptDelegate() {
            @Override
            public GeckoResult<GeckoSession.PromptDelegate.PromptResponse> onFilePrompt(
                    GeckoSession source, GeckoSession.PromptDelegate.FilePrompt prompt) {
                return transfers.onFilePrompt(source, prompt);
            }
        });
        // Debug-only page-load evidence for CI. Never record arbitrary URLs,
        // query strings, proxy links, account data, or credentials.
        if ((getApplicationInfo().flags
                & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            session.setProgressDelegate(new GeckoSession.ProgressDelegate() {
                private String testSite;

                @Override
                public void onPageStart(GeckoSession source, String url) {
                    if (url != null && url.startsWith("https://example.com/")) {
                        testSite = "example";
                    } else if (url != null && "http://glacier-ci.invalid/".equals(url)
                            && "mock-socks".equals(getIntent().getStringExtra("glacier.ci.network"))) {
                        testSite = "proxy_fixture";
                    } else if (url != null && url.startsWith("https://github.com/")) {
                        testSite = "github";
                    } else if (url != null && url.startsWith("https://chatgpt.com/")) {
                        testSite = "chatgpt";
                    }
                    if (testSite != null) {
                        android.util.Log.i("GlacierSmoke", "PAGE_START site=" + testSite);
                    }
                }

                @Override
                public void onPageStop(GeckoSession source, boolean success) {
                    if (testSite != null) {
                        android.util.Log.i("GlacierSmoke",
                                "PAGE_STOP site=" + testSite + " success=" + success);
                    }
                    testSite = null;
                }
            });
        }
        session.setNavigationDelegate(new GeckoSession.NavigationDelegate() {
            @Override
            public GeckoResult<String> onLoadError(
                    GeckoSession source, String uri,
                    org.mozilla.geckoview.WebRequestError error) {
                if (debugBuild() && proxyMode
                        && START_URL.equals(uri)) {
                    boolean refused = error.category ==
                            org.mozilla.geckoview.WebRequestError.ERROR_CATEGORY_PROXY
                            && error.code ==
                            org.mozilla.geckoview.WebRequestError.ERROR_PROXY_CONNECTION_REFUSED;
                    android.util.Log.i("GlacierSmoke",
                            "PROXY_OFFLINE_ERROR=" + (refused ? "proxy_refused" : "other")
                                    + " category=" + error.category + " code=" + error.code);
                }
                return null;
            }

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
        t.url = url;
        t.title = "about:blank".equals(url) ? "新标签页" : url;
        t.session.loadUri(url);
        updateChrome();
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
        tabCounter.setText(Integer.toString(tabs.size()));
        if (newTabPage != null) {
            newTabPage.setVisibility(active != null && "about:blank".equals(active.url)
                    ? View.VISIBLE : View.GONE);
        }
        if (engineLabel != null) {
            if (proxyMode) {
                boolean connected = NativeProxy.alive();
                engineLabel.setText(connected
                        ? "● VLESS 代理运行中"
                        : "● 代理已断开 · 无直连回退");
            } else {
                engineLabel.setText("● 直连模式 · 无代理保护");
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
        ScrollView scroll = new ScrollView(this);
        GridLayout grid = new GridLayout(this);
        grid.setColumnCount(2);
        grid.setPadding(dp(9), dp(10), dp(9), dp(10));
        grid.setBackgroundColor(PALE);
        scroll.addView(grid);
        final AlertDialog[] holder = new AlertDialog[1];
        int screenWidth = getResources().getDisplayMetrics().widthPixels;
        int cardWidth = (screenWidth - dp(60)) / 2;

        for (Tab tab : new ArrayList<>(tabs)) {
            LinearLayout tile = new LinearLayout(this);
            tile.setOrientation(LinearLayout.VERTICAL);
            tile.setPadding(dp(10), dp(8), dp(10), dp(10));
            tile.setBackground(surfaceBorder(Color.WHITE, 18,
                    tab == active ? GLACIER_BLUE : HAIRLINE));
            tile.setContentDescription("标签卡片 · " + tab.title);

            LinearLayout head = horizontal();
            head.setPadding(0, 0, 0, 0);
            TextView favicon = new TextView(this);
            favicon.setText("◉");
            favicon.setTextColor(GLACIER_BLUE);
            favicon.setTextSize(17);
            head.addView(favicon, new LinearLayout.LayoutParams(dp(23), dp(28)));

            TextView title = new TextView(this);
            title.setSingleLine(true);
            title.setEllipsize(android.text.TextUtils.TruncateAt.END);
            title.setText(tab.title);
            title.setTextSize(12);
            title.setTextColor(INK);
            head.addView(title, new LinearLayout.LayoutParams(0, dp(32), 1));

            Button close = button("×");
            close.setTextSize(20);
            close.setContentDescription("关闭标签页");
            close.setOnClickListener(v -> {
                holder[0].dismiss();
                closeTab(tab);
                showTabs();
            });
            head.addView(close, new LinearLayout.LayoutParams(dp(33), dp(33)));
            tile.addView(head);

            TextView preview = new TextView(this);
            preview.setText("❄");
            preview.setTextSize(39);
            preview.setTextColor(GLACIER_BLUE);
            preview.setGravity(Gravity.CENTER);
            preview.setBackground(surface(PALE, 12));
            tile.addView(preview, new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, 0, 1));

            TextView domain = new TextView(this);
            domain.setText(WORK.equals(tab.profile) ? "工作 · " + tab.url
                    : "私人 · " + tab.url);
            domain.setSingleLine(true);
            domain.setEllipsize(android.text.TextUtils.TruncateAt.END);
            domain.setTextSize(10);
            domain.setTextColor(MUTED);
            LinearLayout.LayoutParams domainParams =
                    new LinearLayout.LayoutParams(
                            LinearLayout.LayoutParams.MATCH_PARENT, dp(25));
            tile.addView(domain, domainParams);
            tile.setOnClickListener(v -> {
                holder[0].dismiss();
                switchTo(tab);
            });

            GridLayout.LayoutParams cell = new GridLayout.LayoutParams();
            cell.width = cardWidth;
            cell.height = dp(190);
            cell.setMargins(dp(5), dp(5), dp(5), dp(5));
            grid.addView(tile, cell);
        }

        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle("标签页 · " + tabs.size())
                .setView(scroll)
                .setPositiveButton("＋ 新建标签页",
                        (d, which) -> openTab(selectedProfile, "about:blank"))
                .setNegativeButton("关闭", null)
                .create();
        holder[0] = dialog;
        dialog.show();
    }

    private void closeTab(Tab target) {
        if (target == null || !tabs.contains(target)) return;
        boolean wasActive = target == active;
        if (wasActive) {
            if (web.getSession() != null) web.releaseSession();
            active = null;
        }
        tabs.remove(target);
        target.session.close();
        if (tabs.isEmpty()) {
            openTab(selectedProfile, "about:blank");
        } else if (wasActive) {
            switchTo(tabs.get(tabs.size() - 1));
        } else {
            updateChrome();
        }
    }

    private void closeActiveTab() {
        closeTab(active);
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
        if (newTabPage != null) newTabPage.setVisibility(View.GONE);
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
        if (SavedVlessNode.exists(this)) {
            new AlertDialog.Builder(this)
                    .setTitle("Glacier · 网络连接")
                    .setMessage("已保存 VLESS 节点，可一键重新连接；也可以更换节点或明确使用直连。")
                    .setCancelable(false)
                    .setItems(new String[]{
                            "连接已保存的 VLESS 节点",
                            "导入或更换 VLESS 节点",
                            "明确使用直连"
                    }, (dialog, which) -> {
                        if (which == 0) startSavedVlessMode();
                        if (which == 1) askForNode();
                        if (which == 2) startDirectMode();
                    })
                    .show();
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle("Glacier · 选择网络方式")
                .setMessage("首次导入 VLESS 后可选择记住节点，下次启动自动连接。\n\n"
                        + "VLESS 失败时不会自动切换直连。")
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
        input.setHint("粘贴 vless://UUID@服务器:端口?...");
        input.setInputType(InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        final CheckBox remember = new CheckBox(this);
        remember.setText("记住节点，下次启动自动连接");
        remember.setTextSize(14);
        remember.setChecked(true);

        LinearLayout wrapper = new LinearLayout(this);
        wrapper.setOrientation(LinearLayout.VERTICAL);
        wrapper.setPadding(dp(20), dp(8), dp(20), dp(8));
        wrapper.addView(input, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
        wrapper.addView(remember, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
        new AlertDialog.Builder(this)
                .setTitle("导入 VLESS")
                .setMessage("节点只保存在本机。勾选后会使用 Android Keystore 加密，不上传到服务器。")
                .setView(wrapper)
                .setNegativeButton("返回", (d, w) -> showNetworkGate())
                .setPositiveButton("连接", (d, w) -> {
                    String link = input.getText().toString().trim();
                    boolean saveForNextTime = remember.isChecked();
                    input.setText("");
                    startVlessMode(link, saveForNextTime);
                })
                .setCancelable(false)
                .show();
    }

    private void startDirectMode() {
        try {
            // Explicit DIRECT selection turns off auto-connect without
            // silently deleting an already saved encrypted node.
            if (SavedVlessNode.exists(this)) {
                SavedVlessNode.disableAutoConnect(this);
            }
            proxyMode = false;
            String yaml = NativeProxy.prepareGecko(this, false);
            initializeEngine(yaml);
        } catch (Exception e) {
            showNetworkError("无法初始化直连 GeckoView 内核");
        }
    }

    private void startVlessMode(String value, boolean remember) {
        final VlessLink node;
        try {
            node = VlessLink.parse(value);
        } catch (Exception e) {
            // Do not include any node text in visible errors.
            showNetworkError("节点链接不符合当前支持的 VLESS 格式");
            return;
        }
        android.app.ProgressDialog loading = android.app.ProgressDialog.show(this,
                "Glacier 网络", "正在连接 VLESS…", true, false);
        new Thread(() -> {
            try {
                NativeProxy.start(getApplicationContext(), node);
                String yaml = NativeProxy.prepareGecko(getApplicationContext(), true);
                if (remember) {
                    SavedVlessNode.save(getApplicationContext(), value);
                } else {
                    // An explicitly session-only import must not leave the
                    // previously saved node enabled for next launch.
                    SavedVlessNode.clear(getApplicationContext());
                }
                runOnUiThread(() -> {
                    loading.dismiss();
                    proxyMode = true;
                    initializeEngine(yaml);
                });
            } catch (Exception e) {
                NativeProxy.stop();
                runOnUiThread(() -> {
                    loading.dismiss();
                    showNetworkError("连接或本地加密保存失败，请重新配置");
                });
            }
        }, "glacier-vless-start").start();
    }

    private void startSavedVlessMode() {
        android.app.ProgressDialog loading = android.app.ProgressDialog.show(this,
                "Glacier 网络", "正在连接已保存的 VLESS 节点…", true, false);
        new Thread(() -> {
            try {
                String savedLink = SavedVlessNode.load(getApplicationContext());
                if (savedLink == null) throw new IllegalStateException("No saved node");
                VlessLink node = VlessLink.parse(savedLink);
                NativeProxy.start(getApplicationContext(), node);
                String yaml = NativeProxy.prepareGecko(getApplicationContext(), true);
                runOnUiThread(() -> {
                    loading.dismiss();
                    proxyMode = true;
                    initializeEngine(yaml);
                });
            } catch (Exception ignored) {
                NativeProxy.stop();
                runOnUiThread(() -> {
                    loading.dismiss();
                    showSavedNodeError();
                });
            }
        }, "glacier-vless-auto-connect").start();
    }

    private void showSavedNodeError() {
        // Never reconfigure GeckoRuntime for DIRECT on proxy failure.
        new AlertDialog.Builder(this)
                .setTitle("已保存的 VLESS 连接失败")
                .setMessage("节点或网络暂时不可用，浏览器没有回退直连。\n\n"
                        + "可以重试、重新导入，或者删除本机保存的节点。")
                .setCancelable(false)
                .setPositiveButton("重试", (d,w) -> startSavedVlessMode())
                .setNeutralButton("重新导入", (d,w) -> askForNode())
                .setNegativeButton("删除保存", (d,w) -> {
                    try {
                        SavedVlessNode.clear(this);
                        showNetworkGate();
                    } catch (Exception e) {
                        showSavedNodeError();
                    }
                })
                .show();
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
            String bootUrl = debugBuild()
                    && "mock-socks".equals(getIntent().getStringExtra("glacier.ci.network"))
                    ? "http://glacier-ci.invalid/" : START_URL;
            openTab(PRIVATE, bootUrl);
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
                        : "当前是明确选择的直连模式，没有 VLESS 保护。")
                .setPositiveButton("知道了", null)
                .setNeutralButton("管理已保存节点", (d,w) -> manageSavedNode())
                .show();
    }

    private void manageSavedNode() {
        if (!SavedVlessNode.exists(this)) {
            new AlertDialog.Builder(this).setTitle("网络设置")
                    .setMessage("当前没有保存的 VLESS 节点。")
                    .setPositiveButton("知道了", null).show();
            return;
        }
        new AlertDialog.Builder(this).setTitle("管理已保存节点")
                .setMessage("删除后，下次打开 Glacier 将重新要求选择网络方式。\n"
                        + "当前连接会持续到本次浏览器关闭。")
                .setPositiveButton("保留", null)
                .setNegativeButton("删除已保存节点", (d,w) -> {
                    try {
                        SavedVlessNode.clear(this);
                        android.widget.Toast.makeText(this, "已删除本机保存的节点",
                                android.widget.Toast.LENGTH_SHORT).show();
                    } catch (Exception e) {
                        new AlertDialog.Builder(this).setTitle("删除失败")
                                .setMessage("本机密钥存储暂不可用，请重试。")
                                .setPositiveButton("知道了",null).show();
                    }
                }).show();
    }

    private void showLabWarning() {
        new AlertDialog.Builder(this)
                .setTitle("这是内核实验版")
                .setMessage("已集成 GeckoView 真正的网页内核，可比较网页显示、导航、账号空间隔离和兼容性。"
                        + "\n\n已接入 VLESS/本地 SOCKS5，可选择加密记住节点、下次启动自动连接。不是 Android 系统级 VPN，也未经过独立安全审计。"
                        + "\n\n现已增加系统文件选择器和实验性下载保存（单文件最大 64 MB）；文件夹上传暂不支持。"
                        + "\n\n仍未提供账号保险箱、验证码 API、云同步、完整权限管理。"
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
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (transfers != null) transfers.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    protected void onDestroy() {
        if (transfers != null && isFinishing()) transfers.dispose();
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
