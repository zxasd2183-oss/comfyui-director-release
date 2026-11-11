package cn.borealos.glacier.geckopreview;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;

import androidx.core.content.FileProvider;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Fixed-signature M05 updater, built only into Glacier's own Android APK.
 * Queries official GitHub release metadata with trusted-host HTTPS, checks
 * a strict tag+filename contract, verifies downloaded bytes and same APK
 * signing certificate before asking Android's system installer.
 *
 * No silent installation, no arbitrary URLs, no direct fallback when the
 * browser is configured for VLESS, and no update traffic in Debug builds.
 */
final class BrowserUpdater {
    private static final String PACKAGE_ID = "cn.borealos.glacier.geckopreview";
    private static final String TAG_PREFIX = "glacier-android-browser-v";
    private static final String ASSET_PREFIX = "GlacierAndroid-v";
    private static final String ASSET_SUFFIX = "-ARM64-x86_64-release.apk";
    private static final String RELEASE_ROOT =
            "https://github.com/zxasd2183-oss/comfyui-director-release/releases/download/";
    private static final Pattern VERSION = Pattern.compile(
            "^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$");
    private static final Pattern SHA = Pattern.compile("^sha256:([a-fA-F0-9]{64})$");
    private static final long MIN_SIZE = 10L*1024*1024;
    private static final long MAX_SIZE = 450L*1024*1024;
    private static final int MAX_METADATA = 2*1024*1024;
    private final Activity activity;
    private final ExecutorService executor=Executors.newSingleThreadExecutor();
    private final Handler main=new Handler(Looper.getMainLooper());
    private final File downloadsDir;
    private volatile File verifiedFile;
    private volatile Release verifiedRelease;

    interface Callback<T> {
        void done(T result,Exception error);
    }

    static final class Release {
        final String version,tag,asset,url,sha256;
        final long size;
        Release(String v,String t,String a,String u,String h,long s) {
            version=v;tag=t;asset=a;url=u;sha256=h;size=s;
        }
    }

    BrowserUpdater(Activity owner) {
        activity=owner;
        downloadsDir=new File(owner.getCacheDir(),"glacier-updates");
    }

    static int[] versionParts(String value) {
        if(value==null)return null;
        Matcher m=VERSION.matcher(value);
        if(!m.matches())return null;
        try{
            return new int[]{
                    Integer.parseInt(m.group(1)),
                    Integer.parseInt(m.group(2)),
                    Integer.parseInt(m.group(3))
            };
        }catch(Exception e){return null;}
    }

    static boolean newer(String remote,String installed) {
        int[] a=versionParts(remote),b=versionParts(installed);
        if(a==null||b==null)return false;
        for(int i=0;i<3;i++) {
            if(a[i]!=b[i])return a[i]>b[i];
        }
        return false;
    }

    static Release findLatest(String json,String localVersion) throws Exception {
        JSONArray releases=new JSONArray(json);
        Release best=null;
        for(int i=0;i<releases.length() && i<100;i++) {
            JSONObject release=releases.optJSONObject(i);
            if(release==null||release.optBoolean("draft",false)
                    ||release.optBoolean("prerelease",false))continue;
            String tag=release.optString("tag_name","");
            if(!tag.startsWith(TAG_PREFIX))continue;
            String version=tag.substring(TAG_PREFIX.length());
            if(!newer(version,localVersion))continue;
            String expectedAsset=ASSET_PREFIX+version+ASSET_SUFFIX;
            String expectedUrl=RELEASE_ROOT+tag+"/"+expectedAsset;
            JSONArray assets=release.optJSONArray("assets");
            if(assets==null)continue;
            for(int j=0;j<assets.length();j++) {
                JSONObject asset=assets.optJSONObject(j);
                if(asset==null
                        ||!expectedAsset.equals(asset.optString("name"))
                        ||!"uploaded".equals(asset.optString("state"))
                        ||!expectedUrl.equals(asset.optString("browser_download_url")))continue;
                long size=asset.optLong("size",-1);
                Matcher digest=SHA.matcher(asset.optString("digest",""));
                if(size<MIN_SIZE||size>MAX_SIZE||!digest.matches())continue;
                Release candidate=new Release(version,tag,expectedAsset,expectedUrl,
                        digest.group(1).toLowerCase(Locale.ROOT),size);
                if(best==null||newer(candidate.version,best.version))best=candidate;
            }
        }
        return best;
    }

