# Director V0.4 - borealos.cn: AliDNS + self-owned VPS (NO Cloudflare)

THIS SUPERSEDES the previous Cloudflare Named Tunnel idea. Do NOT run the old install-vps-named-tunnel.sh or install_gpu_named_tunnel.sh scripts for the current design. This file is a proposed deployment, NOT confirmation that DNS, proxies, SSH access or certificates have been installed.

## Target architecture

- Domain borealos.cn stays at Alibaba Cloud DNS; do not move nameservers.
- All public hostnames resolve to the OWNED Guangzhou VPS public IPv4, never the rented RTX 5090 IP.
- VPS terminates HTTPS and serves existing Director VPS read-only MCP, Power Requests MCP, and independent TOTP approval web page.
- GPU establishes an OUTBOUND SSH reverse tunnel into its owner VPS: GPU 127.0.0.1:8790 (Director V3) -> VPS 127.0.0.1:18790.
- When GPU shuts down, the reverse SSH channel drops. GPU startup recovers local V3 and SSH tunnel, WITHOUT DNS changes or ChatGPT plugin updates.
- Never make GPU ComfyUI 8188 or the VPS internal ports accessible from the public Internet.

## A. ICP filing and current DNS check - BEFORE deployment

VPS is located in Guangzhou, Chinese mainland. According to Alibaba Cloud ICP official guidance, even API and tunnel services serving publicly through a domain resolving to a Chinese mainland server generally require corresponding ICP filing / access filing. Do NOT publish the domain records until you have confirmed the appropriate备案 status with your VPS provider. Domain registration at Alibaba and authoritative DNS hosting are distinct; confirm current name servers. Preserve all existing website/email DNS records. No Cloudflare account is needed.

Documentation:
https://help.aliyun.com/zh/dns/pubz-add-parsing-record
https://help.aliyun.com/zh/icp-filing/basic-icp-service/support/faq-about-icp-filing-preparations

## B. Add four records in Alibaba Cloud DNS (after confirming ICP)

At AliDNS console > borealos.cn > DNS Records, add only these A records, if the names are unused:

| Host record | Type | Value |
| --- | --- | --- |
| director | A | OWNER_VPS_PUBLIC_IPV4 |
| status | A | OWNER_VPS_PUBLIC_IPV4 |
| power | A | OWNER_VPS_PUBLIC_IPV4 |
| approve | A | OWNER_VPS_PUBLIC_IPV4 |

Do NOT point DNS at the rented GPU, edit @ or www, change NS records, or delete existing MX/TXT records. If borealos.cn currently uses other authoritative DNS, configure at the actual DNS provider instead.

## C. VPS HTTPS front end (Caddy example)

Before installing a reverse proxy, check if ports 80 and 443 are already used by a website or nginx. NEVER overwrite an existing Caddyfile/nginx configuration. For a fresh VPS Caddy installation after ICP approval, see vps-control/Caddyfile.alidns.example for an example (requires Caddy 2.8+).

Host -> local origin:

- director.borealos.cn -> 127.0.0.1:18790 (VPS loopback SSH reverse-forward; rewrite Host to 127.0.0.1:8790)
- status.borealos.cn -> 127.0.0.1:8891 (existing read-only MCP bridge)
- power.borealos.cn -> 127.0.0.1:8894 (existing V0.3 application-only bridge)
- approve.borealos.cn -> 127.0.0.1:8893 (existing human OTP approval, additionally gate with HTTPS browser basic_auth)

Caddy's automatic HTTPS normally needs working DNS, inbound 80/443 and valid issuance. Use an interactive secure local terminal to run caddy hash-password and put the password HASH in the config; NEVER send the password or approval path to ChatGPT. Do not enable access logging of URLs with private MCP path tokens.

Caddy reference:
https://caddyserver.com/docs/caddyfile/directives/basic_auth
https://caddyserver.com/docs/caddyfile/directives/reverse_proxy

## D. GPU connects outward to VPS via SSH - one-time setup

On VPS, provision a dedicated unprivileged SSH account named directorlink with NO sudo, NO interactive shell and public-key-only authentication. Limit the GPU's SSH public key in authorized_keys to a single remote forwarding bind: 127.0.0.1:18790. For defense in depth, an sshd Match User directorlink section can set:

    AllowTcpForwarding remote
    PermitListen 127.0.0.1:18790
    GatewayPorts no
    X11Forwarding no
    AllowAgentForwarding no
    PermitTTY no
    PasswordAuthentication no

Never edit the live sshd config without first validating with sshd -t and preserving an active administrative session. Public-key restrictions can include restrict,port-forwarding,permitlisten="127.0.0.1:18790"; review OpenSSH server version for support. Do not expose 18790 publicly.

On GPU, generate a dedicated Ed25519 key pair for this ONE tunnel, protect the private key with 0600 permissions, and add ONLY the public key to the above VPS account. Pin and verify the VPS's SSH host key fingerprint, rather than disabling StrictHostKeyChecking. The GPU does NOT need domain DNS, TLS, or Cloudflare credentials.

Test reverse port forwarding on GPU after the keys and host verification are configured:

    ssh -F /root/.ssh/director_backhaul_config -NT \
      -o ExitOnForwardFailure=yes \
      -o ServerAliveInterval=20 -o ServerAliveCountMax=3 \
      -R 127.0.0.1:18790:127.0.0.1:8790 director-backhaul

The SSH Host alias must use a known VPS IP, trusted host key, directorlink user and dedicated GPU private key. A reconnect loop should start from the CompShare GPU's officially documented /start.d boot hook, along with the previously installed Director V3. Never launch a duplicate ComfyUI process. GPU instance deletion/rebuild invalidates stored keys/startup config; revoke old SSH public keys.

OpenSSH reference:
https://man.openbsd.org/sshd_config

## E. ChatGPT and VPS safety preflight: one-time URL change

ChatGPT custom MCP Server URLs (the secret path from existing connections stays the same):

- ComfyUI Director V3: https://director.borealos.cn/mcp/GPU_EXISTING_SECRET
- Director VPS: https://status.borealos.cn/mcp/VPS_READONLY_EXISTING_SECRET
- Director Power Requests: https://power.borealos.cn/mcp/VPS_POWER_EXISTING_SECRET
- Approval browser: https://approve.borealos.cn/approve/VPS_APPROVAL_EXISTING_SECRET

DO NOT put these real secret strings in GitHub, chats, screenshots or shell history. The existing random MCP paths are transitional security; for long-term use deploy proper authenticated MCP/OAuth, NOT a plain public unauthenticated endpoint.

On VPS, update root-owned, 0600 permissions file /etc/comfyui-director-control.env: set DIRECTOR_GPU_MCP_URL to the GPU's fixed HTTPS MCP URL, then restart director-power-mcp and director-power-approval. The shutdown preflight MUST still fail closed if ComfyUI queue isn't verifiably empty. A fixed domain by itself does not grant or change power control permissions.

## F. Status

The old V0.3 approved GPU start is real; this new AliDNS + outbound SSH architecture is NOT yet deployed, and it has NOT been tested on the user's servers. We still need ICP/port 80/443/SSH access checks and to verify the GPU container preserves /start.d and the dedicated key across stop/start. Keep current live remote control plugins operational until the new fixed-domain endpoints are verified independently.

GPU is currently Running and may be billed. These architecture steps never call StartCompShareInstance or StopCompShareInstance.
