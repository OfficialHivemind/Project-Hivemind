# Troubleshooting Hivemind

Find what you see, try the fix, and if that doesn't help, open a bug report
(see [the end of this page](#still-stuck)). Quick answers about safety and
setup are in [`FAQ.md`](FAQ.md); the full tester guide is
[`TESTING.md`](TESTING.md).

**First, on Linux:** run `hivemind doctor` (or "Check this PC" from the menu
entry). It checks everything below that can be checked and prints the fix
for your distro. Fix every ✗ before anything else.

## Installing

**Windows says "Windows protected your PC".**
The installer is not code-signed yet, and Windows warns about any program it
has not seen many times before. Click **More info**, then **Run anyway**. Only
do this for a file from this repository's Releases page.

**My antivirus flags or blocks the installer.**
New, unsigned installers that carry their own Python are often flagged by
mistake. Check the file's SHA-256 against the one in the release notes: if it
matches, the file is the one we built from this code. If your antivirus still
worries you, you can build the installer yourself from the source
(`installer/README.md`). Please report the antivirus name and the detection
name in an issue, so we can send it to the vendor as a false positive.

**Linux: the doctor says Hyprland is missing or too old.**
Hivemind needs Hyprland 0.56 or newer (it only runs inside a window; your own
desktop stays as it is). Arch and Fedora have it. **Ubuntu, Mint and Debian
ship an older one**: on those, Hivemind is not beginner-friendly yet. You can
install a newer Hyprland from the Hyprland wiki, or install Nix and follow the
NixOS steps in `installer/linux/README-LINUX.md`.

**Linux: "X11 cannot work".**
Log out and pick the **Wayland** session at your login screen (often a gear
or a menu next to the password box).

**Linux: `install.sh` printed a command and stopped.**
That is on purpose: the installer never uses sudo. Run the one command it
printed yourself, then run `./install.sh` again.

## Starting

**"Not enough memory to start".**
The bot will not start with less than 6 GB of free memory on Linux (2 GB on
Windows), so the game is never killed halfway. Close other games, browsers
and video apps, then press Start again. On an 8 GB PC, close everything else.

**It never gets past the loading screen ("app never reached home").**
Usually Roblox itself: a disconnect, a Roblox outage, or the Roblox client
crashing while it starts. Press **Stop**, close the game window, wait a minute
and press Start again. If it keeps happening, report it with the debug
bundle (below) and the time it started.

**It joined a public server instead of mine.**
- **Windows:** paste your private server's share link in **Settings >
  Server**, then check that "Which server Start joins" on the same page reads
  **"this share link"**. With no link in use, Windows joins a public server.
- **Linux:** Hivemind joins your own private server through the game's
  Servers tab. If you have none, pick another choice in Settings > Server.
- "Private server share link" and "Follow a friend in" (type them in the
  search box) are used before everything else: leave them empty unless you
  mean to use them.

**It walks to the wrong hive or can't find its own.**
Set **"Your Roblox username"** in Settings (type `username` in the search
box). The walk home steers toward the name printed on your hive. It is only
read from the screen, never typed.

## While it plays

**It paused by itself.**
"Pause while you play a game" is on: another game or your own Roblox was
opened. On Windows, switching to any other window also pauses it. Press
Resume when you are done.

**My clicks go to the game (Linux).**
Don't click into the game window while the bot plays. On desktops other than
KDE, don't minimise that window either: a minimised window sends no
pictures, and the bot loses sight.

**The camera or movement is wrong.**
- Turn **shift lock off** before you start. The bot assumes it starts off.
- Leave Roblox's keys at their defaults (W A S D, Space, E, Shift, `,` `.`,
  Page Up / Page Down).
- Leave "Zoom out while farming" and "Tilt camera down while farming" at 0.
- Only a 1920x1080 game picture is measured. Other screen sizes and UI
  scales are not supported yet. On Windows, a 100% display scale is the
  safest.

**F12 does nothing (Linux).**
Add yourself to the `input` group (`sudo usermod -aG input $USER`), then log
out and back in. Without it, F12 only works while the Hivemind window has
focus, plus a desktop-wide shortcut on some desktops. `hivemind doctor` says
which one you have.

**A key seems stuck after the bot was killed.**
Press **F12** once. It lets go of every key the bot may still be holding.

**It does something risky I didn't turn on.**
Stop it (F12), then pick **Safe first run** in the preset list at the top of
the window and report what happened. Every optional feature is off until you
turn it on.

## Still stuck?

Open a **Bug report** from this repository's Issues tab, or ask in the
Discord. Include:

- what you did, what you expected and what happened (exact words help);
- your system: Windows version or Linux distro and desktop, graphics card,
  screen size;
- on Linux, what `hivemind doctor` printed.

For anything odd during a run, make a **debug bundle**:

- **In the app:** Settings › Help › **Report a problem** (and **Save this
  moment** under the live view while the odd thing is on screen)
- **Linux:** `cd ~/.local/share/hivemind/app && .venv/bin/python scripts/debug_bundle.py`
- **Windows:** in `%LOCALAPPDATA%\Programs\Hivemind`, run
  `python\python.exe scripts\debug_bundle.py`

It takes your tokens, links and username out of the text files, but it holds
**pictures of your game**, which can show your username, friends or chat.
**Send it privately to the team, never in a public channel or issue.**
