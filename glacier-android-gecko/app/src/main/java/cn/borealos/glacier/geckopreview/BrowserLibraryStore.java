package cn.borealos.glacier.geckopreview;

import android.content.Context;
import android.net.Uri;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.AtomicFile;

import org.json.JSONArray;
import org.json.JSONObject;

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
 * M04: encrypted, no-backup browser library (bookmarks, visit history,
 * finished-download metadata). Download file bytes are never duplicated
 * into this database; actual files remain in user-selected SAF locations.
 *
 * Profiles are explicit on every record. UI must filter by profile, not
 * assume whichever account happens to be selected when a callback returns.
 */
final class BrowserLibraryStore {
    private static final String KEY = "glacier_library_aes_gcm_v1";
    private static final String NAME = "glacier-library-v1.bin";
    private static final int MAX_SIZE = 2 * 1024 * 1024;
    private static final int MAX_BOOKMARKS = 160;
    private static final int MAX_HISTORY = 450;
    private static final int MAX_DOWNLOADS = 160;
    private static final byte[] AAD =
            "cn.borealos.glacier.library.v1".getBytes(StandardCharsets.UTF_8);

    static final class Entry {
        String profile;
        String title;
        String url;
        String name;
        String uri;
        String mime;
        long bytes;
        long timestamp;
        Entry(String profile, String title, String url, String name,
              String uri, String mime, long bytes, long timestamp) {
            this.profile=profile;this.title=title;this.url=url;
            this.name=name;this.uri=uri;this.mime=mime;
            this.bytes=bytes;this.timestamp=timestamp;
        }
        Entry copy() {
            return new Entry(profile,title,url,name,uri,mime,bytes,timestamp);
        }
    }
    static final class Snapshot {
        final List<Entry> bookmarks = new ArrayList<>();
        final List<Entry> history = new ArrayList<>();
        final List<Entry> downloads = new ArrayList<>();
        Snapshot copy() {
            Snapshot saved = new Snapshot();
            for (Entry e: bookmarks) saved.bookmarks.add(e.copy());
            for (Entry e: history) saved.history.add(e.copy());
            for (Entry e: downloads) saved.downloads.add(e.copy());
            return saved;
        }
    }

    private BrowserLibraryStore() {}

    static boolean validProfile(String p) {
        return "private".equals(p) || "work".equals(p);
    }

    static boolean validWebUrl(String url) {
        if (url==null || url.length()>2048 || url.length()<8) return false;
        try {
            Uri u=Uri.parse(url);
            String scheme=u.getScheme(),host=u.getHost();
            if (scheme==null || host==null || host.isEmpty()) return false;
            if (!("http".equalsIgnoreCase(scheme)
                    || "https".equalsIgnoreCase(scheme))) return false;
            if (u.getUserInfo()!=null) return false;
            String h=host.toLowerCase(java.util.Locale.ROOT);
            return !h.equals("localhost") && !h.equals("127.0.0.1")
                    && !h.equals("::1") && !h.endsWith(".localhost");
        } catch(Exception ignored) {return false;}
    }

    static boolean validDocumentUri(String raw) {
        try {
            return raw!=null && raw.length()<=4096
                    && "content".equalsIgnoreCase(Uri.parse(raw).getScheme())
                    && Uri.parse(raw).getAuthority()!=null;
        } catch(Exception ignored) {return false;}
    }

