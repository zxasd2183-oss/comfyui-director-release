package cn.borealos.glacier.geckopreview;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.widget.Toast;

import org.mozilla.geckoview.GeckoResult;
import org.mozilla.geckoview.GeckoSession;
import org.mozilla.geckoview.WebResponse;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * User-mediated Android Storage Access Framework upload/download bridge.
 * The Gecko response stream is used directly: no DownloadManager re-fetch
 * (which would bypass Gecko's proxy and isolated cookie session).
 */
final class BrowserTransfers {
    private static final int PICK_UPLOAD = 5011;
    private static final int PICK_DOWNLOAD_DESTINATION = 5012;
    private static final long MAX_DOWNLOAD_BYTES = 64L * 1024 * 1024;
    private final Activity activity;
    private GeckoSession.PromptDelegate.FilePrompt pendingPrompt;
    private GeckoResult<GeckoSession.PromptDelegate.PromptResponse> pendingResult;
    private File pendingDownload;
    private boolean downloadBusy;

    BrowserTransfers(Activity activity) { this.activity = activity; }

    GeckoResult<GeckoSession.PromptDelegate.PromptResponse> onFilePrompt(
            GeckoSession session, GeckoSession.PromptDelegate.FilePrompt prompt) {
        if (pendingResult != null) {
            return GeckoResult.fromValue(prompt.dismiss());
        }
        if (prompt.type == GeckoSession.PromptDelegate.FilePrompt.Type.FOLDER) {
            Toast.makeText(activity, "暂不支持上传文件夹", Toast.LENGTH_SHORT).show();
            return GeckoResult.fromValue(prompt.dismiss());
        }
        Intent pick = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        pick.addCategory(Intent.CATEGORY_OPENABLE);
        pick.setType("*/*");
        pick.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        pick.putExtra(Intent.EXTRA_ALLOW_MULTIPLE,
                prompt.type == GeckoSession.PromptDelegate.FilePrompt.Type.MULTIPLE);
        if (prompt.mimeTypes != null && prompt.mimeTypes.length > 0) {
            ArrayList<String> valid = new ArrayList<>();
            for (String type : prompt.mimeTypes) {
                if (type != null && type.contains("/") && type.length() < 128) {
                    valid.add(type);
                }
            }
            if (!valid.isEmpty()) {
                pick.putExtra(Intent.EXTRA_MIME_TYPES, valid.toArray(new String[0]));
            }
        }
        pendingPrompt = prompt;
        GeckoResult<GeckoSession.PromptDelegate.PromptResponse> result = new GeckoResult<>();
        pendingResult = result;
        try {
            activity.startActivityForResult(pick, PICK_UPLOAD);
        } catch (ActivityNotFoundException | SecurityException ex) {
            finishUpload(null);
            Toast.makeText(activity, "无法打开系统文件选择器", Toast.LENGTH_LONG).show();
        }
        return result;
    }

    private void finishUpload(Uri[] uris) {
        GeckoSession.PromptDelegate.FilePrompt prompt = pendingPrompt;
        GeckoResult<GeckoSession.PromptDelegate.PromptResponse> result = pendingResult;
        pendingPrompt = null;
        pendingResult = null;
        if (prompt == null || result == null) return;
        if (uris == null || uris.length == 0) {
            result.complete(prompt.dismiss());
        } else {
            result.complete(prompt.confirm(activity.getApplicationContext(), uris));
        }
    }

    void onExternalResponse(WebResponse response) {
        if (response.body == null) {
            Toast.makeText(activity, "此下载没有可保存的数据", Toast.LENGTH_LONG).show();
            return;
        }
        Uri uri = Uri.parse(response.uri == null ? "" : response.uri);
        String scheme = uri.getScheme();
        if (!"https".equalsIgnoreCase(scheme)
                && !"http".equalsIgnoreCase(scheme)
                && !"blob".equalsIgnoreCase(scheme)) {
            closeQuietly(response.body);
            Toast.makeText(activity, "不支持此下载类型", Toast.LENGTH_LONG).show();
            return;
        }
        if (downloadBusy) {
            closeQuietly(response.body);
            Toast.makeText(activity, "请先完成当前下载", Toast.LENGTH_SHORT).show();
            return;
        }
        String name = safeFilename(response, uri);
        String mime = header(response.headers, "content-type");
        if (mime == null || mime.trim().isEmpty()) mime = "application/octet-stream";
        else mime = mime.split(";", 2)[0].trim();
        final String safeMime = mime;

        downloadBusy = true;
        new AlertDialog.Builder(activity)
                .setTitle("保存下载文件？")
                .setMessage(name + "\n文件将保存到你在 Android 文件选择器中指定的位置。")
                .setNegativeButton("取消", (d,w) -> {
                    downloadBusy = false;
                    closeQuietly(response.body);
                })
                .setOnCancelListener(d -> {
                    downloadBusy = false;
                    closeQuietly(response.body);
                })
                .setPositiveButton("继续", (d,w) -> stageDownload(response.body,name,safeMime))
                .show();
    }

    private void stageDownload(InputStream body, String filename, String mime) {
        new Thread(() -> {
            File staged = null;
            try (InputStream input = body) {
                staged = File.createTempFile("glacier-dl-", ".part", activity.getCacheDir());
                byte[] buffer = new byte[65536];
                long total = 0;
                try (OutputStream out = new FileOutputStream(staged)) {
                    int n;
                    while ((n = input.read(buffer)) != -1) {
                        total += n;
                        if (total > MAX_DOWNLOAD_BYTES)
                            throw new IllegalStateException("文件超过实验版 64 MB 限制");
                        out.write(buffer, 0, n);
                    }
                }
                File done = staged;
                activity.runOnUiThread(() -> {
                    pendingDownload = done;
                    Intent save = new Intent(Intent.ACTION_CREATE_DOCUMENT);
                    save.addCategory(Intent.CATEGORY_OPENABLE);
                    save.setType(mime);
                    save.putExtra(Intent.EXTRA_TITLE, filename);
                    try {
                        activity.startActivityForResult(save, PICK_DOWNLOAD_DESTINATION);
                    } catch (ActivityNotFoundException | SecurityException ex) {
                        clearDownload();
                        toast("无法打开文件保存选择器");
                    }
                });
            } catch (Exception ex) {
                if (staged != null) staged.delete();
                activity.runOnUiThread(() -> {
                    downloadBusy = false;
                    toast("下载未完成：请检查网络、文件大小或重试");
                });
            }
        }, "glacier-download-stage").start();
    }

    boolean onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == PICK_UPLOAD) {
            if (resultCode != Activity.RESULT_OK || data == null) {
                finishUpload(null);
            } else {
                List<Uri> chosen = new ArrayList<>();
                ClipData clip = data.getClipData();
                if (clip != null) {
                    for (int i=0;i<clip.getItemCount() && i<32;i++) {
                        Uri uri = clip.getItemAt(i).getUri();
                        if (uri != null && "content".equalsIgnoreCase(uri.getScheme()))
                            chosen.add(uri);
                    }
                } else if (data.getData() != null
                        && "content".equalsIgnoreCase(data.getData().getScheme())) {
                    chosen.add(data.getData());
                }
                finishUpload(chosen.toArray(new Uri[0]));
            }
            return true;
        }
        if (requestCode == PICK_DOWNLOAD_DESTINATION) {
            File source = pendingDownload;
            pendingDownload = null;
            if (resultCode == Activity.RESULT_OK && data != null
                    && data.getData() != null && source != null) {
                Uri target = data.getData();
                new Thread(() -> {
                    boolean ok = false;
                    try (InputStream in = new FileInputStream(source);
                         OutputStream out = activity.getContentResolver().openOutputStream(target)) {
                        if (out == null) throw new IllegalStateException("No document stream");
                        byte[] buffer = new byte[65536];
                        int n;
                        while ((n = in.read(buffer)) != -1) out.write(buffer,0,n);
                        ok = true;
                    } catch (Exception ignored) {
                        // Never log document contents, URIs or authorization.
                    } finally {
                        source.delete();
                        final boolean saved = ok;
                        activity.runOnUiThread(() -> {
                            downloadBusy = false;
                            toast(saved ? "文件已保存" : "保存失败，请重试");
                        });
                    }
                }, "glacier-download-save").start();
            } else {
                clearDownload();
            }
            return true;
        }
        return false;
    }

    void dispose() {
        if (pendingPrompt != null) finishUpload(null);
        clearDownload();
    }

    private void clearDownload() {
        if (pendingDownload != null) pendingDownload.delete();
        pendingDownload = null;
        downloadBusy = false;
    }

    private void toast(String message) {
        Toast.makeText(activity, message, Toast.LENGTH_SHORT).show();
    }

    private static void closeQuietly(InputStream stream) {
        try { stream.close(); } catch (Exception ignored) {}
    }

    private static String header(Map<String,String> headers, String name) {
        if (headers == null) return null;
        for (Map.Entry<String,String> entry : headers.entrySet()) {
            if (name.equalsIgnoreCase(entry.getKey())) return entry.getValue();
        }
        return null;
    }

    private static String safeFilename(WebResponse response, Uri uri) {
        String candidate = null;
        String disposition = header(response.headers, "content-disposition");
        if (disposition != null) {
            java.util.regex.Matcher match = java.util.regex.Pattern.compile(
                    "(?:^|;)\\s*filename=\"?([^\";]+)\"?", java.util.regex.Pattern.CASE_INSENSITIVE)
                    .matcher(disposition);
            if (match.find()) candidate = match.group(1).trim();
        }
        if (candidate == null || candidate.isEmpty()) candidate = uri.getLastPathSegment();
        if (candidate == null || candidate.isEmpty()) candidate = "download.bin";
        candidate = candidate.replaceAll("[^a-zA-Z0-9._-]", "_");
        if (candidate.length() > 100) candidate = candidate.substring(candidate.length() - 100);
        if (candidate.isEmpty() || ".".equals(candidate) || "..".equals(candidate))
            candidate = "download.bin";
        return candidate;
    }
}
