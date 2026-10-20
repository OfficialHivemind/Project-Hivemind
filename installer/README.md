# Hivemind for Windows: the installer (RL6i)

One `Hivemind-Setup.exe`: a normal Next / Install / Finish wizard with the
Hivemind icon, installed per user (no admin prompt) into
`%LOCALAPPDATA%\Programs\Hivemind`, with Start-menu and desktop shortcuts and
an uninstaller under Settings > Apps. Python, every library and Tesseract are
inside it; the user installs nothing else. The `.bat` kit stays for quick dev
tests with the owner only.

| file | what it is |
|---|---|
| `build.ps1` | the whole build: app folder, selftest, Inno Setup. CI runs exactly this |
| `hivemind.iss` | the Inno Setup script: wizard, shortcuts, uninstaller, version, AppId |
| `requirements-windows.txt` | every wheel the app imports, pinned with its sha256 |
| `make_icon.py` | `hivemind.ico` and the wizard images, from `data/icon.png` |
| `../.github/workflows/windows-installer.yml` | builds it on `windows-latest` |
| `../data/presets/safe-first-run.yaml` | the first-run settings |

## What gets installed

```
%LOCALAPPDATA%\Programs\Hivemind\
  python\        the official embeddable CPython 3.12.10 + the pinned wheels
  src\ scripts\ data\ pyproject.toml     the repo's own layout
  tesseract\     tesseract.exe + its DLLs + tessdata\afr.traineddata, configs\
  hivemind.ico   unins000.exe
  var\           created by the bot: logs, what it learned (kept on uninstall)
%LOCALAPPDATA%\Hivemind\settings.yaml    the safe first run, only if none existed
%LOCALAPPDATA%\Hivemind\presets\Safe first run.yaml
```

The shortcuts run `python\pythonw.exe -m hivemind.gui` with the Hivemind icon
and AppUserModelID `Hivemind.Hivemind` (the GUI sets the same id, so the
taskbar shows Hivemind, not Python). Play starts `src\hivemind\watchdog.py`
with `python\python.exe`, which runs `scripts\run_farm.py`, exactly as from a
checkout. Tesseract is found because `hivemind/__init__.py` puts
`<install>\tesseract` first on PATH (and sets `TESSDATA_PREFIX`) on Windows,
for the GUI and every process it starts (`datapaths.use_bundled_tesseract`).

**OpenCV is the contrib build** (`opencv-contrib-python-headless`), because
OpenCV 5 moved `cv2.ml` out of the plain wheels. Without it, which-field
sensing (`vision/fieldsense`) and the token school's classifier
(`brain/school`) silently have no model. MEASURED 2026-10-21 on Windows: the
plain headless 5.0.0.93 wheel is 43.8 MB (117.6 MB unpacked, no `cv2/ml`);
the contrib one is 53.7 MB (144.5 MB unpacked), so the download grows by
about 10 MB and the install by about 27 MB. The selftest's "opencv ml" check
fails the build if a later pin loses it again.

## Why embedded Python and not PyInstaller

Both were weighed for this codebase; the embeddable Python (option b, what
pynsist does) is the more robust one here:

- **The code runs scripts by path.** The GUI starts `watchdog.py`, the watchdog
  starts `scripts/run_farm.py` and `scripts/night_report.py`, the Telegram
  panel runs `daily_card.py`, startfails runs `telegram_alerts.py`, all as
  `[sys.executable, script]`. A frozen exe has no interpreter to hand a
  script to: each would need an argument dispatcher and its own frozen code path,
  none of which has ever run.
- **Pids are believed by command line.** `files.pid_running` trusts a pidfile only
  while the process's command line still names `scripts/run_farm.py` or
  `src/hivemind/watchdog.py`. Under one dispatching exe every process is
  `Hivemind.exe`, so that safety rule would need rewriting too.
- **About 30 modules find data and var by `Path(__file__).parents[3]`**, and two
  hash their own source (`act/shoplook`, `act/inventory`). Frozen modules live
  in an archive with no source on disk. With the real layout every one of
  these works unchanged.
- **Antivirus.** PyInstaller's bootloader is a well-known false-positive
  magnet, which is the "looks scammy" problem again. `python.exe` and
  `pythonw.exe` here are the PSF's own signed binaries.
