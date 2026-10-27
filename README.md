# OpenBot Hub

A small web app that you install on your phone or desktop (PWA) to look after an [OpenBot](https://openbot.run) server and its add-ons, without spending model tokens. Each feature is an **app** inside the hub.

Status: early. It runs one real server today.

## Apps

| App | What it does |
| --- | --- |
| `whatsapp_wacli` | For a WhatsApp number linked with [wacli](https://github.com/openclaw/wacli): connection status, the agent's allowlist and blocklist, each contact's latest messages (marked contact, agent or you), send requests waiting for approval, and people who wrote but are not on the list. |

Without a gate, `whatsapp_wacli` is read-only. With a gate (a command that enforces send rules and owns the allowlist), the hub can add, remove, block and unblock contacts, approve or discard requests, and pause sending. The hub never writes the gate's files itself; it calls `gate_cmd admin <action>`.

## Design

- Python 3.11+ standard library only. No build step, no dependencies.
- Reads data straight from disk (for example `wacli.db` in read-only mode). No agent turn, no tokens.
- Access by network identity: only client IPs in `allow_cidrs` and not in `deny_ips`. The intended setup is Tailscale only. Put the server's own Tailscale IP in `deny_ips`, so agents on the server cannot open the hub through its own browser.
- Listens on a Unix socket that only the reverse proxy can open, so local processes cannot skip the IP check.
- Message text is shown with `textContent`, never as HTML.

## Install

1. Copy the repository to `/opt/openbot-hub`.
2. Copy `deploy/config.example.json` to `/etc/openbot-hub/config.json` and edit it.
3. Install `deploy/openbot-hub.service` in `/etc/systemd/system/`, set `User` to a user that can read the app data, and run `systemctl enable --now openbot-hub`.
4. Domain on your tailnet: create a DNS A record for `hub.example.com` that points to the server's Tailscale IP, with no proxy. Get a certificate with a DNS-01 challenge, for example `lego --dns cloudflare -d hub.example.com run`, and copy it to `/etc/openbot-hub/tls/`.
5. Add `deploy/Caddyfile.example` to your Caddyfile and reload Caddy.
6. On Android, open the address in Chrome and choose **Install app**. On a Mac, open it in Safari and choose **File > Add to Dock**.

Without your own domain, `tailscale serve` also gives you an HTTPS address on `*.ts.net`.

## Write an app

Add `hub/apps/<id>.py` with a class `App(config)` that has:

- `info`: `{"id", "name", "icon", "description"}`
- `handle(method, path, query, body)`: returns `(status, json)`

Add `"<id>": {...}` under `apps` in the config. The UI for the app goes in `web/app.js`.

## License

MIT