    private static String hex(byte[] bytes) {
        StringBuilder builder=new StringBuilder();
        for(byte b:bytes)builder.append(String.format(Locale.ROOT,"%02x",b&255));
        return builder.toString();
    }

    private void report(Callback<Release> handler,Release found,Exception error) {
        main.post(()->handler.done(found,error));
    }

    void check(boolean throughVless,Callback<Release> done) {
        if(BuildConfig.DEBUG) {
            done.done(null,new IllegalStateException(
                    "Debug 测试包不访问正式更新源；安装固定签名版后可检查更新"));
            return;
        }
        executor.execute(()->{
            try {
                if(throughVless&&!NativeProxy.alive()) {
                    throw new IllegalStateException("VLESS 当前未连接；不会回退到直连");
                }
                byte[] data=GlacierUpdateTransport.fetchSmall(
                        GlacierUpdateTransport.API,throughVless,NativeProxy.PORT,
                        MAX_METADATA);
                Release found=findLatest(new String(data,java.nio.charset.StandardCharsets.UTF_8),
                        BuildConfig.VERSION_NAME);
                report(done,found,null);
            } catch(Exception failure) {
                report(done,null,failure);
            }
        });
    }

    private void validateApk(File apk,Release release) throws Exception {
        PackageManager pm=activity.getPackageManager();
        final int flag=Build.VERSION.SDK_INT>=28 ?
                PackageManager.GET_SIGNING_CERTIFICATES : PackageManager.GET_SIGNATURES;
        PackageInfo candidate=pm.getPackageArchiveInfo(apk.getAbsolutePath(),flag);
        PackageInfo current=pm.getPackageInfo(activity.getPackageName(),flag);
        if(candidate==null||current==null)throw new SecurityException("无法读取 APK 身份");
        if(!PACKAGE_ID.equals(candidate.packageName)
                ||!PACKAGE_ID.equals(current.packageName)) {
            throw new SecurityException("更新包名与当前 Glacier 不一致");
        }
        if(!release.version.equals(candidate.versionName)) {
            throw new SecurityException("APK 版本与发布信息不匹配");
        }
        long incomingCode=Build.VERSION.SDK_INT>=28
                ?candidate.getLongVersionCode():candidate.versionCode;
        long installedCode=Build.VERSION.SDK_INT>=28
                ?current.getLongVersionCode():current.versionCode;
        if(incomingCode<=installedCode) {
            throw new SecurityException("拒绝相同版本或降级安装");
        }
        Signature[] next;
        Signature[] installed;
        if(Build.VERSION.SDK_INT>=28) {
            next=candidate.signingInfo==null ? null
                    :candidate.signingInfo.getApkContentsSigners();
            installed=current.signingInfo==null ? null
                    :current.signingInfo.getApkContentsSigners();
        } else {
            next=candidate.signatures;
            installed=current.signatures;
        }
        if(next==null||installed==null||next.length!=1||installed.length!=1
                ||!MessageDigest.isEqual(next[0].toByteArray(),
                                          installed[0].toByteArray())) {
            throw new SecurityException("APK 签名与已安装 Glacier 不一致");
        }
    }

