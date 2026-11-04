# Director V0.4 — fixed domain and GPU boot recovery

One-time setup, no repeated temporary Cloudflare URLs.

## Cloudflare configuration (Dashboard → Networking → Tunnels)

Prerequisite: Your own domain on Cloudflare DNS. Create **two remotely managed Named Tunnels**, not Quick Tunnels.

| Tunnel | Published hostname | Origin |
|---|---|---|
| director-gpu | director.YOUR_DOMAIN | http://127.0.0.1:8790 |
| director-vps | status.YOUR_DOMAIN | http://127.0.0.1:8891 |
| director-vps | power.YOUR_DOMAIN | http://127.0.0.1:8894 |
| director-vps | approve.YOUR_DOMAIN | http://127.0.0.1:8893 |

Cloudflare will configure DNS CNAME routes. Do not expose ComfyUI 8188. Each tunnel has its own private TOKEN (see Dashboard → Install connector / Add replica). **Never share tokens in ChatGPT/GitHub**.

Protect approve.YOUR_DOMAIN with Cloudflare Access restricted to the owner, on top of the existing independent mobile TOTP and typed confirmation phrase. For long-term MCP use, also implement proper OAuth; a fixed hostname does NOT by itself authenticate callers. A generic browser Access login in front of MCP can interfere with ChatGPT MCP handshakes, so verify auth integration separately. Existing secret MCP paths are transitional.

## GPU: prepare once in CompShare root shell

CompShare's official GPU FAQ documents executable startup hooks in /start.d/ for GPU containers. The helper below is tailored to the current GPU running V3 under /root/.comfyui-director, and requires cloudflared version 2025.4.0+.

Commands:

    mkdir -p ~/director-fixed
    curl -fsSL https://raw.githubusercontent.com/zxasd2183-oss/comfyui-director-release/main/scripts/gpu-named-tunnel-boot.sh -o ~/director-fixed/gpu-named-tunnel-boot.sh
    curl -fsSL https://raw.githubusercontent.com/zxasd2183-oss/comfyui-director-release/main/scripts/install_gpu_named_tunnel.sh -o ~/director-fixed/install_gpu_named_tunnel.sh
    less ~/director-fixed/install_gpu_named_tunnel.sh
    bash ~/director-fixed/install_gpu_named_tunnel.sh
    bash /start.d/90-comfyui-director-v3.sh
    curl -fsS http://127.0.0.1:8790/health

When prompted, paste the GPU tunnel TOKEN into the local terminal (input hidden). Installer stores it as root-only 0600 in /etc/comfyui-director/gpu-named-tunnel.token; startup hook starts the previously installed Director V3 and named cloudflared without opening incoming ports.

This hook does NOT start a second ComfyUI process or submit video jobs. Check whether the existing GPU image already starts ComfyUI 8188; do not blindly start a duplicate.

## Guangzhou VPS: prepare once

    cd ~/comfyui-director-release
    git pull --ff-only
    cd vps-control
    sudo bash install-vps-named-tunnel.sh
    sudo systemctl is-active director-vps-named-tunnel.service

Paste ONLY the VPS tunnel TOKEN in the secure local prompt. A new systemd service keeps the tunnel online, automatically restarts it, and leaves read-only and power-approval services unchanged.

## ChatGPT: update plugin Server URL only once

Preserve the private MCP path component exactly as before; change only the temporary hostname:

- ComfyUI Director V3: https://director.YOUR_DOMAIN/mcp/GPU_PRIVATE_TOKEN
- Director VPS: https://status.YOUR_DOMAIN/mcp/VPS_READONLY_PRIVATE_TOKEN
- Director Power Requests: https://power.YOUR_DOMAIN/mcp/VPS_POWER_PRIVATE_TOKEN

Do not paste full URLs into ChatGPT messages. If the existing plugin URL cannot be edited, connect a new plugin and disable the old temporary one.

Independent approval page remains at https://approve.YOUR_DOMAIN/approve/ORIGINAL_APPROVAL_ROUTE_SECRET with no secret changes needed. Do not share the route secret.

## VPS shutdown safety preflight must be updated once

On Guangzhou VPS, edit /etc/comfyui-director-control.env with sudoedit and replace DIRECTOR_GPU_MCP_URL with the permanent GPU Director MCP HTTPS URL above. Retain root ownership + mode 0600, then run:

    sudo systemctl restart director-power-mcp director-power-approval

Otherwise the safety gate will not be able to read the ComfyUI queue before a stop; do NOT bypass fail-closed checks.

Once complete, GPU power-off/on makes its Named Tunnel disconnect and later reconnect to the SAME hostname. No repeat edits to ChatGPT plugin URLs or VPS queue URL.

## Limitations

- This does not guarantee recovery after GPU instance deletion, reimaging, or loss of /start.d and /etc/comfyui-director. Verify those paths persist through normal stop/start.
- The GPU /start.d hook launches cloudflared in the background; cloudflared reconnects to the network, but if its process crashes and the GPU stays running, an additional in-container supervisor is required to restart it. VPS uses systemd for automatic restart.
- Stable DNS does not itself mean secured MCP: implement ChatGPT-compatible OAuth for production; Cloudflare Access can secure the human approval page.
- GPU is already Running and may incur rental charges. These installation scripts do not stop or start the GPU, and never touch video jobs.

References:
- https://developers.cloudflare.com/tunnel/get-started/
- https://developers.cloudflare.com/tunnel/concepts/routing/
- https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/
- https://compshare.cn/docs/operation/gpufaq
