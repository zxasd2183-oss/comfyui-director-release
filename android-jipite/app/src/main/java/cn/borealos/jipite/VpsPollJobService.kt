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
 * Shared JobScheduler service for regular and user-initiated one-time polling.
 * Both only call the authenticated read-only /pending endpoint; neither can
 * create GPU requests or submit approvals. No token or request data is logged.
 */
class VpsPollJobService : JobService() {
    private val main = Handler(Looper.getMainLooper())
    private val completed = AtomicBoolean(true)
    private var timeout: Runnable? = null
    private var activeJobId: Int? = null

    private fun record(params: JobParameters, code: String) {
        if (VpsNotifications.isDiagnosticJob(params.jobId)) {
            VpsNotifications.recordDiagnostic(this, code)
        } else {
            VpsNotifications.recordPeriodic(this, code)
        }
    }

    override fun onStartJob(params: JobParameters): Boolean {
        // Android can start two job IDs against the same JobService. Never let
        // a second callback reset the active job's completion/timeout guard.
        if (!completed.compareAndSet(true, false)) {
            if (VpsNotifications.isDiagnosticJob(params.jobId)) {
                VpsNotifications.recordDiagnostic(this, "busy")
            }
            return false
        }
        activeJobId = params.jobId
        if (!VpsNotifications.enabled(this) || BuildConfig.DEBUG) {
            record(params, "disabled")
            completed.set(true)
            activeJobId = null
            return false
        }
        val id = getSharedPreferences("jipite-device", MODE_PRIVATE)
            .getString("device_id", null)
        if (id.isNullOrBlank()) {
            record(params, "unbound")
            completed.set(true)
            activeJobId = null
            return false
        }
        record(params, "running")
        timeout = Runnable { finish(params, "timeout") }
            .also { main.postDelayed(it, 55_000L) }
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
                                    if (completed.get()) return
                                    if (account == null) {
                                        finish(params, "no_account")
                                        return
                                    }
                                    application.acquireTokenSilentAsync(
                                        arrayOf("User.Read"),
                                        "https://login.microsoftonline.com/consumers",
                                        object : SilentAuthenticationCallback {
                                            override fun onSuccess(result: IAuthenticationResult) {
                                                val token = result.account.idToken
                                                if (completed.get()) return
                                                if (token.isNullOrEmpty()) {
                                                    finish(params, "no_token")
                                                    return
                                                }
                                                MobileApi.post(
                                                    "pending", token, JSONObject().put("device_id", id)
                                                ) { response ->
                                                    if (!completed.get()) {
                                                        val reply = response.getOrNull()
                                                        if (reply != null &&
                                                            reply.optBoolean("ok") &&
                                                            reply.optJSONArray("requests") != null) {
                                                            VpsNotifications.onPendingResponse(
                                                                applicationContext, reply
                                                            )
                                                            finish(params, "ok")
                                                        } else {
                                                            finish(params, "vps_error")
                                                        }
                                                    }
                                                }
                                            }

                                            override fun onError(exception: MsalException) {
                                                finish(params, "auth_failed")
                                            }
                                        }
                                    )
                                }

                                override fun onAccountChanged(
                                    priorAccount: com.microsoft.identity.client.IAccount?,
                                    currentAccount: com.microsoft.identity.client.IAccount?
                                ) {
                                    // Never store account data in diagnostic preferences.
                                }

                                override fun onError(exception: MsalException) {
                                    finish(params, "account_error")
                                }
                            }
                        )
                    }

                    override fun onError(exception: MsalException) {
                        finish(params, "msal_error")
                    }
                }
            )
        } catch (_: Exception) {
            finish(params, "internal_error")
        }
        return true
    }

    private fun finish(params: JobParameters, code: String) {
        if (activeJobId == params.jobId && completed.compareAndSet(false, true)) {
            timeout?.let { main.removeCallbacks(it) }
            timeout = null
            record(params, code)
            if (VpsNotifications.isDiagnosticJob(params.jobId)) {
                VpsNotifications.notifyDiagnosticFinished(this, code)
            }
            activeJobId = null
            main.post { jobFinished(params, false) }
        }
    }

    override fun onStopJob(params: JobParameters): Boolean {
        if (activeJobId == params.jobId && completed.compareAndSet(false, true)) {
            timeout?.let { main.removeCallbacks(it) }
            timeout = null
            record(params, "interrupted")
            activeJobId = null
        }
        return false
    }
}
