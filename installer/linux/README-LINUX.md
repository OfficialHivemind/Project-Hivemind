# Hivemind for Linux: tester guide

Hivemind plays Bee Swarm Simulator for you. It runs the game (Sober, the
Android Roblox) inside its own small Hyprland window, so your real mouse and
keyboard stay yours. This is a **test build**: expect rough edges, and please
tell the Hivemind team what you see (see "Reporting" at the end).

The full tester guide is [`docs/TESTING.md`](docs/TESTING.md), and what
Hivemind will and will not do is in [`docs/SECURITY.md`](docs/SECURITY.md).
Both are in this folder.

**Read this first:** bots and macros can break Roblox's rules, and Roblox can
ban the account that uses one. Use Hivemind at your own risk.

## Which Linux works

- **Ready for beginners:** Arch (and EndeavourOS, Manjaro), Fedora, and
  NixOS (no one has tested NixOS yet).
- **Not ready yet:** Ubuntu, Linux Mint, Debian and Pop!_OS. They do not have
  a new enough Hyprland yet. See "Ubuntu, Mint and Debian" below.

## What you need

- **A Wayland desktop session** (KDE Plasma, GNOME, Hyprland, Sway...).
  X11 cannot work. Pick the Wayland session at your login screen.
- **Sober** from Flathub, logged in to your Roblox account.
- **At least 6 GB of free RAM** when you press Play. Hivemind will not
  start with less. A PC with 8 GB of RAM is usually not enough yet. 12 GB or
  more works. You also need a GPU that runs Roblox. AMD and Intel are the
  safe choices. NVIDIA is untested.
- **Hyprland 0.56 or newer.** Your desktop stays as it is. Hyprland only runs
  inside a window.
- Your user in the **`input` group**, so the **F12 panic key** works. This is
  needed. The input group lets programs read your keyboard. Hivemind only
  listens for F12 (and W, A, S, D while it learns). To undo it later, run
  `sudo gpasswd -d $USER input`.

## NixOS (the main target)

1. Add these lines to `/etc/nixos/configuration.nix`, then run
   `sudo nixos-rebuild switch`. Log out and back in afterwards, because the
   input group only applies to new logins.

   ```nix
   programs.hyprland.enable = true;   # Hyprland built against your GPU drivers
   services.flatpak.enable = true;    # for Sober
   users.users.<you>.extraGroups = [ "input" ];   # the F12 panic key
   nix.settings.experimental-features = [ "nix-command" "flakes" ];
   ```

   You do not need uinput (`hardware.uinput.enable`). Hivemind types through
   Hyprland's own virtual keyboard, not through /dev/uinput.

2. Install Sober. This needs no root:

   ```sh
   flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
   flatpak install --user -y flathub org.vinegarhq.Sober
   ```

   Open Sober once and log in.

3. In this folder:

   ```sh
   nix run . -- doctor     # checks your PC: every line should be ✓
   nix run .               # opens Hivemind
   nix profile install .   # optional: adds `hivemind` and a menu entry
   ```

   Hivemind copies itself to `~/.local/share/hivemind/app`, because it writes
   logs and what it learns next to its code.

## Arch and Fedora

```sh
./install.sh
```

It installs into `~/.local/share/hivemind` and adds `hivemind` plus a menu
entry. It never uses sudo. If anything is missing, it prints **one command**
for you to run yourself, for example:

- Arch: `sudo pacman -S --needed hyprland pyside6 python-pywayland ...`
- Fedora: `sudo dnf install hyprland python3-pyside6 ...`

Some problems are not fixed by a package (too little free memory, for
example). Then do the fix written under that line.

For the panic key, run `sudo usermod -aG input $USER`, then log out and back in.

### Ubuntu, Mint and Debian

These (and Pop!_OS) are **not ready yet**. Hivemind needs Hyprland 0.56 or
newer, and these distros do not have it. `./install.sh` stops here and
installs nothing. If you are new to Linux, please wait for a later version.

If you are comfortable in a terminal, you have two choices:

- build Hyprland 0.56 or newer yourself, from the Hyprland wiki, then run
  `./install.sh --force` (you may also need `sudo apt install python3-venv`), or
- install Nix and follow the NixOS steps above, from step 2.

Hivemind also has an experimental setting that runs the game without
Hyprland (`platform.compositor: labwc`). It has not been tested with the real
game yet, so do not rely on it.

## Your first 10 minutes

1. Run `hivemind doctor`, or use "Check this PC" from the menu entry. Fix every ✗.
2. Open Hivemind. The first-run check appears until everything passes.
3. Hivemind starts with **safe settings**:
   - one field (Sunflower)
   - it converts honey when the bag is full
   - quests, buying, crafting, bosses and hatching are all **off**

   You can turn things on in Settings later.
4. Hivemind joins **your own private server** through the game's Servers
   tab. If you don't have one, Settings > Server has the other choices: a
   share link, a server by name, or "follow me".
5. Press **Play**. A Hyprland window opens, Sober starts, and the bot joins
   and walks to its field. **F12 stops everything.** Don't click into the
   Hyprland window while it plays, because your clicks then go to the game.
   On desktops other than KDE, don't minimise that window either.
6. Want to look around first? Run `hivemind demo` to open the window with
   recorded data. No game is needed.

## Privacy

Hivemind sends **nothing** over the internet unless you turn something on.
Only these connect, and only after you switch them on in Settings: update
checks (GitHub), Telegram alerts, Discord alerts, stream chat, server
hopping and the Wax calculator's Load button.

What it keeps on your PC:

- your settings and tokens: `~/.config/hivemind`
- logs, what it learned and game pictures: `~/.local/share/hivemind/app/var`.
  The pictures can show your Roblox name and the game chat.

## Uninstall

```sh
hivemind uninstall           # keeps your settings and what it learned
hivemind uninstall --purge   # removes everything
nix profile remove hivemind  # (Nix only, in addition)
```

## Reporting

Send these to the Hivemind team **in a private message** (a DM on the
Hivemind Discord, not a public channel):

- what `hivemind doctor` printed
- your distro
- your GPU
- the debug bundle. Make it with:

  ```sh
  hivemind bundle
  ```

  It removes your username, server links and secret codes first, and prints
  where it saved the file.

Do not send the raw log files from `var/night`. They can contain your
username and your private server link.
