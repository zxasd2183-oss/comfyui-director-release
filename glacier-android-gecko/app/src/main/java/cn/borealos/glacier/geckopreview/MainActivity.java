package cn.borealos.glacier.geckopreview;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.content.ActivityNotFoundException;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Handler;
import android.os.Looper;
import android.widget.ImageView;
import android.widget.ProgressBar;
import java.util.concurrent.atomic.AtomicBoolean;
import java.io.ByteArrayOutputStream;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
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

import org.json.JSONArray;
import org.json.JSONObject;

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
 * Local Keystore-encrypted per-profile account cards are available; no autofill or cloud sync.
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
    private final Handler tabSaveHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService tabSaveQueue = Executors.newSingleThreadExecutor();
    private final Runnable saveTabsTask = this::persistTabs;
    private final Handler libraryHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService librarySaveQueue = Executors.newSingleThreadExecutor();
    private final Runnable saveLibraryTask = this::persistLibrary;
    private BrowserLibraryStore.Snapshot libraryState = new BrowserLibraryStore.Snapshot();
    private boolean restoringTabs;
    private final List<BrowserAccountsStore.Card> accountCards = new ArrayList<>();
    private final ExecutorService accountCodeQueue = Executors.newSingleThreadExecutor();
    private boolean accountsReadonly;
    private GlacierCloudSync.State cloudState = new GlacierCloudSync.State();
    private boolean cloudSessionReadonly;
    private final ExecutorService cloudQueue = Executors.newSingleThreadExecutor();
    private final Handler cloudAutoHandler = new Handler(Looper.getMainLooper());
    private boolean cloudAutoBusy;
    private int cloudEpoch;
    private final Runnable cloudAutoTimer = new Runnable() {
        @Override public void run() {
            cloudAutoTick();
            if(cloudState.autoEnabled)cloudAutoHandler.postDelayed(this,180000);
        }
    };
    private GeckoView web;
    private BrowserTransfers transfers;
    private BrowserUpdater updater;
    private EditText address;
    private TextView identity;
    private TextView tabCounter;
    private TextView engineLabel;
    private View newTabPage;
    private FrameLayout tabOverview;
    private Button backButton;
    private Button forwardButton;
    private Tab active;
    private String selectedProfile = PRIVATE;

    private static class Tab {
        final GeckoSession session;
        final String profile;
        final String id;
        String url = START_URL;
        String title = "新标签页";
        String geckoState;
        byte[] thumbnail;
        boolean pendingRestore;
        String lastAccountPromptSite = "";
        String expectedRestoreUrl;
        boolean canBack = false;
        boolean canForward = false;

        Tab(GeckoSession session, String profile) {
            this(session, profile, UUID.randomUUID().toString());
        }
        Tab(GeckoSession session, String profile, String id) {
            this.session = session;
            this.profile = profile;
            this.id = id;
        }
    }

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        restoreLibrary();
        restoreAccountVault();
        try {
            cloudState = GlacierCloudSync.load(this);
        } catch(Exception ignored) {
            cloudSessionReadonly = true;
        }
        updater = new BrowserUpdater(this);
        transfers = new BrowserTransfers(this, (profile, filename, mime, bytes, document) -> {
            if (!BrowserLibraryStore.validProfile(profile)
                    || !BrowserLibraryStore.validDocumentUri(document.toString())) return;
            libraryState.downloads.add(0, new BrowserLibraryStore.Entry(
                    profile, "", "", filename, document.toString(),
                    mime, bytes, System.currentTimeMillis()));
            BrowserLibraryStore.cap(libraryState.downloads, 160);
            scheduleLibrarySave();
            if (debugBuild() && filename.equals("glacier-download-test.txt")) {
                android.util.Log.i("GlacierSmoke", "M04_DOWNLOAD_RECORDED=true");
            }
        });
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
        FrameLayout screen = new FrameLayout(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.WHITE);
        if (android.os.Build.VERSION.SDK_INT >= 35) {
            screen.setOnApplyWindowInsetsListener((view, insets) -> {
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
        screen.addView(root, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));
        tabOverview = new FrameLayout(this);
        tabOverview.setVisibility(View.GONE);
        tabOverview.setBackgroundColor(PALE);
        screen.addView(tabOverview, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));
        setContentView(screen);

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
        active.geckoState = null;
        active.thumbnail = null;
        updateChrome();
        scheduleTabsSave();
    }

    private boolean debugBuild() {
        return (getApplicationInfo().flags
                & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0;
    }

    private void scheduleTabsSave() {
        if (restoringTabs) return;
        tabSaveHandler.removeCallbacks(saveTabsTask);
        tabSaveHandler.postDelayed(saveTabsTask, 420);
    }

    private BrowserTabStore.Snapshot snapshotTabs() {
        BrowserTabStore.Snapshot snapshot = new BrowserTabStore.Snapshot();
        snapshot.activeId = active == null ? null : active.id;
        for (Tab tab : tabs) {
            snapshot.tabs.add(new BrowserTabStore.TabRecord(
                    tab.id, tab.profile, tab.url, tab.title,
                    tab.geckoState, tab.thumbnail == null ? null : tab.thumbnail.clone()));
        }
        return snapshot;
    }

    private void persistTabs() {
        if (restoringTabs || tabs.isEmpty()) return;
        BrowserTabStore.Snapshot snapshot = snapshotTabs();
        tabSaveQueue.execute(() -> {
            try {
                BrowserTabStore.save(getApplicationContext(), snapshot);
            } catch (Exception ignored) {
                // No browsing URLs, titles, form state or thumbnails in logs.
            }
        });
    }

    private boolean restoreSavedTabs() {
        BrowserTabStore.Snapshot snapshot;
        try {
            snapshot = BrowserTabStore.load(this);
        } catch (Exception ignored) {
            android.widget.Toast.makeText(this,
                    "标签页数据无法读取，本次开启新的浏览会话",
                    android.widget.Toast.LENGTH_LONG).show();
            return false;
        }
        if (snapshot.tabs.isEmpty()) return false;
        restoringTabs = true;
        try {
            Tab resume = null;
            for (BrowserTabStore.TabRecord row : snapshot.tabs) {
                // Profile/contextId is selected BEFORE opening the GeckoSession.
                Tab tab = new Tab(createSession(row.profile), row.profile, row.id);
                tab.url = row.url;
                tab.title = row.title == null || row.title.isEmpty()
                        ? row.url : row.title;
                tab.geckoState = row.state;
                tab.thumbnail = row.thumb;
                tab.pendingRestore = true;
                tab.expectedRestoreUrl = row.url;
                tabs.add(tab);
                if (row.id.equals(snapshot.activeId)) resume = tab;
            }
            if (tabs.isEmpty()) return false;
            if (resume == null) resume = tabs.get(0);
            switchTo(resume);
            if (debugBuild()) android.util.Log.i("GlacierSmoke",
                    "TAB_RESTORE_COUNT=" + tabs.size());
            return true;
        } finally {
            restoringTabs = false;
        }
    }

    private void captureTabThumbnail(Tab tab) {
        if (tab == null || tab != active || web == null
                || !BrowserTabStore.validUrl(tab.url)
                || "about:blank".equals(tab.url)) return;
        try {
            web.capturePixels().accept(bitmap -> {
                if (bitmap == null || !tabs.contains(tab)) return;
                try {
                    int width = 240;
                    int height = Math.max(1, Math.min(420,
                            (int)((double)bitmap.getHeight() * width / bitmap.getWidth())));
                    Bitmap small = Bitmap.createScaledBitmap(bitmap, width, height, true);
                    ByteArrayOutputStream output = new ByteArrayOutputStream();
                    small.compress(Bitmap.CompressFormat.JPEG, 55, output);
                    byte[] bytes = output.toByteArray();
                    if (bytes.length <= 50 * 1024) {
                        tab.thumbnail = bytes;
                        scheduleTabsSave();
                        if (debugBuild()) android.util.Log.i("GlacierSmoke",
                                "TAB_THUMBNAIL_CAPTURED=true");
                    }
                    if (small != bitmap) small.recycle();
                } catch (Exception ignored) {
                    // A thumbnail is optional; never break browser navigation.
                }
            }, error -> {
                // Gecko compositor may not have painted yet; keep prior preview.
            });
        } catch (Exception ignored) {
            // Surface can be unavailable when app is going to background.
        }
    }

    private void restoreLibrary() {
        try {
            libraryState = BrowserLibraryStore.load(this);
        } catch (Exception ignored) {
            libraryState = new BrowserLibraryStore.Snapshot();
            android.widget.Toast.makeText(this,
                    "本机收藏和历史记录无法读取，请检查设备密钥存储",
                    android.widget.Toast.LENGTH_LONG).show();
        }
    }

    private void scheduleLibrarySave() {
        libraryHandler.removeCallbacks(saveLibraryTask);
        libraryHandler.postDelayed(saveLibraryTask, 550);
    }

    private void persistLibrary() {
        BrowserLibraryStore.Snapshot copy = libraryState.copy();
        librarySaveQueue.execute(() -> {
            try {
                BrowserLibraryStore.save(getApplicationContext(),copy);
            } catch(Exception ignored) {
                // URLs, titles, document paths and profile records are private.
            }
        });
    }

    private static String safeTitle(String title, String fallback) {
        String result=title==null||title.trim().isEmpty()?fallback:title.trim();
        return result.length()>180?result.substring(0,180):result;
    }

    private boolean isCurrentBookmarked() {
        if(active==null||!BrowserLibraryStore.validWebUrl(active.url))return false;
        for(BrowserLibraryStore.Entry e:libraryState.bookmarks) {
            if(active.profile.equals(e.profile)&&active.url.equals(e.url))return true;
        }
        return false;
    }

    private void toggleBookmark() {
        if(debugBuild())android.util.Log.i("GlacierSmoke","M04_BOOKMARK_ACTION=INVOKED");
        if(active==null||!BrowserLibraryStore.validWebUrl(active.url)) {
            if(debugBuild())android.util.Log.i("GlacierSmoke","M04_BOOKMARK_REJECTED=INVALID_PAGE");
            android.widget.Toast.makeText(this,"当前页面暂不能收藏",
                    android.widget.Toast.LENGTH_SHORT).show();
            return;
        }
        for(int i=0;i<libraryState.bookmarks.size();i++) {
            BrowserLibraryStore.Entry e=libraryState.bookmarks.get(i);
            if(active.profile.equals(e.profile)&&active.url.equals(e.url)) {
                libraryState.bookmarks.remove(i);
                scheduleLibrarySave();
                android.widget.Toast.makeText(this,"已取消收藏",
                        android.widget.Toast.LENGTH_SHORT).show();
                if(debugBuild())android.util.Log.i("GlacierSmoke","M04_BOOKMARK_REMOVED=true");
                return;
            }
        }
        libraryState.bookmarks.add(0,new BrowserLibraryStore.Entry(
                active.profile,safeTitle(active.title,active.url),active.url,
                "","","",0,System.currentTimeMillis()));
        BrowserLibraryStore.cap(libraryState.bookmarks,160);
        scheduleLibrarySave();
        android.widget.Toast.makeText(this,"已收藏到当前账号空间",
                android.widget.Toast.LENGTH_SHORT).show();
        if(debugBuild())android.util.Log.i("GlacierSmoke","M04_BOOKMARK_ADDED=true");
    }

    private void rememberVisit(Tab tab) {
        if(tab==null || !BrowserLibraryStore.validWebUrl(tab.url))return;
        long time=System.currentTimeMillis();
        String name=safeTitle(tab.title,tab.url);
        List<BrowserLibraryStore.Entry> rows=libraryState.history;
        if(!rows.isEmpty()) {
            BrowserLibraryStore.Entry newest=rows.get(0);
            if(tab.profile.equals(newest.profile)&&tab.url.equals(newest.url)
                    && time-newest.timestamp<2500) {
                newest.title=name;
                newest.timestamp=time;
                scheduleLibrarySave();
                return;
            }
        }
        rows.add(0,new BrowserLibraryStore.Entry(tab.profile,name,tab.url,
                "","","",0,time));
        BrowserLibraryStore.cap(rows,450);
        scheduleLibrarySave();
        if(debugBuild() && "https://example.com/".equals(tab.url)) {
            android.util.Log.i("GlacierSmoke","M04_HISTORY_EXAMPLE=true");
        }
    }

    private void reviseRecentHistoryTitle(Tab tab) {
        if(tab==null || !BrowserLibraryStore.validWebUrl(tab.url))return;
        for(BrowserLibraryStore.Entry item:libraryState.history) {
            if(item.profile.equals(tab.profile)&&item.url.equals(tab.url)) {
                item.title=safeTitle(tab.title,tab.url);
                scheduleLibrarySave();
                return;
            }
        }
    }

    private List<BrowserLibraryStore.Entry> currentLibraryEntries(String kind) {
        List<BrowserLibraryStore.Entry> all;
        if("bookmarks".equals(kind))all=libraryState.bookmarks;
        else if("history".equals(kind))all=libraryState.history;
        else all=libraryState.downloads;
        List<BrowserLibraryStore.Entry> filtered=new ArrayList<>();
        for(BrowserLibraryStore.Entry e:all) {
            if(selectedProfile.equals(e.profile))filtered.add(e);
        }
        return filtered;
    }

    private void showLibraryList(String kind, boolean removingBookmarks) {
        List<BrowserLibraryStore.Entry> rows=currentLibraryEntries(kind);
        if (debugBuild()) android.util.Log.i("GlacierSmoke",
                "M04_LIBRARY_LIST kind="+kind+" profile="+selectedProfile+" count="+rows.size());
        String heading="bookmarks".equals(kind)?"书签":
                "history".equals(kind)?"历史记录":"下载记录";
        String space=WORK.equals(selectedProfile)?"工作空间":"私人空间";
        if(rows.isEmpty()) {
            new AlertDialog.Builder(this).setTitle(space+" · "+heading)
                    .setMessage("当前空间暂无记录。")
                    .setPositiveButton("关闭",null).show();
            return;
        }
        String[] titles=new String[rows.size()];
        for(int i=0;i<rows.size();i++) {
            BrowserLibraryStore.Entry item=rows.get(i);
            if("downloads".equals(kind)) {
                titles[i]=safeTitle(item.name,"下载文件")+
                        " · "+Math.max(0,item.bytes)+" 字节";
            } else {
                titles[i]=safeTitle(item.title,item.url);
            }
        }
        AlertDialog.Builder dialog=new AlertDialog.Builder(this)
                .setTitle(space+" · "+heading+(removingBookmarks?" · 点击删除":""))
                .setItems(titles,(d,i)-> {
                    BrowserLibraryStore.Entry item=rows.get(i);
                    if(removingBookmarks) {
                        libraryState.bookmarks.remove(item);
                        scheduleLibrarySave();
                        android.widget.Toast.makeText(this,"已删除书签",
                                android.widget.Toast.LENGTH_SHORT).show();
                        showLibraryList("bookmarks",true);
                    } else if("downloads".equals(kind)) {
                        openSavedDownload(item);
                    } else if(BrowserLibraryStore.validWebUrl(item.url)) {
                        navigate(item.url);
                    }
                })
                .setNegativeButton("关闭",null);
        if("history".equals(kind)||"downloads".equals(kind)) {
            dialog.setNeutralButton("清空本空间记录",(d,w)-> {
                new AlertDialog.Builder(this).setTitle("确认清空"+heading+"？")
                        .setMessage("仅清除"+space+"的"+heading+"。"
                                +("downloads".equals(kind)
                                ?"已经保存到手机的文件不会被删除。":""))
                        .setNegativeButton("取消",null)
                        .setPositiveButton("清空",(confirm,which)-> {
                            if("history".equals(kind)) {
                                libraryState.history.removeIf(e->selectedProfile.equals(e.profile));
                            } else {
                                libraryState.downloads.removeIf(e->selectedProfile.equals(e.profile));
                            }
                            scheduleLibrarySave();
                        }).show();
            });
        }
        dialog.show();
    }

    private void openSavedDownload(BrowserLibraryStore.Entry item) {
        if(!BrowserLibraryStore.validDocumentUri(item.uri))return;
        try {
            Uri target=Uri.parse(item.uri);
            Intent view=new Intent(Intent.ACTION_VIEW);
            view.setDataAndType(target,item.mime==null||item.mime.isEmpty()
                    ?"application/octet-stream":item.mime);
            view.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            startActivity(Intent.createChooser(view,"打开已保存文件"));
        } catch(ActivityNotFoundException | SecurityException e) {
            new AlertDialog.Builder(this).setTitle("无法打开文件")
                    .setMessage("文件可能已移动、被删除，或文件管理器不再授予访问权限。")
                    .setPositiveButton("知道了",null).show();
        }
    }

    private void showInternalTestMenu() {
        // Only the Debug build exposes artificial loopback fixtures. Keeping
        // these options in a short submenu avoids pushing common browser
        // actions beyond Android's visible overflow menu height.
        if (!debugBuild() || proxyMode) return;
        final String[] fixtures = {
                "隔离自测：私人写入",
                "隔离自测：工作检查",
                "隔离自测：私人复查",
                "传输自测：打开测试页面"
        };
        new AlertDialog.Builder(this)
                .setTitle("Glacier · 内部测试工具")
                .setItems(fixtures, (d, index) -> {
                    if (active == null) return;
                    if (index == 3) {
                        active.session.loadUri("http://127.0.0.1:18765/transfer");
                    } else {
                        String phase=index == 0 ? "seed"
                                : index == 1 ? "work" : "return";
                        active.session.loadUri(
                                "http://127.0.0.1:18765/profile?phase=" + phase);
                    }
                })
                .setNegativeButton("取消",null)
                .show();
    }

    private android.content.SharedPreferences updatePreferences() {
        return getSharedPreferences("glacier_update_settings",Context.MODE_PRIVATE);
    }

    private boolean autoUpdateCheckEnabled() {
        return updatePreferences().getBoolean("auto_check",true);
    }

    private void maybeCheckUpdatesAtStartup() {
        // Automatically CHECK only; download/install always need user action.
        // Network routing is already configured when initializeEngine returns.
        if(debugBuild()||updater==null||!autoUpdateCheckEnabled())return;
        long now=System.currentTimeMillis();
        long last=updatePreferences().getLong("last_checked",0);
        if(last>0 && now-last<6L*60*60*1000 && now>=last)return;
        updatePreferences().edit().putLong("last_checked",now).apply();
        updater.check(proxyMode,(found,error)->{
            if(isFinishing()||error!=null||found==null)return;
            new AlertDialog.Builder(this)
                    .setTitle("Glacier 发现新版 "+found.version)
                    .setMessage("已检查官方发布记录。你可以选择下载并验证新版 APK，"
                            +"安装仍需要 Android 系统确认。")
                    .setNegativeButton("以后再说",null)
                    .setPositiveButton("查看更新",(d,w)->showAvailableUpdate(found))
                    .show();
        });
    }

    private void showUpdatePanel() {
        final String version=BuildConfig.VERSION_NAME;
        final String auto=autoUpdateCheckEnabled()?"已开启":"已关闭";
        final String[] choices=updater!=null&&updater.hasReady()?
                new String[]{"检查更新","启动时检查新版："+auto,
                        "更新安全说明","安装已验证 APK"}:
                new String[]{"检查更新","启动时检查新版："+auto,"更新安全说明"};
        // Android AlertDialog's message view can hide its items list on
        // some versions. A compact list and a separate explanation dialog
        // keep the actual update actions reachable on real devices.
        new AlertDialog.Builder(this)
                .setTitle("Glacier · 更新与版本 "+version)
                .setItems(choices,(d,which)->{
                    if(which==0)checkForUpdates(true);
                    else if(which==1) {
                        boolean next=!autoUpdateCheckEnabled();
                        updatePreferences().edit().putBoolean("auto_check",next).apply();
                        android.widget.Toast.makeText(this,next?
                                "启动更新提醒已开启":"启动更新提醒已关闭",
                                android.widget.Toast.LENGTH_SHORT).show();
                    } else if(which==2) {
                        new AlertDialog.Builder(this)
                                .setTitle("Glacier · 更新安全说明")
                                .setMessage(debugBuild()
                                        ?"当前是 Debug 预览包。签名每次可能变化，"
                                         +"不能保证覆盖安装保留数据；在线更新仅支持固定签名 Release。"
                                        :"官方 GitHub 发布源；验证 SHA-256、包名、版本及 APK 签名。"
                                         +"VLESS 更新通过本地 SOCKS5，不会静默直连；安装由 Android 确认。")
                                .setPositiveButton("知道了",null).show();
                    } else if(which==3)installVerifiedUpdate();
                })
                .setNegativeButton("关闭",null)
                .show();
    }

    private void checkForUpdates(boolean explicit) {
        if(updater==null)return;
        final AlertDialog dialog=new AlertDialog.Builder(this)
                .setTitle("正在检查 Glacier 更新")
                .setMessage("正在通过当前网络模式访问官方更新源…")
                .setCancelable(true).create();
        if(explicit)dialog.show();
        updater.check(proxyMode,(release,error)->{
            if(dialog.isShowing())dialog.dismiss();
            if(isFinishing())return;
            if(error!=null) {
                new AlertDialog.Builder(this)
                        .setTitle("未能检查更新")
                        .setMessage(error.getMessage()==null?"更新检查失败":error.getMessage())
                        .setPositiveButton("知道了",null).show();
            } else if(release==null) {
                new AlertDialog.Builder(this)
                        .setTitle("已是最新版本")
                        .setMessage("当前版本："+BuildConfig.VERSION_NAME)
                        .setPositiveButton("知道了",null).show();
            } else {
                showAvailableUpdate(release);
            }
        });
    }

    private void showAvailableUpdate(BrowserUpdater.Release release) {
        String size=String.format(java.util.Locale.ROOT,"%.1f MB",
                release.size/1024.0/1024.0);
        new AlertDialog.Builder(this)
                .setTitle("可更新到 Glacier "+release.version)
                .setMessage("安装包大小："+size
                        +"\n来源：官方 GitHub Releases"
                        +"\n将使用当前网络模式下载后验证 SHA-256、APK 版本和签名证书。"
                        +"\n\n只有验证成功才会打开 Android 系统安装器。")
                .setNegativeButton("取消",null)
                .setPositiveButton("下载并验证",(d,w)->startVerifiedDownload(release))
                .show();
    }

    private void startVerifiedDownload(BrowserUpdater.Release release) {
        if(updater==null)return;
        AtomicBoolean cancelled=new AtomicBoolean(false);
        LinearLayout layout=new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(dp(20),dp(16),dp(20),dp(12));
        TextView notice=new TextView(this);
        notice.setText("正在下载：0%");
        notice.setTextColor(INK);
        layout.addView(notice);
        ProgressBar bar=new ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal);
        bar.setMax(100);
        layout.addView(bar,new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,dp(20)));
        AlertDialog progress=new AlertDialog.Builder(this)
                .setTitle("Glacier 安全更新")
                .setView(layout)
                .setNegativeButton("取消",(d,w)->cancelled.set(true))
                .setOnCancelListener(d->cancelled.set(true))
                .create();
        progress.show();
        updater.download(release,proxyMode,cancelled,
                percent->{
                    if(progress.isShowing()) {
                        bar.setProgress(percent);
                        notice.setText("正在下载："+percent+"%");
                    }
                },
                (file,error)->{
                    if(progress.isShowing())progress.dismiss();
                    if(isFinishing())return;
                    if(error!=null) {
                        new AlertDialog.Builder(this)
                                .setTitle("更新未安装")
                                .setMessage(error.getMessage()==null?"下载或验证失败":error.getMessage())
                                .setPositiveButton("知道了",null).show();
                    } else {
                        new AlertDialog.Builder(this)
                                .setTitle("更新文件已经通过校验")
                                .setMessage("APK 的 SHA-256、包名、版本与安装签名均已验证。"
                                        +"\n点击安装将由 Android 系统再次询问。")
                                .setNegativeButton("稍后安装",null)
                                .setPositiveButton("系统安装",(d,w)->installVerifiedUpdate())
                                .show();
                    }
                });
    }

    private void installVerifiedUpdate() {
        if(updater==null||!updater.hasReady()) {
            android.widget.Toast.makeText(this,"当前没有已验证的 APK",
                    android.widget.Toast.LENGTH_SHORT).show();
            return;
        }
        try {
            if(!updater.requestInstall()) {
                android.widget.Toast.makeText(this,
                        "请在系统设置中允许此应用安装更新，然后返回菜单再次点安装",
                        android.widget.Toast.LENGTH_LONG).show();
            }
        } catch(Exception error) {
            new AlertDialog.Builder(this).setTitle("拒绝安装")
                    .setMessage(error.getMessage()==null?"更新 APK 再次校验失败":error.getMessage())
                    .setPositiveButton("知道了",null).show();
        }
    }

    private void restoreAccountVault() {
        try {
            accountCards.clear();
            accountCards.addAll(BrowserAccountsStore.load(this));
        } catch (Exception ignored) {
            // Never replace unreadable ciphertext with an empty vault.
            accountsReadonly = true;
            accountCards.clear();
        }
    }

    private boolean persistAccountVault(List<BrowserAccountsStore.Card> candidate) {
        if (accountsReadonly) return false;
        try {
            BrowserAccountsStore.save(this, candidate);
            accountCards.clear();
            accountCards.addAll(candidate);
            scheduleCloudAuto();
            return true;
        } catch (Exception ignored) {
            // No private account details ever enter logs.
            return false;
        }
    }

    private String currentAccountSite() {
        return active == null ? "" : BrowserAccountsStore.siteFromUrl(active.url);
    }

    private void copyAccountValue(String value) {
        android.content.ClipboardManager manager =
                (android.content.ClipboardManager)getSystemService(Context.CLIPBOARD_SERVICE);
        if (manager == null) return;
        manager.setPrimaryClip(android.content.ClipData.newPlainText("Glacier", value));
        tabSaveHandler.postDelayed(() -> {
            try {
                if (!manager.hasPrimaryClip()) return;
                CharSequence latest=manager.getPrimaryClip().getItemAt(0).coerceToText(this);
                if (value.contentEquals(latest)) manager.setPrimaryClip(
                        android.content.ClipData.newPlainText("Glacier", ""));
            } catch (Exception ignored) {}
        }, 30000);
        android.widget.Toast.makeText(this, "已复制，30 秒后自动清除",
                android.widget.Toast.LENGTH_SHORT).show();
    }

    private void maybePromptSiteAccount(Tab tab) {
        if(tab==null || tab!=active || isFinishing())return;
        final String site=BrowserAccountsStore.siteFromUrl(tab.url);
        if(site.isEmpty() || site.equals(tab.lastAccountPromptSite))return;
        boolean matched=false;
        for(BrowserAccountsStore.Card card:accountCards) {
            if(card.profile.equals(tab.profile) && card.site.equals(site)) {
                matched=true;
                break;
            }
        }
        if(!matched)return;
        tabSaveHandler.postDelayed(() -> {
            if(isFinishing() || tab!=active || !site.equals(
                    BrowserAccountsStore.siteFromUrl(tab.url))
                    || site.equals(tab.lastAccountPromptSite))return;
            List<BrowserAccountsStore.Card> matchedCards=new ArrayList<>();
            for(BrowserAccountsStore.Card card:accountCards) {
                if(card.profile.equals(tab.profile) && card.site.equals(site))
                    matchedCards.add(card);
            }
            if(matchedCards.isEmpty())return;
            tab.lastAccountPromptSite=site;
            String[] names=new String[matchedCards.size()];
            for(int i=0;i<matchedCards.size();i++)names[i]=matchedCards.get(i).name;
            new AlertDialog.Builder(this)
                    .setTitle("Glacier · "+site+" 的已保存账号")
                    .setItems(names,(dialog,which)->showAccountCard(matchedCards.get(which)))
                    .setNegativeButton("暂不使用",null).show();
        },350);
    }

    private void showAccountVault() {
        if (accountsReadonly) {
            new AlertDialog.Builder(this).setTitle("Glacier · 账号资料保护")
                    .setMessage("本机账号加密文件无法解密，已进入只读保护，原文件不会被覆盖。")
                    .setPositiveButton("知道了", null).show();
            return;
        }
        final String profile = active == null ? selectedProfile : active.profile;
        final String site = currentAccountSite();
        List<BrowserAccountsStore.Card> shown = new ArrayList<>();
        for (BrowserAccountsStore.Card card : accountCards) {
            if (profile.equals(card.profile)) shown.add(card);
        }
        String[] labels = new String[shown.size()];
        for (int i=0;i<shown.size();i++) {
            BrowserAccountsStore.Card c=shown.get(i);
            labels[i]=c.name+" · "+c.site;
        }
        String space = WORK.equals(profile) ? "工作空间" : "私人空间";
        AlertDialog.Builder builder = new AlertDialog.Builder(this)
                .setTitle("Glacier · "+space+"账号保险箱")
                .setItems(labels,(dialog,index)->showAccountCard(shown.get(index)))
                .setNegativeButton("关闭",null);
        if (!site.isEmpty()) {
            builder.setPositiveButton("添加当前网站账号",
                    (dialog,index)->editAccountCard(null,profile,site));
        }
        builder.show();
    }

    private EditText cardInput(LinearLayout layout,String label,String value,boolean secret) {
        TextView heading=new TextView(this);
        heading.setText(label);
        heading.setTextSize(13);
        heading.setTextColor(MUTED);
        layout.addView(heading);
        EditText field=new EditText(this);
        field.setSingleLine(true);
        field.setText(value);
        if(secret)field.setInputType(InputType.TYPE_CLASS_TEXT
                |InputType.TYPE_TEXT_VARIATION_PASSWORD);
        layout.addView(field,new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,dp(48)));
        return field;
    }

    private void editAccountCard(BrowserAccountsStore.Card original,String profile,String site) {
        if(accountsReadonly)return;
        LinearLayout form=new LinearLayout(this);
        form.setOrientation(LinearLayout.VERTICAL);
        form.setPadding(dp(20),dp(8),dp(20),0);
        EditText name=cardInput(form,"名称",
                original==null?"":original.name,false);
        EditText username=cardInput(form,"账号",
                original==null?"":original.username,false);
        EditText password=cardInput(form,"密码（可留空）",
                original==null?"":original.password,true);
        EditText api=cardInput(form,"接码 API HTTPS 地址（可留空）",
                original==null?"":original.codeApi,false);
        ScrollView scroll=new ScrollView(this);
        scroll.addView(form);
        new AlertDialog.Builder(this)
                .setTitle(original==null?"添加网站账号 · "+site:"编辑网站账号 · "+site)
                .setView(scroll)
                .setNegativeButton("取消",null)
                .setPositiveButton("加密保存",(d,which)->{
                    BrowserAccountsStore.Card updated=new BrowserAccountsStore.Card(
                            profile,site,name.getText().toString().trim(),
                            username.getText().toString(),password.getText().toString(),
                            api.getText().toString().trim());
                    if(!BrowserAccountsStore.valid(updated)) {
                        new AlertDialog.Builder(this).setMessage("账号字段或接码 API 地址不合法；未保存。")
                                .setPositiveButton("知道了",null).show();
                        return;
                    }
                    List<BrowserAccountsStore.Card> next=new ArrayList<>(accountCards);
                    if(original!=null)next.remove(original);
                    next.add(updated);
                    if(!persistAccountVault(next)) {
                        new AlertDialog.Builder(this).setMessage("加密保存失败；原有资料保持不变。")
                                .setPositiveButton("知道了",null).show();
                    } else {
                        android.widget.Toast.makeText(this,"账号已加密保存",
                                android.widget.Toast.LENGTH_SHORT).show();
                    }
                }).show();
    }

    private void showAccountCard(BrowserAccountsStore.Card card) {
        List<String> actions=new ArrayList<>();
        actions.add("复制账号");
        if(!card.password.isEmpty())actions.add("复制密码");
        if(!card.codeApi.isEmpty())actions.add("点击获取验证码");
        actions.add("编辑");
        actions.add("删除");
        new AlertDialog.Builder(this)
                .setTitle(card.name+" · "+card.site)
                .setItems(actions.toArray(new String[0]),(d,which)->{
                    String item=actions.get(which);
                    if("复制账号".equals(item))copyAccountValue(card.username);
                    else if("复制密码".equals(item))copyAccountValue(card.password);
                    else if("点击获取验证码".equals(item))fetchAccountCode(card.codeApi);
                    else if("编辑".equals(item))editAccountCard(card,card.profile,card.site);
                    else if("删除".equals(item)) {
                        new AlertDialog.Builder(this).setTitle("删除本机账号卡片")
                                .setMessage("删除后无法恢复。")
                                .setNegativeButton("取消",null)
                                .setPositiveButton("删除",(dialog,button)->{
                                    List<BrowserAccountsStore.Card> next=new ArrayList<>(accountCards);
                                    next.remove(card);
                                    if(!persistAccountVault(next)) {
                                        android.widget.Toast.makeText(this,"删除失败，原数据已保留",
                                                android.widget.Toast.LENGTH_LONG).show();
                                    }
                                }).show();
                    }
                }).setNegativeButton("关闭",null).show();
    }

    private void fetchAccountCode(String api) {
        if(!BrowserAccountsStore.validApi(api) || api.isEmpty())return;
        if(!proxyMode) {
            new AlertDialog.Builder(this).setMessage(
                    "接码 API 必须通过已经启动的 VLESS/SOCKS5 连接访问；当前未启用代理。")
                    .setPositiveButton("知道了",null).show();
            return;
        }
        accountCodeQueue.execute(() -> {
            String code="";
            try {
                java.net.Proxy proxy=new java.net.Proxy(java.net.Proxy.Type.SOCKS,
                        new java.net.InetSocketAddress("127.0.0.1",NativeProxy.PORT));
                java.net.HttpURLConnection connection=(java.net.HttpURLConnection)
                        new java.net.URL(api).openConnection(proxy);
                connection.setInstanceFollowRedirects(false);
                connection.setConnectTimeout(7500);
                connection.setReadTimeout(7500);
                connection.setUseCaches(false);
                try {
                    if(connection.getResponseCode()==200) {
                        java.io.InputStream input=connection.getInputStream();
                        java.io.ByteArrayOutputStream buffer=new java.io.ByteArrayOutputStream();
                        try(input) {
                            byte[] chunk=new byte[512];int n;
                            while((n=input.read(chunk))!=-1) {
                                if(buffer.size()+n>4096)throw new java.io.IOException("Response too large");
                                buffer.write(chunk,0,n);
                            }
                        }
                        code=parseAccountCode(buffer.toByteArray());
                    }
                } finally {connection.disconnect();}
            } catch(Exception ignored) {
                // Do not print OTP endpoints, credentials or response data.
            }
            final String result=code;
            runOnUiThread(() -> {
                if(isFinishing())return;
                if(result.isEmpty()) {
                    new AlertDialog.Builder(this).setMessage("接口未返回可识别的 4–10 位数字验证码。")
                            .setPositiveButton("知道了",null).show();
                } else {
                    copyAccountValue(result);
                }
            });
        });
    }

    private static String parseAccountCode(byte[] response) {
        if(response.length>4096)return "";
        String body=new String(response,java.nio.charset.StandardCharsets.UTF_8).trim();
        if(body.matches("[0-9]{4,10}"))return body;
        try {
            org.json.JSONObject payload=new org.json.JSONObject(body);
            for(int i=0;i<2;i++) {
                org.json.JSONObject obj=i==0?payload:payload.optJSONObject("data");
                if(obj==null)continue;
                for(String field:new String[]{"code","otp","verification_code","sms_code"}) {
                    String value=obj.optString(field,"");
                    if(value.matches("[0-9]{4,10}"))return value;
                }
            }
        } catch(Exception ignored) {}
        return "";
    }

    private interface CloudTask {
        String run() throws Exception;
    }

    private void cloudRun(CloudTask task) {
        if(!proxyMode) {
            new AlertDialog.Builder(this).setTitle("Glacier 云端账号")
                    .setMessage("当前不是 VLESS/SOCKS5 网络模式，已禁止同步直连。")
                    .setPositiveButton("知道了",null).show();
            return;
        }
        cloudQueue.execute(() -> {
            String message;
            try {
                message=task.run();
            } catch(Exception ignored) {
                // Never expose account IDs, access tokens, vault passphrases,
                // provider responses, or raw URL parameters to the UI/logs.
                message="同步操作未完成，请检查代理、设备授权与加密口令。";
            }
            final String output=message;
            runOnUiThread(() -> {
                if(isFinishing() || output==null)return;
                new AlertDialog.Builder(this).setTitle("Glacier 统一账号")
                        .setMessage(output).setPositiveButton("知道了",null).show();
            });
        });
    }

    private EditText cloudField(LinearLayout form,String label,String initial,boolean password) {
        TextView caption=new TextView(this);
        caption.setText(label);caption.setTextColor(MUTED);
        form.addView(caption);
        EditText input=new EditText(this);
        input.setSingleLine(true);
        input.setText(initial);
        if(password)input.setInputType(InputType.TYPE_CLASS_TEXT
                |InputType.TYPE_TEXT_VARIATION_PASSWORD);
        form.addView(input,new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,dp(52)));
        return input;
    }

    private void showCloudMenu() {
        if(cloudSessionReadonly) {
            new AlertDialog.Builder(this).setTitle("加密登录会话受保护")
                    .setMessage("旧的云端会话文件无法解密，原文件不会被覆盖。")
                    .setPositiveButton("知道了",null).show();
            return;
        }
        String[] actions={"注册 Glacier 账号","登录 / 申请设备授权","确认设备已获批准",
                "管理其他设备","加密上传当前账号空间","解密下载当前账号空间",
                "开启安全自动同步（本机加密保存口令）","关闭自动同步","退出 Glacier 账号"};
        new AlertDialog.Builder(this).setTitle("Glacier 统一账号 · "
                +(cloudState.username.isEmpty()?"未登录":cloudState.username))
                .setItems(actions,(dialog,which)->{
                    if(which==0||which==1)cloudPromptLogin(which==0);
                    else if(which==2)cloudActivate();
                    else if(which==3)cloudDevices();
                    else if(which==4||which==5)cloudPromptVault(which==4);
                    else if(which==6)cloudPromptAuto();
                    else if(which==7)cloudDisableAuto();
                    else cloudLogout();
                }).setNegativeButton("关闭",null).show();
    }

    private void cloudPromptLogin(boolean register) {
        LinearLayout form=new LinearLayout(this);
        form.setPadding(dp(22),dp(14),dp(22),0);
        form.setOrientation(LinearLayout.VERTICAL);
        EditText base=cloudField(form,"Glacier Sync HTTPS 服务器地址",
                cloudState.base.isEmpty()?"https://sync.borealos.cn":cloudState.base,false);
        EditText user=cloudField(form,"Glacier 账号 ID",
                cloudState.username,false);
        EditText pass=cloudField(form,"登录密码（至少 12 位）","",true);
        EditText invite=register?cloudField(form,"管理员注册邀请码","",true):null;
        ScrollView scroller=new ScrollView(this);scroller.addView(form);
        new AlertDialog.Builder(this)
                .setTitle(register?"创建 Glacier 账号":"登录 Glacier 账号")
                .setView(scroller)
                .setNegativeButton("取消",null)
                .setPositiveButton(register?"创建":"登录",(dialog,button)->{
                    final String server=GlacierCloudSync.validateBase(base.getText().toString());
                    final String username=user.getText().toString().trim();
                    final String password=pass.getText().toString();
                    final String invitation=register?invite.getText().toString():"";
                    if(server.isEmpty()||password.length()<12||username.length()<3) {
                        new AlertDialog.Builder(this).setMessage("HTTPS 地址、账号或密码不合法。")
                                .setPositiveButton("知道了",null).show();
                        return;
                    }
                    cloudRun(() -> {
                        GlacierCloudSync.State pending=new GlacierCloudSync.State();
                        pending.base=server;
                        JSONObject payload=new JSONObject();
                        payload.put("username",username);
                        payload.put("password",password);
                        payload.put("device_name",android.os.Build.MANUFACTURER+" "
                                +android.os.Build.MODEL);
                        if(register)payload.put("invite",invitation);
                        else if(!cloudState.deviceId.isEmpty()
                                &&!cloudState.deviceSecret.isEmpty()
                                &&username.equals(cloudState.username)
                                &&server.equals(cloudState.base)) {
                            payload.put("device_id",cloudState.deviceId);
                            payload.put("device_secret",cloudState.deviceSecret);
                        }
                        JSONObject response=GlacierCloudSync.call(pending,"POST",
                                register?"/v1/register":"/v1/login",payload);
                        GlacierCloudSync.State next=new GlacierCloudSync.State();
                        next.base=server;next.username=username;
                        next.token=response.getString("token");
                        next.deviceId=response.getString("device_id");
                        next.deviceSecret=response.optString("device_secret",
                                username.equals(cloudState.username)
                                &&server.equals(cloudState.base)?cloudState.deviceSecret:"");
                        next.approved=response.getBoolean("approved");
                        GlacierCloudSync.save(this,next);
                        cloudEpoch++;
                        cloudState=next;
                        return next.approved?"账号已登录，当前设备已授权。":
                                "登录成功，已提交新设备申请。请在已授权主设备中批准设备 ID："
                                        +next.deviceId;
                    });
                }).show();
    }

    private void cloudActivate() {
        cloudRun(() -> {
            JSONObject status=GlacierCloudSync.call(cloudState,"GET","/v1/session",null);
            if(!status.getBoolean("approved"))return "此设备仍在等待主设备批准。";
            if(status.optBoolean("pending",false)) {
                JSONObject approved=GlacierCloudSync.call(cloudState,"POST",
                        "/v1/session/activate",new JSONObject());
                cloudState.token=approved.getString("token");
                cloudState.approved=true;
                GlacierCloudSync.save(this,cloudState);
            }
            return "设备已授权；可以同步被允许的账号空间。";
        });
    }

    private void cloudDevices() {
        cloudRun(() -> {
            JSONObject response=GlacierCloudSync.call(cloudState,"GET","/v1/devices",null);
            JSONArray devices=response.getJSONArray("devices");
            String[] labels=new String[devices.length()];
            for(int i=0;i<devices.length();i++) {
                JSONObject d=devices.getJSONObject(i);
                labels[i]=d.optString("name","设备")+" · "+d.optString("id","").substring(0,10)
                        +(d.optBoolean("approved")?" · 已批准":" · 待批准");
            }
            runOnUiThread(() -> {
                if(isFinishing())return;
                new AlertDialog.Builder(this).setTitle("Glacier 已关联设备")
                        .setItems(labels,(dialog,index)->{
                            try {cloudDeviceAction(devices.optJSONObject(index));}
                            catch(Exception ignored) {}
                        }).setNegativeButton("关闭",null).show();
            });
            return null; // The device picker is the result; avoid a second dialog.
        });
    }

    private void cloudDeviceAction(JSONObject device) throws Exception {
        if(device==null)return;
        String id=device.getString("id");
        String[] actions={"批准新设备","允许私人空间","允许私人和工作空间","撤销设备"};
        new AlertDialog.Builder(this).setTitle(device.optString("name","设备"))
                .setItems(actions,(dialog,which)->{
                    if(which==3) {
                        new AlertDialog.Builder(this).setMessage("撤销后此设备无法再次同步，确定？")
                                .setNegativeButton("取消",null)
                                .setPositiveButton("撤销",(d,b)->cloudUpdateDevice(id,3))
                                .show();
                    } else cloudUpdateDevice(id,which);
                }).show();
    }

    private void cloudUpdateDevice(String id,int action) {
        cloudRun(() -> {
            String route="/v1/devices/"+id;
            if(action==0)GlacierCloudSync.call(cloudState,"POST",
                    route+"/approve",new JSONObject());
            else if(action==3)GlacierCloudSync.call(cloudState,"DELETE",route,null);
            else {
                JSONObject payload=new JSONObject();
                JSONArray spaces=new JSONArray();
                spaces.put("private");
                if(action==2)spaces.put("work");
                payload.put("spaces",spaces);
                GlacierCloudSync.call(cloudState,"PUT",route+"/grants",payload);
            }
            return "设备授权已更新。";
        });
    }

    private void cloudPromptAuto() {
        if(cloudSessionReadonly || cloudState.token.isEmpty() || !cloudState.approved) {
            new AlertDialog.Builder(this).setMessage("请先登录并批准当前设备。")
                    .setPositiveButton("知道了",null).show();
            return;
        }
        EditText password=new EditText(this);
        password.setSingleLine(true);
        password.setInputType(InputType.TYPE_CLASS_TEXT
                |InputType.TYPE_TEXT_VARIATION_PASSWORD);
        password.setHint("同步口令（至少 12 位）");
        LinearLayout form=new LinearLayout(this);
        form.setPadding(dp(22),dp(12),dp(22),0);
        form.addView(password);
        new AlertDialog.Builder(this)
                .setTitle("开启 Glacier 安全自动同步")
                .setMessage("每 3 分钟及本机账号变动后自动同步。"
                        +"同步口令仅用 Android Keystore 在本机加密保存，不上传服务器。"
                        +"双方都修改时停止覆盖；首次需手动上传或下载空间资料。")
                .setView(form).setNegativeButton("取消",null)
                .setPositiveButton("启用",(d,w)->{
                    String pass=password.getText().toString();
                    if(pass.length()<12) {
                        new AlertDialog.Builder(this).setMessage("同步口令至少 12 位，未启用。")
                                .setPositiveButton("知道了",null).show();
                        return;
                    }
                    try {
                        cloudState.autoEnabled=true;
                        cloudState.autoPassphrase=pass;
                        GlacierCloudSync.save(this,cloudState);
                        scheduleCloudAuto();
                        android.widget.Toast.makeText(this,"自动加密同步已开启",
                                android.widget.Toast.LENGTH_SHORT).show();
                    } catch(Exception ignored) {
                        cloudState.autoEnabled=false;
                        cloudState.autoPassphrase="";
                    }
                }).show();
    }

    private void cloudDisableAuto() {
        cloudEpoch++;
        cloudAutoHandler.removeCallbacks(cloudAutoTimer);
        cloudState.autoEnabled=false;
        cloudState.autoPassphrase="";
        try {
            GlacierCloudSync.save(this,cloudState);
            android.widget.Toast.makeText(this,"自动同步与本机同步口令已关闭",
                    android.widget.Toast.LENGTH_SHORT).show();
        } catch(Exception ignored) {
            new AlertDialog.Builder(this).setMessage("本机同步状态保存失败。")
                    .setPositiveButton("知道了",null).show();
        }
    }

    private void scheduleCloudAuto() {
        if(!cloudState.autoEnabled || !cloudState.approved
                || cloudState.autoPassphrase.length()<12)return;
        cloudAutoHandler.removeCallbacks(cloudAutoTimer);
        cloudAutoHandler.postDelayed(cloudAutoTimer,2500);
    }

    private void cloudMarkBaseline(String space,int version) {
        try {
            cloudSetBaseline(space,version,GlacierAutoSync.fingerprint(accountCards,space));
        } catch(Exception ignored) {}
    }

    private void cloudSetBaseline(String space,int version,String hash) {
        try {
            JSONObject item=new JSONObject();
            item.put("version",version);
            item.put("local_hash",hash);
            cloudState.baselines.put(space,item);
            GlacierCloudSync.save(this,cloudState);
        } catch(Exception ignored) {
            // Do not invalidate existing encrypted account cards if sync
            // session metadata cannot be saved.
        }
    }

    private void cloudAutoTick() {
        if(!proxyMode || cloudAutoBusy || !cloudState.autoEnabled
                || !cloudState.approved || cloudState.token.isEmpty()
                || cloudState.autoPassphrase.length()<12 || accountsReadonly)return;
        boolean hasBaseline=cloudState.baselines.has("private")
                ||cloudState.baselines.has("work");
        if(!hasBaseline)return;
        final GlacierCloudSync.State snapshot=new GlacierCloudSync.State();
        snapshot.base=cloudState.base;
        snapshot.username=cloudState.username;
        snapshot.token=cloudState.token;
        snapshot.deviceId=cloudState.deviceId;
        snapshot.deviceSecret=cloudState.deviceSecret;
        snapshot.autoPassphrase=cloudState.autoPassphrase;
        final int generation=cloudEpoch;
        final String device=snapshot.deviceId,account=snapshot.username;
        final List<BrowserAccountsStore.Card> cards=new ArrayList<>(accountCards);
        final JSONObject baselines;
        try {baselines=new JSONObject(cloudState.baselines.toString());}
        catch(Exception ignored) {return;}
        cloudAutoBusy=true;
        cloudQueue.execute(() -> {
            List<GlacierAutoSync.Result> outcome=new ArrayList<>();
            for(String space:new String[]{PRIVATE,WORK}) {
                if(!baselines.has(space))continue;
                try {
                    outcome.add(GlacierAutoSync.reconcile(
                            snapshot,space,cards,baselines.optJSONObject(space)));
                } catch(Exception ignored) {
                    outcome.add(new GlacierAutoSync.Result(
                            space,"failed",0,"",null));
                }
            }
            runOnUiThread(() -> {
                cloudAutoBusy=false;
                if(isFinishing() || generation!=cloudEpoch
                        || !cloudState.autoEnabled
                        || !device.equals(cloudState.deviceId)
                        || !account.equals(cloudState.username))return;
                for(GlacierAutoSync.Result event:outcome) {
                    if("conflict".equals(event.kind)) {
                        android.widget.Toast.makeText(this,
                                "Glacier "+event.space+"账号空间有同步冲突，已禁止覆盖",
                                android.widget.Toast.LENGTH_LONG).show();
                    } else if("uploaded".equals(event.kind)) {
                        try {
                            JSONObject updated=new JSONObject();
                            updated.put("version",event.version);
                            updated.put("local_hash",event.localHash);
                            cloudState.baselines.put(event.space,updated);
                            GlacierCloudSync.save(this,cloudState);
                        } catch(Exception ignored) {}
                    } else if("downloaded".equals(event.kind)) {
                        try {
                            // If a local edit landed during the request, do not
                            // overwrite it with an older remote snapshot.
                            if(!GlacierAutoSync.fingerprint(accountCards,event.space)
                                    .equals(event.localHash))continue;
                            List<BrowserAccountsStore.Card> merged=new ArrayList<>();
                            for(BrowserAccountsStore.Card existing:accountCards)
                                if(!event.space.equals(existing.profile))merged.add(existing);
                            merged.addAll(event.cards);
                            if(persistAccountVault(merged))
                                cloudMarkBaseline(event.space,event.version);
                        } catch(Exception ignored) {}
                    }
                }
            });
        });
    }

    private void cloudPromptVault(boolean push) {
        final String space=active==null?selectedProfile:active.profile;
        EditText secret=new EditText(this);
        secret.setSingleLine(true);
        secret.setHint("云端保险箱加密口令（至少 12 位）");
        secret.setInputType(InputType.TYPE_CLASS_TEXT
                |InputType.TYPE_TEXT_VARIATION_PASSWORD);
        LinearLayout layout=new LinearLayout(this);
        layout.setPadding(dp(22),dp(14),dp(22),0);
        layout.addView(secret);
        new AlertDialog.Builder(this)
                .setTitle(push?"加密上传当前空间":"解密下载当前空间")
                .setMessage("只处理"+(WORK.equals(space)?"工作":"私人")
                        +"空间。云端仅接收密文，不保存加密口令。"
                        +(push?"已有远端数据将更新为本地版本。":"本地对应空间的账号将被替换。"))
                .setView(layout)
                .setNegativeButton("取消",null)
                .setPositiveButton(push?"加密上传":"下载并替换",(d,w)->{
                    final String password=secret.getText().toString();
                    if(password.length()<12) {
                        new AlertDialog.Builder(this).setMessage("加密口令至少 12 位，未执行。")
                                .setPositiveButton("知道了",null).show();
                        return;
                    }
                    if(push)cloudPush(space,password);
                    else cloudPull(space,password);
                }).show();
    }

    private void cloudPush(String space,String password) {
        final List<BrowserAccountsStore.Card> snapshot=new ArrayList<>();
        for(BrowserAccountsStore.Card card:accountCards)
            if(space.equals(card.profile))snapshot.add(card);
        final String uploadedHash;
        try {uploadedHash=GlacierAutoSync.fingerprint(snapshot,space);}
        catch(Exception ignored) {return;}
        cloudRun(() -> {
            JSONObject remote=GlacierCloudSync.call(cloudState,"GET",
                    "/v1/vault/"+space,null);
            int version=remote.getInt("version");
            String envelope=GlacierCloudSync.encrypt(space,snapshot,password);
            JSONObject body=new JSONObject();
            body.put("expected_version",version);
            body.put("envelope",envelope);
            JSONObject result=GlacierCloudSync.call(cloudState,"PUT",
                    "/v1/vault/"+space,body);
            int confirmed=result.getInt("version");
            runOnUiThread(() -> {
                if(!isFinishing())cloudSetBaseline(space,confirmed,uploadedHash);
            });
            return "当前账号空间已端到端加密同步。";
        });
    }

    private void cloudPull(String space,String password) {
        final String beforeDownload;
        try {beforeDownload=GlacierAutoSync.fingerprint(accountCards,space);}
        catch(Exception ignored) {return;}
        if(accountsReadonly) {
            new AlertDialog.Builder(this).setMessage("本机账号资料处于只读保护，未覆盖。")
                    .setPositiveButton("知道了",null).show();
            return;
        }
        cloudRun(() -> {
            JSONObject remote=GlacierCloudSync.call(cloudState,"GET",
                    "/v1/vault/"+space,null);
            if(remote.isNull("envelope"))return "该账号空间尚未上传云端资料。";
            final List<BrowserAccountsStore.Card> received=GlacierCloudSync.decrypt(
                    space,remote.getString("envelope"),password);
            runOnUiThread(() -> {
                if(isFinishing())return;
                try {
                    if(!beforeDownload.equals(GlacierAutoSync.fingerprint(accountCards,space))) {
                        new AlertDialog.Builder(this).setMessage(
                                "同步期间本机账号发生修改，已拒绝用旧下载数据覆盖。")
                                .setPositiveButton("知道了",null).show();
                        return;
                    }
                } catch(Exception ignored) {return;}
                List<BrowserAccountsStore.Card> merged=new ArrayList<>();
                for(BrowserAccountsStore.Card old:accountCards)
                    if(!space.equals(old.profile))merged.add(old);
                merged.addAll(received);
                boolean saved=persistAccountVault(merged);
                if(saved)cloudMarkBaseline(space,remote.optInt("version",0));
                new AlertDialog.Builder(this).setTitle("Glacier 加密同步")
                        .setMessage(saved?"账号空间已成功下载并加密保存到本机。":
                                "本地保存失败，原有账号资料未更改。")
                        .setPositiveButton("知道了",null).show();
            });
            return null;
        });
    }

    private void cloudLogout() {
        cloudRun(() -> {
            try {GlacierCloudSync.call(cloudState,"POST",
                    "/v1/logout",new JSONObject());}
            catch(Exception ignored) {}
            cloudEpoch++;
            cloudAutoHandler.removeCallbacks(cloudAutoTimer);
            cloudState.token="";
            cloudState.approved=false;
            cloudState.autoEnabled=false;
            cloudState.autoPassphrase="";
            cloudState.baselines=new JSONObject();
            GlacierCloudSync.save(this,cloudState);
            return "已退出同步账号。本机已保存账号不受影响。";
        });
    }

    private void showBrowserMenu() {
        final List<String> actions = new ArrayList<>();
        actions.add("新建标签页");
        actions.add("刷新");
        actions.add("后退");
        actions.add("前进");
        actions.add(isCurrentBookmarked() ? "取消收藏此页" : "收藏当前页面");
        actions.add("书签");
        actions.add("管理书签");
        actions.add("历史记录");
        actions.add("下载记录");
        actions.add("更新与版本");
        actions.add("切换账号空间");
        actions.add("网站账号保险箱");
        actions.add("Glacier 统一账号与同步");
        actions.add("网络连接信息");
        actions.add("打开 ChatGPT");
        actions.add("打开 GitHub");
        actions.add("打开 Gecko 内核信息");
        actions.add("测试说明");
        if (debugBuild() && !proxyMode) {
            actions.add("内部测试工具");
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
                    } else if ("收藏当前页面".equals(item)
                            || "取消收藏此页".equals(item)) {
                        toggleBookmark();
                    } else if ("书签".equals(item)) {
                        showLibraryList("bookmarks",false);
                    } else if ("管理书签".equals(item)) {
                        showLibraryList("bookmarks",true);
                    } else if ("历史记录".equals(item)) {
                        showLibraryList("history",false);
                    } else if ("下载记录".equals(item)) {
                        showLibraryList("downloads",false);
                    } else if ("更新与版本".equals(item)) {
                        showUpdatePanel();
                    } else if ("切换账号空间".equals(item)) {
                        chooseProfile();
                    } else if ("网站账号保险箱".equals(item)) {
                        showAccountVault();
                    } else if ("Glacier 统一账号与同步".equals(item)) {
                        showCloudMenu();
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
                    } else if ("内部测试工具".equals(item)
                            && debugBuild() && !proxyMode) {
                        showInternalTestMenu();
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
                // Preserve real site titles for the tab grid, without logging
                // browsing history or touching profile isolation.
                Tab titledTab = findBySession(source);
                if (titledTab != null && title != null && !title.isEmpty()
                        && !"about:blank".equals(title)
                        && !title.startsWith("GLACIER_TEST_")) {
                    titledTab.title = title.length() > 65
                            ? title.substring(0, 65) + "…" : title;
                    reviseRecentHistoryTitle(titledTab);
                }
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
                Tab owner = findBySession(source);
                transfers.onExternalResponse(response,
                        owner == null ? null : owner.profile);
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
        session.setProgressDelegate(new GeckoSession.ProgressDelegate() {
                private String testSite;

                @Override
                public void onPageStart(GeckoSession source, String url) {
                    if (!debugBuild()) return;
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
                    if (debugBuild() && testSite != null) {
                        android.util.Log.i("GlacierSmoke",
                                "PAGE_STOP site=" + testSite + " success=" + success);
                    }
                    testSite = null;
                    if (success) {
                        Tab target = findBySession(source);
                        if (target != null) {
                            rememberVisit(target);
                            maybePromptSiteAccount(target);
                            if(cloudState.autoEnabled && !cloudAutoBusy)
                                scheduleCloudAuto();
                            tabSaveHandler.postDelayed(
                                    () -> captureTabThumbnail(target), 950);
                        }
                    }
                }

                @Override
                public void onSessionStateChange(GeckoSession source,
                                                 GeckoSession.SessionState state) {
                    Tab target = findBySession(source);
                    if (target == null || state == null) return;
                    String serialized = state.toString();
                    if (serialized != null && serialized.length() <= 256 * 1024) {
                        target.geckoState = serialized;
                        scheduleTabsSave();
                    }
                }
            });
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
                    // Opening a GeckoSession can emit a transient about:blank
                    // location before its saved history has been restored.
                    // Never let it overwrite a persisted HTTPS tab.
                    if ("about:blank".equals(url) && t.expectedRestoreUrl != null
                            && !"about:blank".equals(t.expectedRestoreUrl)) return;
                    if (!"about:blank".equals(url)) t.expectedRestoreUrl = null;
                    String nextAccountSite=BrowserAccountsStore.siteFromUrl(url);
                    if(!nextAccountSite.equals(BrowserAccountsStore.siteFromUrl(t.url)))
                        t.lastAccountPromptSite="";
                    t.url = url;
                    t.title = url.length() > 40 ? url.substring(0, 40) + "…" : url;
                    if (t == active) updateChrome();
                    scheduleTabsSave();
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
        t.url = url;
        t.title = "about:blank".equals(url) ? "新标签页" : url;
        switchTo(t);
        t.session.loadUri(url);
        updateChrome();
        scheduleTabsSave();
    }

    private void switchTo(Tab next) {
        if (next == active) return;
        if (active != null) {
            captureTabThumbnail(active);
            active.session.setActive(false);
        }
        if (web.getSession() != null) web.releaseSession();
        active = next;
        selectedProfile = next.profile;
        web.setSession(next.session);
        next.session.setActive(true);
        maybePromptSiteAccount(next);
        if (next.pendingRestore) {
            next.pendingRestore = false;
            boolean usedState = false;
            if (next.geckoState != null && !next.geckoState.isEmpty()) {
                try {
                    GeckoSession.SessionState previous =
                            GeckoSession.SessionState.fromString(next.geckoState);
                    if (previous != null && previous.size() > 0) {
                        next.session.restoreState(previous);
                        if (!"about:blank".equals(next.url)) {
                            // Gecko history restoration is async. Only reload
                            // after a short delay if no real location change
                            // arrived; preserve the old history if it did.
                            String targetUrl = next.url;
                            tabSaveHandler.postDelayed(() -> {
                                if (next == active && targetUrl.equals(next.expectedRestoreUrl)
                                        && targetUrl.equals(next.url)) {
                                    next.session.loadUri(targetUrl);
                                }
                            }, 1400);
                        }
                        usedState = true;
                    }
                } catch (Exception ignored) {
                    // Corrupt session history must not prevent basic URL restore.
                }
            }
            if (!usedState) next.session.loadUri(next.url);
        }
        updateChrome();
        scheduleTabsSave();
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
            if (!address.hasFocus()) address.setText(
                    "about:blank".equals(active.url) ? "" : active.url);
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
        if (tabs.isEmpty() || tabOverview == null) return;
        captureTabThumbnail(active);
        // Full-screen grid like the Android Chrome switcher, not a small
        // clipped AlertDialog. Data is an in-memory per-tab placeholder;
        // M03 will add persistent thumbnails and session restoration.
        tabOverview.removeAllViews();
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setBackgroundColor(PALE);

        LinearLayout header = horizontal();
        header.setPadding(dp(20), dp(10), dp(14), dp(10));
        TextView title = new TextView(this);
        title.setText("标签页 · " + tabs.size());
        title.setTextSize(20);
        title.setTextColor(INK);
        title.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        header.addView(title, new LinearLayout.LayoutParams(0, dp(49), 1));

        Button add = button("+");
        add.setTextSize(26);
        add.setTextColor(GLACIER_BLUE);
        add.setContentDescription("新建标签页");
        add.setOnClickListener(v -> {
            tabOverview.setVisibility(View.GONE);
            openTab(selectedProfile, "about:blank");
        });
        header.addView(add, new LinearLayout.LayoutParams(dp(45), dp(45)));

        Button dismiss = button("×");
        dismiss.setTextSize(25);
        dismiss.setContentDescription("返回浏览器");
        dismiss.setOnClickListener(v -> tabOverview.setVisibility(View.GONE));
        LinearLayout.LayoutParams dismissParams =
                new LinearLayout.LayoutParams(dp(45), dp(45));
        dismissParams.setMargins(dp(8), 0, 0, 0);
        header.addView(dismiss, dismissParams);
        page.addView(header);

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        GridLayout grid = new GridLayout(this);
        grid.setColumnCount(2);
        grid.setPadding(dp(8), dp(8), dp(8), dp(12));
        int screenWidth = getResources().getDisplayMetrics().widthPixels;
        int cardWidth = (screenWidth - dp(62)) / 2;

        for (Tab tab : new ArrayList<>(tabs)) {
            LinearLayout tile = new LinearLayout(this);
            tile.setOrientation(LinearLayout.VERTICAL);
            tile.setPadding(dp(10), dp(8), dp(10), dp(10));
            tile.setBackground(surfaceBorder(Color.WHITE, 18,
                    tab == active ? GLACIER_BLUE : HAIRLINE));
            tile.setContentDescription("标签卡片 · " + tab.title);

            LinearLayout cardHeader = horizontal();
            cardHeader.setPadding(0, 0, 0, 0);
            TextView marker = new TextView(this);
            marker.setText("◉");
            marker.setTextColor(GLACIER_BLUE);
            marker.setTextSize(17);
            cardHeader.addView(marker, new LinearLayout.LayoutParams(dp(23), dp(28)));

            TextView caption = new TextView(this);
            caption.setSingleLine(true);
            caption.setEllipsize(android.text.TextUtils.TruncateAt.END);
            caption.setText(tab.title);
            caption.setTextSize(12);
            caption.setTextColor(INK);
            cardHeader.addView(caption, new LinearLayout.LayoutParams(0, dp(32), 1));

            Button close = button("×");
            close.setTextSize(20);
            close.setContentDescription("关闭标签页");
            close.setOnClickListener(v -> {
                closeTab(tab);
                showTabs();
            });
            cardHeader.addView(close, new LinearLayout.LayoutParams(dp(33), dp(33)));
            tile.addView(cardHeader);

            FrameLayout previewFrame = new FrameLayout(this);
            previewFrame.setBackground(surface(PALE, 12));
            if (tab.thumbnail != null && tab.thumbnail.length > 0) {
                try {
                    Bitmap bitmap = BitmapFactory.decodeByteArray(
                            tab.thumbnail, 0, tab.thumbnail.length);
                    if (bitmap != null) {
                        ImageView preview = new ImageView(this);
                        preview.setImageBitmap(bitmap);
                        preview.setScaleType(ImageView.ScaleType.CENTER_CROP);
                        previewFrame.addView(preview, new FrameLayout.LayoutParams(
                                FrameLayout.LayoutParams.MATCH_PARENT,
                                FrameLayout.LayoutParams.MATCH_PARENT));
                    }
                } catch (Exception ignored) {
                    // Malformed preview should simply show the fallback.
                }
            }
            if (previewFrame.getChildCount() == 0) {
                TextView placeholder = new TextView(this);
                placeholder.setText("❄");
                placeholder.setTextSize(39);
                placeholder.setTextColor(GLACIER_BLUE);
                placeholder.setGravity(Gravity.CENTER);
                previewFrame.addView(placeholder, new FrameLayout.LayoutParams(
                        FrameLayout.LayoutParams.MATCH_PARENT,
                        FrameLayout.LayoutParams.MATCH_PARENT));
            }
            tile.addView(previewFrame, new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, 0, 1));

            TextView domain = new TextView(this);
            domain.setText(WORK.equals(tab.profile) ? "工作 · " + tab.url
                    : "私人 · " + tab.url);
            domain.setSingleLine(true);
            domain.setEllipsize(android.text.TextUtils.TruncateAt.END);
            domain.setTextSize(10);
            domain.setTextColor(MUTED);
            tile.addView(domain, new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, dp(25)));

            tile.setOnClickListener(v -> {
                tabOverview.setVisibility(View.GONE);
                switchTo(tab);
            });
            GridLayout.LayoutParams cell = new GridLayout.LayoutParams();
            cell.width = cardWidth;
            cell.height = dp(190);
            cell.setMargins(dp(5), dp(5), dp(5), dp(5));
            grid.addView(tile, cell);
        }

        scroll.addView(grid);
        page.addView(scroll, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1));
        tabOverview.addView(page, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));
        tabOverview.setVisibility(View.VISIBLE);
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
        scheduleTabsSave();
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
        active.url = url;
        active.title = url;
        active.session.loadUri(url);
        scheduleTabsSave();
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
            // Synthetic offline/mock SOCKS CI uses a known fixture URL and
            // must never read a previous tab snapshot from another network.
            String ciNetwork = getIntent().getStringExtra("glacier.ci.network");
            if (!"offline-socks".equals(ciNetwork) && !"mock-socks".equals(ciNetwork)
                    && restoreSavedTabs()) {
                // Persisted sessions retain their original Gecko context IDs.
            } else {
                openTab(PRIVATE, bootUrl);
            }
            if (!debugBuild()) {
                tabSaveHandler.postDelayed(this::maybeCheckUpdatesAtStartup, 5000);
            }
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
                        + "\n\n已提供本机加密账号保险箱与点击获取验证码 API；尚未提供自动登录、云同步或完整设备权限管理。"
                        + "\n\n直连模式仅用于对照测试；VLESS 模式必须验证真实出口。请勿输入关键账号。")
                .setPositiveButton("知道了", null)
                .show();
    }

    @Override
    public void onBackPressed() {
        if (tabOverview != null && tabOverview.getVisibility() == View.VISIBLE) {
            tabOverview.setVisibility(View.GONE);
            return;
        }
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
    protected void onStop() {
        tabSaveHandler.removeCallbacks(saveTabsTask);
        persistTabs();
        libraryHandler.removeCallbacks(saveLibraryTask);
        persistLibrary();
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        tabSaveHandler.removeCallbacks(saveTabsTask);
        libraryHandler.removeCallbacks(saveLibraryTask);
        if (isFinishing()) {
            librarySaveQueue.shutdown();
            try {
                librarySaveQueue.awaitTermination(1600, java.util.concurrent.TimeUnit.MILLISECONDS);
                BrowserLibraryStore.save(this,libraryState.copy());
            } catch(Exception ignored) {
                // No browsing metadata in logs.
            }
        }
        if (isFinishing() && !tabs.isEmpty()) {
            try {
                // This path deliberately terminates the process, so flush
                // synchronously before Gecko sessions are closed.
                BrowserTabStore.save(this, snapshotTabs());
            } catch (Exception ignored) {
                // Never log browsing metadata.
            }
        }
        if (isFinishing()) accountCodeQueue.shutdownNow();
        if (isFinishing()) {
            cloudEpoch++;
            cloudAutoHandler.removeCallbacks(cloudAutoTimer);
            cloudQueue.shutdownNow();
        }
        if (transfers != null && isFinishing()) transfers.dispose();
        if (updater != null && isFinishing()) updater.dispose();
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
