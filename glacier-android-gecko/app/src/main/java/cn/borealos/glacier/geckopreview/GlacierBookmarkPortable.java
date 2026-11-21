package cn.borealos.glacier.geckopreview;

import org.json.JSONArray;
import org.json.JSONObject;
import android.util.Base64;

import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.security.GeneralSecurityException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;

import javax.crypto.Cipher;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.PBEKeySpec;
import javax.crypto.spec.SecretKeySpec;

/**
 * A separate, opt-in, encrypted bookmark format shared with desktop clients.
 *
 * NEVER put this data in /v1/vault/private|work: that endpoint contains
 * account cards and older clients would overwrite or misinterpret bookmarks.
 * No network, cookie or device-session access occurs in this helper.
 */
final class GlacierBookmarkPortable {
    static final String FORMAT="glacier-bookmarks-v1";
    static final String KDF="pbkdf2-sha256-400k";
    private static final int LIMIT=160;
    private static final int MAX_PLAIN=150000;
    private static final int MAX_TS=2100;
    private static final SecureRandom RANDOM=new SecureRandom();

    private GlacierBookmarkPortable(){}

    static String b64(byte[] value) {
        return Base64.encodeToString(value,Base64.URL_SAFE|Base64.NO_WRAP|Base64.NO_PADDING);
    }

    static byte[] decode(String text) throws Exception {
        if(text==null||text.length()>350000||!text.matches("[A-Za-z0-9_-]+"))
            throw new java.io.IOException("Invalid bookmark base64");
        byte[] decoded=Base64.decode(text,Base64.URL_SAFE|Base64.NO_WRAP|Base64.NO_PADDING);
        if(!b64(decoded).equals(text))
            throw new java.io.IOException("Noncanonical bookmark base64");
        return decoded;
    }

    private static String space(String profile) throws Exception {
        if(!BrowserLibraryStore.validProfile(profile))
            throw new java.io.IOException("Invalid bookmark space");
        return profile;
    }

    private static byte[] key(String pass,byte[] salt) throws Exception {
        if(pass==null||pass.length()<12||salt.length!=16)
            throw new GeneralSecurityException("Invalid bookmark passphrase");
        PBEKeySpec spec=new PBEKeySpec(pass.toCharArray(),salt,400000,256);
        try {
            return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256")
                    .generateSecret(spec).getEncoded();
        } finally {spec.clearPassword();}
    }

    private static void check(BrowserLibraryStore.Entry e,String profile)
            throws Exception {
        if(e==null||!profile.equals(e.profile)||!BrowserLibraryStore.validWebUrl(e.url)
                ||e.title==null||e.title.isEmpty()||e.title.length()>180
                ||e.timestamp<0||e.timestamp>4102444800000L)
            throw new java.io.IOException("Invalid or cross-space bookmark");
        for(int i=0;i<e.title.length();i++) {
            char ch=e.title.charAt(i);
            if(ch<32||ch==127)throw new java.io.IOException("Unsafe bookmark title");
        }
        for(int i=0;i<e.url.length();i++) {
            char ch=e.url.charAt(i);
            if(ch<32||ch==127)throw new java.io.IOException("Unsafe bookmark URL");
        }
    }

