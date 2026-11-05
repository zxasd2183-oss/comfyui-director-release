package cn.borealos.glacier.geckopreview;

import org.junit.Test;
import static org.junit.Assert.*;

public final class UrlPolicyTest {
    @Test public void removesQueriesAndFragments() {
        assertEquals("https://example.com/path",
            UrlPolicy.safePersistentUrl("https://example.com/path?code=secret#session"));
    }

    @Test public void acceptsOrdinarySecureUrls() {
        assertEquals("https://chatgpt.com/",
            UrlPolicy.safePersistentUrl("https://chatgpt.com/"));
        assertEquals("https://github.com/org/project",
            UrlPolicy.safePersistentUrl("https://github.com/org/project"));
    }

    @Test public void rejectsExposedCredentials() {
        assertNull(UrlPolicy.safePersistentUrl("https://alice:secret@example.com/private"));
        assertNull(UrlPolicy.safePersistentUrl("https://alice@example.com/private"));
    }

    @Test public void rejectsScriptsAndInternalPages() {
        assertNull(UrlPolicy.safePersistentUrl("javascript:alert(1)"));
        assertNull(UrlPolicy.safePersistentUrl("file:///etc/passwd"));
        assertNull(UrlPolicy.safePersistentUrl("about:buildconfig"));
        assertNull(UrlPolicy.safePersistentUrl("data:text/html,evil"));
    }

    @Test public void rejectsCleartextSchemesAndMalformedHosts() {
        assertNull(UrlPolicy.safePersistentUrl("http://example.com/"));
        assertNull(UrlPolicy.safePersistentUrl("https://"));
        assertNull(UrlPolicy.safePersistentUrl("https:///missing-host"));
        assertNull(UrlPolicy.safePersistentUrl("https://name space.com/"));
    }

    @Test public void titlesAreSafeForDialogDisplay() {
        assertEquals("Hello World", UrlPolicy.label(" Hello\nWorld\r", "https://example.com"));
        assertEquals("https://example.com", UrlPolicy.label(null, "https://example.com"));
    }
}
