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
 * Glacier Gecko Engine Lab v0.2: GeckoView with profile-separated metadata.
 * No credential vault, automatic login, cloud sync or VLESS proxy exists yet.
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
    private Button bookmarkButton;
    private TextView pageLabel;
    private BrowserStore store;
    private Tab active;
    private String selectedProfile = PRIVATE;

    private static class Tab {
        final GeckoSession session;
        final String profile;
        String url = START_URL;
        String title = "新标签页";
        boolean canBack = false;
        boolean canForward = false;
        boolean loaded = false;

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
        store = new BrowserStore(this);
        buildChrome();
        restoreTabs();
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

        bookmarkButton = button("☆");
        bookmarkButton.setContentDescription("添加或取消书签");
        bookmarkButton.setOnClickListener(v -> toggleCurrentBookmark());
        LinearLayout.LayoutParams starParams = new LinearLayout.LayoutParams(dp(37), dp(43));
        starParams.setMargins(dp(5), 0, 0, 0);
        nav.addView(bookmarkButton, starParams);

        Button go = button("→");
        go.setContentDescription("打开网址");
        go.setOnClickListener(v -> navigate(address.getText().toString()));
        LinearLayout.LayoutParams end = new LinearLayout.LayoutParams(dp(40), dp(43));
        end.setMargins(dp(6), 0, 0, 0);
        nav.addView(go, end);
        root.addView(nav);

        // Testing banner makes the network security limitation explicit.
        engineLabel = new TextView(this);
        engineLabel.setText("GeckoView 159 · v0.2 测试版 · 当前无 VLESS");
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

        pageLabel = new TextView(this);
        pageLabel.setText("Glacier 浏览器");
        pageLabel.setGravity(Gravity.CENTER);
        pageLabel.setSingleLine(true);
        pageLabel.setEllipsize(android.text.TextUtils.TruncateAt.END);
        pageLabel.setTextColor(MUTED);
        pageLabel.setTextSize(12);
        bottom.addView(pageLabel, new LinearLayout.LayoutParams(0, dp(44), 1));

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
        menu.setContentDescription("浏览器菜单");
        menu.setOnClickListener(v -> showBrowserMenu());
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
        session.setContentDelegate(new GeckoSession.ContentDelegate() {
            @Override
            public void onTitleChange(GeckoSession source, String title) {
                Tab tab = findBySession(source);
                if (tab == null) return;
                tab.title = UrlPolicy.label(title, tab.url);
                store.addHistory(tab.profile, tab.url, tab.title);
                saveTabSnapshots();
                if (tab == active) updateChrome();
            }
        });
        session.setNavigationDelegate(new GeckoSession.NavigationDelegate() {
            @Override
            public void onLocationChange(GeckoSession source, String url,
                                         List<GeckoSession.PermissionDelegate.ContentPermission> perms,
                                         Boolean userGesture) {
                Tab t = findBySession(source);
                if (t != null && url != null) {
                    t.url = url;
                    t.title = UrlPolicy.label("", url);
                    store.addHistory(t.profile, url, t.title);
                    saveTabSnapshots();
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
                // GeckoView controls initial navigation for the newly opened popup.
                child.loaded = true;
                if (url != null && !url.isEmpty()) child.url = url;
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
        t.url = url;
        switchTo(t);
    }

    private void switchTo(Tab next) {
        if (next == active) return;
        if (web.getSession() != null) web.releaseSession();
        active = next;
        selectedProfile = next.profile;
        web.setSession(next.session);
        if (!next.loaded) {
            next.loaded = true;
            next.session.loadUri(next.url);
        }
        store.setLastProfile(selectedProfile);
        saveTabSnapshots();
        updateChrome();
    }

    private void updateChrome() {
        if (address == null) return;
        identity.setText(WORK.equals(selectedProfile) ? "工作空间  ▾" : "私人空间  ▾");
        tabCounter.setText(Integer.toString(tabs.size()));
        if (active != null) {
            bookmarkButton.setText(store.isBookmarked(active.profile, active.url) ? "★" : "☆");
            pageLabel.setText(UrlPolicy.label(active.title, active.url));
            if (!address.hasFocus()) address.setText(active.url);
            backButton.setEnabled(active.canBack);
            forwardButton.setEnabled(active.canForward);
        } else {
            backButton.setEnabled(false);
            forwardButton.setEnabled(false);
            bookmarkButton.setText("☆");
            pageLabel.setText("Glacier 浏览器");
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
        saveTabSnapshots();
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
     * Rebuild tabs without launching background navigation in all profiles.
     * GeckoView retains cookies by persistent contextId, while the browser
     * only re-opens safe HTTPS URLs when the user actually selects a tab.
     */
    private void restoreTabs() {
        List<BrowserStore.Entry> personal = store.tabs(PRIVATE);
        List<BrowserStore.Entry> workTabs = store.tabs(WORK);
        for (BrowserStore.Entry entry : personal) restoreOne(PRIVATE, entry);
        for (BrowserStore.Entry entry : workTabs) restoreOne(WORK, entry);

        selectedProfile = store.lastProfile();
        Tab target = null;
        for (int i = tabs.size() - 1; i >= 0; i--) {
            Tab t = tabs.get(i);
            if (selectedProfile.equals(t.profile)) {
                target = t;
                break;
            }
        }
        if (target == null) {
            openTab(selectedProfile, START_URL);
        } else {
            switchTo(target);
        }
    }

    private void restoreOne(String profile, BrowserStore.Entry entry) {
        String safe = UrlPolicy.safePersistentUrl(entry.url);
        if (safe == null) return;
        Tab tab = createTab(profile);
        tab.url = safe;
        tab.title = entry.title;
        tab.loaded = false;
    }

    private void saveTabSnapshots() {
        if (store == null) return;
        List<BrowserStore.Entry> privateTabs = new ArrayList<>();
        List<BrowserStore.Entry> workTabs = new ArrayList<>();
        for (Tab tab : tabs) {
            if (UrlPolicy.safePersistentUrl(tab.url) == null) continue;
            BrowserStore.Entry entry = new BrowserStore.Entry(tab.url, tab.title);
            if (PRIVATE.equals(tab.profile)) privateTabs.add(entry);
            else if (WORK.equals(tab.profile)) workTabs.add(entry);
        }
        store.saveTabs(PRIVATE, privateTabs);
        store.saveTabs(WORK, workTabs);
    }

    private void toggleCurrentBookmark() {
        if (active == null) return;
        String safe = UrlPolicy.safePersistentUrl(active.url);
        if (safe == null) {
            new AlertDialog.Builder(this)
                    .setMessage("这个页面暂时无法添加书签。请打开 HTTPS 网站后重试。")
                    .setPositiveButton("知道了", null).show();
            return;
        }
        boolean added = store.toggleBookmark(active.profile, safe, active.title);
        android.widget.Toast.makeText(this, added ? "已添加书签" : "已取消书签",
                android.widget.Toast.LENGTH_SHORT).show();
        updateChrome();
    }

    private void showSavedEntries(boolean bookmarks) {
        String profile = selectedProfile;
        List<BrowserStore.Entry> entries = bookmarks
                ? store.bookmarks(profile) : store.history(profile);
        if (entries.isEmpty()) {
            new AlertDialog.Builder(this)
                    .setTitle(bookmarks ? "当前空间的书签" : "当前空间的历史记录")
                    .setMessage(bookmarks ? "还没有收藏的网页。" : "还没有浏览记录。")
                    .setPositiveButton("确定", null).show();
            return;
        }
        String[] names = new String[entries.size()];
        for (int i = 0; i < entries.size(); i++) {
            BrowserStore.Entry e = entries.get(i);
            names[i] = UrlPolicy.label(e.title, e.url) + "\n" + e.url;
        }
        new AlertDialog.Builder(this)
                .setTitle((WORK.equals(profile) ? "工作空间" : "私人空间")
                        + (bookmarks ? " · 书签" : " · 历史"))
                .setItems(names, (d, index) -> {
                    // This entry belongs to profile at dialog creation time.
                    openTab(profile, entries.get(index).url);
                })
                .setNegativeButton("关闭", null)
                .show();
    }

    private void confirmClearHistory() {
        String profile = selectedProfile;
        new AlertDialog.Builder(this)
                .setTitle("清空当前空间的历史记录？")
                .setMessage("只删除" + (WORK.equals(profile) ? "工作空间" : "私人空间")
                        + "的本地浏览历史。不会清除另一空间的记录、书签或 Cookie。")
                .setNegativeButton("取消", null)
                .setPositiveButton("清空", (d, which) -> {
                    store.clearHistory(profile);
                    android.widget.Toast.makeText(this, "历史记录已清空",
                            android.widget.Toast.LENGTH_SHORT).show();
                }).show();
    }

    private void showBrowserMenu() {
        new AlertDialog.Builder(this)
                .setTitle("Glacier · 浏览器")
                .setItems(new String[]{
                    "☆ 收藏 / 取消收藏当前页面", "书签", "历史记录",
                    "＋ 新建标签", "查看所有标签", "切换账号空间",
                    "打开 ChatGPT", "打开 GitHub", "GeckoView 内核信息",
                    "清空当前空间历史", "关于实验版与网络安全"
                }, (d, option) -> {
                    switch (option) {
                        case 0: toggleCurrentBookmark(); break;
                        case 1: showSavedEntries(true); break;
                        case 2: showSavedEntries(false); break;
                        case 3: openTab(selectedProfile, START_URL); break;
                        case 4: showTabs(); break;
                        case 5: chooseProfile(); break;
                        case 6: navigate("https://chatgpt.com/"); break;
                        case 7: navigate("https://github.com/"); break;
                        case 8: navigate("about:buildconfig"); break;
                        case 9: confirmClearHistory(); break;
                        case 10: showLabWarning(); break;
                        default: break;
                    }
                }).show();
    }

    private void showLabWarning() {
        new AlertDialog.Builder(this)
                .setTitle("这是内核实验版")
                .setMessage("v0.2 已集成 GeckoView 真正的网页内核、独立账号空间、书签、历史记录及标签网址恢复。"
                        + "\n\n仅在本机保存网页标题和不含查询参数的网址；不同空间互不共享。"
                        + "\n\n尚未接入 VLESS、账号保险箱、验证码 API、云同步、完整文件下载和网站权限管理。"
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
    protected void onStop() {
        saveTabSnapshots();
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        // Also free session resources on configuration changes; URL snapshots
        // rebuild the tabs when Android recreates the Activity.
        if (web != null && web.getSession() != null) web.releaseSession();
        for (Tab t : tabs) t.session.close();
        tabs.clear();
        active = null;
        super.onDestroy();
    }
}
