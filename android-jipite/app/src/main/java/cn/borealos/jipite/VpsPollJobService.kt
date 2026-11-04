package cn.borealos.jipite

import android.app.job.JobParameters
import android.app.job.JobService
import android.os.Handler
import android.os.Looper
import com.microsoft.identity.client.IAuthenticationResult
import com.microsoft.identity.client.IPublicClientApplication
import com.microsoft.identity.client.ISingleAccountPublicClientApplication
import com.microsoft.identity.client.PublicClientApplication
import com.microsoft.identity.client.SilentAuthenticationCallback
import com.microsoft.identity.client.exception.MsalException
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicBoolean

/**
 * System-scheduled, battery-aware background poll; no Google Play / Xiaomi SDK.
 *
 * Microsoft ID tokens are acquired only through MSAL's existing secure cache
 * and used in-memory for the same authenticated VPS pending endpoint.
 * This service never launches a login UI or performs an approval.
 *
 * Doze/HyperOS restrictions can delay or prevent execution; it is NOT an
 * always-on guaranteed real-time push transport.
 */
class VpsPollJobService : JobService() {
    private val main = Handler(Looper.getMainLooper())
    private val completed = AtomicBoolean(false)
    private var timeout: Runnable? = null

    override fun onStartJob(params: JobParameters): Boolean {
        completed.set(false)
        if (!VpsNotifications.enabled(this) || BuildConfig.DEBUG) return false
        val id = getSharedPreferences("jipite-device", MODE_PRIVATE)
            .getString("device_id", null) ?: return false
        timeout = Runnable { finish(params) }.also { main.postDelayed(it, 55_000) }
        try {
            PublicClientApplication.createSingleAccountPublicClientApplication(
                applicationContext, R.raw.msal_config,
                object : IPublicClientApplication.ISingleAccountApplicationCreatedListener {
                    override fun onCreated(application: ISingleAccountPublicClientApplication) {
                        if (completed.get()) return
                        application.getCurrentAccountAsync(
                            object : ISingleAccountPublicClientApplication.CurrentAccountCallback {
                                override fun onAccountLoaded(
                                    account: com.microsoft.identity.client.IAccount?
                                ) {
                                    if (account == null || completed.get()) {
                                        finish(params)
                                        return
                                    }
                                    application.acquireTokenSilentAsync(
                                        arrayOf("User.Read"),
                                        "https://login.microsoftonline.com/consumers",
                                        object : SilentAuthenticationCallback {
                                            override fun onSuccess(result: IAuthenticationResult) {
                                                val token = result.account.idToken
                                                if (token.isNullOrEmpty() || completed.get()) {
                                                    finish(params)
                                                    return
                                                }
                                                MobileApi.post(
                                                    "pending", token, JSONObject().put("device_id", id)
                                                ) { response ->
                                                    if (!completed.get()) {
                                                        response.onSuccess {
                                                            VpsNotifications.onPendingResponse(
                                                                applicationContext, it
                                                            )
                                                        }
                                                    }
                                                    finish(params)
                                                }
                                            }

                                            override fun onError(exception: MsalException) {
                                                finish(params)
                                            }
                                        }
                                    )
                                }

                                override fun onAccountChanged(
                                    priorAccount: com.microsoft.identity.client.IAccount?,
                                    currentAccount: com.microsoft.identity.client.IAccount?
                                ) {
                                    // No cached data or token is copied to this job.
                                }

                                override fun onError(exception: MsalException) {
                                    finish(params)
                                }
                            }
                        )
                    }

                    override fun onError(exception: MsalException) {
                        finish(params)
                    }
                }
            )
        } catch (_: Exception) {
            finish(params)
        }
        return true
    }

    private fun finish(params: JobParameters) {
        if (completed.compareAndSet(false, true)) {
            timeout?.let { main.removeCallbacks(it) }
            main.post { jobFinished(params, false) }
        }
    }

    override fun onStopJob(params: JobParameters): Boolean {
        completed.set(true)
        timeout?.let { main.removeCallbacks(it) }
        // Periodic scheduler will handle the next check; no background retry loop.
        return false
    }
}
