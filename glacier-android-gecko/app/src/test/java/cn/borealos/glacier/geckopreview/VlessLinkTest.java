package cn.borealos.glacier.geckopreview;
import org.junit.Test;
import static org.junit.Assert.*;

public final class VlessLinkTest {
    private static final String UUID="123e4567-e89b-12d3-a456-426614174000";
    private static final String BASE="vless://"+UUID+"@example.com:443?encryption=none";

    @Test public void acceptsTlsTcp() throws Exception {
        VlessLink n=VlessLink.parse(BASE+"&security=tls&type=tcp&sni=example.com");
        assertEquals("example.com",n.host);
        assertEquals(443,n.port);
        assertEquals("tls",n.security);
        assertEquals("tcp",n.transport);
    }
    @Test public void acceptsRealityAndVision() throws Exception {
        VlessLink n=VlessLink.parse(BASE+"&security=reality&type=tcp&flow=xtls-rprx-vision"
                +"&sni=example.org&pbk=fake_public_key&sid=ab12&fp=chrome");
        assertEquals("reality",n.security);
        assertEquals("fake_public_key",n.publicKey);
        assertEquals("xtls-rprx-vision",n.flow);
    }
    @Test public void rejectsInsecureOrMissingTls() {
        reject(BASE+"&security=none");
        reject(BASE+"&security=tls&allowInsecure=1");
        reject(BASE+"&security=reality&insecure=true&pbk=fake_key");
        reject(BASE+"&security=tls&insecure=1");
    }
    @Test public void rejectsUnsupportedOrBrokenNode() {
        reject(BASE+"&security=tls&type=grpc");
        reject(BASE+"&security=tls&type=ws&flow=xtls-rprx-vision");
        reject(BASE+"&security=reality");
        reject(BASE+"&security=tls&flow=unknown-flow");
        reject("vless://broken@example.com:443?security=tls");
        reject("https://example.com");
        reject(BASE+"&security=tls&security=reality");
    }
    private static void reject(String link) {
        try { VlessLink.parse(link); fail("Accepted unsafe share link"); }
        catch(Exception expected) {}
    }
}
