# Testing Hivemind: a guide for testers

Thank you for testing Hivemind. This page is for people who signed up to try
a test build. It says what you need, how to install it, how to stop it, and
what to send back. Test builds go out in waves: **Linux testers first, then a
Windows alpha**. macOS comes later.

If something here does not match what you see, that is worth reporting too.
If a question is not answered here, **ask in the Discord**.

## Contents

- [What Hivemind is (and is not)](#what-hivemind-is-and-is-not)
- [Before you start](#before-you-start)
- [Install on Windows](#install-on-windows)
- [Install on Linux](#install-on-linux)
- [Your first run](#your-first-run)
- [Safe settings](#safe-settings)
- [How to stop it (F12 and friends)](#how-to-stop-it-f12-and-friends)
- [What to report, and how](#what-to-report-and-how)
- [What not to share](#what-not-to-share)
- [Known limits today](#known-limits-today)
- [Uninstall](#uninstall)

## What Hivemind is (and is not)

Hivemind is a bot that plays **Bee Swarm Simulator** for you. It looks at the
game through screenshots (text reading and image matching), decides what to
do, and plays with keyboard and mouse input, like a person at the keyboard.

What it **never** does:

- **It never spends Robux** and never presses Buy on anything priced in Robux.
- **It never asks for your password.** You log in to Roblox yourself. Hivemind
  never needs your PC password either: if anything asks for one in
  Hivemind's name, it is not Hivemind.
- **It never types in chat.** That switch ("Never type in chat") is locked
  on and cannot be turned off.
- **It never reads or changes the game's memory** and never injects code into
  Roblox.
- **It never clicks Roblox's "I Agree"** or accepts terms for you.

Please also know:

- **It is a test build.** Expect rough edges. Some parts work better than
  others.
- **Ban risk is yours.** Using a bot or macro can break Roblox's rules or the
  game's rules. Hivemind plays only through the screen, keyboard and mouse,
  but that does not make it allowed. We cannot promise an account will not be
  banned. "Human-like timing" in Settings does not make it undetectable.
- **What goes online:** the Telegram or Discord alerts you set up yourself,
  and the stream's YouTube chat if you set that up (all off until you do).
  The wax calculator also reads public tables from the game's wiki. None of
  these sends your account details.

## Before you start

### Your PC

**Windows**

- Windows 10 (version 1903 or newer) or Windows 11, 64-bit.
- A monitor of **1920x1080 or larger**. Every screen position the bot uses is
  measured on a 1920x1080 picture of the game.
- Display scale (Windows Settings > Display > Scale): **100% is the safest.**
  Note what yours is when you report.
- **Roblox installed from roblox.com**, not from the Microsoft Store.
  Hivemind finds Roblox through the `roblox://` link handler and the
  `Roblox\Versions` folder that the roblox.com installer sets up.
- Roblox does not run inside a virtual machine, so test on a real PC.
- How much RAM and which graphics cards work best on Windows is not known yet:
  ask in the Discord, and tell us yours.

**Linux**

- **A Wayland desktop session** (KDE Plasma, GNOME, Hyprland, Sway...).
  X11 cannot work: pick the Wayland session at your login screen.
- **Hyprland 0.56 or newer.** Your own desktop stays as it is; Hyprland only
  runs inside a window, where the game plays.
- **Sober** (the Roblox app for Linux) from Flathub. The first-run window can
  install it for you (about 1 GB the first time).
- **Python 3.12 or newer** (`hivemind doctor` checks it).
- **At least 6 GB of free RAM** when you press Play (Hivemind will not start
  with less; 8 GB of RAM in the PC is usually not enough yet, 12 GB or more
  works) and a GPU that runs Roblox. AMD and Intel are the
  safe choices. **NVIDIA is untested**: it may still work, so tell us.
- Your user in the **`input` group** is needed, so the F12 panic
  key works everywhere (see [How to stop it](#how-to-stop-it-f12-and-friends)).

### Your game and account

- **Your Roblox username.** Set "Your Roblox username" in Settings (the
  search box at the top right finds it: type `username`). The walk home steers toward the
  name printed on your own hive, which is how it finds your hive among the
  others. It is only read from the screen, never typed.
- **A private server is best.**
  - Linux joins **your own private server** through the game's Servers tab.
    No private server? Settings > Server has other choices.
  - Windows joins by **share link**: in Roblox, open Servers, your server,
    Configure, and copy its share link. Paste it in Settings > Server >
    "Share link to join", and **check that "Which server Start joins" on the
    same page reads "this share link"**. A new install sets that for you, but
    an upgrade or settings you brought over keep your old choice, and then
    the link is ignored. With no link in use, Windows joins a **public** Bee
    Swarm server. One more check: "Private server share link" and "Follow a
    friend in" (type them in the search box) are used before all of this,
    so leave them empty unless you mean to use them.
- **Leave Roblox's controls at their defaults.** The bot presses the standard
  keys (W A S D, Space, E, Shift for shift lock, `,` and `.` to turn the
  camera, Page Up and Page Down). Changed keybinds, other screen sizes and
  other UI scales are not supported yet.
- **Leave the camera to the bot.** Keep shift lock **off**: the bot assumes
  it starts off and cannot see it, so it will not fix a shift lock you left
  on. The "Zoom out while farming" and "Tilt
  camera down while farming" settings are best left at 0 for now.
- **Close your own games first.** "Pause while you play a game" is on by
  default: if you start a Steam game, Minecraft, your own Roblox or (on
  Windows) any full-screen app, the bot finishes its step and pauses. It
  never resumes by itself: press Resume when you are done.

## Install on Windows

The Windows alpha is not out yet. When it is, this is how the installer
works.

1. You get one file, **`Hivemind-Setup.exe`**. (If you were sent
   `Hivemind-Setup-PARTS.exe` with some `.bin` files, keep them all in the
   same folder and run the `.exe`.)
2. Double-click it. It is a normal Next / Install / Finish wizard. It installs
   **for your user only**, so it does not ask for an admin password. Python,
   every library and the text reader (Tesseract) are inside it: you install
   nothing else.
3. Open **Hivemind** from the Start menu (or the desktop shortcut, if you
   ticked it).

**"Windows protected your PC".** The installer is **not code-signed yet**, and
Windows warns about any program it has not seen many times before. Click
**More info**, then **Run anyway**.

**Antivirus.** Some antivirus programs scan a new installer before it opens,
and may cover the setup window for a moment. That is normal: let the scan
finish. If your antivirus is worried, every line of the code is public, and
the Python inside is the Python Software Foundation's own signed program.

Where things go:

| what | where |
|---|---|
| the app | `%LOCALAPPDATA%\Programs\Hivemind` |
| logs and what it learned | `%LOCALAPPDATA%\Programs\Hivemind\var` |
| your settings and presets | `%LOCALAPPDATA%\Hivemind` |

Installing again (an update) keeps your settings and logs. If Hivemind is
open, Setup offers to close it first.

## Install on Linux

The full steps are in
[`installer/linux/README-LINUX.md`](../installer/linux/README-LINUX.md). In
short:

- **NixOS:** add four lines to `configuration.nix` (Hyprland, Flatpak, the
  `input` group, flakes), rebuild, log out and back in, install Sober, then
  `nix run . -- doctor` and `nix run .` in the Hivemind folder.
- **Arch, Fedora:** run `./install.sh`. It installs
  into `~/.local/share/hivemind`, adds a `hivemind` command and a menu entry,
  and **never uses sudo**. If something is missing it prints one command for
  you to run yourself.
- **Ubuntu, Mint and Debian:** not ready yet: the Hyprland in their
  repositories is too old, so `./install.sh` stops and installs nothing.
  Install 0.56 or newer from the Hyprland wiki (then `./install.sh --force`),
  or use Nix.

Then run **`hivemind doctor`** (or "Check this PC" from the menu entry). It
checks every requirement and prints the fix for your distro. Fix every ✗
before you press Play.

Hivemind runs from `~/.local/share/hivemind/app`; its logs are in the `var`
folder there. Your settings are in `~/.config/hivemind`.

## Your first run

### Linux

The first time you open Hivemind, a **"Set up Hivemind"** window walks you
through three steps (about five minutes):

1. **Install Sober**, from Flathub, just for your user.
2. **Log in to Roblox.** Press Open Roblox. Roblox opens in Hivemind's own
   game window and its picture appears in the setup window: click the picture
   and log in as usual, then press **Done, I'm logged in**. You type your
   password into Roblox yourself; your login stays saved in Sober.
3. **Start.** Hivemind checks that everything is in place, then starts.

Until every check has passed once, Hivemind shows the first-run check when it
opens. Want to look around with no game? `hivemind demo` opens the window with
recorded demo data.

When it plays: a Hyprland window opens, Sober starts, and the bot joins and
walks to its field. **Don't click into that window while it plays**: your
clicks then go to the game. On desktops other than KDE, **don't minimise it**
either (a minimised window sends no pictures, and the bot loses sight).

### Windows

There is **no setup window on Windows yet**. Today:

1. The installer has already written the safe settings (below).
2. Sign in to Roblox yourself, the way you always do. Open Bee Swarm once by
   hand, then **close Roblox**: Hivemind opens its own, and a Roblox you
   opened yourself counts as you playing (so the bot pauses for it).
3. Open Hivemind. Paste your private server's share link in
   **Settings > Server**, check that "Which server Start joins" reads
   "this share link", and set your Roblox username.
4. Press **Start** (F1). Hivemind opens Roblox by link, makes its window
   borderless at 1920x1080, brings it to the front and plays.

**The PC is the bot's while it plays.** Windows has one mouse and keyboard,
and the bot's keys go to whatever window is in front. So when you switch to
another window, the bot **lets go of every key and pauses**; when Roblox is in
front again, it carries on. Using your PC beside the bot is planned for later.

## Safe settings

Every new install starts with the **Safe first run** preset:

- one field (**Sunflower**), near the hive, with no mobs;
- it converts honey when the backpack is 95% full;
- **quests, buying, crafting, planters, bosses, mobs, hatching, boosts, the
  vision model, alerts and start-on-boot are all off**;
- "Pause while you play a game" is **on**.

Please test with these first. Once the basics work for you, turn things on one
at a time in Settings, so a report can say which switch changed what. You can
always go back: pick **Safe first run** in the preset list at the top of the
window. Every optional feature in Hivemind is off until you turn it on.

## How to stop it (F12 and friends)

| key | what it does |
|---|---|
| **F12** (emergency stop) | Stops everything and lets go of every held key. |
| F3 / the Stop button | Stops the bot normally. |
| F2 / the Pause button | Pauses; press again to resume. |
| F1 / the Start button | Starts. |

F1, F2 and F3 work while the Hivemind window has focus. **F12 is meant to
work wherever you are**:

- **Windows:** F12 is read wherever the focus is. It is missed while a UAC
  prompt or a program running as administrator is in front, so in that case
  close the prompt first. Hold the key for a moment rather than a very quick
  tap.
- **Linux:** in the `input` group, the bot reads F12 from the keyboard itself,
  even if its game window stops responding. Without it, Hivemind uses F12
  while its window has focus, plus a desktop-wide shortcut on KDE, GNOME and
  Hyprland (your desktop may ask you once to allow it) or on X11. `hivemind
  doctor` says which one you have. If it shows ✗, there is no working panic
  key: fix that before you run the bot unattended.

You can change the key in Settings > General > "Emergency stop key". If the
bot ever had to be killed, Hivemind tells you so: press **F12** once
afterwards, because it releases any key that may still be held.

## What to report, and how

**One report per test.** Please include:

- **What you did**, what you **expected**, and what **happened** (exact words
  on screen help a lot).
- **Your PC:** Windows version or Linux distro and desktop, graphics card,
  monitor size, and on Windows your display scale.
- **Linux:** what `hivemind doctor` printed.
- **The debug bundle** (below) for anything odd.
- Anything confusing in installing or setting up, exactly as you saw it.
- Does it fight your real mouse? Does it ever type into another window? Tell
  us exactly what happened.

### The debug bundle

One zip with what the team needs to debug a run: your newest logs, the
newest incident pictures, your settings, and (on Windows) your screen and
Roblox window sizes.

- **Easiest:** Settings › Help › **Report a problem**. It makes the zip and
  opens its folder. Saw something odd while it played? Press **Save this
  moment** under the live view first, and the zip has those seconds too.
- **Windows:** open a terminal in `%LOCALAPPDATA%\Programs\Hivemind` and run
  `python\python.exe scripts\debug_bundle.py`
- **Linux:** in a terminal, run `hivemind bundle`

It prints where it wrote the zip: `var/reports/debug-bundle-<date>-<time>.zip`
in the app folder. `--runs 5` adds more run logs (the default is 3). The
pictures are thinned to about 8 MB so the zip fits a Discord DM;
`--frames-mb 0` keeps them all.

**What it takes out for you:** your Telegram bot token, chat id and Discord
webhook, your API keys, your private-server links (and their codes), your
private server's name, the friend you follow, and your Roblox username.
Text files have them replaced with `[secret]` or `[blanked]`; any other file
that holds one is left out, and `left-out.txt` lists it.

**What it cannot take out:** the zip holds **pictures of your game**, and a
picture can show your username (it is printed on your hive), your friends, or
chat. So **send the bundle privately** (a DM to the team), **never in a public
channel**.

### Screenshots

Full-screen screenshots of a problem help (on Windows, Win+Shift+S). Check
them before you post: **don't post a screenshot that shows your username in a
public channel.** Send those privately.

## What not to share

Never post these anywhere public (a channel, an issue, a screenshot, a
stream):

- your **private-server link** or share link;
- your **Roblox username** and your friends' names (they show in game
  pictures);
- any **password**: Roblox, Google, Telegram or your PC's (nobody on the team
  will ever ask for one);
- your **Telegram bot token** or **YouTube API key**;
- the files `telegram.env`, `secrets.env` and `server.yaml` from your settings
  folder.

**Presets hold more than you think.** A preset (the preset list's "Save
current as preset", or Export preset) leaves out your keys, tokens and
share links, but it keeps **your Roblox username**, your **server name**
(often named after your username) and a **friend's user id**. Before you share
a preset, open the file in a text editor and blank `account.username`,
`server.name` and `account.follow_user`.

Leaked something by accident? [`docs/SECURITY.md`](SECURITY.md) says how to
replace each secret.

## Known limits today

- **Windows is new.** Every screen position was measured on the Linux
  (Android) Roblox app. The Windows app may look different in places, so the
  bot can misread a menu. Those reports are exactly what we need.
- **Windows: the PC is the bot's while it plays.** Switching windows pauses
  it. Using the PC beside the bot is planned (roadmap RL6j).
- **Windows joins by share link, or a public server.** Whether the share link
  gets into your server on every PC is not proven yet: please report it either
  way.
- **No setup window on Windows yet**, and the PC check (`hivemind doctor`) is
  Linux only.
- **Only 1920x1080 is measured.** Other screen sizes, UI scales and keybinds
  are not supported yet. A screen smaller than 1920x1080 (a laptop, a Steam
  Deck) is untested on Linux.
- **Linux: X11 cannot work**, and NVIDIA graphics are untested.
- **Joining a friend's server by name only watches for now** (it logs what it
  would do and does not click).
- **No macOS yet** (roadmap RL7).
- **No auto update yet.** You install each new build yourself (roadmap
  U15f).

The full list of what is built, being tested and planned is in
[`docs/ROADMAP-PUBLIC.md`](ROADMAP-PUBLIC.md).

## Uninstall

- **Windows:** Settings > Apps > Hivemind > Uninstall. Your settings
  (`%LOCALAPPDATA%\Hivemind`) and logs (`var`) are kept; delete those folders
  yourself to remove everything.
- **Linux:** `hivemind uninstall` keeps your settings and what it learned;
  `hivemind uninstall --purge` removes everything. On Nix, also run
  `nix profile remove hivemind`.

<!--
FOR MAINTAINERS: where each claim comes from (keep this page true to the code).
- Never/always rules: AGENTS.md hard rules; world/settings.py LOCKED
  (safety.never_chat only); docs/SECURITY.md; the
  public README's Safety and FAQ (tools/export_public.py README).
- Windows PC needs: installer/hivemind.iss (MinVersion 10.0.18362,
  x64compatible, PrivilegesRequired=lowest, the PARTS build);
  platform/win/session.py (1920x1080 client, borderless, roblox:// protocol
  key, Roblox\Versions fallback, DPI awareness); act/bootstrap.py
  WINDOWS_PUBLIC; the Windows port notes (display scale, roblox.com client,
  no VMs).
- Linux needs: installer/linux/README-LINUX.md, cli/doctor.py.
- Game settings: world/settings.py account.username, server.*,
  gather.camera_zoom_out, gather.camera_tilt; act/routes.py CAMERA_KEYS;
  world/bearings.py + nav/journey.py (shift lock assumed off at spawn, only
  the bot's own toggle undone); data/presets/safe-first-run.yaml;
  scripts/run_farm.py + platform/lastserver.target (follow_user and
  account.share_link first, server.link only with server.join "this share
  link"); installer/hivemind.iss (settings.yaml onlyifdoesntexist).
- What goes online: alerts (telegram/discord env), stream.youtube_api_key,
  brain/waxcalc.py API (the game wiki).
- Presets: gui/panels/settings.py export_preset (drops SECRET and
  NOT_IN_PRESETS only).
- First run: gui/firstrun.py, gui/app.py first_run_check, installer/linux/
  hivemind; Windows: gui/shell.py HOW_TO_START, brain/controls.py
  (GameNotFocused is a pause).
- Stop keys: gui/window.py (F1-F3), gui/panic.py, platform/win/panic.py,
  cli/doctor.py safety(), gui/launcher.py (kill message).
- Debug bundle: scripts/debug_bundle.py (secret_values: .env values of 12+
  characters, so a short Telegram chat id is not blanked; PRIVATE_KEYS).
- Install paths: installer/README.md, installer/hivemind.iss.
- Limits: docs/ROADMAP-PUBLIC.md, act/join.py JOIN_CHOSEN_LIVE.
-->
