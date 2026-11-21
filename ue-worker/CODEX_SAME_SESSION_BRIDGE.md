# Codex same-RDP-session message bridge — v1

Scope: route a text message from the existing, owner-authenticated Director Hub
to the owner's **current** Windows Codex desktop thread. No other account,
thread, command, executable, network address, or local project path can be
selected by a remote request. This uses the existing authenticated SSH reverse
tunnel and its installed signed Worker updater.

## One-time local consent (do this in the Windows Codex desktop app)

1. Verify the desktop conversation's thread UUID from the GUI and local CLI.
2. From the same Windows Administrator account, create a plain UTF-8 file at
   %LOCALAPPDATA%\DirectorCodexBridge\consent.json containing exactly:
   {"format":"director_codex_bridge_v1","enabled":true,"thread_id":"<your-existing-uuid>"}
   Only the owner creates this file locally. Neither the VPS nor ChatGPT
   receives the thread ID or the Codex login credentials.
3. Check the already-installed Windows Scheduled Task named
   Director-UE-Interactive-Hero is the trusted existing task, configured for
   the current RDP account and interactive token. Start/restart that exact
   task so its Python process loads the current signed ue_process.py. Do
   not edit or create an unfamiliar scheduled task.
4. Verify Worker status.codex_bridge.available=true and matching session ID.
5. Try one harmless message and verify it appears in the original GUI thread.

## Interface and delivery semantics

- The signed Windows Worker exposes authenticated, loopback-only endpoints:
  GET /v16/codex/status
  POST /v16/codex/queue with {"message": "..."}
  GET /v16/codex/requests/<32-lowercase-hex-id>.
- The Hub exposes get_codex_bridge_status, codex_queue_message and
  get_codex_message_status. It cannot select a thread, execution path, URL,
  executable, interpreter, browser, authentication, or elevated mode.
- The existing submit_director_task endpoint offers a safe fixed
  codex_queue_probe_v1 test, constrained to WaitingOffice/EP01, for clients
  whose MCP tool list predates this release.
- Successful staging is NOT evidence that CLI queued; CLI exit code 0 is
  NOT evidence the GUI has displayed it, and is NOT proof the actual work
  succeeded. GUI acknowledgement or separately authorized app-server result
  reading is necessary for that last step.

To revoke future deliveries, remove the local consent.json file or set
enabled=false. Expired requests are rejected. Each request is claimed only
once; ambiguous delivery is not replayed. No raw Codex stdout, stderr,
conversation history, account token or local consent is exposed.
