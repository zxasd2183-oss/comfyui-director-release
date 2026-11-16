package cn.borealos.glacier.geckopreview;

import android.net.Uri;
import android.util.SparseArray;

import org.mozilla.geckoview.Autofill;
import org.mozilla.geckoview.GeckoSession;

import java.util.ArrayDeque;
import java.util.Locale;

/**
 * Native GeckoView account fill with no JavaScript, auto-submit or network access.
 *
 * Call only on a user's explicit action after the host Activity has verified
 * that the active GeckoSession uses the selected saved account's unique contextId.
 * Gecko's own autofill tree supplies node IDs, visibility and origin metadata.
 */
final class GlacierAccountFill34 {
    private GlacierAccountFill34() {}

    static boolean exactHttpsSite(String url, String site) {
        if (site == null || !site.equals(BrowserAccountsStore.site(site)))
            return false;
        try {
            Uri uri = Uri.parse(url);
            if (!"https".equalsIgnoreCase(uri.getScheme())
                    || uri.getUserInfo() != null
                    || (uri.getPort() != -1 && uri.getPort() != 443)
                    || uri.getHost() == null) return false;
            String host = uri.getHost().toLowerCase(Locale.ROOT);
            return host.equals(site) || host.equals("www." + site);
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    private static boolean exactNodeSite(String domain, String site) {
        if (domain == null || domain.isEmpty()) return false;
        String value = domain.trim().toLowerCase(Locale.ROOT);
        // Gecko reports an input's web domain. Support explicit HTTPS origin
        // and raw hostname but never wildcard or registrable-domain matching.
        if (value.startsWith("https://")) return exactHttpsSite(value, site);
        if (value.contains("/") || value.contains(":") || value.contains("@"))
            return false;
        return value.equals(site) || value.equals("www." + site);
    }

    /**
     * Returns the number of fields handed to Gecko, not a login success claim.
     * Refuses missing/mismatched origins, hidden and ambiguous input fields.
     */
    static int fill(GeckoSession gecko, String currentUrl,
                    BrowserAccountsStore.Card card) {
        if (gecko == null || !BrowserAccountsStore.valid(card)
                || !exactHttpsSite(currentUrl, card.site)) return 0;

        try {
            Autofill.Session session = gecko.getAutofillSession();
            Autofill.Node root = session.getRoot();
            if (root == null) return 0;
            ArrayDeque<Autofill.Node> queue = new ArrayDeque<>();
            queue.add(root);
            Autofill.Node username = null;
            Autofill.Node password = null;
            int count = 0;
            while (!queue.isEmpty()) {
                if (++count > 500) return 0; // Refuse unusually complex trees.
                Autofill.Node node = queue.removeFirst();
                if (node.getChildren() != null) {
                    for (Autofill.Node child : node.getChildren()) {
                        if (child != null) queue.add(child);
                    }
                }
                if (!"input".equalsIgnoreCase(node.getTag())
                        || !node.getEnabled() || !node.getFocusable()
                        || !session.isVisible(node)
                        || !exactNodeSite(node.getDomain(), card.site)) continue;

                int hint = node.getHint();
                if (hint == Autofill.Hint.PASSWORD) {
                    if (password != null) return 0;  // Ambiguous login forms.
                    password = node;
                } else if (hint == Autofill.Hint.USERNAME
                        || hint == Autofill.Hint.EMAIL_ADDRESS) {
                    if (username != null) return 0;
                    username = node;
                }
            }
            SparseArray<CharSequence> values = new SparseArray<>(2);
            if (username != null) {
                values.put(session.dataFor(username).getId(), card.username);
            }
            if (password != null && !card.password.isEmpty()) {
                values.put(session.dataFor(password).getId(), card.password);
            }
            if (values.size() == 0) return 0;
            // Dispatch values only into the currently active GeckoSession's
            // visible, first-party input nodes; never submit the web form.
            session.autofill(values);
            return values.size();
        } catch (RuntimeException ignored) {
            // No credentials, URL, exception text, or field values in logs.
            return 0;
        }
    }
}
