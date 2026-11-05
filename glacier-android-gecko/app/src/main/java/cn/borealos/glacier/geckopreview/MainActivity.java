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
import org.mozilla.geckoview.GeckoRuntime;
import org.mozilla.geckoview.GeckoSession;
import org.mozilla.geckoview.GeckoSessionSettings;
import org.mozilla.geckoview.GeckoView;

import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Glacier Gecko Engine Lab v0.1, a REAL GeckoView embedding, not a WebView.
 * No credential vault, automatic login, data sync or VLESS proxy exists yet.
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
        if (runtime == null) {
            runtime = GeckoRuntime.create(getApplicationContext());
        }
        buildChrome();
        openTab(PRIVATE, START_URL);
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
        engineLabel.setText("GeckoView 真内核测试版 · 尚未接入 VLESS");
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
                    "切换账号空间", "测试说明"
                }, (dialog, index) -> {
                    if (index == 0) navigate("about:buildconfig");
                    if (index == 1) navigate("https://chatgpt.com/");
                    if (index == 2) navigate("https://github.com/");
                    if (index == 3) chooseProfile();
                    if (index == 4) showLabWarning();
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

    private void showLabWarning() {
        new AlertDialog.Builder(this)
                .setTitle("这是内核实验版")
                .setMessage("已集成 GeckoView 真正的网页内核，可比较网页显示、导航、账号空间隔离和兼容性。"
                        + "\n\n尚未接入 VLESS、账号保险箱、验证码 API、数据同步或安全权限管理。"
                        + "\n\n当前网页走手机默认网络，不保证代理。请勿使用关键账号测试。")
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
    }
}
