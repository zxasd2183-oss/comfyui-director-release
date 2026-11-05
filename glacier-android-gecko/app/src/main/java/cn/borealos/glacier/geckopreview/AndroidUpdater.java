package cn.borealos.glacier.geckopreview;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.widget.Toast;

import androidx.core.content.FileProvider;

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
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

/**
 * In-app update checker for the separate Glacier Android release channel.
 *
 * Security model:
 * - GitHub HTTPS API and pinned owner/release/asset names.
 * - Redirect host restrictions, maximum size, SHA-256 and no version rollback.
 * - Verify APK package name, versionCode and Android signing certificate match
 *   BEFORE handing it to Android's user-confirmed installer.
 * - When VLESS is selected, the updater also uses LOCAL SOCKS. It never
 *   switches to direct HTTP as a fallback.
 *
 * This is an experimental opt-in APK updater, not a silent installer.
 */
public final class AndroidUpdater {
    private static final long CHECK_PERIOD_MS=12L*60L*60L*1000L;
    private static final String PREFS="glacier_android_update_v1";
    private final Activity activity;
    private final boolean viaProxy;
    private volatile boolean inFlight;
    private volatile File verifiedApk;
    private volatile String verifiedDigest;

    private static final class Release {
        final String version;
        final String url;
        final String digest;
        final long size;

        Release(String version,String url,String digest,long size) {
            this.version=version;
            this.url=url;
            this.digest=digest;
            this.size=size;
        }
    }

    public AndroidUpdater(Activity activity, boolean viaProxy) {
        this.activity=activity;
        this.viaProxy=viaProxy;
    }

    /** Check on first use and when the app is reopened after 12 hours. */
    public void automaticCheck() {
        SharedPreferences p=activity.getSharedPreferences(PREFS,Activity.MODE_PRIVATE);
        long last=p.getLong("last_check",0L);
        long now=System.currentTimeMillis();
        if(last>0L && now>=last && now-last<CHECK_PERIOD_MS) return;
        check(false);
    }

    public void checkNow() {
        check(true);
    }

    private synchronized boolean begin() {
        if(inFlight) return false;
        inFlight=true;
        return true;
    }

    private void finish() {
        synchronized(this){inFlight=false;}
    }

    private void check(boolean userInitiated) {
        if(viaProxy && !NativeProxy.alive()){
            if(userInitiated) alert("更新检查失败",
                    "VLESS 本地代理没有运行。不会绕过代理使用直连，请先恢复代理连接。");
            return;
        }
        if(!begin()) {
            if(userInitiated) toast("更新检查正在进行");
            return;
        }
        if(userInitiated) toast("正在检查 Glacier Android 更新");
        new Thread(() -> {
            try {
                Release found=checkLatest();
                activity.getSharedPreferences(PREFS,Activity.MODE_PRIVATE)
                        .edit().putLong("last_check",System.currentTimeMillis()).apply();
                if(found==null) {
                    if(userInitiated) onUi(()->alert("检查更新","当前已是最新可用版本，或尚无可升级的正式签名 APK。"));
                }else{
                    onUi(()->new AlertDialog.Builder(activity)
                            .setTitle("发现 Glacier Android "+found.version)
                            .setMessage("发现新版本，安装包约 "+(found.size/1048576L)
                                    +" MB。\n\n将通过 GitHub 下载，并验证 SHA-256、APK 包名、版本和签名证书。"
                                    +"\n\nAndroid 系统会要求你确认安装。")
                            .setNegativeButton("稍后",null)
                            .setPositiveButton("下载并安装",(d,w)->download(found))
                            .show());
                }
            }catch(Exception e){
                if(userInitiated)onUi(()->alert("检查更新失败",
                        "无法读取可信的 GitHub 更新信息。请检查网络或 VLESS 代理，稍后重试。"));
            }finally{
                finish();
            }
        },"glacier-update-check").start();
    }

    private String versionName() {
        try {
            PackageInfo info=activity.getPackageManager().getPackageInfo(
                    activity.getPackageName(),0);
            return info.versionName==null?"0.0.0":info.versionName;
        }catch(Exception e){return "0.0.0";}
    }

