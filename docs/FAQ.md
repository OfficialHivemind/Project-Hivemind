# Hivemind FAQ

Short answers for players. Something not working? See
[`TROUBLESHOOTING.md`](TROUBLESHOOTING.md). Testing a build? The full guide is
[`TESTING.md`](TESTING.md).

## The basics

**What is Hivemind?**
A free, open-source bot that plays Bee Swarm Simulator for you. It looks at the
game through screenshots, decides what is worth doing, and plays with keyboard
and mouse input, like a person at the keyboard.

**Does it cost anything?**
No. Hivemind is free, and the code is public under GPL-3.0. There is no paid
version: if someone asks you to pay for "Hivemind Pro" or a "premium" build,
it is not us.

**Where do I download it?**
Only from the **Releases** page of this repository. Builds sent in DMs, on
file-sharing sites or in video comments are not ours, even if they use the
name.

**Which systems does it run on?**
Linux and Windows. macOS is planned for later. On Linux it needs a Wayland
desktop, Hyprland 0.56 or newer and Sober (the Roblox app for Linux); the
`hivemind doctor` command checks all of it. On Windows it needs Roblox from
roblox.com (not the Microsoft Store). The details are in
[`TESTING.md`](TESTING.md#before-you-start).

**Does it run on a Steam Deck?**
SteamOS is Linux and Sober runs there, but nobody has tested Hivemind on a
Deck yet. Screens smaller than 1920x1080 are untested too. If you try it,
please tell us what happened.

**How strong a PC do I need?**
The bot will not start with less than **6 GB of free memory** on Linux or
**2 GB** on Windows, and it needs a graphics card that runs Roblox (AMD and
Intel are the safe choices on Linux; NVIDIA is untested there). The local
vision model is optional and off in the safe settings.

## Safety and your account

**Can I get banned?**
We can't promise you won't. Using a bot or macro can break Roblox's Terms of
Use or the game's rules, and any account that uses one takes that risk.
Hivemind only plays through the screen, keyboard and mouse, but that does not
make it allowed, and no setting makes it "undetectable". It is your choice and
your account.

**Does it spend Robux?**
Never. It never spends Robux and never presses Buy on anything priced in
Robux.

**Does it need my password?**
No. You log in to Roblox yourself. Hivemind never asks for your Roblox
password or your PC's password. If anything asks for one in Hivemind's name,
it is not Hivemind.

**Does it type in chat?**
No. "Never type in chat" is locked on.

**Does it read the game's memory or inject code?**
No. It only reads the screen.

**What does it send over the internet?**
Nothing about your account. The only online parts are ones you turn on
yourself: Telegram or Discord alerts, YouTube chat for streams, and the update
check (all off until you turn them on). The wax calculator reads public tables
from the game's wiki.

## Using it

**What does a new install do?**
It starts with the **Safe first run** settings: one field (Sunflower), convert
when the bag is 95% full, and quests, buying, crafting, planters, bosses,
hatching and alerts all off. Turn things on one at a time in Settings.

**How do I stop it?**
**F12** stops everything at once and lets go of every key. F3 or the Stop
button stops it normally, F2 pauses. See
[`TESTING.md`](TESTING.md#how-to-stop-it-f12-and-friends).

**Can I use my PC while it plays?**
On Linux, yes: the game runs in its own window. Don't click into that window
while it plays. On Windows, not yet: when you switch to another window, the
bot lets go of every key and pauses until Roblox is in front again.

**Why did it pause by itself?**
"Pause while you play a game" is on by default. If you start another game (or
your own Roblox), the bot finishes its step and pauses. Press Resume when you
are done.

**Do I need a private server?**
It is the best choice, so the bot plays where nobody bothers it. Without one,
Settings > Server has other choices.

**Can I look around before I install the real thing?**
Yes. The UI Preview and `hivemind demo` open the app with made-up demo data.
Start does nothing there.

**Can I stream it?**
Yes. Settings has a stream mode that hides private details (paths, links,
memory figures) from the stream window. Still check your stream before you go
live: your username is printed on your hive in the game itself.

## The project

**Why GPL-3.0?**
Hivemind's gather patterns and field paths come from Natro Macro, which is
GPL-3.0, so Hivemind is GPL-3.0 too. Anyone who shares a changed copy must
share its code as well.

**How can I help?**
Report bugs and ideas with the issue forms, send measurements, or pick an
issue labelled **good first issue**. Start with
[`CONTRIBUTING.md`](../CONTRIBUTING.md).

**Where do I get help?**
Read [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) first, then ask in the
Discord (linked from this repository's main page) or open a bug report.
