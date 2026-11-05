package cn.borealos.glacier.geckopreview;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * v0.2 local metadata only: bookmarks, history and URL-only tab restoration.
 * Stored in Android app-private SharedPreferences, separated by Gecko context.
 *
 * Cookie / localStorage are NOT copied or managed here: GeckoView owns those,
 * isolated by GeckoSessionSettings.contextId("glacier-" + profile).
 *
 * No passwords, OTPs, search terms, URL queries or fragments are stored.
 */
public final class BrowserStore {
    public static final String PRIVATE = "private";
    public static final String WORK = "work";
    private static final int MAX_HISTORY = 100;
    private static final int MAX_BOOKMARKS = 120;
    private static final int MAX_TABS = 24;

    public static final class Entry {
        public final String url;
        public final String title;

        public Entry(String url, String title) {
            this.url = url;
            this.title = UrlPolicy.label(title, url);
        }
    }

    private final Context app;

    public BrowserStore(Context context) {
        app = context.getApplicationContext();
    }

    private SharedPreferences prefs(String profile) {
        if (!PRIVATE.equals(profile) && !WORK.equals(profile)) {
            throw new IllegalArgumentException("Unknown Glacier identity");
        }
        return app.getSharedPreferences("glacier_android_v02_" + profile,
                Context.MODE_PRIVATE);
    }

    public String lastProfile() {
        String profile = app.getSharedPreferences("glacier_android_v02_general",
                Context.MODE_PRIVATE).getString("selected_profile", PRIVATE);
        return WORK.equals(profile) ? WORK : PRIVATE;
    }

    public void setLastProfile(String profile) {
        prefs(profile); // validate identity
        app.getSharedPreferences("glacier_android_v02_general", Context.MODE_PRIVATE)
                .edit().putString("selected_profile", profile).apply();
    }

    private List<Entry> readList(String profile, String key, int limit) {
        List<Entry> result = new ArrayList<>();
        String raw = prefs(profile).getString(key, "[]");
        try {
            JSONArray array = new JSONArray(raw);
            for (int i = 0; i < array.length() && result.size() < limit; i++) {
                JSONObject object = array.optJSONObject(i);
                if (object == null) continue;
                String safeUrl = UrlPolicy.safePersistentUrl(object.optString("url", ""));
                if (safeUrl == null) continue;
                result.add(new Entry(safeUrl, object.optString("title", "")));
            }
        } catch (JSONException ignored) {
            // Corrupt local metadata should not crash the browser or mix profiles.
        }
        return result;
    }

    private void writeList(String profile, String key, List<Entry> entries, int limit) {
        JSONArray json = new JSONArray();
        int count = 0;
        for (Entry entry : entries) {
            if (count >= limit) break;
            String safe = UrlPolicy.safePersistentUrl(entry.url);
            if (safe == null) continue;
            JSONObject row = new JSONObject();
            try {
                row.put("url", safe);
                row.put("title", UrlPolicy.label(entry.title, safe));
                json.put(row);
                count++;
            } catch (JSONException ignored) {
                // Ignore malformed metadata, never throw into GeckoView callbacks.
            }
        }
        prefs(profile).edit().putString(key, json.toString()).apply();
    }

    public List<Entry> tabs(String profile) {
        return readList(profile, "tabs", MAX_TABS);
    }

    public void saveTabs(String profile, List<Entry> entries) {
        writeList(profile, "tabs", entries, MAX_TABS);
    }

    public List<Entry> bookmarks(String profile) {
        return readList(profile, "bookmarks", MAX_BOOKMARKS);
    }

    public boolean isBookmarked(String profile, String url) {
        String safe = UrlPolicy.safePersistentUrl(url);
        if (safe == null) return false;
        for (Entry e : bookmarks(profile)) {
            if (e.url.equals(safe)) return true;
        }
        return false;
    }

    public boolean toggleBookmark(String profile, String url, String title) {
        String safe = UrlPolicy.safePersistentUrl(url);
        if (safe == null) return false;
        List<Entry> entries = bookmarks(profile);
        for (int i = 0; i < entries.size(); i++) {
            if (entries.get(i).url.equals(safe)) {
                entries.remove(i);
                writeList(profile, "bookmarks", entries, MAX_BOOKMARKS);
                return false;
            }
        }
        entries.add(0, new Entry(safe, title));
        writeList(profile, "bookmarks", entries, MAX_BOOKMARKS);
        return true;
    }

    public List<Entry> history(String profile) {
        return readList(profile, "history", MAX_HISTORY);
    }

    public void addHistory(String profile, String url, String title) {
        String safe = UrlPolicy.safePersistentUrl(url);
        if (safe == null) return;
        List<Entry> entries = history(profile);
        for (int i = entries.size() - 1; i >= 0; i--) {
            if (entries.get(i).url.equals(safe)) entries.remove(i);
        }
        entries.add(0, new Entry(safe, title));
        writeList(profile, "history", entries, MAX_HISTORY);
    }

    public void clearHistory(String profile) {
        prefs(profile).edit().remove("history").apply();
    }
}
