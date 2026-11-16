package cn.borealos.glacier.geckopreview;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Synthetic host/profile guards; never requires real accounts or network. */
@RunWith(AndroidJUnit4.class)
public final class GlacierAccountFillInstrumentedTest {
    @Test
    public void requiresExactHttpsSiteAndNeverAcceptsSiblingSubdomains() {
        assertTrue(GlacierAccountFill34.exactHttpsSite(
                "https://github.com/login", "github.com"));
        assertTrue(GlacierAccountFill34.exactHttpsSite(
                "https://www.github.com:443/", "github.com"));
        for (String candidate: new String[]{
                "http://github.com/login", "https://github.com:444/login",
                "https://github.com.evil.invalid/", "https://login.github.com/",
                "https://attacker@github.com/", "file:///github.com/login",
                "https://github.com@evil.invalid/", "about:blank"
        }) {
            assertFalse(candidate,GlacierAccountFill34.exactHttpsSite(
                    candidate,"github.com"));
        }
        assertFalse(GlacierAccountFill34.exactHttpsSite(
                "https://github.com/","github.com.evil/path"));
        assertFalse(GlacierAccountFill34.exactHttpsSite(
                "https://github.com/",""));
    }

    @Test
    public void refusesMissingSessionOrInvalidAccountWithoutTouchingGecko() {
        BrowserAccountsStore.Card saved = new BrowserAccountsStore.Card(
                "private","github.com","Primary","test@example.invalid","test-only",""
        );
        assertTrue(BrowserAccountsStore.valid(saved));
        assertEquals(0,GlacierAccountFill34.fill(null,
                "https://github.com/login",saved));
        assertEquals(0,GlacierAccountFill34.fill(null,
                "https://github.com.evil.invalid/",saved));
        assertEquals(0,GlacierAccountFill34.fill(null,
                "https://github.com/",null));
    }
}