    private Release checkLatest() throws Exception {
        String data=readText(UpdatePolicy.API,2*1024*1024);
        JSONArray releases=new JSONArray(data);
        Release newest=null;
        for(int i=0;i<releases.length();i++){
            JSONObject release=releases.optJSONObject(i);
            if(release==null||release.optBoolean("draft",true))continue;
            String version=UpdatePolicy.tagVersion(release.optString("tag_name",""));
            if(version==null||!UpdatePolicy.newer(version,versionName()))continue;
            if(newest!=null&&!UpdatePolicy.newer(version,newest.version))continue;
            if(release.optString("published_at","").isEmpty())continue;
            JSONArray assets=release.optJSONArray("assets");
            if(assets==null)continue;
            String expected=UpdatePolicy.assetName(version);
            Release candidate=null;
            int matches=0;
            for(int j=0;j<assets.length();j++){
                JSONObject a=assets.optJSONObject(j);
                if(a==null||!expected.equals(a.optString("name","")))continue;
                matches++;
                String hex=a.optString("digest","");
                String url=a.optString("browser_download_url","");
                long size=a.optLong("size",0L);
                if(!hex.startsWith("sha256:"))continue;
                hex=hex.substring("sha256:".length());
                if(!"uploaded".equals(a.optString("state",""))
                        ||!UpdatePolicy.saneAsset(size,hex)
                        ||!UpdatePolicy.allowedDownloadUrl(url))continue;
                candidate=new Release(version,url,hex,size);
            }
            if(matches==1&&candidate!=null)newest=candidate;
        }
        return newest;
    }

    private HttpURLConnection open(String raw) throws Exception {
        URL url=new URL(raw);
        Proxy proxy=Proxy.NO_PROXY;
        if(viaProxy){
            if(!NativeProxy.alive())throw new IllegalStateException("Proxy stopped");
            proxy=new Proxy(Proxy.Type.SOCKS,
                    new InetSocketAddress("127.0.0.1",NativeProxy.PORT));
        }
        HttpURLConnection connection=(HttpURLConnection)url.openConnection(proxy);
        connection.setConnectTimeout(14000);
        connection.setReadTimeout(28000);
        connection.setInstanceFollowRedirects(false);
        connection.setRequestProperty("User-Agent","GlacierAndroidUpdater/0.1");
        connection.setRequestProperty("Accept","application/vnd.github+json, application/octet-stream, */*");
        return connection;
    }

    private HttpURLConnection follow(String initial) throws Exception {
        String url=initial;
        for(int i=0;i<7;i++){
            if(!UpdatePolicy.allowedHttpsHop(url)) throw new IllegalArgumentException("Untrusted redirect host");
            HttpURLConnection c=open(url);
            int code=c.getResponseCode();
            if(code==301||code==302||code==303||code==307||code==308){
                String location=c.getHeaderField("Location");
                if(location==null)throw new IllegalStateException("Missing redirect");
                URL next=new URL(new URL(url),location);
                url=next.toString();
                c.disconnect();
                continue;
            }
            if(code!=200){
                c.disconnect();
                throw new IllegalStateException("GitHub update HTTP "+code);
            }
            return c;
        }
        throw new IllegalArgumentException("Too many redirects");
    }

    private String readText(String url,int maxBytes) throws Exception {
        HttpURLConnection c=follow(url);
        try(InputStream in=c.getInputStream(); ByteArrayOutputStream out=new ByteArrayOutputStream()){
            byte[] buf=new byte[16384];
            for(int n;(n=in.read(buf))!=-1;){
                if(out.size()+n>maxBytes)throw new IllegalArgumentException("Update API response too large");
                out.write(buf,0,n);
            }
            return new String(out.toByteArray(),StandardCharsets.UTF_8);
        }finally{c.disconnect();}
    }

    private void download(Release release) {
        if(!begin()) {toast("已有更新任务正在运行");return;}
        toast("正在下载更新包，完成后会提示安装");
        new Thread(()->{
            File partial=null;
            try{
                File folder=new File(activity.getCacheDir(),"updates");
                if(!folder.exists()&&!folder.mkdirs())
                    throw new IllegalStateException("Cannot create update cache");
                File apk=new File(folder,"GlacierAndroid-update.apk");
                if(verifiedApk!=null && verifiedApk.equals(apk)
                        && verifiedDigest!=null && verifiedDigest.equals(release.digest)
                        && apk.isFile() && apk.length()==release.size
                        && verifyDigest(apk,release.digest)) {
                    verifyPackage(apk,release);
                    onUi(()->install(apk));
                    return;
                }
                partial=new File(folder,"download.part");
                if(partial.exists())partial.delete();
                if(folder.getUsableSpace()<release.size+30L*1024L*1024L)
                    throw new IllegalStateException("Not enough storage");
                MessageDigest sha=MessageDigest.getInstance("SHA-256");
                HttpURLConnection c=follow(release.url);
                long length=0L;
                try(InputStream in=c.getInputStream();
                    FileOutputStream out=new FileOutputStream(partial,false)){
                    byte[] block=new byte[65536];
                    for(int n;(n=in.read(block))!=-1;){
                        length+=n;
                        if(length>release.size||length>UpdatePolicy.MAX_APK_BYTES)
                            throw new IllegalArgumentException("APK exceeds declared size");
                        sha.update(block,0,n);
                        out.write(block,0,n);
                    }
                    out.flush();
                    out.getFD().sync();
                }finally{c.disconnect();}
                if(length!=release.size||!hex(sha.digest()).equals(release.digest))
                    throw new IllegalArgumentException("APK checksum mismatch");
                if(apk.exists()&&!apk.delete())
                    throw new IllegalStateException("Cannot replace previous update cache");
                if(!partial.renameTo(apk))
                    throw new IllegalStateException("Cannot finalize APK download");
                verifyPackage(apk,release);
                verifiedApk=apk;
                verifiedDigest=release.digest;
                onUi(()->install(apk));
            }catch(Exception e){
                if(partial!=null)partial.delete();
                onUi(()->alert("更新未安装",
                        "APK 下载或安全验证失败。未打开安装程序，也不会退回不安全下载。\n\n"
                                +"如果是网络超时，可以切换网络后再尝试。"));
            }finally{finish();}
        },"glacier-update-download").start();
    }

