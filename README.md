<p align="center">
  <img src="assets/logo.png" alt="PyxeeTB" width="140">
</p>

## <p align="center">PyxeeTB</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/twitchio-3.3.2-9146FF?logo=twitch&logoColor=white" alt="TwitchIO 3.3.2">
  <img src="https://img.shields.io/badge/platform-Linux-lightgrey" alt="Platform: Linux">
</p>

A standalone Twitch chat bot for moderation, viewer engagement, and stream
alerts — chat filters, a points/watch-time economy with owner-only custom
commands, and optional follow/sub/raid announcements, plus a public
`/commands` reference page and a `/settings` dashboard that your reverse
proxy signs you in to.

## Features

- **Points economy** — passive points and watch-time for active chatters,
  ranks (Newcomer → Legend), `!daily`, `!give`, an opt-in `!gamble`, an
  opt-in `!duel` (PvP wagers), and automatic bonuses for follows, subs and
  bits; subscribers can earn at a higher rate. See
  [Points economy](#points-economy).
- **Quotes, 8-ball, a viewer queue and giveaways** — `!quote`/`!addquote`,
  `!8ball`, `!queue` (who's up next to play with the streamer), and
  `!giveaway` for an actual-prize draw — all need no scope or toggle. See
  [Games & fun](#games--fun).
- **Named counters** — mod-managed (`!counter add deaths`), viewed and
  bumped directly in chat (`!deaths`, `!deaths++`, `!deaths--`), optionally
  open to everyone rather than mods only. See [Counters](#counters).
- **Predictions & Hype Train** — `!predict` wraps native Twitch
  Predictions (channel points payout handled by Twitch itself); Hype Train
  progress announces alongside the other alerts. See
  [Predictions & Hype Train](#predictions--hype-train).
- **Chat filters (AutoMod)** — links (including bare domains like
  `discord.gg/x`), excessive caps (emotes ignored), and a blocked-terms
  list, with `!permit`, an allowed-domain list, VIP/sub exemptions, rate-limited
  warnings, optional message deletion and warn-then-timeout escalation. See
  [Chat filters](#chat-filters-automod).
- **Timers** — scheduled messages that post only while the channel is live
  and chat is actually active. See [Timers](#timers).
- **Custom commands** — **owner/broadcaster only** (only you can create,
  edit, delete or run them; moderators and viewers can't), with `{user}
  {touser} {args} {count} {channel}` variables, a per-command cooldown
  (`!comopt`) and a name reserve list so they never clash with another
  bot. They are never listed on the public commands page or in `!commands`.
  See [Custom commands](#custom-commands).
- **Alerts, shoutouts, clips & polls** — optional (off by default) chat
  announcements for follows/subs/cheers/raids with auto-shoutout on raid,
  plus `!uptime`/`!title`/`!game`/`!followage`/`!clip`/`!so`/`!poll`; each
  needs its own small OAuth scope beyond the base setup and degrades
  gracefully without it — see
  [Alerts, shoutouts, clips & polls](#alerts-shoutouts-clips--polls).
- **Stream state** — live/offline, uptime, title and category come from
  EventSub (`stream.online`/`offline`, `channel.update`) with a polling
  fallback, so `!uptime`, `!title` and `!game` cost no API call; an optional
  end-of-stream summary posts the top point earners.
- **Command throttling and usage counts** — viewers' built-in commands are
  rate-limited (silently; moderators exempt), and every command's use is
  counted so keeping or cutting one is a decision made on numbers
  (shown on `/settings`).
- **Chat overlay** (`/chat-overlay`) — a Browser Source showing recent chat
  on stream, last 10 messages or 10 minutes each, whichever's first; the
  bot's own messages never appear in it — see [Chat overlay](#chat-overlay).
- **Public commands page** — a searchable, categorized reference of the
  built-in commands, published as a static site to GitHub Pages at
  <https://pylxyr.github.io/PyxeeTB/commands> on every push to `main`, and
  linked from chat's `!commands` / `!help` by default — see
  [Public commands page](#public-commands-page).
- **Auto-deploy** — a push to `main` updates the Oracle host over SSH and
  restarts `pyxeetb` (`data/` is never touched) — see
  [Auto-deploy](#auto-deploy-github-actions--ssh).
- **`/settings` web page** — every tunable and feature toggle (grouped),
  command usage counts, a command reference and a read-only community
  dashboard, behind your reverse proxy's sign-in.
- **Health and backups** — `/healthz` reports chat connectivity, live state,
  the age of the last chat message and database status (HTTP 503 when the
  database is unreachable); `community.db` is backed up daily and the newest
  seven copies are kept (`TWITCH_DB_BACKUP_KEEP`).
- **`--check-config`** validates `.env` without starting the bot or
  touching Twitch.

## Requirements

- A Linux server (Ubuntu/Debian assumed by `deploy/setup.sh`; any
  distribution works)
- Python 3.11+
- A Twitch account for the bot to chat as (a dedicated account, made a
  moderator in your channel, is recommended over reusing your own), and an
  app registered at
  [dev.twitch.tv/console/apps](https://dev.twitch.tv/console/apps)

## Installation

### Quick install (Linux)

```bash
git clone https://github.com/Pylxyr/pyxee-twitch-bot.git pyxeetb
cd pyxeetb
bash ./deploy/setup.sh
```

Installs system packages, a virtualenv, and a systemd unit (installed, not
started), then walks through `.env` interactively — the four required
credentials first, then every other setting with its current default
shown. It also offers to set up [Caddy](#publishing-with-caddy) for HTTPS.
Safe to re-run; already-filled values are left alone.
`SKIP_WIZARD=1` skips the interactive part for a scripted install.

### Manual install

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp deploy/.env.example .env   # then edit it
mkdir -p data
```

Run `python bot.py` directly, or adapt `deploy/pyxeetb.service` for
your own paths/user.

Upgrading an existing install? See [UPGRADING.md](UPGRADING.md).

## Configuration

All settings live in `.env` (copy from `deploy/.env.example`). Four are
required; everything else has a default.

| Variable | Default | Notes |
|---|---|---|
| `TWITCH_CLIENT_ID` | — required | From your app at dev.twitch.tv/console/apps |
| `TWITCH_CLIENT_SECRET` | — required | " |
| `TWITCH_BOT_ID` | — required | Numeric Twitch user ID the bot chats as (digits only) |
| `TWITCH_OWNER_ID` | — required | Numeric Twitch user ID of the broadcaster/channel |
| `TWITCH_PREFIX` | `!` | Chat command prefix |
| `TWITCH_HTTP_HOST` | `127.0.0.1` | HTTP bind address. Leave it on loopback and publish through [Caddy](#publishing-with-caddy) |
| `TWITCH_HTTP_PORT` | `8098` | HTTP port, 1024–65535 |
| `TWITCH_TRUSTED_PROXIES` | `127.0.0.1/32,::1/128` | IPs/CIDRs of reverse proxies whose `X-Forwarded-*` and `X-Authenticated-User` headers are believed |
| `TWITCH_PUBLIC_BASE_URL` | `https://pylxyr.github.io/PyxeeTB` | Base URL of the public commands page (no trailing slash); `!commands` / `!help` link to `<url>/commands`. The default is the GitHub Pages site, so there is nothing to set per deploy. Forks set their own Pages URL (or their bot's address). `none` switches to the terse in-chat listing. A value in `.env` wins over the default — see [Public commands page](#public-commands-page) |
| `TWITCH_EMOTE_PROVIDERS` | `7tv,bttv,ffz` | Third-party emote providers the [chat overlay](#chat-overlay) loads; `none` = Twitch emotes and cheermotes only |
| `TWITCH_RESERVED_COMMANDS` | unset | Comma-separated command names another bot answers to (`sr,skip,queue`); custom commands can't reuse them |
| `TWITCH_REPLY_SUFFIXES` | `✨,💫,⭐,🌟` | Comma-separated suffixes the bot adds to a reply *only when it would repeat a message it just sent* (Twitch silently drops exact repeats); `none` disables |
| `TWITCH_DB_BACKUP_KEEP` | `7` | Daily database backups to keep under `data/backups/`; `0` disables |
| `LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`. Logs go to stdout — under systemd, `journalctl -u pyxeetb` |

Feature toggles and tuning values (everything on `/settings`, `!toggle` and
`!setlimit`) are stored in the database, not in `.env`, so a backup of
`data/community.db` carries them.

Registering the Twitch app: Category **Chat Bot**, OAuth Redirect URL
exactly `http://localhost:4343/oauth/callback`, Client Type
**Confidential**. Look up a numeric user ID from a username with
[streamweasels.com's converter](https://www.streamweasels.com/tools/convert-twitch-username-to-user-id/).

### One-time Twitch authorization

`.env` alone isn't enough to read or send chat — that needs a User Access
Token, obtained once through a small local OAuth server the bot starts on
port 4343.

1. Start the service (`sudo systemctl enable --now pyxeetb`, or run
   `python bot.py`). Chat won't respond yet — that's expected until step 3.
2. On a remote server, tunnel the port first:
   ```bash
   ssh -L 4343:localhost:4343 <user>@<host>
   ```
3. In a browser, **as the bot account**, visit:
   `http://localhost:4343/oauth?scopes=user:read:chat+user:write:chat+user:bot+moderator:manage:chat_messages+moderator:read:followers+moderator:manage:shoutouts+moderator:manage:banned_users&force_verify=true`
   Then, in a **separate** browser session, **as the broadcaster account**:
   `http://localhost:4343/oauth?scopes=channel:bot+channel:read:subscriptions+bits:read+clips:edit+channel:manage:polls+channel:manage:predictions+channel:read:hype_train&force_verify=true`
   (`channel:bot` is optional if the bot account is already a moderator in
   your channel, but doing it anyway removes that dependency.)

Reusing the same already-logged-in session for both steps is the most
common way this goes wrong — Twitch just authorizes whichever account is
currently logged in, with no error either way, and chat silently doesn't
work afterward. The bot checks for this on every token save and logs which
account (if either) is missing a token — check `journalctl -u pyxeetb
-f -o cat` if the bot doesn't respond in chat after both steps.

Chat comes online automatically the moment both accounts are authorized —
no restart needed. Tokens save to `data/twitch_tokens.json` and reload on
every future start; you won't need to repeat this unless that file is
deleted or Twitch revokes the token.

Both URLs above already request every scope this bot ever asks for, so
there's nothing to come back and redo later no matter which optional
features you turn on:

| Scope | Account | Unlocks |
|---|---|---|
| `user:read:chat` + `user:write:chat` + `user:bot` | bot | reading/sending chat — the base bot |
| `channel:bot` | broadcaster | same, from the broadcaster's side (skippable if the bot's a mod) |
| `moderator:manage:chat_messages` | bot | `filter_delete_enabled` actually deleting a flagged message |
| `moderator:read:followers` | bot | `!followage`, follow alerts |
| `moderator:manage:shoutouts` | bot | `!so`, auto-shoutout on raid |
| `moderator:manage:banned_users` | bot | `filter_timeout_enabled` (timeouts after repeated violations) |
| `channel:read:subscriptions` | broadcaster | sub alerts |
| `bits:read` | broadcaster | cheer alerts |
| `clips:edit` | broadcaster | `!clip` |
| `channel:manage:polls` | broadcaster | `!poll` |
| `channel:manage:predictions` | broadcaster | `!predict` |
| `channel:read:hype_train` | broadcaster | Hype Train alerts |

Granting a scope doesn't turn its feature on by itself — `alerts_enabled`,
`filter_delete_enabled`, etc. are still off by default and controlled
separately via `!toggle` or `/settings` (see
[Alerts, shoutouts, clips & polls](#alerts-shoutouts-clips--polls)); this
just means flipping one on later never requires touching OAuth again. If
you'd rather not grant everything upfront, drop whichever scopes you don't
want from the two URLs above — every feature that needs one degrades to a
plain "not set up yet" reply instead of an error when its scope is
missing, so leaving some out is always safe.

## Commands (in Twitch chat)

Full descriptions, usage, and access level for every command below are also
on the `/settings` page, generated from the same source
(`pyxeetb/commands_reference.py`); a test fails if a command is
registered but not documented there (or the reverse).

| Command | Who | Does |
|---|---|---|
| `!points [user]` / `!balance` | anyone | Points, watch-time and rank — yours or another chatter's |
| `!rank` | anyone | Your rank and the time to the next one |
| `!daily` | anyone | Claims the daily points bonus (~every 20 hours) |
| `!give <user> <amount>` / `!pay` | anyone | Gives some of your points to another chatter |
| `!gamble <amount\|all\|half\|25%>` / `!bet` | anyone | Coin-flip bet — only when `gamble_enabled` is on |
| `!duel <user> <amount>` | anyone | Challenges a PvP points wager — only when `duels_enabled` is on |
| `!accept` / `!decline` | anyone | Accepts or declines a `!duel` challenge against you |
| `!watchtime` | anyone | Your tracked chat-activity time |
| `!leaderboard [watch]` / `!top` | anyone | Top 5 by points, or by chat time with `watch` |
| `!quote [id]` | anyone | A random quote, or a specific one by id |
| `!8ball <question>` | anyone | Answers a yes/no question |
| `!queue [join\|leave\|list]` | anyone | Joins/leaves the viewer queue, or checks it |
| `!giveaway [status]` | anyone | Enters the running giveaway |
| `!uptime` / `!title` / `!game` | anyone | Stream info |
| `!followage` | anyone | How long you've followed — needs `moderator:read:followers` |
| `!clip` | anyone | Clips the last ~30s — needs `clips:edit` on the broadcaster's token |
| `!commands` / `!help` | anyone | Links to the `/commands` page, or lists commands in chat |
| `!<counter>` / `!<counter>++` / `!<counter>--` | anyone (view) / moderators or public counters (adjust) | Views or adjusts a counter created with `!counter add` |
| `!setlimit <key> [value]` | moderators | Shows or sets a tunable live — same keys/ranges as `/settings` |
| `!toggle <key> [on\|off]` | moderators | Flips a feature toggle, or sets it with `on`/`off` |
| `!addcom <name> <response>` / `!editcom` | broadcaster only | Adds or edits a custom command (only the broadcaster can run it, too) |
| `!delcom <name>` | broadcaster only | Removes a custom command |
| `!comopt <name> cd <seconds\|default>` | broadcaster only | A custom command's cooldown |
| `!counter add\|del\|set\|public <name> [value]` / `list` | moderators | Manages a named counter |
| `!addquote <text>` / `!delquote <id>` | moderators | Adds or removes a quote |
| `!timer add <name> <minutes> <message>` | moderators | Also `remove`, `on`, `off`, `min <name> <messages>`, `list` |
| `!queue open\|close\|next [n]\|clear` | moderators | Manages the viewer queue (size cap: `!setlimit queue_max_size`) |
| `!giveaway start <prize>` / `pick` / `reroll` / `cancel` | moderators | Runs a prize giveaway |
| `!permit <user> [seconds]` | moderators | Lets a chatter post links briefly |
| `!blockterm add\|remove <term>` / `list` | moderators | Manages the blocked-terms list |
| `!allowdomain add\|remove <domain>` / `list` | moderators | Manages always-allowed link domains |
| `!so <username>` / `!shoutout` | moderators | Native Twitch shoutout — needs `moderator:manage:shoutouts` |
| `!poll <seconds> <question> ; <choice> ; <choice> [...]` | moderators | Native Twitch poll (2-5 choices, 15-1800s) — needs `channel:manage:polls` |
| `!predict start <seconds> <title> ; <outcome> ; <outcome> [...]` | moderators | Also `lock`, `resolve <n>`, `cancel` — needs `channel:manage:predictions` |

A non-moderator running a moderator command (or anyone but the broadcaster
running a broadcaster-only one) is ignored silently rather than told off in
public chat. Any prefixed message the bot doesn't recognise is checked
against custom commands (broadcaster only) and counters with an in-memory
lookup (no database query), so sharing the `!` prefix with another bot is
cheap.

## HTTP endpoints

Binds to `127.0.0.1` by default (`TWITCH_HTTP_HOST`).

| Endpoint | Access | Description |
|---|---|---|
| `GET /chat-overlay` | public | Recent-chat widget — see [Chat overlay](#chat-overlay) |
| `GET /commands` | public, rate-limited | Searchable command reference for every viewer — see [Public commands page](#public-commands-page) |
| `GET /chat.json` | public, rate-limited | Recent chat messages as JSON, for a custom chat overlay |
| `GET /ws/chat` | public, connection-capped | WebSocket version, pushed on every new message |
| `GET /healthz` | public, rate-limited, cached 5s | Chat connection, live state, last-chat age, alert subscriptions, missing scopes, database status (503 if the database is down) |
| `GET /logo.png` | public | The bot mark (add `?s=32` for the favicon size) |
| `GET`/`POST /settings` | proxy sign-in | Toggles, tunables and command usage |

`/settings` has no login of its own. It is reached one of two ways:

- **Through your reverse proxy**, which signs you in (Caddy's `basic_auth`,
  set up by `deploy/setup.sh`) and tells the bot who it let through in an
  `X-Authenticated-User` header. The bot only believes that header when the
  connection comes from a trusted proxy address (`TWITCH_TRUSTED_PROXIES`),
  and the proxy overwrites it on every request, so a client can't forge it.
- **Directly on this machine** (loopback, no proxy headers): your own
  browser, or over an SSH tunnel. The request's `Host` must be `localhost`,
  `127.0.0.1` or `[::1]`, which stops a malicious web page from reaching it
  via DNS rebinding.

Anything else gets a `403`. Saving the form also requires a matching
`Origin` (a browser resends Basic credentials on its own, so this is what
stops another site from submitting it as you). Everything else is always
public, since it's meant to be fetched by OBS or a browser without auth:
`/chat.json` allows 120 requests a minute per visitor, `/healthz` 30, and
`/ws/chat` 8 open sockets per visitor (100 in total).

## Public commands page

The public command sheet is a small, self-contained static page — a sidebar of
categories (Points & Leaderboard, Games & Fun, Stream Info, Moderator Tools), a
live search box, and a card for every command with its usage, who can use it
and what it does. It lists the **built-in** commands marked `public=True` in
`pyxeetb/commands_reference.py` — the same set chat's `!commands` draws on.
**Custom commands are never on it** (they are owner-only, and the page builder
doesn't even accept them), and neither are the owner-only `!addcom`,
`!editcom`, `!delcom`, `!comopt` (`public=False`).

**It lives on GitHub Pages:** <https://pylxyr.github.io/PyxeeTB/commands>.
`.github/workflows/pages.yml` rebuilds it (`python -m pyxeetb.pages _site`) and
redeploys on every push to `main`. One-time repository setting: **Settings →
Pages → Source = GitHub Actions**.

**`!commands` / `!help` link to it by default** — `TWITCH_PUBLIC_BASE_URL`
defaults to `https://pylxyr.github.io/PyxeeTB` and the link is that plus
`/commands`, so no `.env` edit is needed after a commit. Forks set
`TWITCH_PUBLIC_BASE_URL` to their own Pages URL (no trailing slash); `none`
turns the link off and uses the terse in-chat listing. Note that an existing
`TWITCH_PUBLIC_BASE_URL` line in `.env` (older `setup.sh` runs wrote one) wins
over the default — delete it to use the Pages link. The deploy prints a notice
when it finds one.

The live `/settings` page, the chat overlay and the websockets stay on the bot
(behind Caddy if you use it); Pages only hosts the public command sheet. The
bot also still serves the same built-in page (plus counters) at its own
`/commands` route, which is what the notes below describe.

Because this is the one page on this server explicitly meant to be
opened by everyone watching a stream rather than just the streamer or a
mod, it's held to a higher bar than the other public endpoints above:

- **Read-only.** No form, no query parameter the server ever reads, no
  state anywhere. The page is built from the command list, the configured prefix and
  the current counters, cached for 30 seconds, and served identically to every
  visitor.
- **Rate-limited** at 60 requests/minute per IP — generous for a person
  browsing, enough to blunt a script hammering the one route now linked
  to an entire channel's chat at once.
- **Locked-down headers**: a `Content-Security-Policy` that starts from
  `default-src 'none'` and only opens exactly what the page needs (its
  own inline style/script, Google Fonts, same-origin images), plus
  `frame-ancestors 'none'`/`X-Frame-Options: DENY` so it can't be framed
  elsewhere, `nosniff`, and `Referrer-Policy: no-referrer`.
- **A `public=False` command would be excluded server-side**, not just
  hidden by CSS — it would never be in the data the page sends to the
  browser in the first place, so there'd be nothing to find by reading
  the page's source or network traffic either.

## Chat overlay

`/chat-overlay` shows recent chat on stream — a stack of `Author: message`
lines, each sliding up into place as it arrives. Add it to OBS as a
**Browser Source** pointed at `https://<your-domain>/chat-overlay` (or
`http://localhost:8098/chat-overlay` if the bot runs on the same machine as
OBS), transparent background, sized to taste. Two limits keep it from
turning into a wall of text, whichever one a given message hits first:

- **The last 10 messages.** An 11th pushes the oldest off.
- **10 minutes.** A message disappears once it's been up that long, even
  if fewer than 10 have come in since to push it off on their own — the
  overlay keeps re-checking this on its own, so a message doesn't linger
  past 10 minutes just because chat went quiet and nothing new arrived to
  trigger a recheck.

**The bot's own messages never appear here** — command replies, alert
announcements, none of it. Everything else does, moderators and the
broadcaster included; only the link/caps filters exempt mods, not
visibility on this overlay.

**Emotes are drawn as images**, not as their names:

- **Twitch** emotes (global and subscriber) arrive resolved in the message and
  are loaded from Twitch's CDN. **Cheermotes** are shown as the artwork
  followed by the bit amount in the tier's colour (artwork from Twitch's Bits
  API, refreshed every 30 minutes).
- **7TV, BetterTTV and FrankerFaceZ** emotes (global and your channel's) are
  looked up by name and swapped in for the matching words. The bot downloads
  each provider's lists in its own background task (aiohttp, 20 s timeout per
  request) and refreshes them every 30 minutes — every 2 minutes until
  something has loaded — so a slow provider never delays chat. If a provider is
  down its emotes simply show as text, and its last good list is kept.
  `TWITCH_EMOTE_PROVIDERS` chooses which providers are used (default all).
- Where two providers use the same name, channel beats global, and within a
  scope 7TV beats BTTV beats FFZ.
- **7TV unlisted emotes are included**: anything in the channel's *active* 7TV
  set renders, listed or not. Only emotes 7TV flags as not allowed on Twitch
  are skipped.
- **7TV zero-width emotes** (a hat or effect drawn over the previous emote) are
  stacked on the emote before them, with only whitespace allowed between.
  Limit: overlays are placed over the previous emote's box, so very wide
  effects may be clipped to it; BTTV "modifier" emotes (`c!`, `h!`, ...) and FFZ
  modifiers are left as text, not applied.
- Image URLs only ever come from the providers' API responses, are https, and
  are checked against a host allowlist (`7tv.app`, `betterttv.net`,
  `frankerfacez.com`); chat text can't introduce one.

Public APIs used (no authentication): 7TV `GET https://7tv.io/v3/emote-sets/global`,
`/v3/users/twitch/{id}` (and `/v3/emote-sets/{id}` if needed); BetterTTV
`GET https://api.betterttv.net/3/cached/emotes/global` and
`/3/cached/users/twitch/{id}`; FrankerFaceZ `GET https://api.frankerfacez.com/v1/set/global`
and `/v1/room/id/{id}`. The channel id is `TWITCH_OWNER_ID`. Images are loaded by
the OBS browser source directly from the providers' CDNs (2x artwork, which
covers retina), so the machine running OBS needs internet access.

Nothing here is persisted — a restart starts the strip empty, which is
correct for a "what's happening right now" widget rather than a log.
Per-author colors are generated from a hash of the username rather than
pulled from Twitch's own per-account chat color, which would need a
separate API call per unique chatter for a purely cosmetic detail; the
hash is at least stable, so the same username always lands on the same
color here.

## Publishing with Caddy

The bot listens on `127.0.0.1` only. [Caddy](https://caddyserver.com) sits
in front on ports 80 and 443, gets a browser-trusted certificate from
Let's Encrypt, renews it, redirects HTTP to HTTPS, and forwards everything
to the bot. A reverse proxy is the right shape for this bot: one listener
already carries every page and WebSocket, and TLS, renewal and
internet-facing hardening are better handled by a proxy built for it than
by the bot.

`deploy/setup.sh` sets it up — answer yes at the Caddy prompt, or later:

```bash
CADDY_DOMAIN=bot.example.com CADDY_EMAIL=you@example.com bash deploy/setup.sh
```

The domain's A record must point at the VPS. With no domain, leave it
blank and the script uses `<ip-with-dashes>.sslip.io`, a public wildcard
DNS name that resolves to that IP, which Caddy can get a real certificate
for. The script:

- installs Caddy from its official apt repository
- writes `/etc/caddy/conf.d/pyxeetb.caddy` from `deploy/Caddyfile` and
  adds one `import` line to `/etc/caddy/Caddyfile` (the stock file is
  backed up first; a customised one is kept and only appended to)
- validates and reloads Caddy, opens ports 80/443 in `ufw` if it's active,
  and prints the cloud-firewall and Oracle `iptables` steps for 80/443
- asks for a `/settings` password (or
  generates one) that Caddy checks before it lets anyone near `/settings` —
  username `admin`, stored only as a hash in the Caddy config

Open **80/tcp, 443/tcp and 443/udp** (HTTP/3). Keep the bot's own port
closed to the internet.

`deploy/Caddyfile` puts `/settings` behind `basic_auth` and passes the signed-in
name to the bot as `X-Authenticated-User` (stripping that header from every
other request), flushes responses without buffering, retries for up to 5
seconds while the bot restarts instead of returning 502, and caps request
bodies at 1 MB.

Behind the proxy the bot reads the visitor's real address from
`X-Forwarded-For` (only when the connection comes from a trusted proxy,
loopback by default — see `TWITCH_TRUSTED_PROXIES`), so rate limits apply
per visitor instead of to everyone at once, and it refuses `/settings` for
anything that came through a proxy that didn't vouch for it.

Other setups: nginx needs `proxy_buffering off`, a long `proxy_read_timeout`,
`Upgrade` headers for `/ws/`, `Host`, `X-Forwarded-For` and
`X-Forwarded-Proto` passed through, and for `/settings` its own `auth_basic`
plus `proxy_set_header X-Authenticated-User $remote_user;` (and clearing that
header everywhere else). If only your own machines need access,
an SSH tunnel or Tailscale exposes nothing to the internet instead.

## Auto-deploy (GitHub Actions + SSH)

Pushing to `main` runs `.github/workflows/deploy.yml`, which SSHes to the host
and runs `deploy/remote-deploy.sh` there. It is written for the Oracle Linux
box: user `tian`, host `pylxyrSG`, app in `~/PyxeeTB` (`/home/tian/PyxeeTB`),
systemd unit `pyxeetb`.

**What it does, in order:** checks the checkout and `data/` exist → `git fetch`
+ `git reset --hard origin/main` (untracked files are cleaned **except**
`data/`, `.env`, `.env.bak`, `.venv`, `logs`) → applies the new `.env` if one
was supplied → creates/updates `.venv` when `requirements.txt` changed → runs
`bot.py --check-config` against the new code → `systemctl restart pyxeetb` →
checks the service is active. Any failure (SSH, git, config check, restart,
service not active) exits non-zero and the Actions job goes red; a failed
config check stops *before* the running bot is touched. **`data/` (database,
backups, OAuth tokens) is never deleted or overwritten** — it is git-ignored,
and the script prints its size and file count before and after.

**Secrets** (Settings → Secrets and variables → Actions; the first four are
already configured):

| Secret | Required | Meaning |
|---|---|---|
| `SSH_HOST` | yes | Host to deploy to |
| `SSH_USER` | yes | `tian` |
| `SSH_PRIVATE_KEY` | yes | Private key whose public half is in `~/.ssh/authorized_keys` on the host |
| `SSH_PORT` | no | Defaults to 22 |
| `DEPLOY_ENV` | no | The full contents of `.env`. **When set it overwrites `~/PyxeeTB/.env` on every deploy** (the old file is kept as `.env.bak`, mode 600). **When unset the server's `.env` is left alone** — `.env` holds Twitch secrets, so it can't be in git, and wiping it without a source would stop the bot |

**Server prerequisites:** `tian` needs passwordless sudo for the restart —
for example `/etc/sudoers.d/pyxeetb`:
`tian ALL=(root) NOPASSWD: /usr/bin/systemctl restart pyxeetb, /usr/bin/journalctl -u pyxeetb *`
(check the paths with `command -v systemctl journalctl`). The installed unit
must point at the real checkout: `deploy/setup.sh` rewrites the template's
`/home/ubuntu/pyxeetb` and `User=ubuntu` to wherever it was run and by whom, so
running it from `~/PyxeeTB` as `tian` produces the right unit; check with
`systemctl cat pyxeetb`. The committed `deploy/pyxeetb.service` is only that
template.

**Verify after a push:**

1. Actions tab: **Deploy** and **Pages** are green.
2. On the host: `systemctl status pyxeetb` shows `active (running)` with a
   fresh start time; `journalctl -u pyxeetb -n 50` shows
   `Chat emotes loaded (7tv=…, bttv=…, ffz=…)`.
3. `ls data/` still has `community.db` and `twitch_tokens.json`.
4. Open <https://pylxyr.github.io/PyxeeTB/commands> (built-ins only), and type
   `!commands` in chat — it answers with that URL.
5. In the `/chat-overlay`, send a 7TV/FFZ/BTTV emote from your channel's sets
   and check it renders as an image.

## Security

- **`/settings` is gated by the reverse proxy's sign-in** (Caddy
  `basic_auth`; the password lives only as a hash in the Caddy config).
  The bot trusts the proxy's `X-Authenticated-User` header only from a
  trusted proxy address, and answers direct requests only on loopback with
  a loopback `Host`.
- **Saving `/settings` is protected against CSRF** — a POST whose
  `Origin`/`Referer` doesn't match the host, or that the browser marks
  cross-site, is rejected with 403.
- **The OAuth token file** (`data/twitch_tokens.json`) is `chmod 600`
  after every save; the database and its backups are created `600` and
  `data/` `700`, and the systemd unit sets `UMask=0077`.
- **The public chat overlay only shows messages that passed AutoMod.** A
  message the filters catch never reaches `/chat-overlay`, `/chat.json` or
  `/ws/chat`, and a message or user a moderator removes on Twitch
  (`channel.chat.message_delete`, `channel.chat.clear_user_messages`) is
  removed from them too. If AutoMod itself errors, the message is still shown
  rather than blanking the overlay.
- **The bot won't repeat a blocked word or a link in its own voice.** What
  viewers type into `{args}`/`{touser}` of a custom command, or as the name
  in `!give`, `!duel` and `!points`, is checked against the blocked-terms
  list and the link filter first (whether or not those filters are switched
  on) and replaced with `[removed]` if it trips either. The mod's own
  command text is left exactly as written.
- **Custom commands are owner-only and never public** — only the broadcaster
  can create, edit, delete or run them, and neither the GitHub Pages sheet,
  the bot's `/commands` route nor `!commands` ever lists them (they are visible
  only on the `/settings` page, which sits behind your proxy's sign-in).
- **The moderation filter's delete action is opt-in and scope-gated** —
  `filter_delete_enabled` needs `moderator:manage:chat_messages` on the
  bot's token (not requested by the base OAuth setup); without it, a
  permission failure is logged once and the filter quietly stays
  warn-only rather than retrying forever.
- **`.env` and `data/` are gitignored**, and the systemd unit's sandbox
  only allows writes under `data/`.

**Trust model.** Moderators can manage most of the bot from chat: switch
chat features on and off (`!toggle`), tune non-economy limits (`!setlimit`),
manage the blocked-term and domain lists, timers, counters, custom commands
and prediction/poll state. **Economy and enforcement settings are the
broadcaster's alone:** every points/rewards and gambling limit, and the
`gamble_enabled`, `duels_enabled`, `filter_delete_enabled`,
`filter_timeout_enabled` and `stream_summary_enabled` toggles, can be *read*
by a moderator but only *changed* by the broadcaster (the `/settings` page is
the broadcaster's own, behind the proxy's sign-in). Only add moderators
you'd trust with the rest.

This isn't a hardened public-internet service — the intent is "one
streamer's own bot, reachable by the people who need it," not "safe to
expose to strangers with no other precautions." Publish it through Caddy
rather than binding it to a public address.

## Notes

### Points economy

Points and watch-time accrue for chat *activity* — sending messages while
the stream is live — not true viewer presence (that needs viewer-list data
this bot doesn't fetch). `!give`, `!duel` and `!points <user>` find a chatter
by Twitch login or display name (login first), as recorded when they chat. Every minute, each chatter active in the last five
minutes earns `points_per_active_minute` (subscribers get
`sub_multiplier_percent` of that). Live/offline comes from EventSub
`stream.online`/`stream.offline` when available and a cached Helix poll
otherwise; if the poll fails, the last known state is kept.

- **Bonuses** — `follow_bonus_points` (paid once per viewer, so
  unfollow/refollow can't farm it), `sub_bonus_points`, `bits_points_per_100`.
  They are paid regardless of the `alerts_enabled` toggle, which only controls
  the chat announcement.
- **`!daily`** — `daily_bonus_points` every ~20 hours.
- **Ranks** — Newcomer, Regular (1h), Fan (10h), Veteran (25h), Legend (60h)
  of tracked chat time.
- **`!give`** — moves points atomically in one database transaction.
- **`!gamble`** — off until `gamble_enabled` is turned on; the win chance,
  max bet and cooldown are tunables (`gamble_win_chance_percent` defaults to
  45, so the house has a small edge). A bet can never overdraw a balance.
- **`!duel <user> <amount>`** — off until `duels_enabled` is turned on. The
  challenged chatter has `duel_timeout_seconds` to `!accept`/`!decline`; a
  target can only have one pending challenge at a time. Unlike `!gamble`,
  `duel_challenger_win_chance_percent` defaults to 50 — a fair coin flip,
  since this is PvP, not a wager against the house. Settlement
  (`Database.settle_duel`) re-checks the loser's balance atomically at
  accept time, not just when the challenge was issued, and refuses cleanly
  (no points move) if they can no longer cover it.
- **End-of-stream summary** — with `stream_summary_enabled`, the bot posts
  the top three earners of the session when the stream goes offline.

### Games & fun

- **`!quote [id]`** / **`!addquote <text>`** (mod) / **`!delquote <id>`**
  (mod) — a plain quote board; `!quote` with no id picks one at random.
- **`!8ball <question>`** — a fixed set of classic Magic 8-Ball answers,
  no state, no cooldown.
- **`!queue`** — "who's up next to play with the streamer." Viewers
  `!queue join`/`leave`; `!queue` alone shows your position. Mods
  `!queue open`/`close` (existing members stay when closed to new joins),
  `!queue next [n]` pops and announces the front of the line, `!queue
  clear` empties it. The size cap is the `queue_max_size` tunable (`0` =
  unlimited), not a separate command — set it with `!setlimit
  queue_max_size <n>` like every other runtime knob. In-memory only, like
  the chat feed — it's a per-session lineup, not a record worth persisting
  across a restart.
- **`!giveaway`** — for an actual prize, not points, so there's no
  currency and no toggle to gate it behind. `!giveaway start <prize>`
  (mod) opens entries; a bare `!giveaway` from a viewer enters (idempotent
  — entering twice just confirms you're in); `!giveaway pick` (mod) draws
  a random winner, `!giveaway reroll` (mod) draws a replacement if they
  don't answer, and `!giveaway cancel` (mod) scraps it. One giveaway at a
  time, in-memory, cleared when the stream goes offline.

### Counters

Mod-managed named counters — `!counter add deaths` creates one starting at
0. From then on, `!deaths` shows the value, `!deaths++`/`!deaths--` adjust
it by one. Adjusting is mod-only by default; `!counter public deaths`
(toggle again to turn it back off) opens it up so anyone can `++`/`--` it —
the classic "type !deaths to add one" chaos counter. `!counter set <name>
<value>` jumps to an exact number; `!counter list` shows what exists;
`!counter del <name>` removes one. A counter's name can't collide with a
built-in command or an existing custom command, and vice versa —
`!addcom`/`!counter add` each check the other's namespace.

### Predictions & Hype Train

`!predict start <seconds> <title> ; <outcome> ; <outcome> [...]` wraps
Twitch's native Predictions feature directly — channel-points payout is
handled by Twitch itself, this just starts/locks/resolves/cancels one and
announces the result. `!predict lock` locks entries, `!predict resolve <n>`
picks the Nth outcome (as numbered when it started) as the winner,
`!predict cancel` refunds everyone. If a prediction is instead resolved
from the Twitch dashboard directly (bypassing the bot entirely), a
`channel.prediction.end` listener still announces the outcome — the bot
only double-checks against its own tracked state, so nothing announces
twice when it *does* go through `!predict` itself.

Hype Train progress announces alongside the other alerts — gated by the
same `alerts_enabled` toggle, since it's the same kind of "something
happened on stream" event as a follow or a raid. A level-up is announced once
per level (Twitch reports it as a higher `level`, with `progress` reset, so
the bot remembers the highest level it has announced for the current train);
contributions within a level stay silent, which would otherwise spam chat on
a busy train.

### Chat filters (AutoMod)

All filters are off by default. Moderators and the broadcaster are never
filtered; VIPs are exempt by default (`filter_exempt_vips`) and subscribers
can be (`filter_exempt_subs`).

- **Links** (`link_filter_enabled`) — matches `http(s)://`, `www.` and bare
  domains on common spam TLDs (`discord.gg/x`, `spam.com`), including
  `discord[.]gg` / `spam(dot)com` and look-alike dots or fullwidth letters. Deliberately not
  every TLD, so a typo like `yeah.it was` isn't flagged. `!allowdomain`
  whitelists a domain (subdomains included); `!permit <user>` gives one
  chatter a short window.
- **Caps** (`caps_filter_enabled`) — shouting is measured on the message
  *without emotes*, so `KEKW KEKW KEKW` is fine. `caps_threshold_percent`
  sets the ratio; needs 10 letters. 
- **Blocked terms** (`term_filter_enabled`) — whole-word, case-insensitive;
  the list is managed with `!blockterm` and never echoed into chat. Text is
  compared after Unicode normalisation, so zero-width characters, soft
  hyphens, accents/zalgo, fullwidth letters and common Cyrillic/Greek
  lookalikes (`bаdword` with a Cyrillic *а*) don't get past it. It does not
  catch spaced-out letters (`b a d`) or leetspeak — keep Twitch's own AutoMod
  on as well.
- **Response** — a public warning at most once per
  `filter_warning_cooldown_seconds` per chatter (violations are still
  counted and acted on); `filter_delete_enabled` also deletes the message;
  `filter_timeout_enabled` times a chatter out after
  `filter_strikes_before_timeout` violations within
  `filter_strike_window_seconds` (needs `moderator:manage:banned_users` on the
  bot's token — missing scopes are detected once and that action stays off).

### Timers

`!timer add promo 20 Follow for more!` posts every 20 minutes — but only
while the channel is live, and only if at least `min` chat messages arrived
since it last fired (default 5; change with `!timer min promo 10`). The first
time a timer is seen it only sets a baseline, so nothing fires the moment the
bot starts or a timer is created, and going offline discards baselines so
timers don't burst when the stream resumes. `timers_enabled` pauses them all.

### Custom commands

`!addcom <name> <response>` creates a command; the response may contain
`{user}`, `{touser}` (first argument, else the caller), `{args}`, `{count}`
(times used) and `{channel}`. Names are letters/numbers/`_` (max 25) and can't
reuse a built-in command, an existing counter (see [Counters](#counters)),
or anything in `TWITCH_RESERVED_COMMANDS` — list the commands another bot
in your channel answers to (for example `TWITCH_RESERVED_COMMANDS=sr,skip,np`
for a separate song-request bot) so a custom command can't shadow them.
`!comopt <name> cd <seconds|default>` sets a per-command cooldown.

Custom commands are **broadcaster-only**: only the broadcaster can run
`!addcom`/`!editcom`/`!delcom`/`!comopt`, and only the broadcaster's `!<name>`
produces a reply. A moderator or viewer typing one gets silence. (The
per-command role option from earlier versions is gone; the old `min_role`
column stays in the database, unused.) They never appear on the public
commands page or in `!commands`. Custom commands never answer with an
error (no permission, cooldown, unknown), since other bots share the prefix.
Viewer-typed `{args}`/`{touser}` are scrubbed of blocked terms and links (see
[Security](#security)).

### Backups and health

`data/backups/community-<UTC timestamp>.db` is written on startup (unless one
from the last ~22 hours exists) and daily, using SQLite's online backup so it
is consistent while the bot runs; only the newest `TWITCH_DB_BACKUP_KEEP` (7)
are kept, `0` disables. **Backups live on the same disk as the database**, so
they don't protect against losing the machine or its disk: copy `data/backups/`
somewhere else on a schedule (an `rsync`/`rclone` cron job is enough). Schema changes are versioned (`PRAGMA user_version`)
and applied in place, so an existing `community.db` upgrades automatically.

### Alerts, shoutouts, clips & polls

None of this is required for the base bot, and every command/toggle here
is off by default even though the default OAuth setup already grants the
scopes for all of it — see
[One-time Twitch authorization](#one-time-twitch-authorization) for
exactly which scope backs which feature (and what still works if you
trimmed some out of those URLs). One toggle, `alerts_enabled`, gates chat
announcements for follows, new subs, resubs (Twitch only sends one when the
viewer chooses to share the resub message), gifted subs (announced once, for
the gifter, who also earns the subscription bonus for each sub gifted, up to
50 per gift; the recipients' own events are ignored so a gift is never
announced twice), cheers, raids, and Hype Train progress, plus an
automatic shoutout for whoever raided — see
[Predictions & Hype Train](#predictions--hype-train) for the Hype Train
side specifically. Each underlying EventSub subscription is attempted
independently at startup regardless of the toggle (subscribing is
side-effect-free; the toggle only gates whether an event that arrives
gets announced) — raid alerts need no extra scope at all, so they work
even if you trimmed every optional scope out; follow/sub/cheer each need
their own and simply don't fire if that scope isn't there, with no error
either way.

`!so`, `!followage`, `!clip`, and `!poll` each need one of those same
scopes too, and each gives a plain "not set up yet" reply instead of an
error if its scope is missing — check the commands table above for which
scope each needs. A missing scope is remembered after the first failed
attempt (not re-logged for every subsequent raid or command), so turning
a feature's toggle on without having granted the matching scope is
harmless either way — just inert until you have.

### Systemd hardening

`deploy/pyxeetb.service` runs with a fairly tight systemd sandbox:
`MemoryDenyWriteExecute`, `SystemCallFilter=@system-service`,
`ProtectSystem=strict`, `ProtectHome=read-only` with only `data/` and
`logs/` writable, `UMask=0077`, `PrivateDevices`, `ProtectProc=invisible`,
`RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`, `RestrictNamespaces`,
`NoNewPrivileges`, an empty capability set, and the rest of the usual
hardening directives. After changing the unit, run
`systemd-analyze security pyxeetb` and restart it to confirm the bot still
connects.

### Resource caps (`MemoryMax`, `MemoryHigh`, `CPUQuota`)

`deploy/pyxeetb.service` sets a cgroup-level memory/CPU ceiling
(512M/768M/150%) independent of `OOMScoreAdjust` above — that only
affects the *global* OOM-killer's priority, not what happens if this unit
alone runs away. These are conservative starting points, not a hard
requirement; raise them if the service gets killed under normal,
non-runaway load.

## License

MIT — see [LICENSE](LICENSE).