    private static SecretKey key(boolean create) throws Exception {
        KeyStore store=KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (store.containsAlias(KEY)) {
            java.security.Key existing=store.getKey(KEY,null);
            if (!(existing instanceof SecretKey))
                throw new GeneralSecurityException("Invalid library key");
            return (SecretKey)existing;
        }
        if (!create) throw new GeneralSecurityException("Missing library key");
        KeyGenerator generator=KeyGenerator.getInstance(
                KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(KEY,
                KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .setUserAuthenticationRequired(false)
                .setKeySize(256).build());
        return generator.generateKey();
    }

    private static AtomicFile dataFile(Context c) {
        return new AtomicFile(new File(c.getNoBackupFilesDir(), NAME));
    }

    private static JSONObject jsonEntry(Entry e) throws Exception {
        JSONObject j=new JSONObject();
        j.put("profile",e.profile);
        j.put("title",e.title==null?"":e.title);
        j.put("url",e.url==null?"":e.url);
        j.put("name",e.name==null?"":e.name);
        j.put("uri",e.uri==null?"":e.uri);
        j.put("mime",e.mime==null?"":e.mime);
        j.put("bytes",e.bytes);
        j.put("at",e.timestamp);
        return j;
    }

    private static JSONArray encode(List<Entry> source, int limit, String kind)
            throws Exception {
        JSONArray a=new JSONArray();
        for(Entry e:source) {
            if(a.length()>=limit)break;
            if(!validProfile(e.profile))continue;
            boolean valid="download".equals(kind)
                    ? validDocumentUri(e.uri) : validWebUrl(e.url);
            if(!valid)continue;
            a.put(jsonEntry(e));
        }
        return a;
    }

    static synchronized void save(Context ctx, Snapshot snapshot) throws Exception {
        JSONObject json=new JSONObject();
        json.put("version",1);
        json.put("bookmarks",encode(snapshot.bookmarks,MAX_BOOKMARKS,"bookmark"));
        json.put("history",encode(snapshot.history,MAX_HISTORY,"history"));
        json.put("downloads",encode(snapshot.downloads,MAX_DOWNLOADS,"download"));
        byte[] plain=json.toString().getBytes(StandardCharsets.UTF_8);
        if(plain.length>MAX_SIZE-64)throw new GeneralSecurityException("Library too large");
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE,key(true));
        cipher.updateAAD(AAD);
        byte[] iv=cipher.getIV();
        byte[] encrypted=cipher.doFinal(plain);
        ByteBuffer output=ByteBuffer.allocate(4+12+encrypted.length);
        output.putInt(1).put(iv).put(encrypted);
        AtomicFile f=dataFile(ctx);
        FileOutputStream stream=null;
        try {
            stream=f.startWrite();
            stream.write(output.array());
            f.finishWrite(stream);
        } catch(Exception e) {
            if(stream!=null)f.failWrite(stream);
            throw e;
        }
    }

    private static void decode(JSONArray input,List<Entry> dest,
                               int limit, String kind) {
        if(input==null)return;
        for(int i=0;i<input.length()&&dest.size()<limit;i++) {
            JSONObject j=input.optJSONObject(i);
            if(j==null)continue;
            String profile=j.optString("profile");
            String title=j.optString("title");
            String url=j.optString("url");
            String name=j.optString("name");
            String uri=j.optString("uri");
            String mime=j.optString("mime");
            if(!validProfile(profile))continue;
            if("download".equals(kind)
                    ? !validDocumentUri(uri) : !validWebUrl(url))continue;
            if(title.length()>300||name.length()>180||mime.length()>100)continue;
            dest.add(new Entry(profile,title,url,name,uri,mime,
                    j.optLong("bytes",0),j.optLong("at",0)));
        }
    }

    static synchronized Snapshot load(Context ctx) throws Exception {
        Snapshot snapshot=new Snapshot();
        AtomicFile f=dataFile(ctx);
        if(!f.getBaseFile().exists())return snapshot;
        byte[] data=f.readFully();
        if(data.length<4+12+16||data.length>MAX_SIZE)
            throw new GeneralSecurityException("Invalid library snapshot");
        ByteBuffer input=ByteBuffer.wrap(data);
        if(input.getInt()!=1)
            throw new GeneralSecurityException("Unknown library version");
        byte[] iv=new byte[12],ciphertext=new byte[input.remaining()-12];
        input.get(iv);input.get(ciphertext);
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE,key(false),
                new GCMParameterSpec(128,iv));
        cipher.updateAAD(AAD);
        JSONObject j=new JSONObject(new String(
                cipher.doFinal(ciphertext),StandardCharsets.UTF_8));
        if(j.optInt("version")!=1)
            throw new GeneralSecurityException("Unknown library format");
        decode(j.optJSONArray("bookmarks"),snapshot.bookmarks,MAX_BOOKMARKS,"bookmark");
        decode(j.optJSONArray("history"),snapshot.history,MAX_HISTORY,"history");
        decode(j.optJSONArray("downloads"),snapshot.downloads,MAX_DOWNLOADS,"download");
        return snapshot;
    }

    /** Keep newest entries first and cap growing collections. */
    static void cap(List<Entry> entries,int maximum) {
        while(entries.size()>maximum)entries.remove(entries.size()-1);
    }
}
