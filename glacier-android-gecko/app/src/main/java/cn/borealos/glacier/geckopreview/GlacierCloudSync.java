package cn.borealos.glacier.geckopreview;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import android.util.AtomicFile;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.InetSocketAddress;
import java.net.Proxy;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.List;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.PBEKeySpec;
import javax.crypto.spec.SecretKeySpec;

/** Glacier Sync v1: explicit account operations via current SOCKS5 connection.
 * Session tokens are stored in an Android Keystore-encrypted no-backup file.
 * Account vault encryption is PBKDF2-HMAC-SHA256 + AES-256-GCM with the same
 * authenticated format as Windows/macOS. The server never receives plaintext.
 */
final class GlacierCloudSync {
    static final String FORMAT="glacier-vault-v1";
    private static final String KEY="glacier_sync_session_v1";
    private static final String FILE="glacier-sync-session-v1.bin";
    private static final byte[] SESSION_AAD="glacier-sync-session-v1".getBytes(StandardCharsets.UTF_8);
    private static final int ITERATIONS=400000;
    private static final SecureRandom RANDOM=new SecureRandom();

    static final class State {
        String base="", username="", token="", deviceId="", deviceSecret="";
        boolean approved;
        JSONObject toJson() throws Exception {
            JSONObject o=new JSONObject();
            o.put("base",base);o.put("username",username);
            o.put("token",token);o.put("device_id",deviceId);
            o.put("device_secret",deviceSecret);
            o.put("approved",approved);
            return o;
        }
        static State fromJson(JSONObject o) {
            State state=new State();
            state.base=o.optString("base","");
            state.username=o.optString("username","");
            state.token=o.optString("token","");
            state.deviceId=o.optString("device_id","");
            state.deviceSecret=o.optString("device_secret","");
            state.approved=o.optBoolean("approved",false);
            return state;
        }
    }

    private GlacierCloudSync() {}

    static String validateBase(String raw) {
        if(raw==null)return "";
        String value=raw.trim();
        if(value.endsWith("/"))value=value.substring(0,value.length()-1);
        try {
            android.net.Uri uri=android.net.Uri.parse(value);
            if(!"https".equals(uri.getScheme()) || uri.getUserInfo()!=null
                    ||uri.getPort()!=-1 && uri.getPort()!=443
                    ||uri.getPath()!=null && !uri.getPath().isEmpty()
                    ||uri.getQuery()!=null || uri.getFragment()!=null
                    ||BrowserAccountsStore.site(uri.getHost()).isEmpty()
                    ||value.length()>255)return "";
            return value;
        } catch(Exception ignored) {return "";}
    }

    private static SecretKey deviceKey(boolean create) throws Exception {
        KeyStore store=KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if(store.containsAlias(KEY))return (SecretKey)store.getKey(KEY,null);
        if(!create)throw new java.security.GeneralSecurityException("Missing Glacier session key");
        KeyGenerator gen=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
        gen.init(new KeyGenParameterSpec.Builder(KEY,
                KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true).setKeySize(256).build());
        return gen.generateKey();
    }

    private static AtomicFile stateFile(Context context) {
        return new AtomicFile(new File(context.getNoBackupFilesDir(), FILE));
    }

