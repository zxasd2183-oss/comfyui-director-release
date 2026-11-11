package cn.borealos.glacier.geckopreview;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.AtomicFile;
import android.util.Base64;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.KeyStore;
import java.util.ArrayList;
import java.util.List;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * Encrypted, crash-resilient snapshot of browser tabs only.
 * All URLs, Gecko session states (including optional form state), titles and
 * thumbnails stay in an authenticated AES-GCM blob in the no-backup directory.
 * Uses an independent non-exportable Android Keystore key, never the VLESS key.
 */
final class BrowserTabStore {
    private static final String FILENAME = "glacier-tabs-v1.bin";
    private static final String KEY = "glacier_tabs_aes_gcm_v1";
    private static final int LIMIT = 25;
    private static final int MAX_STATE = 256 * 1024;
    private static final int MAX_THUMB = 50 * 1024;
    private static final int MAX_CIPHERTEXT = 3 * 1024 * 1024;
    private static final byte[] AAD =
            "cn.borealos.glacier.tab-store.v1".getBytes(StandardCharsets.UTF_8);

    static final class TabRecord {
        String id, profile, url, title, state;
        byte[] thumb;
        TabRecord(String id, String profile, String url, String title,
                  String state, byte[] thumb) {
            this.id = id;
            this.profile = profile;
            this.url = url;
            this.title = title;
            this.state = state;
            this.thumb = thumb;
        }
    }

    static final class Snapshot {
        String activeId;
        final List<TabRecord> tabs = new ArrayList<>();
    }

    private BrowserTabStore() {}

    private static AtomicFile file(Context ctx) {
        File dir = ctx.getApplicationContext().getNoBackupFilesDir();
        return new AtomicFile(new File(dir, FILENAME));
    }

    private static SecretKey key(boolean create) throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (store.containsAlias(KEY)) {
            java.security.Key found = store.getKey(KEY, null);
            if (!(found instanceof SecretKey)) throw new GeneralSecurityException("Invalid tab key");
            return (SecretKey) found;
        }
        if (!create) throw new GeneralSecurityException("Missing tab key");
        KeyGenerator generator = KeyGenerator.getInstance(
                KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(KEY,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .setUserAuthenticationRequired(false)
                .setKeySize(256).build());
        return generator.generateKey();
    }

    static boolean validUrl(String url) {
        if (url == null || url.length() > 2048) return false;
        if ("about:blank".equals(url)) return true;
        // Do not reopen the localhost-only CI fixtures or unsupported schemes.
        try {
            android.net.Uri parsed = android.net.Uri.parse(url);
            return "https".equalsIgnoreCase(parsed.getScheme())
                    && parsed.getHost() != null && !parsed.getHost().isEmpty();
        } catch (Exception ex) {
            return false;
        }
    }

    private static JSONObject serialize(Snapshot snapshot) throws Exception {
        JSONObject out = new JSONObject();
        out.put("version", 1);
        out.put("active", snapshot.activeId == null ? "" : snapshot.activeId);
        JSONArray entries = new JSONArray();
        for (TabRecord item : snapshot.tabs) {
            if (entries.length() >= LIMIT) break;
            if (!validUrl(item.url)) continue;
            if (!"private".equals(item.profile) && !"work".equals(item.profile)) continue;
            JSONObject obj = new JSONObject();
            obj.put("id", item.id);
            obj.put("profile", item.profile);
            obj.put("url", item.url);
            obj.put("title", item.title == null ? "" : item.title);
            if (item.state != null && item.state.length() <= MAX_STATE) {
                obj.put("state", item.state);
            }
            if (item.thumb != null && item.thumb.length <= MAX_THUMB) {
                obj.put("thumb", Base64.encodeToString(item.thumb, Base64.NO_WRAP));
            }
            entries.put(obj);
        }
        out.put("tabs", entries);
        return out;
    }

    static synchronized void save(Context ctx, Snapshot snapshot) throws Exception {
        byte[] plaintext = serialize(snapshot).toString().getBytes(StandardCharsets.UTF_8);
        if (plaintext.length > MAX_CIPHERTEXT - 128)
            throw new GeneralSecurityException("Tab snapshot too large");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key(true));
        cipher.updateAAD(AAD);
        byte[] iv = cipher.getIV();
        byte[] ciphertext = cipher.doFinal(plaintext);
        ByteBuffer buffer = ByteBuffer.allocate(4 + 12 + ciphertext.length);
        buffer.putInt(1).put(iv).put(ciphertext);
        AtomicFile f = file(ctx);
        FileOutputStream stream = null;
        try {
            stream = f.startWrite();
            stream.write(buffer.array());
            f.finishWrite(stream);
        } catch (Exception e) {
            if (stream != null) f.failWrite(stream);
            throw e;
        }
    }

    static synchronized Snapshot load(Context ctx) throws Exception {
        Snapshot result = new Snapshot();
        AtomicFile f = file(ctx);
        if (!f.getBaseFile().exists()) return result;
        byte[] source = f.readFully();
        if (source.length < 4 + 12 + 16 || source.length > MAX_CIPHERTEXT)
            throw new GeneralSecurityException("Tab data invalid");
        ByteBuffer buffer = ByteBuffer.wrap(source);
        if (buffer.getInt() != 1) throw new GeneralSecurityException("Unsupported tabs format");
        byte[] iv = new byte[12], encrypted = new byte[buffer.remaining() - 12];
        buffer.get(iv);
        buffer.get(encrypted);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(false), new GCMParameterSpec(128, iv));
        cipher.updateAAD(AAD);
        JSONObject json = new JSONObject(new String(
                cipher.doFinal(encrypted), StandardCharsets.UTF_8));
        if (json.optInt("version") != 1)
            throw new GeneralSecurityException("Unsupported tab snapshot version");
        result.activeId = json.optString("active");
        JSONArray rows = json.optJSONArray("tabs");
        if (rows == null) return result;
        for (int i = 0; i < rows.length() && result.tabs.size() < LIMIT; i++) {
            JSONObject row = rows.optJSONObject(i);
            if (row == null) continue;
            String profile = row.optString("profile");
            String url = row.optString("url");
            String id = row.optString("id");
            if (!validUrl(url) || !("private".equals(profile) || "work".equals(profile))
                    || id.length() < 8 || id.length() > 100) continue;
            String state = row.optString("state", "");
            if (state.length() > MAX_STATE) state = "";
            byte[] thumb = null;
            try {
                thumb = Base64.decode(row.optString("thumb", ""), Base64.NO_WRAP);
                if (thumb.length > MAX_THUMB) thumb = null;
            } catch (Exception ignored) {
                thumb = null;
            }
            result.tabs.add(new TabRecord(id, profile, url, row.optString("title"),
                    state, thumb));
        }
        return result;
    }
}
