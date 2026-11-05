package cn.borealos.glacier.geckopreview;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;

/** Conservative persistent browser history / bookmark / startup URL filter. */
public final class UrlPolicy {
    private UrlPolicy() {}

    /**
     * Persist only HTTPS network locations with no credentials, query, or fragment.
     * This deliberately drops query-string OTPs, auth codes and tracking tokens
     * rather than writing them into history or tab-recovery snapshots.
     */
    public static String safePersistentUrl(String raw) {
        if (raw == null) return null;
        String input = raw.trim();
        if (input.length() < 9 || input.length() > 4096) return null;
        try {
            URI uri = new URI(input);
            if (!"https".equalsIgnoreCase(uri.getScheme())) return null;
            String host = uri.getHost();
            if (host == null || host.trim().isEmpty()) return null;
            if (uri.getRawUserInfo() != null) return null;
            if (uri.getPort() > 65535) return null;
            if (uri.getRawAuthority() == null || uri.getRawAuthority().contains("\\")) return null;
            int cut = input.length();
            int question = input.indexOf('?');
            int hash = input.indexOf('#');
            if (question >= 0) cut = Math.min(cut, question);
            if (hash >= 0) cut = Math.min(cut, hash);
            return input.substring(0, cut);
        } catch (URISyntaxException | IllegalArgumentException e) {
            return null;
        }
    }

    public static String label(String title, String url) {
        String text = title == null ? "" : title.replace('\n', ' ').replace('\r', ' ').trim();
        if (text.isEmpty()) text = url;
        if (text == null) text = "网页";
        return text.length() > 100 ? text.substring(0, 100) + "…" : text;
    }
}
