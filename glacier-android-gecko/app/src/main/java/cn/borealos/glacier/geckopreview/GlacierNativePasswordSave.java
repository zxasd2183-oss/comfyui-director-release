package cn.borealos.glacier.geckopreview;

import org.mozilla.geckoview.Autocomplete;

import java.util.ArrayList;
import java.util.List;

/**
 * Browser-native GeckoView login-save input -> existing Keystore-encrypted vault.
 *
 * GeckoView identifies the login form and passes a LoginEntry to the host.
 * Only a user-confirmed save may call BrowserAccountsStore.save; there is
 * deliberately no DOM password scraping or automatic submission.
 *
 * Autofill retrieval is not globally attached here: GeckoRuntime's
 * StorageDelegate.onLoginFetch(domain) has no requesting GeckoSession, and
 * could cross the private/work context boundary. Existing session-scoped
 * explicit fill remains supported until a scoped fetch mechanism is built.
 */
final class GlacierNativePasswordSave {
    private GlacierNativePasswordSave() {}

    static BrowserAccountsStore.Card proposed(String profile, String currentUrl,
            Autocomplete.LoginEntry entry) {
        if (!BrowserLibraryStore.validProfile(profile) || entry==null) return null;
        final String site=BrowserAccountsStore.siteFromUrl(currentUrl);
        if (site.isEmpty() || !site.equals(BrowserAccountsStore.siteFromUrl(entry.origin)))
            return null;
        if (entry.formActionOrigin != null && !entry.formActionOrigin.isEmpty()
                && BrowserAccountsStore.siteFromUrl(entry.formActionOrigin).isEmpty())
            return null;
        if (entry.httpRealm != null && !entry.httpRealm.isEmpty())
            return null; // HTTP Basic Auth is a separate save prompt class.
        if (entry.username==null || entry.username.isEmpty()
                || entry.username.length()>250 || entry.password==null
                || entry.password.isEmpty() || entry.password.length()>2048)
            return null;
        String label=entry.username.trim();
        if (label.isEmpty()) return null;
        if (label.length()>60) label=label.substring(0,60);
        BrowserAccountsStore.Card next=new BrowserAccountsStore.Card(
                profile,site,label,entry.username,entry.password,"");
        return BrowserAccountsStore.valid(next)?next:null;
    }

    /**
     * Pure atomic-vault candidate builder. Match the user's login identity;
     * a password update must replace that identity without losing any other
     * account, code API or the private/work compartment.
     */
    static List<BrowserAccountsStore.Card> previewSave(
            List<BrowserAccountsStore.Card> old,
            BrowserAccountsStore.Card incoming) {
        if (old==null || !BrowserAccountsStore.valid(incoming))
            throw new IllegalArgumentException("Invalid password-save candidate");
        List<BrowserAccountsStore.Card> result=new ArrayList<>();
        boolean replaced=false;
        for(BrowserAccountsStore.Card c:old) {
            if (!BrowserAccountsStore.valid(c))
                throw new IllegalArgumentException("Damaged local account vault");
            if (c.profile.equals(incoming.profile) && c.site.equals(incoming.site)
                    && c.username.equals(incoming.username)) {
                if (replaced) throw new IllegalArgumentException("Duplicate site login");
                result.add(new BrowserAccountsStore.Card(
                        c.profile,c.site,c.name,c.username,incoming.password,c.codeApi));
                replaced=true;
            } else {
                result.add(c);
            }
        }
        if (!replaced) {
            // Existing name can belong to another login; make a unique short
            // display label rather than collide with the atomic vault schema.
            String base=incoming.name;
            String unique=base;
            int suffix=2;
            boolean collision;
            do {
                collision=false;
                for (BrowserAccountsStore.Card c:result) {
                    if (c.profile.equals(incoming.profile) && c.site.equals(incoming.site)
                            && c.name.equalsIgnoreCase(unique)) {
                        collision=true;break;
                    }
                }
                if (collision) {
                    String ending=" ("+(suffix++)+")";
                    unique=base.substring(0,Math.min(base.length(),60-ending.length()))+ending;
                }
            } while (collision && suffix<=110);
            if (collision)throw new IllegalArgumentException("Too many accounts for this site");
            result.add(new BrowserAccountsStore.Card(
                    incoming.profile,incoming.site,unique,incoming.username,incoming.password,""));
        }
        if (result.size()>100)throw new IllegalArgumentException("Account capacity exceeded");
        return result;
    }

    static boolean existingPasswordUnchanged(List<BrowserAccountsStore.Card> cards,
                                               BrowserAccountsStore.Card proposed) {
        for(BrowserAccountsStore.Card c:cards)
            if(c.profile.equals(proposed.profile)&&c.site.equals(proposed.site)
                    &&c.username.equals(proposed.username)
                    &&c.password.equals(proposed.password))
                return true;
        return false;
    }
}
