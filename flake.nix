# Hivemind on NixOS, and on any distro with Nix (RL1, docs/pending/linux-package.md).
#
#   nix run .                  try it (opens the window; first run checks the PC)
#   nix run . -- doctor        every requirement, with the NixOS fix for each
#   nix profile install .      the `hivemind` command + its menu entry
#
# The rest needs system configuration, so it lives in configuration.nix, not
# here (README-LINUX.md has the lines): programs.hyprland.enable (Hyprland
# built against YOUR system's GPU drivers), services.flatpak.enable + Sober
# from Flathub, and the input group for the F12 panic key.
#
# [assumed: not evaluated] -- written on a machine without Nix. Verify with:
#   nix flake check && nix build . && ./result/bin/hivemind doctor
{
  description = "Hivemind: autonomous Bee Swarm Simulator player for Linux/Wayland";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      lib = pkgs.lib;
      version = (builtins.fromTOML (builtins.readFile ./pyproject.toml)).project.version;

      python = pkgs.python3.withPackages (ps: with ps; [
        pyside6 pywayland xkbcommon opencv4 numpy evdev pyyaml platformdirs
      ]);
      # the bot reads the game's text with tesseract's Afrikaans model (vision/beemenu)
      tesseract = pkgs.tesseract.override { enableLanguages = [ "afr" "eng" ]; };

      # The app's own files, as the tarball ships them: no var/, no tests, and
      # never the owner's account files.
      app = lib.fileset.toSource {
        root = ./.;
        fileset = lib.fileset.difference
          (lib.fileset.unions [ ./src ./scripts ./data ./pyproject.toml ./installer/linux ])
          (lib.fileset.fileFilter (f: lib.hasPrefix "account" f.name && f.hasExt "yaml") ./data);
      };

      hivemind = pkgs.writeShellApplication {
        name = "hivemind";
        runtimeInputs = [ python tesseract pkgs.procps pkgs.util-linux pkgs.coreutils
                          pkgs.gnused pkgs.findutils pkgs.libnotify ];
        text = ''
          export HIVEMIND_SOURCE=${app}
          export HIVEMIND_PYTHON=${python}/bin/python3
          # Qt's Wayland platform plugin, which a bare python env does not point Qt at
          export QT_PLUGIN_PATH="${pkgs.qt6.qtwayland}/${pkgs.qt6.qtbase.qtPluginPrefix}:${pkgs.qt6.qtbase}/${pkgs.qt6.qtbase.qtPluginPrefix}''${QT_PLUGIN_PATH:+:$QT_PLUGIN_PATH}"
          # Hyprland LAST: the system's (programs.hyprland.enable) wins, since it
          # matches the system's mesa; this one is only the fallback.
          export PATH="$PATH:${pkgs.hyprland}/bin"
          exec bash ${app}/installer/linux/hivemind "$@"
        '';
      };

      desktop = pkgs.makeDesktopItem {
        name = "hivemind";
        desktopName = "Hivemind";
        genericName = "Bee Swarm Simulator Autopilot";
        comment = "Autonomous Bee Swarm Simulator player";
        exec = "hivemind";
        icon = "hivemind";
        categories = [ "Game" ];
      };
    in {
      packages.${system}.default = pkgs.symlinkJoin {
        name = "hivemind-${version}";
        paths = [ hivemind desktop ];
        postBuild = ''
          install -Dm644 ${./data/icon.png} $out/share/icons/hicolor/512x512/apps/hivemind.png
        '';
      };
      apps.${system}.default = {
        type = "app";
        program = "${hivemind}/bin/hivemind";
      };
    };
}
