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
import java.util.Locale;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * Local account cards. AES-256-GCM Android Keystore key never leaves this device.
 * Private/work account cards carry explicit profile IDs and never auto-fill.
 * Corrupt ciphertext must never be silently replaced.
 */
final class BrowserAccountsStore {
    private static final String KEY="glacier_accounts_aes_v1";
    private static final String NAME="glacier-accounts-v1.bin";
    private static final byte[] AAD="glacier.accounts.v1".getBytes(StandardCharsets.UTF_8);
    private static final int MAX_BYTES=256*1024;
    private static final int MAX_CARDS=100;

    static final class Card {
        final String profile,site,name,username,password,codeApi;
        Card(String profile,String site,String name,String username,String password,String codeApi) {
            this.profile=profile;this.site=site;this.name=name;this.username=username;
            this.password=password;this.codeApi=codeApi;
        }
    }

    static String site(String raw) {
        if(raw==null)return "";
        String s=raw.trim().toLowerCase(Locale.ROOT);
        if(s.startsWith("www."))s=s.substring(4);
        if(s.length()>253||!s.matches("(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,63}"))
            return "";
        return s;
    }

    static String siteFromUrl(String url) {
        try {
            Uri uri=Uri.parse(url);
            if(!"https".equalsIgnoreCase(uri.getScheme())||uri.getUserInfo()!=null
                    ||(uri.getPort()!=-1&&uri.getPort()!=443))return "";
            return site(uri.getHost());
        } catch(Exception ignored) {return "";}
    }

    static boolean validApi(String raw) {
        if(raw==null)return false;
        if(raw.isEmpty())return true;
        if(raw.length()>2048||raw.indexOf('\n')>=0||raw.indexOf('\r')>=0)return false;
        try {
            Uri uri=Uri.parse(raw);
            return "https".equalsIgnoreCase(uri.getScheme()) && uri.getUserInfo()==null
                    && (uri.getPort()==-1||uri.getPort()==443)
                    && uri.getFragment()==null && !site(uri.getHost()).isEmpty();
        } catch(Exception ignored) {return false;}
    }

    static boolean valid(Card c) {
        return c!=null && ("private".equals(c.profile)||"work".equals(c.profile))
                && !c.site.isEmpty() && c.site.equals(site(c.site))
                && c.name!=null && !c.name.trim().isEmpty() && c.name.length()<=60
                && c.username!=null && !c.username.isEmpty() && c.username.length()<=250
                && c.password!=null && c.password.length()<=2048
                && validApi(c.codeApi);
    }

    private static SecretKey key(boolean create) throws Exception {
        KeyStore ks=KeyStore.getInstance("AndroidKeyStore");
        ks.load(null);
        if(ks.containsAlias(KEY)) {
            java.security.Key found=ks.getKey(KEY,null);
            if(!(found instanceof SecretKey))throw new GeneralSecurityException("Invalid account key");
            return (SecretKey)found;
        }
        if(!create)throw new GeneralSecurityException("Account encryption key unavailable");
        KeyGenerator generator=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(KEY,
                KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true).setKeySize(256).build());
        return generator.generateKey();
    }

    private static AtomicFile file(Context context) {
        return new AtomicFile(new File(context.getNoBackupFilesDir(),NAME));
    }

    static synchronized List<Card> load(Context context) throws Exception {
        AtomicFile store=file(context);
        if(!store.getBaseFile().exists())return new ArrayList<>();
        if(store.getBaseFile().length()>MAX_BYTES)
            throw new GeneralSecurityException("Account file too large");
        byte[] encrypted;
        try(java.io.InputStream in=store.openRead()) {
            java.io.ByteArrayOutputStream buffer=new java.io.ByteArrayOutputStream();
            byte[] block=new byte[8192];int n;
            while((n=in.read(block))!=-1) {
                if(buffer.size()+n>MAX_BYTES)throw new GeneralSecurityException("Account file too large");
                buffer.write(block,0,n);
            }
            encrypted=buffer.toByteArray();
        }
        if(encrypted.length<33)throw new GeneralSecurityException("Account file incomplete");
        ByteBuffer encoded=ByteBuffer.wrap(encrypted);
        if(encoded.getInt()!=1)throw new GeneralSecurityException("Unsupported account format");
        byte[] nonce=new byte[12];encoded.get(nonce);
        byte[] ciphertext=new byte[encoded.remaining()];encoded.get(ciphertext);
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE,key(false),new GCMParameterSpec(128,nonce));
        cipher.updateAAD(AAD);
        JSONObject json=new JSONObject(new String(cipher.doFinal(ciphertext),StandardCharsets.UTF_8));
        if(json.getInt("schema")!=1)throw new GeneralSecurityException("Unsupported account schema");
        JSONArray entries=json.getJSONArray("accounts");
        if(entries.length()>MAX_CARDS)throw new GeneralSecurityException("Too many account cards");
        List<Card> cards=new ArrayList<>();
        for(int i=0;i<entries.length();i++) {
            JSONObject e=entries.getJSONObject(i);
            Card c=new Card(e.getString("profile"),e.getString("site"),
                    e.getString("name"),e.getString("username"),
                    e.getString("password"),e.optString("code_api",""));
            if(!valid(c))throw new GeneralSecurityException("Corrupt account entry");
            for(Card old:cards) {
                if(old.profile.equals(c.profile)&&old.site.equals(c.site)
                        &&old.name.equalsIgnoreCase(c.name))
                    throw new GeneralSecurityException("Duplicate encrypted account entry");
            }
            cards.add(c);
        }
        return cards;
    }

    static synchronized void save(Context context,List<Card> cards) throws Exception {
        if(cards==null||cards.size()>MAX_CARDS)throw new GeneralSecurityException("Too many accounts");
        JSONArray entries=new JSONArray();
        List<String> seen=new ArrayList<>();
        for(Card c:cards) {
            if(!valid(c))throw new GeneralSecurityException("Invalid account");
            String identity=c.profile+"|"+c.site+"|"+c.name.toLowerCase(Locale.ROOT);
            if(seen.contains(identity))throw new GeneralSecurityException("Duplicate account name");
            seen.add(identity);
            JSONObject item=new JSONObject();
            item.put("profile",c.profile);item.put("site",c.site);
            item.put("name",c.name.trim());item.put("username",c.username);
            item.put("password",c.password);item.put("code_api",c.codeApi);
            entries.put(item);
        }
        JSONObject root=new JSONObject();
        root.put("schema",1);root.put("accounts",entries);
        byte[] plain=root.toString().getBytes(StandardCharsets.UTF_8);
        if(plain.length>MAX_BYTES-64)throw new GeneralSecurityException("Account data too large");
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE,key(true));
        cipher.updateAAD(AAD);
        byte[] nonce=cipher.getIV();
        if(nonce==null||nonce.length!=12)throw new GeneralSecurityException("Invalid nonce");
        byte[] body=cipher.doFinal(plain);
        ByteBuffer encoded=ByteBuffer.allocate(4+nonce.length+body.length);
        encoded.putInt(1).put(nonce).put(body);
        AtomicFile destination=file(context);
        FileOutputStream out=null;
        try {
            out=destination.startWrite();
            out.write(encoded.array());
            destination.finishWrite(out);
        } catch(Exception ex) {
            if(out!=null)destination.failWrite(out);
            throw ex;
        }
    }
}
