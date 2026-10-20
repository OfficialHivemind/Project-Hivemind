# Security: where Hivemind keeps its secrets

Plain English. Every file below is in Hivemind's config folder
(`~/.config/hivemind/` on Linux, `%LOCALAPPDATA%\Hivemind\` on Windows) and
is readable by you alone (permissions 0600 on Linux). None of them is ever put in a
preset, the Log tab, the bot's logs, a Telegram message or the stream.

| Secret | File | Set or changed in |
|---|---|---|
| Telegram bot token (and your chat id) | `telegram.env` | Hivemind's Telegram tab |
| YouTube Data API key | `secrets.env` (`YOUTUBE_API_KEY=`) | Settings > Stream, "YouTube Data API key" |
| Private-server link | `server.yaml` | by hand (`hivemind doctor` checks it is 0600) |
| Private-server links typed into Settings | `secrets.env` (`SERVER_LINK=`, `SHARE_LINK=`) | Settings, drawn as dots |

`settings.yaml` holds ordinary settings only. Older versions kept the YouTube
key there; the window (when it opens or saves) and the bot (when it starts)
move it into `secrets.env` once and take it out of `settings.yaml`. Old
`settings.yaml.bak-*` copies made by hand before 2026-10-14 can still hold the
key: delete them, or rotate the key.

## If a secret leaks (on stream, in a screenshot, in a shared file)

**Telegram bot token.** In Telegram, open @BotFather, send `/revoke`, pick
your bot. BotFather gives you a new token and the old one stops working at
once. Paste the new one into Hivemind's Telegram tab and press Detect chat
again if it asks.

**YouTube API key.** Go to console.cloud.google.com > APIs & Services >
Credentials, open the key and press "Regenerate key" (or delete it and create
a new one, restricted to "YouTube Data API v3"). Paste the new key into
Settings > Stream. A leaked key can only read public chat and spend your free
quota; it cannot post or change anything.

**Private-server link.** Generate a new link in the game's server settings
and put it in `server.yaml` (or Settings); the old link stops working.

## Never share

- the Telegram token or the YouTube key (not in a chat, an issue, a screenshot)
- the private-server link
- any password: Roblox, Google, Telegram or this PC's
- the files `telegram.env`, `secrets.env`, `server.yaml`

Presets (Settings > Export preset) are safe to share: they never contain a
key, a token or the server link.

## Hivemind never needs your PC password

Hivemind runs as you and never asks for your login or sudo password. A setup
hint (`hivemind doctor`) may print a `sudo ...` command for you to run yourself
in a terminal; you type the password there, never into Hivemind, Telegram or a
chat. If anything asks for it in Hivemind's name, it is not Hivemind.