    static String encrypt(String profile,List<BrowserLibraryStore.Entry> rows,
                          String pass) throws Exception {
        space(profile);
        if(rows==null||rows.size()>LIMIT)throw new java.io.IOException("Too many bookmarks");
        JSONArray bookmarks=new JSONArray();
        HashSet<String> unique=new HashSet<>();
        for(BrowserLibraryStore.Entry e:rows) {
            check(e,profile);
            if(!unique.add(e.url))throw new java.io.IOException("Duplicate bookmark");
            JSONObject row=new JSONObject();
            row.put("profile",profile);
            row.put("title",e.title);
            row.put("url",e.url);
            row.put("at",e.timestamp);
            bookmarks.put(row);
        }
        JSONObject document=new JSONObject();
        document.put("schema",1);
        document.put("space",profile);
        document.put("bookmarks",bookmarks);
        byte[] plain=document.toString().getBytes(StandardCharsets.UTF_8);
        if(plain.length>MAX_PLAIN)throw new java.io.IOException("Bookmark document too large");
        byte[] salt=new byte[16],nonce=new byte[12];
        RANDOM.nextBytes(salt);RANDOM.nextBytes(nonce);
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE,new SecretKeySpec(key(pass,salt),"AES"),
                new GCMParameterSpec(128,nonce));
        cipher.updateAAD((FORMAT+":"+profile).getBytes(StandardCharsets.UTF_8));
        byte[] data=cipher.doFinal(plain);
        JSONObject outer=new JSONObject();
        outer.put("format",FORMAT);
        outer.put("kdf",KDF);
        outer.put("salt",b64(salt));
        outer.put("nonce",b64(nonce));
        outer.put("ciphertext",b64(data));
        return outer.toString();
    }

    static List<BrowserLibraryStore.Entry> decrypt(String profile,String encrypted,
                                                    String pass) throws Exception {
        space(profile);
        if(encrypted==null||encrypted.length()>350000)
            throw new java.io.IOException("Bookmark encrypted payload too large");
        JSONObject outer=new JSONObject(encrypted);
        if(!FORMAT.equals(outer.getString("format"))
                ||!KDF.equals(outer.getString("kdf")))
            throw new java.io.IOException("Unsupported bookmark format");
        byte[] salt=decode(outer.getString("salt"));
        byte[] nonce=decode(outer.getString("nonce"));
        byte[] ciphertext=decode(outer.getString("ciphertext"));
        if(salt.length!=16||nonce.length!=12
                ||ciphertext.length<16||ciphertext.length>200000)
            throw new java.io.IOException("Bad bookmark ciphertext length");
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE,new SecretKeySpec(key(pass,salt),"AES"),
                new GCMParameterSpec(128,nonce));
        cipher.updateAAD((FORMAT+":"+profile).getBytes(StandardCharsets.UTF_8));
        byte[] plain=cipher.doFinal(ciphertext);
        if(plain.length>MAX_PLAIN)throw new java.io.IOException("Bookmark plaintext too large");
        JSONObject document=new JSONObject(new String(plain,StandardCharsets.UTF_8));
        if(document.getInt("schema")!=1||!profile.equals(document.getString("space")))
            throw new java.io.IOException("Bookmark data in wrong space");
        JSONArray records=document.getJSONArray("bookmarks");
        if(records.length()>LIMIT)throw new java.io.IOException("Too many imported bookmarks");
        List<BrowserLibraryStore.Entry> out=new ArrayList<>();
        HashSet<String> unique=new HashSet<>();
        for(int i=0;i<records.length();i++) {
            JSONObject row=records.getJSONObject(i);
            BrowserLibraryStore.Entry e=new BrowserLibraryStore.Entry(
                    row.getString("profile"),row.getString("title"),
                    row.getString("url"),"","","",0,row.getLong("at"));
            check(e,profile);
            if(!unique.add(e.url))throw new java.io.IOException("Duplicate imported bookmark");
            out.add(e);
        }
        return out;
    }

    /** Pure preview; caller persists after explicit consent. Never deletes local data. */
    static BrowserLibraryStore.Snapshot previewMerge(
            BrowserLibraryStore.Snapshot current,String profile,
            List<BrowserLibraryStore.Entry> imported) throws Exception {
        space(profile);
        if(current==null||imported==null||imported.size()>LIMIT)
            throw new java.io.IOException("Missing bookmark snapshot");
        BrowserLibraryStore.Snapshot result=current.copy();
        // BrowserLibraryStore persists at most 160 bookmarks TOTAL, not per
        // profile. An import must never let its serializer silently discard
        // either a private or a work bookmark.
        if(result.bookmarks.size()>LIMIT)
            throw new java.io.IOException("Local bookmark store exceeds capacity");
        HashSet<String> local=new HashSet<>();
        int count=0;
        for(BrowserLibraryStore.Entry e:result.bookmarks) {
            if(profile.equals(e.profile)) {
                check(e,profile);
                count++;
                local.add(e.url);
            }
        }
        HashSet<String> seen=new HashSet<>();
        for(BrowserLibraryStore.Entry e:imported) {
            check(e,profile);
            if(!seen.add(e.url))throw new java.io.IOException("Duplicate import");
            if(local.add(e.url)) {
                if(++count>LIMIT || result.bookmarks.size()>=LIMIT)
                    throw new java.io.IOException("Bookmark capacity exceeded");
                result.bookmarks.add(e.copy());
            }
        }
        return result;
    }
}
