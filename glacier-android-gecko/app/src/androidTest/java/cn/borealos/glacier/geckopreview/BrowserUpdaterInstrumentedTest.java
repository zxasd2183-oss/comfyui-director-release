package cn.borealos.glacier.geckopreview;

import androidx.test.ext.junit.runners.AndroidJUnit4;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

import java.io.InputStream;
import java.io.OutputStream;
import java.io.IOException;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.Assert.*;

/** Synthetic local-only M05 tests. Never contact GitHub, VPS or a VLESS node. */
@RunWith(AndroidJUnit4.class)
public final class BrowserUpdaterInstrumentedTest {
    private static JSONObject release(String version,String digest) throws Exception {
        String tag="glacier-android-browser-v"+version;
        String asset="GlacierAndroid-v"+version+"-ARM64-x86_64-release.apk";
        String url="https://github.com/zxasd2183-oss/comfyui-director-release/releases/download/"
                +tag+"/"+asset;
        JSONObject file=new JSONObject()
                .put("name",asset)
                .put("state","uploaded")
                .put("size",250000000L)
                .put("digest","sha256:"+digest)
                .put("browser_download_url",url);
        return new JSONObject()
                .put("draft",false).put("tag_name",tag)
                .put("assets",new JSONArray().put(file));
    }

    @Test
    public void updateReleaseSelectionRejectsOtherAppsBadDigestsAndDowngrades()
            throws Exception {
        String sha="abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789";
        JSONArray input=new JSONArray();
        input.put(release("0.2.1",sha)); // Current installed version.
        input.put(release("0.2.3",sha));
        input.put(release("0.2.2",sha));
        JSONObject imposter=release("0.2.9",sha);
        imposter.getJSONArray("assets").getJSONObject(0)
                .put("browser_download_url","https://evil.example/update.apk");
        input.put(imposter);
        JSONObject missingDigest=release("0.2.8",sha);
        missingDigest.getJSONArray("assets").getJSONObject(0).put("digest","");
        input.put(missingDigest);
        JSONObject draft=release("0.3.0",sha).put("draft",true);
        input.put(draft);
        input.put(new JSONObject().put("tag_name","jipite-v99.0.0")
                .put("assets",new JSONArray()));
        BrowserUpdater.Release found=BrowserUpdater.findLatest(input.toString(),"0.2.1");
        assertNotNull(found);
        assertEquals("0.2.3",found.version);
        assertEquals(250000000L,found.size);
        assertEquals(sha,found.sha256);
        assertNull(BrowserUpdater.findLatest(input.toString(),"0.2.5"));
        assertTrue(BrowserUpdater.newer("0.3.0","0.2.10"));
        assertFalse(BrowserUpdater.newer("0.2.0","0.2.1"));
        assertFalse(BrowserUpdater.newer("0.2.1-evil","0.2.0"));
    }

    @Test
    public void updateTransportRejectsUntrustedHostsAndSchemes() {
        assertTrue(GlacierUpdateTransport.allowed(GlacierUpdateTransport.API));
        assertTrue(GlacierUpdateTransport.allowed("https://github.com/a"));
        assertTrue(GlacierUpdateTransport.allowed("https://release-assets.githubusercontent.com/a"));
        for(String url:new String[]{
                "http://api.github.com/a","https://api.github.com.evil.com/a",
                "https://user:password@github.com/a","https://github.com:8443/a",
                "https://github.com.evil.example/a","file:///sdcard/Download/a.apk",
                "https://evil.example/a","https://github.com/a#token"
        }) assertFalse("Untrusted URL accepted: "+url,GlacierUpdateTransport.allowed(url));
    }

    private static int mustByte(InputStream in) throws IOException {
        int b=in.read();
        if(b<0)throw new IOException("Local fixture unexpectedly closed");
        return b;
    }
    private static void fully(InputStream in,byte[] data) throws IOException {
        int pos=0;
        while(pos<data.length) {
            int n=in.read(data,pos,data.length-pos);
            if(n<0)throw new IOException("Local fixture truncated");
            pos+=n;
        }
    }

    @Test
    public void socksV5SendsHostnameToProxyAndNeverConnectsRemoteDirectly()
            throws Exception {
        ServerSocket local=new ServerSocket(0,1,InetAddress.getByName("127.0.0.1"));
        local.setSoTimeout(10000);
        AtomicReference<String> host=new AtomicReference<>();
        AtomicReference<Throwable> error=new AtomicReference<>();
        Thread server=new Thread(()->{
            try(Socket peer=local.accept()) {
                peer.setSoTimeout(8000);
                InputStream in=peer.getInputStream();
                OutputStream out=peer.getOutputStream();
                assertEquals(5,mustByte(in));
                assertEquals(1,mustByte(in));
                assertEquals(0,mustByte(in));
                out.write(new byte[]{5,0});out.flush();
                assertEquals(5,mustByte(in));
                assertEquals(1,mustByte(in));  // CONNECT
                assertEquals(0,mustByte(in));
                assertEquals(3,mustByte(in));  // DNS hostname, NOT local IPv4 address
                int len=mustByte(in);
                byte[] bytes=new byte[len];fully(in,bytes);
                host.set(new String(bytes,StandardCharsets.US_ASCII));
                int port=(mustByte(in)<<8)|mustByte(in);
                assertEquals(443,port);
                out.write(new byte[]{5,0,0,1,127,0,0,1,0,0});out.flush();
            }catch(Throwable ex){error.set(ex);}
        },"m05-local-socks-fixture");
        server.start();
        try(Socket route=GlacierUpdateTransport.connectSocks(
                "api.github.com",443,local.getLocalPort())) {
            assertNotNull(route);
        } finally {
            server.join(10000);
            local.close();
        }
        assertNull("SOCKS fixture error: "+error.get(),error.get());
        assertEquals("api.github.com",host.get());
    }

    @Test
    public void socksWithoutLocalServiceFailsClosed() throws Exception {
        int port;
        try(ServerSocket local=new ServerSocket(0,1,InetAddress.getByName("127.0.0.1"))) {
            port=local.getLocalPort();
        }
        try(Socket forbidden=GlacierUpdateTransport.connectSocks("github.com",443,port)) {
            fail("Unreachable local SOCKS must never use DIRECT socket");
        }catch(IOException expected){
            // No proxy listener. Request was rejected rather than routed directly.
        }
    }
}