    private static String hex(byte[] bytes){
        StringBuilder out=new StringBuilder(bytes.length*2);
        for(byte b:bytes)out.append(String.format("%02x",b&0xff));
        return out.toString();
    }

    private boolean verifyDigest(File file,String expected) throws Exception {
        MessageDigest sha=MessageDigest.getInstance("SHA-256");
        try(InputStream in=new java.io.FileInputStream(file)){
            byte[] block=new byte[65536];
            for(int n;(n=in.read(block))!=-1;)sha.update(block,0,n);
        }
        return hex(sha.digest()).equals(expected);
    }

    private Set<String> signatureDigests(PackageInfo info) throws Exception {
        if(info==null)return java.util.Collections.emptySet();
        Signature[] sigs;
        if(Build.VERSION.SDK_INT>=28){
            if(info.signingInfo==null)return java.util.Collections.emptySet();
            sigs=info.signingInfo.getApkContentsSigners();
        }else{
            sigs=info.signatures;
        }
        Set<String> result=new HashSet<>();
        if(sigs==null)return result;
        for(Signature sig:sigs){
            result.add(hex(MessageDigest.getInstance("SHA-256").digest(sig.toByteArray())));
        }
        return result;
    }

    private void verifyPackage(File apk,Release release) throws Exception {
        PackageManager pm=activity.getPackageManager();
        int flags=Build.VERSION.SDK_INT>=28
                ? PackageManager.GET_SIGNING_CERTIFICATES : PackageManager.GET_SIGNATURES;
        PackageInfo archive=pm.getPackageArchiveInfo(apk.getAbsolutePath(),flags);
        PackageInfo current=pm.getPackageInfo(activity.getPackageName(),flags);
        if(archive==null||current==null||!activity.getPackageName().equals(archive.packageName))
            throw new SecurityException("APK package name mismatch");
        if(!release.version.equals(archive.versionName))
            throw new SecurityException("APK version differs from signed release");
        long incoming=Build.VERSION.SDK_INT>=28?archive.getLongVersionCode():archive.versionCode;
        long installed=Build.VERSION.SDK_INT>=28?current.getLongVersionCode():current.versionCode;
        if(incoming<=installed)throw new SecurityException("APK rollback rejected");
        Set<String> installedSigs=signatureDigests(current);
        Set<String> archiveSigs=signatureDigests(archive);
        if(installedSigs.isEmpty()||!installedSigs.equals(archiveSigs))
            throw new SecurityException("APK signing identity mismatch");
    }

    private void install(File apk){
        if(Build.VERSION.SDK_INT>=26&&!activity.getPackageManager().canRequestPackageInstalls()){
            new AlertDialog.Builder(activity)
                    .setTitle("允许 Glacier 安装更新")
                    .setMessage("Android 需要你允许本应用安装更新包。\n\n授权后返回 Glacier，再点击「检查更新」继续。已验证的 APK 会暂存在缓存中。")
                    .setNegativeButton("取消",null)
                    .setPositiveButton("打开系统设置",(d,w)->{
                        Intent settings=new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                Uri.parse("package:"+activity.getPackageName()));
                        activity.startActivity(settings);
                    }).show();
            return;
        }
        Uri uri=FileProvider.getUriForFile(activity,
                activity.getPackageName()+".updates",apk);
        Intent installer=new Intent(Intent.ACTION_VIEW);
        installer.setDataAndType(uri,"application/vnd.android.package-archive");
        installer.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {activity.startActivity(installer);}
        catch(Exception e){
            alert("无法打开 Android 安装器",
                    "已完成验证，但无法调用系统安装界面。请检查安装权限。");
        }
    }

    private void onUi(Runnable action){activity.runOnUiThread(action);}
    private void toast(String text){onUi(()->Toast.makeText(activity,text,Toast.LENGTH_LONG).show());}
    private void alert(String title,String message){
        onUi(()->new AlertDialog.Builder(activity)
                .setTitle(title).setMessage(message).setPositiveButton("确定",null).show());
    }
}
