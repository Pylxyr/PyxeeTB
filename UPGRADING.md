# Upgrading to PyxeeTB

The project was renamed (package `twitch_radio` → `pyxeetb`, service
`twitch-radio` → `pyxeetb`) and reorganised. Your data carries over; a few
things change shape. **Back up `data/` first** (`cp -a data data.bak`) — the
database upgrades itself in place and an older version can't read it afterwards.

## Steps

1. Stop the old service: `sudo systemctl stop twitch-radio`.
2. Get the new code (and, optionally, rename the folder: `mv ~/twitch-radio-bot ~/pyxeetb`).
3. Tidy `.env`. These keys are gone and are now ignored — delete them:
   `TWITCH_SETTINGS_PASSWORD`, `TWITCH_SETTINGS_ALLOW_OPEN`, `TWITCH_SESSION_HOURS`,
   `TWITCH_SESSION_REMEMBER_DAYS`, `TWITCH_CHAT_EMOTE_SOURCES`, `TWITCH_TOKEN_FILE`,
   `TWITCH_TUNABLES_FILE`, `TWITCH_SPECS_FILE`, `TWITCH_TOGGLES_FILE`, `TWITCH_DB_FILE`,
   `LOG_TO_FILE`. **If you set `TWITCH_NOWPLAYING_HOST` / `TWITCH_NOWPLAYING_PORT`,
   rename them to `TWITCH_HTTP_HOST` / `TWITCH_HTTP_PORT`** — the old names no longer
   work, and the bot would silently fall back to the defaults.
4. Run `bash deploy/setup.sh`. It removes the old `twitch-radio` unit, logrotate
   file and Caddy site file, installs the `pyxeetb` unit, and (if you use Caddy)
   asks for a new `/settings` password — the old in-app password is gone; Caddy
   checks the new one before anyone reaches `/settings`.
5. `sudo systemctl enable --now pyxeetb`, then `journalctl -u pyxeetb -f`.

## What happens to your data

- `data/community.db` is upgraded automatically (points, quotes, commands,
  timers, counters and filter lists are untouched).
- On the first start, `tunables.json` and `toggles.json` are imported into the
  database and renamed to `*.migrated`. `specs.json` becomes two ordinary custom
  commands, `!specs` and `!peripherals` (edit them with `!editcom`); an existing
  command with either name is left alone.
- `data/twitch_tokens.json` is unchanged — no need to re-authorize with Twitch.
- Backups (`data/backups/`) now include your settings.
- Old log files in `logs/` are no longer written; read logs with
  `journalctl -u pyxeetb`. You can delete `logs/`.

## What behaves differently

- **No login page.** `/settings` is protected by your reverse proxy (Caddy
  `basic_auth`, username `admin`) or reached directly on the machine itself.
- **Settings the broadcaster controls.** Points/rewards and gambling limits and the
  `gamble_enabled`, `duels_enabled`, `filter_delete_enabled`, `filter_timeout_enabled`
  and `stream_summary_enabled` toggles can only be changed by the broadcaster from
  chat; moderators can still read them and change everything else.
- **Built-in commands are throttled** for non-moderators (5s per viewer, 2s per
  channel, per command; `!followage` 15s/3s) and counted — see "Command usage" on
  `/settings`.
- **The reply suffix (✨ …)** is added only when a message would repeat one the bot
  just sent, instead of to every message.
- **Chat overlay emotes:** only Twitch's own emotes and cheermotes; 7TV, BetterTTV
  and FrankerFaceZ are no longer drawn.
- **New:** resubs and gifted subs are announced and (gifter) rewarded; `!giveaway
  reroll`; `!give`/`!duel`/`!points <user>` match by login.
- **Fixed:** the Hype Train start announcement never fired (twitchio dispatches it as
  `event_hype_train`), and level-ups are now announced once per level.