- **Upgrades are plain files**, so a fix is one changed `.py`.

PyInstaller itself would have coped with the libraries. PySide6 and OpenCV have
maintained hooks, numpy is routine, and windows-capture is a single
self-contained `.pyd` (it needs only `vcruntime140.dll` and the Universal CRT).
The cost is all in the bullets above. What (b) gives up: the shortcut target
is `pythonw.exe` (the shortcut, Start menu and taskbar still show Hivemind),
and Task Manager lists the processes as Python.

## Build it on Linux (no Windows needed)

`bash installer/build-linux.sh`: same steps, Wine only for ISCC, the selftest and an install/uninstall smoke test. Under Wine the Qt selftest checks fail (no icuuc.dll in Wine; Windows ships it), so those are skipped.

## Build it locally on Windows

Needs Windows 10/11 x64, any Python 3.9+ with pip (only to fetch the wheels;
they are chosen for 3.12 whatever runs pip), [7-Zip](https://www.7-zip.org/),
and Inno Setup 6 (`choco install innosetup`, which now installs it per user and puts
ISCC on PATH; the build finds either, or installs it with
choco when it is missing).

```powershell
git clone <the repo> Hivemind; cd Hivemind
powershell -ExecutionPolicy Bypass -File installer\build.ps1
# -> installer\build\Hivemind-Setup.exe   (the app folder is installer\build\app)
```

To try the app without installing: `installer\build\app\python\pythonw.exe -m hivemind.gui`.
To check a build: `installer\build\app\python\python.exe -B -m hivemind.gui --selftest`.

The downloads (the Python zip, the UB Mannheim Tesseract installer, `afr.traineddata`,
Tesseract's licence) are pinned by URL and sha256 in `build.ps1` and cached in
`installer\cache`. A changed file fails the build. The wheels are pinned the
same way in `requirements-windows.txt` (`pip --require-hashes`).

**Version:** `pyproject.toml`'s `version`, numbers only (`x.y.z`, Inno's
`VersionInfoVersion` requires it). The app prints it with `--version`.
**AppId** (in `hivemind.iss`): never change it, or Windows treats the next
build as a different app (no upgrade, two uninstall entries).

## What the GitHub workflow does

`.github/workflows/windows-installer.yml`, on `windows-latest`. It runs on a
push to main/integ/wininstaller or a pull request that touches the app or the
installer, or by hand (Actions > windows-installer > Run workflow).

1. Checks out the repo and sets up Python 3.12.
2. Restores `installer\cache` (the pinned downloads).
3. Runs `installer\build.ps1`. That builds the app folder and runs
   `--version` and `--selftest` against it. The selftest imports every
   package, starts the Qt platform plugin and runs `run_farm.py`'s top level
   without `main()`. It then runs the bundled `tesseract --list-langs` and
   requires `afr`. Last, the script packs the folder with Inno Setup.
4. Smoke test: installs `Hivemind-Setup.exe` silently, runs the selftest
   from the installed copy, checks the settings file, the Start-menu shortcut
   and the uninstaller exist, then uninstalls silently.
5. Uploads `Hivemind-Setup.exe` as the artifact **Hivemind-Setup**, kept 30 days.
   Download it from the run's summary page.

No secrets are used. The exe is **not code signed**, so SmartScreen says
"Windows protected your PC / unknown publisher" (More info > Run anyway).
Signing costs money and is the owner's call. It would be one `signtool` step
after Inno Setup (Inno's `SignTool=` directive), with the certificate in a
repository secret.

## Licences of what is bundled

- CPython: PSF licence.
- PySide6 and shiboken6: LGPLv3. They are shipped as the unmodified wheels'
  separate DLLs, which LGPL allows.
- OpenCV (with the opencv_contrib modules): Apache 2.0. numpy, psutil, PyYAML, platformdirs, comtypes, dxcam:
  BSD/MIT. windows-capture: MIT.
- Tesseract: Apache 2.0, licence in `tesseract\LICENSE-tesseract.txt`. Its
  DLLs from the UB Mannheim build are permissive or LGPL libraries shipped as
  separate files.
- `afr.traineddata` (tessdata 4.1.0): Apache 2.0.
- The MSVC runtime DLLs come from the shiboken6 wheel and the Python zip,
  as Microsoft's redistributable terms allow.
