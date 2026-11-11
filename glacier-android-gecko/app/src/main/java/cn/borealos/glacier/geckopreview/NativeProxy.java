package cn.borealos.glacier.geckopreview;

import android.content.Context;
import org.mozilla.geckoview.GeckoRuntimeSettings;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;

/**
 * Experimental Gecko-only networking:
 * official sing-box android CLI ELF (packaged as libsingbox.so in native libs)
 * + loopback SOCKS5 + Gecko runtime YAML prefs.
 *
 * Not an Android VpnService; doesn't protect traffic from other Android apps.
 * No direct fallback: manual SOCKS5 with remote DNS, HTTP/3 and WebRTC disabled.
 */
public final class NativeProxy {
    public static final int PORT = 18566;
    private static Process process;
    private static File config;
    private static boolean running;

    private NativeProxy() {}

    private static File noBackupFile(Context ctx, String name) {
        File folder=ctx.getNoBackupFilesDir();
        if(!folder.exists()) folder.mkdirs();
        return new File(folder,name);
    }

    private static void writePrivate(File path,String value) throws Exception {
        try (FileOutputStream output=new FileOutputStream(path,false)) {
            output.write(value.getBytes(StandardCharsets.UTF_8));
            output.flush();
            output.getFD().sync();
        }
        path.setReadable(false,false);
        path.setWritable(false,false);
        path.setReadable(true,true);
        path.setWritable(true,true);
    }

    public static String prepareGecko(Context ctx, boolean useProxy) throws Exception {
        // Config is always written before GeckoRuntime is created, so no
        // request can occur using default network settings by accident.
        File yaml=noBackupFile(ctx,"gecko-network.yaml");
        String text;
        if (useProxy) {
            text="prefs:\n"+
                 "  network.proxy.type: 1\n"+
                 "  network.proxy.socks: \"127.0.0.1\"\n"+
                 "  network.proxy.socks_port: "+PORT+"\n"+
                 "  network.proxy.socks_version: 5\n"+
                 "  network.proxy.socks_remote_dns: true\n"+
                 "  network.proxy.failover_direct: false\n"+
                 "  network.proxy.no_proxies_on: \"\"\n"+
                 // Force DNS through SOCKS; avoid private DoH/prefetch paths.
                 "  network.proxy.allow_hijacking_localhost: true\n"+
                 "  network.trr.mode: 5\n"+
                 "  network.dns.disablePrefetch: true\n"+
                 "  network.predictor.enabled: false\n"+
                 "  network.prefetch-next: false\n"+
                 "  network.http.http3.enable: false\n"+
                 // WebRTC can disclose local/public addresses outside SOCKS.
                 "  media.peerconnection.enabled: false\n";
        } else {
            // Deliberate direct mode; user must opt in explicitly.
            text="prefs:\n  network.proxy.type: 0\n";
        }
        writePrivate(yaml,text);
        return yaml.getAbsolutePath();
    }

    /** Worker thread only; may take a few seconds. No node details are logged. */
    public static synchronized void start(Context context,VlessLink node) throws Exception {
        stop();
        File binary=new File(context.getApplicationInfo().nativeLibraryDir,"libsingbox.so");
        if(!binary.isFile()||!binary.canExecute())
            throw new Exception("内置 sing-box 核心缺失或无法执行");
        // Never use someone else's listener as a trusted proxy.
        try (ServerSocket check = new ServerSocket(PORT,1,
                InetAddress.getByName("127.0.0.1"))) {
            // Free the port before starting the local sing-box process.
        } catch (Exception ex) {
            throw new Exception("本地代理端口已被占用，请先关闭占用端口的应用");
        }
        config=noBackupFile(context,"sing-box-node.json");
        writePrivate(config,node.singBoxConfig(PORT).toString());
        try {
            process=new ProcessBuilder(binary.getAbsolutePath(),"run","-c",
                    config.getAbsolutePath())
                    .directory(context.getNoBackupFilesDir())
                    .redirectErrorStream(true)
                    // Discard stdout: upstream diagnostics can contain server
                    // addresses or other secrets. Do not log them.
                    .redirectOutput(new File("/dev/null"))
                    .start();
            for(int i=0;i<40;i++) {
                if(!process.isAlive())
                    throw new Exception("sing-box 核心启动失败或配置不兼容");
                if(isSocksReady()) {
                    running=true;
                    return;
                }
                Thread.sleep(250);
            }
            throw new Exception("本地 SOCKS5 端口未就绪");
        } catch(Exception e) {
            stop();
            throw e;
        }
    }

    private static boolean isSocksReady() {
        try (Socket sock=new Socket()) {
            sock.connect(new java.net.InetSocketAddress("127.0.0.1",PORT),200);
            sock.setSoTimeout(200);
            sock.getOutputStream().write(new byte[]{5,1,0});
            byte[] reply=new byte[2];
            int first=sock.getInputStream().read();
            int second=sock.getInputStream().read();
            return first==5 && second==0;
        } catch (Exception e) {
            return false;
        }
    }

    public static synchronized boolean alive() {
        return running && process!=null && process.isAlive();
    }

    public static synchronized void stop() {
        running=false;
        if(process!=null) {
            process.destroy();
            try {
                if(!process.waitFor(1500,java.util.concurrent.TimeUnit.MILLISECONDS))
                    process.destroyForcibly();
            } catch(InterruptedException e) {
                Thread.currentThread().interrupt();
                process.destroyForcibly();
            }
            process=null;
        }
        if(config!=null) {
            config.delete();
            config=null;
        }
    }

    public static synchronized void deleteStaleFiles(Context ctx) {
        // Called on cold startup, before user supplies another node.
        noBackupFile(ctx,"sing-box-node.json").delete();
        noBackupFile(ctx,"gecko-network.yaml").delete();
    }
}