    void download(Release release,boolean throughVless,
                  AtomicBoolean canceled,java.util.function.IntConsumer progress,
                  Callback<File> done) {
        if(BuildConfig.DEBUG) {
            done.done(null,new IllegalStateException("Debug 测试版禁止在线下载更新"));
            return;
        }
        executor.execute(()->{
            File temp=null;
            try {
                if(release==null||!newer(release.version,BuildConfig.VERSION_NAME)
                        ||!GlacierUpdateTransport.allowed(release.url)
                        ||!release.asset.equals(ASSET_PREFIX+release.version+ASSET_SUFFIX)
                        ||!release.url.equals(RELEASE_ROOT+release.tag+"/"+release.asset)
                        ||!release.tag.equals(TAG_PREFIX+release.version)
                        ||release.size<MIN_SIZE||release.size>MAX_SIZE) {
                    throw new SecurityException("更新来源不符合 Glacier 发布约定");
                }
                if(throughVless&&!NativeProxy.alive()) {
                    throw new SecurityException("VLESS 未连接，已拒绝任何直连下载");
                }
                if(!downloadsDir.exists()&&!downloadsDir.mkdirs())
                    throw new IllegalStateException("无法创建私有更新目录");
                temp=new File(downloadsDir,"glacier-update.apk.part");
                File ready=new File(downloadsDir,"glacier-update-verified.apk");
                if(!temp.delete()&&temp.exists())
                    throw new IllegalStateException("无法删除上次的临时文件");
                MessageDigest sha=MessageDigest.getInstance("SHA-256");
                long total=0;
                try(GlacierUpdateTransport.Response response=
                            GlacierUpdateTransport.open(release.url,throughVless,NativeProxy.PORT);
                    InputStream input=response.body;
                    FileOutputStream output=new FileOutputStream(temp)) {
                    byte[] buffer=new byte[64*1024];
                    int n,last=-1;
                    while((n=input.read(buffer))!=-1) {
                        if(canceled.get())throw new IllegalStateException("用户已取消下载");
                        total+=n;
                        if(total>release.size||total>MAX_SIZE)
                            throw new SecurityException("下载内容超出签名发布大小");
                        sha.update(buffer,0,n);output.write(buffer,0,n);
                        int percent=(int)(total*100/release.size);
                        if(percent!=last) {
                            last=percent;
                            final int value=percent;
                            main.post(()->progress.accept(value));
                        }
                    }
                    output.getFD().sync();
                }
                if(canceled.get())throw new IllegalStateException("用户已取消下载");
                if(total!=release.size||!hex(sha.digest()).equals(release.sha256))
                    throw new SecurityException("下载文件长度或 SHA-256 校验失败");
                validateApk(temp,release);
                if(ready.exists()&&!ready.delete())
                    throw new IllegalStateException("无法替换旧更新文件");
                if(!temp.renameTo(ready))
                    throw new IllegalStateException("无法保存已验证 APK");
                verifiedFile=ready;
                verifiedRelease=release;
                File accepted=ready;
                main.post(()->done.done(accepted,null));
            } catch(Exception error) {
                if(temp!=null)temp.delete();
                main.post(()->done.done(null,error));
            }
        });
    }

    boolean hasReady() {
        return verifiedFile!=null&&verifiedFile.isFile()&&verifiedRelease!=null;
    }

    /** Calls Android's normal installer, never does privileged/silent installs. */
    boolean requestInstall() throws Exception {
        if(BuildConfig.DEBUG)return false;
        File file=verifiedFile; Release release=verifiedRelease;
        if(file==null||release==null||!file.isFile())return false;
        File expected=new File(downloadsDir,"glacier-update-verified.apk");
        if(!file.getCanonicalFile().equals(expected.getCanonicalFile()))
            throw new SecurityException("非私有更新缓存文件");
        // Re-verify bytes as well as APK signer immediately before installer.
        MessageDigest hash=MessageDigest.getInstance("SHA-256");
        long count=0;
        try(FileInputStream in=new FileInputStream(file)) {
            byte[] buffer=new byte[65536];
            int n;
            while((n=in.read(buffer))!=-1) {
                count+=n;
                if(count>MAX_SIZE)throw new SecurityException("APK 超出限制");
                hash.update(buffer,0,n);
            }
        }
        if(count!=release.size||!hex(hash.digest()).equals(release.sha256))
            throw new SecurityException("更新包在缓存中发生变化");
        validateApk(file,release);
        if(Build.VERSION.SDK_INT>=26&&!activity.getPackageManager().canRequestPackageInstalls()) {
            Intent permission=new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:"+activity.getPackageName()));
            activity.startActivity(permission);
            return false;
        }
        Uri content=FileProvider.getUriForFile(activity,
                activity.getPackageName()+".updates",file);
        Intent install=new Intent(Intent.ACTION_VIEW);
        install.setDataAndType(content,"application/vnd.android.package-archive");
        install.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        activity.startActivity(install);
        return true;
    }

    void dispose() { executor.shutdownNow(); }
}
