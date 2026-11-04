# borealos.cn: integrate with EXISTING Nginx + Let's Encrypt

LIVE facts reported by owner: all five domains respond HTTPS 200 with a generic placeholder page; Let's Encrypt certs reside under /etc/nginx/certs/borealos-new/ and acme.sh renews them. VPS Power Requests MCP reports ready; GPU currently Running (billable). None of this proves API proxy routing is live yet.

The snippet files here are fragments for existing Nginx TLS server blocks, NOT entire virtual hosts. They do not define listen, server_name, certificates, port 80 redirects, or root placeholders. Do not overwrite the working five-host TLS configuration.

## Preflight, on Guangzhou VPS

    sudo systemctl is-active director-vps-control director-vps-bridge director-power-mcp director-power-approval director-power-bridge
    sudo ss -ltn | grep -E ':(8891|8893|8894|18790)\b' || true

Ports 8891 (readonly bridge), 8894 (power application bridge), 8893 (OTP approval) should be localhost-only. Port 18790 will NOT exist until GPU outbound SSH reverse tunnel is connected.

## Install snippets (does not modify active Nginx config)

    cd ~/comfyui-director-release
    git pull --ff-only
    sudo install -d -m 0755 /etc/nginx/snippets
    sudo install -o root -g root -m 0644 vps-control/nginx-alidns/director.conf /etc/nginx/snippets/director-borealos.conf
    sudo install -o root -g root -m 0644 vps-control/nginx-alidns/status.conf /etc/nginx/snippets/status-borealos.conf
    sudo install -o root -g root -m 0644 vps-control/nginx-alidns/power.conf /etc/nginx/snippets/power-borealos.conf
    sudo install -o root -g root -m 0644 vps-control/nginx-alidns/approve.conf /etc/nginx/snippets/approve-borealos.conf

## Protect human approval with browser password in addition to phone OTP

    sudo apt-get update && sudo apt-get install -y apache2-utils
    sudo test -e /etc/nginx/.director-approve.htpasswd || sudo install -o root -g www-data -m 0640 /dev/null /etc/nginx/.director-approve.htpasswd
    sudo htpasswd -B /etc/nginx/.director-approve.htpasswd director-owner

Use a unique long password only in the secure local terminal. Confirm the Ubuntu Nginx worker group is www-data; otherwise adapt the file group safely. The existing 6-digit TOTP and typed START GPU / STOP GPU confirmation remain independently mandatory.

## Add an include to the proper EXISTING HTTPS server blocks

Insert each line INSIDE its existing server { } block, not inside a location { } and NOT in the port-80 redirect server. All other Nginx configuration remains intact.

For director.borealos.cn:

    include /etc/nginx/snippets/director-borealos.conf;

For status.borealos.cn:

    include /etc/nginx/snippets/status-borealos.conf;

For power.borealos.cn:

    include /etc/nginx/snippets/power-borealos.conf;

For approve.borealos.cn:

    include /etc/nginx/snippets/approve-borealos.conf;

Leave jipite.borealos.cn untouched as the future AI studio control-panel placeholder.

If existing virtual hosts already define location /mcp/ or /approve/, carefully merge instead of adding duplicate locations.

## Validate before any reload

    sudo nginx -t && sudo systemctl reload nginx

If nginx -t fails, do NOT reload. Back out only the newly added include lines. Do NOT replace certificate files, break the 301-to-HTTPS redirects, or open raw MCP service ports to the public internet.

Expected after successful reload:
- Root / of each hostname still displays its current 200 placeholder (intentional).
- The existing private MCP path of status resolves to VPS 127.0.0.1:8891.
- The private MCP path of power resolves to VPS 127.0.0.1:8894, which can create applications but cannot power a GPU without independent approval.
- The private approval route on approve resolves to 127.0.0.1:8893 and requires both browser Basic Auth and existing TOTP approval.
- The private MCP path of director resolves to 127.0.0.1:18790; this is UNAVAILABLE until the GPU reverse SSH tunnel has been installed.
- jipite root stays a placeholder.

Do not paste private MCP paths, full URLs or OTPs into ChatGPT messages, screenshots, or public files.

## Certificates

The owner already configured certs in /etc/nginx/certs/borealos-new/ for all five names. Preserve them. Ensure the acme.sh install-cert configuration includes a reload command such as systemctl reload nginx after copying a renewed certificate to its production Nginx path. Cron-only renewal does not by itself prove Nginx will load the renewed files. See https://github.com/acmesh-official/acme.sh#3-install-the-cert-to-apachenginx-etc .

## Remaining GPU SSH backhaul work

GPU initiates an outbound SSH reverse tunnel to the owned VPS, with only VPS loopback 127.0.0.1:18790 forwarded to the GPU's Director V3 127.0.0.1:8790. Limit SSH user, key and port forwarding permissions. Never expose GPU ComfyUI 8188 publicly. Use approved CompShare boot hooks only after persistence is verified. Keep the VPS shutdown queue preflight fail-closed.

This change does not touch provider power APIs or ComfyUI generation jobs.
