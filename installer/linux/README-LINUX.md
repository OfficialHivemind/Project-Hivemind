# Hivemind for Linux: tester guide

Hivemind plays Bee Swarm Simulator for you. It runs the game (Sober, the
Android Roblox) inside its own small Hyprland window, so your real mouse and
keyboard stay yours. This is a **test build**: expect rough edges, and please
tell the owner what you see.

## What you need

- **A Wayland desktop session** (KDE Plasma, GNOME, Hyprland, Sway...).
  X11 cannot work. Pick the Wayland session at your login screen.
- **Sober** from Flathub, logged in to your Roblox account.
- **About 4 GB of free RAM** and a GPU that runs Roblox. AMD and Intel are
  the safe choices. NVIDIA is untested.
- **Hyprland 0.56 or newer.** Your desktop stays as it is. Hyprland only runs
  inside a window.
- Your user in the **`input` group**, so the **F12 panic key** works. This is
  not optional.

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

## Arch, Ubuntu / Mint / Debian, Fedora

```sh
./install.sh
```

It installs into `~/.local/share/hivemind` and adds `hivemind` plus a menu
entry. It never uses sudo. If anything is missing, it prints **one command**
for you to run yourself, for example:

- Arch: `sudo pacman -S --needed hyprland pyside6 python-pywayland ...`
- Ubuntu, Mint or Debian: `sudo apt install python3-pyside6.qtwidgets ...`

For the panic key, run `sudo usermod -aG input $USER`, then log out and back in.

**Ubuntu, Mint and Debian:** the Hyprland in their repositories is too old.
Install 0.56 or newer from the Hyprland wiki, or install Nix and use the
NixOS steps above (from step 2).

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

## Uninstall

```sh
hivemind uninstall           # keeps your settings and what it learned
hivemind uninstall --purge   # removes everything
nix profile remove hivemind  # (Nix only, in addition)
```

## Reporting

Send the owner:

- what `hivemind doctor` printed
- your distro
- your GPU
- `~/.local/share/hivemind/app/var/night/attempts.log`
