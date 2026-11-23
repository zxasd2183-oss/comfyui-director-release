package cn.borealos.glacier.geckopreview;

import org.mozilla.geckoview.Autocomplete;
import org.junit.Test;
import org.junit.runner.RunWith;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import static org.junit.Assert.*;
import java.util.Arrays;
import java.util.ArrayList;
import java.util.List;

/** Synthetic browser-submitted logins; no real credentials or remote websites. */
@RunWith(AndroidJUnit4.class)
public class GlacierNativePasswordSaveInstrumentedTest {
    private Autocomplete.LoginEntry login(String origin,String username,String password) {
        return new Autocomplete.LoginEntry.Builder()
                .origin(origin).username(username).password(password).build();
    }

    @Test public void geckoLoginProducesEncryptedVaultCandidateWithoutPageScript() {
        BrowserAccountsStore.Card c=GlacierNativePasswordSave.proposed(
                "private","https://accounts.example.org/sign-in",
                login("https://accounts.example.org","person@example.org","test-pass-value"));
        assertNotNull(c);
        assertEquals("accounts.example.org",c.site);
        assertEquals("private",c.profile);
        assertEquals("person@example.org",c.username);
        assertEquals("test-pass-value",c.password);
        assertTrue(BrowserAccountsStore.valid(c));
    }

    @Test public void rejectsUntrustedOriginsAndOtherWorkspaceContext() {
        assertNull(GlacierNativePasswordSave.proposed(
                "work","http://accounts.example.org/login",
                login("http://accounts.example.org","user","secret")));
        assertNull(GlacierNativePasswordSave.proposed(
                "private","https://accounts.example.org/login",
                login("https://evil.example.net","user","secret")));
        assertNull(GlacierNativePasswordSave.proposed(
                "private","https://accounts.example.org/login",
                login("https://accounts.example.org","user","")));
        assertNull(GlacierNativePasswordSave.proposed(
                "unknown","https://accounts.example.org/login",
                login("https://accounts.example.org","user","secret")));
        Autocomplete.LoginEntry crossAction=new Autocomplete.LoginEntry.Builder()
                .origin("https://accounts.example.org")
                .formActionOrigin("https://evil.example.net")
                .username("test").password("secret").build();
        assertNull(GlacierNativePasswordSave.proposed(
                "private","https://accounts.example.org/login",crossAction));
    }

    @Test public void updatesExistingIdentityWhilePreservingOthersAndCodeApi() {
        BrowserAccountsStore.Card existing=new BrowserAccountsStore.Card(
                "work","accounts.example.org","Personal label","user@example.org",
                "old-password","https://otp.example.org/api");
        BrowserAccountsStore.Card privateCard=new BrowserAccountsStore.Card(
                "private","accounts.example.org","Private user","user@example.org",
                "private-password","");
        List<BrowserAccountsStore.Card> original=Arrays.asList(existing,privateCard);
        BrowserAccountsStore.Card incoming=GlacierNativePasswordSave.proposed(
                "work","https://accounts.example.org/",
                login("https://accounts.example.org","user@example.org","new-password"));
        List<BrowserAccountsStore.Card> updated=GlacierNativePasswordSave.previewSave(
                original,incoming);
        assertEquals(2,updated.size());
        assertEquals("new-password",updated.get(0).password);
        assertEquals("Personal label",updated.get(0).name);
        assertEquals("https://otp.example.org/api",updated.get(0).codeApi);
        assertEquals("private-password",updated.get(1).password);
        assertEquals("old-password",original.get(0).password); // old list immutable
        assertFalse(GlacierNativePasswordSave.existingPasswordUnchanged(original,incoming));
        assertTrue(GlacierNativePasswordSave.existingPasswordUnchanged(updated,incoming));
    }

    @Test public void newLoginWithSameAliasDoesNotReplaceAnotherUsername() {
        BrowserAccountsStore.Card old=new BrowserAccountsStore.Card(
                "private","accounts.example.org","user@example.org",
                "other@example.org","other-password","");
        BrowserAccountsStore.Card incoming=GlacierNativePasswordSave.proposed(
                "private","https://accounts.example.org/login",
                login("https://accounts.example.org","user@example.org","password"));
        List<BrowserAccountsStore.Card> result=GlacierNativePasswordSave.previewSave(
                Arrays.asList(old),incoming);
        assertEquals(2,result.size());
        assertEquals("other-password",result.get(0).password);
        assertTrue(result.get(1).name.contains("(2)"));
    }
}
