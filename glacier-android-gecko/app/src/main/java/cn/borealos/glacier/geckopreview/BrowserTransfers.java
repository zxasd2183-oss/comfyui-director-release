package cn.borealos.glacier.geckopreview;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.database.Cursor;
import android.provider.OpenableColumns;
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
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * User-mediated Android Storage Access Framework upload/download bridge.
 * The Gecko response stream is used directly: no DownloadManager re-fetch
 * (which would bypass Gecko's proxy and isolated cookie session).
 */
final class BrowserTransfers {
    private static final int PICK_UPLOAD = 5011;
    private static final int PICK_DOWNLOAD_DESTINATION = 5012;
    private static final long MAX_DOWNLOAD_BYTES = 64L * 1024 * 1024;
    private static final long MAX_UPLOAD_BYTES = 64L * 1024 * 1024;
    private static final int MAX_UPLOAD_COUNT = 16;
    private static final long UPLOAD_CACHE_LIFETIME_MS = 24L * 60 * 60 * 1000;
    private final List<File> preparedUploadFolders = new ArrayList<>();
    interface DownloadObserver {
        void onSaved(String profile, String filename, String mime, long bytes, Uri document);
    }
    private final Activity activity;
    private final DownloadObserver observer;
    private String pendingProfile;
    private String pendingFilename;
    private String pendingMime;
    private long pendingBytes;
    private GeckoSession.PromptDelegate.FilePrompt pendingPrompt;
    private GeckoResult<GeckoSession.PromptDelegate.PromptResponse> pendingResult;
    private File pendingDownload;
    private boolean downloadBusy;
    private boolean pendingFixtureDownload;

    private void debugEvent(String event) {
        if ((activity.getApplicationInfo().flags
                & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            android.util.Log.i("GlacierSmoke", "FILE_EVENT=" + event);
        }
    }

    BrowserTransfers(Activity activity, DownloadObserver observer) {
        this.activity = activity;
        this.observer = observer;
        // Old staged files are only removed after a day, so a page has time
        // to read its selected file before the Gecko prompt/session ends.
        File folder = new File(activity.getCacheDir(), "glacier-gecko-uploads");
        File[] entries = folder.listFiles();
        if (entries != null) {
            long cutoff = System.currentTimeMillis() - UPLOAD_CACHE_LIFETIME_MS;
            for (File entry : entries) {
                if (entry.isDirectory() && entry.lastModified() < cutoff) {
                    deleteRecursively(entry);
                }
            }
        }
    }

    private static void deleteRecursively(File f) {
        if (f.isDirectory()) {
            File[] children = f.listFiles();
            if (children != null) for (File child : children) deleteRecursively(child);
        }
        f.delete();
    }

    private String safeUploadName(Uri uri) {
        String filename = null;
        try (Cursor cursor = activity.getContentResolver().query(uri,
                new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) {
                int col = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                if (col >= 0) filename = cursor.getString(col);
            }
        } catch (Exception ignored) {
            // Do not log document paths or metadata.
        }
        if (filename == null || filename.isEmpty()) filename = "upload.bin";
        filename = filename.replaceAll("[^\\p{L}\\p{N}._ -]", "_").trim();
        if (filename.length() > 120) filename = filename.substring(filename.length() - 120);
        if (filename.isEmpty() || ".".equals(filename) || "..".equals(filename))
            filename = "upload.bin";
        return filename;
    }

    private Uri copyUploadToInternalFile(Uri selected, List<File> created) throws IOException {
        if (selected == null || !"content".equalsIgnoreCase(selected.getScheme()))
            throw new IOException("Unsupported selected file scheme");
        File base = new File(activity.getCacheDir(), "glacier-gecko-uploads");
        if (!base.exists() && !base.mkdirs()) throw new IOException("Upload cache unavailable");
        File folder = new File(base, "u-" + UUID.randomUUID());
        if (!folder.mkdir()) throw new IOException("Cannot create private upload folder");
        created.add(folder);
        File local = new File(folder, safeUploadName(selected));
        long total = 0;
        try (InputStream source = activity.getContentResolver().openInputStream(selected)) {
            if (source == null) throw new IOException("Cannot open selected document");
            try (OutputStream target = new FileOutputStream(local)) {
                byte[] buffer = new byte[65536];
                int n;
                while ((n = source.read(buffer)) != -1) {
                    total += n;
                    if (total > MAX_UPLOAD_BYTES)
                        throw new IOException("Selected file exceeds experiment size limit");
                    target.write(buffer, 0, n);
                }
                target.flush();
            }
        }
        // GeckoView currently requires a readable file:// filesystem path on
        // Android for some FilePrompt workflows. All files stay inside the
        // private app cache; only the user-selected content is copied.
        return Uri.fromFile(local);
    }

    private void prepareSelectedFiles(List<Uri> selected) {
        new Thread(() -> {
            List<File> created = new ArrayList<>();
            try {
                if (selected.isEmpty() || selected.size() > MAX_UPLOAD_COUNT)
                    throw new IOException("Invalid selection count");
                Uri[] localFiles = new Uri[selected.size()];
                for (int i = 0; i < selected.size(); ++i) {
                    localFiles[i] = copyUploadToInternalFile(selected.get(i), created);
                }
                activity.runOnUiThread(() -> {
                    preparedUploadFolders.addAll(created);
                    debugEvent("UPLOAD_PRIVATE_COPY_READY");
                    finishUpload(localFiles);
                });
            } catch (Exception ex) {
                for (File folder : created) deleteRecursively(folder);
                activity.runOnUiThread(() -> {
                    finishUpload(null);
                    Toast.makeText(activity,
                            "所选文件无法读取或超过 64 MB 限制", Toast.LENGTH_LONG).show();
                });
            }
        }, "glacier-upload-copy").start();
    }

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
            debugEvent("UPLOAD_PICKER_OPEN");
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
            debugEvent("UPLOAD_CANCELLED");
            result.complete(prompt.dismiss());
        } else {
            debugEvent("UPLOAD_SELECTION_CONFIRMED");
            result.complete(prompt.confirm(activity.getApplicationContext(), uris));
        }
    }

    void onExternalResponse(WebResponse response, String ownerProfile) {
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
        pendingFixtureDownload = "http://127.0.0.1:18765/test-attachment".equals(response.uri);
        if (pendingFixtureDownload) debugEvent("DOWNLOAD_RESPONSE_RECEIVED");
        String name = safeFilename(response, uri);
        // The profile is captured from the originating GeckoSession, not
        // whichever profile becomes selected while the picker is open.
        pendingProfile = ownerProfile;
        pendingFilename = name;
        pendingBytes = 0L;
        String mime = header(response.headers, "content-type");
        if (mime == null || mime.trim().isEmpty()) mime = "application/octet-stream";
        else mime = mime.split(";", 2)[0].trim();
        final String safeMime = mime;
        pendingMime = safeMime;

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
                    pendingBytes = done.length();
                    if (pendingFixtureDownload) debugEvent("DOWNLOAD_STREAM_STAGED");
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
                if (chosen.isEmpty()) finishUpload(null);
                else prepareSelectedFiles(chosen);
            }
            return true;
        }
        if (requestCode == PICK_DOWNLOAD_DESTINATION) {
            File source = pendingDownload;
            pendingDownload = null;
            if (resultCode == Activity.RESULT_OK && data != null
                    && data.getData() != null && source != null) {
                Uri target = data.getData();
                final String savedProfile = pendingProfile;
                final String savedFilename = pendingFilename;
                final String savedMime = pendingMime;
                final long savedBytes = pendingBytes;
                // ACTION_CREATE_DOCUMENT grants may be persistable. Retain
                // read permission only when the provider explicitly grants it.
                try {
                    int flags = data.getFlags() & Intent.FLAG_GRANT_READ_URI_PERMISSION;
                    if (flags != 0) activity.getContentResolver()
                            .takePersistableUriPermission(target, flags);
                } catch (Exception ignored) {
                    // Files may still be saved, but reopening can depend on
                    // the document provider and Android's access policy.
                }
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
                            if (saved && observer != null && "content".equals(target.getScheme())
                                    && BrowserLibraryStore.validProfile(savedProfile)) {
                                observer.onSaved(savedProfile, savedFilename, savedMime,
                                        savedBytes, target);
                            }
                            if (pendingFixtureDownload) debugEvent(saved
                                    ? "DOWNLOAD_SAVED" : "DOWNLOAD_SAVE_FAILED");
                            pendingProfile = null;
                            pendingFilename = null;
                            pendingMime = null;
                            pendingBytes = 0;
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
        for (File folder : preparedUploadFolders) deleteRecursively(folder);
        preparedUploadFolders.clear();
    }

    private void clearDownload() {
        if (pendingDownload != null) pendingDownload.delete();
        pendingDownload = null;
        downloadBusy = false;
        pendingFixtureDownload = false;
        pendingProfile = null;
        pendingFilename = null;
        pendingMime = null;
        pendingBytes = 0;
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