    static synchronized State load(Context context) throws Exception {
        AtomicFile file=stateFile(context);
        if(!file.getBaseFile().exists())return new State();
        if(file.getBaseFile().length()>16384)throw new java.io.IOException("Sync session too large");
        byte[] data;
        try(InputStream in=file.openRead()) {
            ByteArrayOutputStream b=new ByteArrayOutputStream();
            byte[] chunk=new byte[1024];int n;
            while((n=in.read(chunk))!=-1) {
                if(b.size()+n>16384)throw new java.io.IOException("Sync session too large");
                b.write(chunk,0,n);
            }
            data=b.toByteArray();
        }
        if(data.length<32)throw new java.io.IOException("Invalid session data");
        ByteBuffer b=ByteBuffer.wrap(data);
        if(b.getInt()!=1)throw new java.io.IOException("Invalid session format");
        byte[] nonce=new byte[12];b.get(nonce);
        byte[] ciphertext=new byte[b.remaining()];b.get(ciphertext);
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE,deviceKey(false),new GCMParameterSpec(128,nonce));
        cipher.updateAAD(SESSION_AAD);
        State state=State.fromJson(new JSONObject(new String(
                cipher.doFinal(ciphertext),StandardCharsets.UTF_8)));
        if(!state.base.isEmpty() && !state.base.equals(validateBase(state.base)))
            throw new java.io.IOException("Unsafe sync URL");
        return state;
    }

    static synchronized void save(Context context,State state) throws Exception {
        if(!state.base.isEmpty() && !state.base.equals(validateBase(state.base)))
            throw new java.io.IOException("Unsafe sync URL");
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE,deviceKey(true));
        cipher.updateAAD(SESSION_AAD);
        byte[] clear=state.toJson().toString().getBytes(StandardCharsets.UTF_8);
        byte[] nonce=cipher.getIV();
        byte[] encrypted=cipher.doFinal(clear);
        if(nonce.length!=12||encrypted.length>12000)
            throw new java.io.IOException("Sync session exceeds limit");
        ByteBuffer out=ByteBuffer.allocate(4+12+encrypted.length);
        out.putInt(1).put(nonce).put(encrypted);
        AtomicFile file=stateFile(context);
        FileOutputStream stream=null;
        try {
            stream=file.startWrite();stream.write(out.array());file.finishWrite(stream);
        } catch(Exception e) {
            if(stream!=null)file.failWrite(stream);
            throw e;
        }
    }

    private static byte[] readLimited(InputStream in) throws Exception {
        try(InputStream src=in) {
            ByteArrayOutputStream out=new ByteArrayOutputStream();
            byte[] buffer=new byte[4096];int n;
            while((n=src.read(buffer))!=-1) {
                if(out.size()+n>360000)
                    throw new java.io.IOException("Sync response too large");
                out.write(buffer,0,n);
            }
            return out.toByteArray();
        }
    }

    static JSONObject call(State state,String method,String route,JSONObject payload) throws Exception {
        if(!state.base.equals(validateBase(state.base)) || state.base.isEmpty()
                || !route.matches("/v1/[a-zA-Z0-9_/-]+"))
            throw new java.io.IOException("Invalid Glacier Sync endpoint");
        // Caller MUST confirm NativeProxy is active: this call never uses DIRECT.
        Proxy proxy=new Proxy(Proxy.Type.SOCKS,new InetSocketAddress(
                "127.0.0.1",NativeProxy.PORT));
        HttpURLConnection connection=(HttpURLConnection)new URL(
                state.base+route).openConnection(proxy);
        connection.setInstanceFollowRedirects(false);
        connection.setConnectTimeout(7000);
        connection.setReadTimeout(12000);
        connection.setRequestMethod(method);
        connection.setUseCaches(false);
        connection.setRequestProperty("Accept","application/json");
        if(!state.token.isEmpty())
            connection.setRequestProperty("Authorization","Bearer "+state.token);
        if(payload!=null) {
            byte[] body=payload.toString().getBytes(StandardCharsets.UTF_8);
            if(body.length>270000)throw new java.io.IOException("Sync upload too large");
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type","application/json");
            try(java.io.OutputStream output=connection.getOutputStream()) {
                output.write(body);
            }
        }
        try {
            int status=connection.getResponseCode();
            if(status<200||status>=300) {
                throw new java.io.IOException("Glacier Sync HTTP "+status);
            }
            return new JSONObject(new String(readLimited(connection.getInputStream()),
                    StandardCharsets.UTF_8));
        } finally {
            connection.disconnect();
        }
    }

    static String b64(byte[] raw) {
        return Base64.encodeToString(raw,Base64.URL_SAFE|Base64.NO_WRAP|Base64.NO_PADDING);
    }
    static byte[] decode(String data) {
        if(data==null||data.length()>350000)
            throw new IllegalArgumentException("Invalid encoded data");
        return Base64.decode(data,Base64.URL_SAFE|Base64.NO_WRAP);
    }

    private static byte[] key(String passphrase,byte[] salt) throws Exception {
        if(passphrase==null||passphrase.length()<12||salt.length!=16)
            throw new java.security.GeneralSecurityException("Invalid passphrase or salt");
        PBEKeySpec spec=new PBEKeySpec(passphrase.toCharArray(),salt,ITERATIONS,256);
        try {
            return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256")
                    .generateSecret(spec).getEncoded();
        } finally {spec.clearPassword();}
    }

    static String encrypt(String space,List<BrowserAccountsStore.Card> cards,
                          String passphrase) throws Exception {
        if(!"private".equals(space)&&!"work".equals(space))
            throw new java.io.IOException("Unknown account space");
        JSONArray array=new JSONArray();
        for(BrowserAccountsStore.Card c:cards) {
            if(!space.equals(c.profile) || !BrowserAccountsStore.valid(c))
                throw new java.io.IOException("Cross-space account refused");
            JSONObject row=new JSONObject();
            row.put("space",space);row.put("site",c.site);row.put("name",c.name);
            row.put("username",c.username);row.put("password",c.password);
            row.put("code_api",c.codeApi);
            array.put(row);
        }
        JSONObject document=new JSONObject();
        document.put("schema",1);document.put("space",space);
        document.put("accounts",array);
        byte[] plain=document.toString().getBytes(StandardCharsets.UTF_8);
        if(plain.length>150000)throw new java.io.IOException("Space too large");
        byte[] salt=new byte[16],nonce=new byte[12];
        RANDOM.nextBytes(salt);RANDOM.nextBytes(nonce);
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE,new SecretKeySpec(key(passphrase,salt),"AES"),
                new GCMParameterSpec(128,nonce));
        cipher.updateAAD(("glacier-sync-v1:"+space).getBytes(StandardCharsets.UTF_8));
        byte[] encrypted=cipher.doFinal(plain);
        JSONObject envelope=new JSONObject();
        envelope.put("format",FORMAT);
        envelope.put("kdf","pbkdf2-sha256-400k");
        envelope.put("salt",b64(salt));envelope.put("nonce",b64(nonce));
        envelope.put("ciphertext",b64(encrypted));
        return envelope.toString();
    }

    static List<BrowserAccountsStore.Card> decrypt(String space,String envelope,
                                                    String passphrase) throws Exception {
        if(!"private".equals(space)&&!"work".equals(space))
            throw new java.io.IOException("Unknown account space");
        JSONObject json=new JSONObject(envelope);
        if(!FORMAT.equals(json.getString("format"))
                ||!"pbkdf2-sha256-400k".equals(json.getString("kdf")))
            throw new java.io.IOException("Unsupported vault format");
        byte[] salt=decode(json.getString("salt"));
        byte[] nonce=decode(json.getString("nonce"));
        byte[] ciphertext=decode(json.getString("ciphertext"));
        if(salt.length!=16||nonce.length!=12||ciphertext.length>200000)
            throw new java.io.IOException("Invalid vault envelope");
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE,new SecretKeySpec(key(passphrase,salt),"AES"),
                new GCMParameterSpec(128,nonce));
        cipher.updateAAD(("glacier-sync-v1:"+space).getBytes(StandardCharsets.UTF_8));
        byte[] plaintext=cipher.doFinal(ciphertext);
        if(plaintext.length>150000)throw new java.io.IOException("Invalid decrypted size");
        JSONObject document=new JSONObject(new String(plaintext,StandardCharsets.UTF_8));
        if(document.getInt("schema")!=1||!space.equals(document.getString("space")))
            throw new java.io.IOException("Vault from wrong account space");
        JSONArray records=document.getJSONArray("accounts");
        if(records.length()>100)throw new java.io.IOException("Too many cards");
        List<BrowserAccountsStore.Card> cards=new ArrayList<>();
        for(int i=0;i<records.length();i++) {
            JSONObject row=records.getJSONObject(i);
            if(!space.equals(row.optString("space","private")))
                throw new java.io.IOException("Cross-space card");
            BrowserAccountsStore.Card card=new BrowserAccountsStore.Card(
                    space,row.getString("site"),row.getString("name"),
                    row.getString("username"),row.getString("password"),
                    row.optString("code_api",""));
            if(!BrowserAccountsStore.valid(card))
                throw new java.io.IOException("Invalid encrypted card");
            cards.add(card);
        }
        return cards;
    }
}
