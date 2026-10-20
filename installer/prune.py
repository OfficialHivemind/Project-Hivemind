"""Shrinks the Windows app folder before it is packed (ROADMAP U15c).

    python installer/prune.py installer/build/app

build.ps1 and build-linux.sh both run it after the app folder is complete and
before the selftest, so the selftest checks the pruned folder that ships.
Runs on any Python 3.9+ (the build's own Python, not the app's).

MEASURED 2026-10-26 on the 2026-10-22 build (installer/build/app, 627 MB of files):
python 436 MB (PySide6 214, cv2 138, numpy 22 + numpy.libs 21) and tesseract
175 MB, of which tessdata is only 7.6 MB. Most of the rest is never loaded by
the app: Qt's QML/Quick stack, developer tools and build files, FFmpeg, and
Tesseract's training-tool libraries and debug info. MEASURED 2026-10-26, a
full `build.ps1 -Preview` with this step: app folder 626.7 -> 273.5 MB (4863 ->
1949 files), Hivemind-UI-Preview.exe 156.4 -> 77.3 MB, selftest passing.

Two parts, both checked:
1. PRUNE, an explicit list of what goes and why it is safe. After deleting,
   every .dll/.pyd/.exe left in the folder is read, and the build fails if one
   still imports a file this script removed and no folder Windows would search
   for it still has a copy (SEARCH; a missing DLL would only show on a
   tester's PC, as a Windows error box).
2. strip_debug: libtesseract-5.dll and tesseract.exe from the UB Mannheim build
   carry their DWARF debug sections (see STRIP for the sizes). Only those
   sections are cut off; the code and data the loader maps are untouched.

Sizes are in MB of 10**6 bytes throughout (bytes / 1e6, as the script prints).

Keep in mind when adding a line: the selftest (src/hivemind/selftest.py) is the
proof, and it imports only QtCore/QtGui/QtWidgets/QtSvg, cv2, numpy, starts
the Qt platform plugin and runs the bundled Tesseract on a rendered line.
"""
from __future__ import annotations

import shutil
import struct
import sys
from pathlib import Path

SITE = "python/Lib/site-packages"

# (glob under the app folder, what it is and why the app never needs it, ~MB saved)
# The MB figures are MEASURED 2026-10-26 on the 2026-10-22 build (PySide6 6.12.0,
# opencv-contrib-python-headless 5.0.0.93, numpy 2.5.4, Tesseract 5.4.0.20240606).
# Which Qt modules the app imports: `grep -rhoE "(from|import) PySide6\.\w+" src
# scripts` gives QtCore, QtGui, QtWidgets and QtSvg only (QtOpenGL is in
# tools/universal/probe.py and QtTest in tests/, neither of which is shipped).
PRUNE = (
    # ---- PySide6 (214 MB) ----------------------------------------------------
    (f"{SITE}/PySide6/opengl32sw.dll",
     "Mesa software OpenGL, loaded only when an OpenGL context falls back to "
     "software. The GUI is plain QtWidgets in the Fusion style (gui/app.py) with "
     "no QOpenGLWidget or Qt Quick, so it never makes an OpenGL context", 20),
    (f"{SITE}/PySide6/qml", "QML modules for Qt Quick; the app has no QML", 17),
    (f"{SITE}/PySide6/translations",
     "Qt's own UI translations, read only through a QTranslator, which the app "
     "never installs (no QTranslator in src/ or scripts/)", 14),
    (f"{SITE}/PySide6/resources",
     "icudtl.dat, QtWebEngine's ICU data. WebEngine is not in this wheel and no "
     "binary in the folder names the file (searched as ASCII and UTF-16)", 10),
    (f"{SITE}/PySide6/metatypes", "build-time type data for qmltyperegistrar", 7),
    (f"{SITE}/PySide6/*.exe",
     "developer tools: designer, assistant, linguist, lupdate, lrelease, uic, "
     "rcc, qmlls, qmlformat, qmllint, qmlcachegen, ... none is ever started", 14),
    (f"{SITE}/PySide6/include", "C++ headers, for compiling against PySide6", 1),
    (f"{SITE}/PySide6/typesystems", "binding generator input", 1),
    (f"{SITE}/PySide6/glue", "binding generator input", 0.2),
    (f"{SITE}/PySide6/lib", "CMake files, for compiling against PySide6", 0.1),
    (f"{SITE}/PySide6/doc", "binding docs (.rst)", 0.1),
    (f"{SITE}/PySide6/*.lib", "import libraries, for linking against PySide6", 0.1),
    (f"{SITE}/PySide6/*.pyi", "type stubs for IDEs; never imported", 4),
    # Binding modules the app never imports, and the Qt libraries only they use.
    # Kept: QtCore, QtGui, QtWidgets, QtSvg (.pyd) and Qt6Core/Gui/Widgets/Svg,
    # Qt6Network (plugins/generic imports it), pyside6.abi3 and the MSVC runtime.
    (f"{SITE}/PySide6/QtOpenGL.pyd", "binding not imported (only tools/)", 8.5),
    (f"{SITE}/PySide6/QtOpenGLWidgets.pyd", "binding not imported", 0.1),
    (f"{SITE}/PySide6/QtQml*.pyd", "binding not imported", 0.5),
    (f"{SITE}/PySide6/QtQuick*.pyd", "binding not imported", 1.1),
    (f"{SITE}/PySide6/QtDesigner.pyd", "binding not imported", 0.5),
    (f"{SITE}/PySide6/QtHelp.pyd", "binding not imported", 0.3),
    (f"{SITE}/PySide6/QtSql.pyd", "binding not imported", 0.4),
    (f"{SITE}/PySide6/QtXml.pyd", "binding not imported", 0.2),
    (f"{SITE}/PySide6/QtDBus.pyd", "binding not imported", 0.3),
    (f"{SITE}/PySide6/QtNetwork.pyd", "binding not imported", 1),
    (f"{SITE}/PySide6/QtPrintSupport.pyd", "binding not imported", 0.3),
    (f"{SITE}/PySide6/QtConcurrent.pyd", "binding not imported", 0.1),
    (f"{SITE}/PySide6/QtUiTools.pyd", "binding not imported", 0.1),
    (f"{SITE}/PySide6/QtSvgWidgets.pyd", "binding not imported (QtSvg is kept)", 0.1),
    (f"{SITE}/PySide6/QtLabsStyleKit.pyd", "binding not imported", 0.1),
    (f"{SITE}/PySide6/QtTest.pyd", "binding used by tests/ only, not shipped", 0.2),
    (f"{SITE}/PySide6/pyside6qml.abi3.dll", "QML support for the bindings", 0.1),
    (f"{SITE}/PySide6/Qt6Quick*.dll", "Qt Quick and its controls/styles", 34),
    (f"{SITE}/PySide6/Qt6Qml*.dll", "the QML engine", 9),
    (f"{SITE}/PySide6/Qt6Labs*.dll", "Qt Labs QML extras", 4.5),
    (f"{SITE}/PySide6/Qt6Lottie*.dll", "Lottie animation for Qt Quick", 0.7),
    (f"{SITE}/PySide6/Qt6Designer*.dll", "Qt Designer", 7.5),
    (f"{SITE}/PySide6/Qt6OpenGL*.dll", "OpenGL helpers (see opengl32sw)", 2),
    (f"{SITE}/PySide6/Qt6Help.dll", "Qt Assistant help engine", 0.6),
    (f"{SITE}/PySide6/Qt6Sql.dll", "SQL module; the app keeps no database through Qt", 0.3),
    (f"{SITE}/PySide6/Qt6Xml.dll", "XML module; the app reads YAML, not Qt XML", 0.2),
    (f"{SITE}/PySide6/Qt6DBus.dll", "D-Bus, a Linux bus", 0.7),
    (f"{SITE}/PySide6/Qt6PrintSupport.dll", "printing; the app prints nothing", 0.4),
    (f"{SITE}/PySide6/Qt6Concurrent.dll", "QtConcurrent; the app uses Python threads", 0.1),
    (f"{SITE}/PySide6/Qt6UiTools.dll", ".ui file loader; the GUI is built in code", 0.7),
    (f"{SITE}/PySide6/Qt6SvgWidgets.dll", "QSvgWidget (QSvgRenderer is in Qt6Svg)", 0.1),
    (f"{SITE}/PySide6/Qt6Test.dll", "QtTest, for tests/ only", 0.4),
    # Qt plugins for the modules above. Kept: platforms (qwindows; qoffscreen
    # and qminimal for headless runs), imageformats, iconengines, styles,
    # generic, platforminputcontexts.
    (f"{SITE}/PySide6/plugins/qmltooling", "QML debugger plugins", 1.3),
    (f"{SITE}/PySide6/plugins/sqldrivers", "SQL drivers", 2.5),
    (f"{SITE}/PySide6/plugins/designer", "Qt Designer plugins", 0.6),
    (f"{SITE}/PySide6/plugins/vectorimageformats", "Lottie for Qt Quick", 0.1),
    (f"{SITE}/PySide6/plugins/tls", "TLS backends for QtNetwork, unused", 0.7),
    (f"{SITE}/PySide6/plugins/networkinformation", "QtNetwork reachability, unused", 0.1),
    (f"{SITE}/PySide6/plugins/imageformats/qpdf.dll",
     "PDF images; it needs Qt6Pdf.dll, which is not in this wheel, so it never loads", 0.1),
    (f"{SITE}/PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll",
     "on-screen keyboard; it needs Qt6VirtualKeyboard.dll, not in this wheel", 0.1),
    # ---- OpenCV (138 MB; cv2.pyd itself is 107 MB and stays) ------------------
    # The one VideoCapture shipped is scripts/fetch_gear_images.py:decode(), which
    # reads the first frame of a GIF. MEASURED 2026-10-26: a GIF written with the
    # unpruned build's cv2 5.0.0 reads back the same with this DLL gone
    # (VideoCapture backend FFMPEG before, CV_IMAGES, OpenCV's own image reader,
    # after; same pixels). src/, windows_capture and dxcam use no VideoCapture
    # or VideoWriter: game frames come from the screen.
    (f"{SITE}/cv2/opencv_videoio_ffmpeg*_64.dll",
     "FFmpeg, loaded on demand by cv2.VideoCapture/VideoWriter for video files "
     "and streams. The only shipped use, a GIF in scripts/fetch_gear_images.py, "
     "is read by OpenCV's own image backend without it (measured)", 30),
    # ---- numpy ----------------------------------------------------------------
    (f"{SITE}/numpy/**/tests", "numpy's own test suite (numpy.testing stays)", 8),
    # ---- Tesseract (168 MB) ---------------------------------------------------
    # The UB Mannheim folder carries the libraries of its training tools
    # (text2image renders fonts with pango/cairo/harfbuzz/ICU). tesseract.exe
    # does not import any of them: MEASURED 2026-10-26, the import closure of
    # tesseract.exe is libtesseract, leptonica, libarchive and their image and
    # compression libraries (26 DLLs). The check after deleting proves it again.
    ("tesseract/libicu*.dll", "ICU (libicudt75 is 30 MB of Unicode data)", 35),
    ("tesseract/libcairo-*.dll", "cairo, for text2image", 1.2),
    ("tesseract/libpango*.dll", "pango, for text2image", 0.7),
    ("tesseract/libharfbuzz-*.dll", "harfbuzz, for pango", 1.3),
    ("tesseract/libgraphite2.dll", "graphite2, for harfbuzz", 0.1),
    ("tesseract/libgio-*.dll", "GLib's gio, for pango", 1.7),
    ("tesseract/libglib-*.dll", "GLib, for pango", 1.4),
    ("tesseract/libgobject-*.dll", "GObject, for pango", 0.3),
    ("tesseract/libgmodule-*.dll", "GModule, for gio", 0.1),
    ("tesseract/libfontconfig-*.dll", "fontconfig, for pango", 0.3),
    ("tesseract/libfreetype-*.dll", "FreeType, for cairo", 0.7),
    ("tesseract/libfribidi-*.dll", "fribidi, for pango", 0.1),
    ("tesseract/libthai-*.dll", "libthai, for pango", 0.1),
    ("tesseract/libdatrie-*.dll", "libdatrie, for libthai", 0.1),
    ("tesseract/libpixman-*.dll", "pixman, for cairo", 0.7),
    ("tesseract/libpcre2-*.dll", "PCRE2, for GLib", 0.4),
    ("tesseract/libintl-*.dll", "gettext, for GLib", 0.2),
    ("tesseract/libffi-*.dll", "libffi, for GObject", 0.1),
    ("tesseract/libbrotli*.dll", "brotli, for FreeType", 0.2),
)

# Binaries whose trailing DWARF sections are cut (strip_debug). MEASURED
# 2026-10-26 (MB = 10**6 bytes): libtesseract-5.dll is 101.5 MB, of which 97.2 MB
# are .debug_* sections; the cut, from the first of them to the end of the file
# (with the COFF symbol table and the old signature), is 98.2 MB, as prune.py
# prints. tesseract.exe: 1.6 MB, 1.4 MB of debug sections, 1.5 MB cut. No other
# DLL there has any.
# Both carry a Universitaet Mannheim Authenticode signature, which cutting
# breaks, so it is dropped. MEASURED 2026-10-26 (Get-AuthenticodeSignature on
# both, and on the pinned setup exe): status UnknownError, "A required
# certificate is not within its validity period"; the certificate ran out
# 2023-12-10 and the files were built 2024-06-06. Windows already treats them as
# not validly signed, so nothing is lost; every other DLL there is unsigned.
STRIP = ("tesseract/tesseract.exe", "tesseract/libtesseract-*.dll")


# ---- reading a PE file (exe/dll/pyd) -----------------------------------------
def _headers(b: bytes):
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    if b[:2] != b"MZ" or b[pe:pe + 4] != b"PE\0\0":
        raise ValueError("not a PE file")
    coff = pe + 4
    nsec, symptr, nsym, optsz = (struct.unpack_from("<H", b, coff + 2)[0],
                                 *struct.unpack_from("<II", b, coff + 8),
                                 struct.unpack_from("<H", b, coff + 16)[0])
    opt = coff + 20
    pe32plus = struct.unpack_from("<H", b, opt)[0] == 0x20B
    ndirs_at = opt + (108 if pe32plus else 92)
    ndirs = struct.unpack_from("<I", b, ndirs_at)[0]
    dirs = [struct.unpack_from("<II", b, ndirs_at + 4 + 8 * i) for i in range(min(ndirs, 16))]
    strtab = symptr + 18 * nsym if symptr else 0
    sections = []
    for i in range(nsec):
        at = opt + optsz + 40 * i
        raw_name = b[at:at + 8].rstrip(b"\0").decode("latin-1")
        name = raw_name
        if raw_name.startswith("/") and strtab:          # a long name, kept in the string table
            start = strtab + int(raw_name[1:])
            name = b[start:b.index(b"\0", start)].decode("latin-1")
        vsize, va, rawsize, rawptr = struct.unpack_from("<IIII", b, at + 8)
        sections.append({"name": name, "raw_name": raw_name, "va": va, "vsize": vsize,
                         "rawptr": rawptr, "rawsize": rawsize, "header": at})
    return {"coff": coff, "opt": opt, "symptr": symptr, "dirs": dirs, "dirs_at": ndirs_at + 4,
            "sections": sections}


def imports(path) -> list:
    """The DLL names a PE file imports, normal and delay-loaded."""
    b = Path(path).read_bytes()
    h = _headers(b)

    def at(rva):
        for s in h["sections"]:
            if s["va"] <= rva < s["va"] + max(s["vsize"], s["rawsize"]):
                return rva - s["va"] + s["rawptr"]
        raise ValueError(f"rva {rva:#x} outside every section")

    def name(rva):
        o = at(rva)
        return b[o:b.index(b"\0", o)].decode("latin-1")

    names = []
    dirs = h["dirs"]
    if len(dirs) > 1 and dirs[1][0]:                    # the import table: 20-byte entries
        o = at(dirs[1][0])
        while any(struct.unpack_from("<IIIII", b, o)):
            names.append(name(struct.unpack_from("<I", b, o + 12)[0]))
            o += 20
    if len(dirs) > 13 and dirs[13][0]:                  # delay-load imports: 32-byte entries
        o = at(dirs[13][0])
        while any(struct.unpack_from("<8I", b, o)):
            names.append(name(struct.unpack_from("<I", b, o + 4)[0]))
            o += 32
    return names


def strip_debug(path, drop_signature=False) -> int:
    """Cut the trailing .debug_* sections and the COFF symbol table off a
    MinGW-built PE file, as `strip --strip-debug` would. Returns the bytes
    saved (0 when it has none). Refuses (ValueError) anything it cannot cut
    cleanly: a debug section in the middle, a kept section with a long name, a
    data directory reaching into the cut part, or a signed file unless
    drop_signature (cutting breaks a signature, so it is removed too)."""
    path = Path(path)
    b = bytearray(path.read_bytes())
    h = _headers(b)
    secs = h["sections"]
    first = len(secs)
    while first > 0 and secs[first - 1]["name"].startswith(".debug_"):
        first -= 1
    if first == len(secs):
        return 0
    kept, cut = secs[:first], secs[first:]
    if any(s["name"].startswith(".debug_") for s in kept):
        raise ValueError(f"{path.name}: a .debug_ section before the code; not cutting")
    if any(s["raw_name"].startswith("/") for s in kept):
        raise ValueError(f"{path.name}: a kept section's name is in the symbol table")
    cut_va, end = cut[0]["va"], cut[0]["rawptr"]
    signed = False
    for i, (rva, size) in enumerate(h["dirs"]):
        if i == 4:                                      # the certificate table is a file offset
            signed = bool(rva or size)
            if signed and not drop_signature:
                raise ValueError(f"{path.name}: signed; cutting would break the signature")
            if signed and rva < end:
                raise ValueError(f"{path.name}: its signature lies before the debug sections")
        elif rva and rva + size > cut_va:
            raise ValueError(f"{path.name}: data directory {i} points into the debug sections")
    if any(s["rawptr"] + s["rawsize"] > end for s in kept if s["rawsize"]):
        raise ValueError(f"{path.name}: a kept section lies after the debug sections")
    if h["symptr"] and h["symptr"] < end:
        raise ValueError(f"{path.name}: the symbol table lies before the debug sections")
    coff, opt = h["coff"], h["opt"]
    section_align = struct.unpack_from("<I", b, opt + 32)[0]
    last = kept[-1]
    image_end = last["va"] + max(last["vsize"], last["rawsize"])
    image_size = -(-image_end // section_align) * section_align
    struct.pack_into("<H", b, coff + 2, len(kept))      # NumberOfSections
    struct.pack_into("<II", b, coff + 8, 0, 0)          # no symbol table any more
    struct.pack_into("<I", b, opt + 56, image_size)     # SizeOfImage
    if signed:
        struct.pack_into("<II", b, h["dirs_at"] + 8 * 4, 0, 0)   # the cut-off signature
    for s in cut:
        b[s["header"]:s["header"] + 40] = bytes(40)
    del b[end:]
    if struct.unpack_from("<I", b, opt + 64)[0]:        # keep a set CheckSum right
        struct.pack_into("<I", b, opt + 64, _checksum(b, opt + 64))
    saved = path.stat().st_size - len(b)
    tmp = path.with_name(path.name + ".strip")
    tmp.write_bytes(bytes(b))
    tmp.replace(path)
    return saved


def _checksum(b, field) -> int:
    """The PE image checksum (16-bit one's-complement sum plus the length),
    with the CheckSum field itself counted as zero."""
    data = bytes(b[:field]) + b"\0\0\0\0" + bytes(b[field + 4:])
    if len(data) % 2:
        data += b"\0"
    total = 0
    for (word,) in struct.iter_unpack("<H", data):
        total += word
        total = (total & 0xFFFF) + (total >> 16)
    return (total + len(b)) & 0xFFFFFFFF


# ---- the prune ----------------------------------------------------------------
def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def _binaries(app: Path):
    for p in app.rglob("*"):
        if p.suffix.lower() in (".dll", ".pyd", ".exe") and p.is_file():
            yield p


# Where Windows looks for a DLL that a binary imports, per process, besides the
# binary's own folder (Python loads extension modules with
# LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR) and System32 (nothing here is pruned from
# there). Keyed by the folder a binary sits under; the first match wins.
# - tesseract\: tesseract.exe is its own process; its DLLs are found in its own
#   folder only, never in python\.
# - python\: python.exe's own folder, plus the folders the packages add with
#   os.add_dll_directory (MEASURED 2026-10-26 in the built site-packages:
#   PySide6/__init__.py adds shiboken6, cv2/__init__.py its BINARIES_PATHS, the
#   delvewheel patch in numpy/__init__.py numpy.libs). PySide6 is there too: its
#   Qt6*.dll are loaded into the process by the bindings before Qt loads the
#   plugins that import them, and Windows reuses a loaded DLL by name.
SEARCH = (
    ("tesseract", ("tesseract",)),
    ("python", ("python", f"{SITE}/PySide6", f"{SITE}/shiboken6", f"{SITE}/cv2",
                f"{SITE}/numpy.libs")),
)


def _search_dirs(app: Path, binary: Path) -> list:
    """The folders Windows would search for a DLL that `binary` imports."""
    rel = binary.relative_to(app).as_posix()
    dirs = [binary.parent]
    for top, extra in SEARCH:
        if rel.startswith(top + "/"):
            dirs += [app / d for d in extra]
            break
    return dirs


def _missing(app: Path, removed: set) -> list:
    """Every binary left that imports a removed DLL which none of its search
    folders still holds, as 'path imports name' lines."""
    broken = []
    for p in _binaries(app):
        gone = [n for n in imports(p) if n.lower() in removed
                and not any((d / n).is_file() for d in _search_dirs(app, p))]
        if gone:
            broken.append(f"{p.relative_to(app).as_posix()} imports {', '.join(gone)}")
    return broken


def prune(app, say=print) -> int:
    """Delete PRUNE and strip STRIP under the app folder; returns bytes saved.
    Raises RuntimeError when a binary left behind imports a removed DLL."""
    app = Path(app)
    removed, saved = set(), 0
    for pattern, _why, _mb in PRUNE:
        hits = sorted(app.glob(pattern))
        if not hits:
            say(f"prune: nothing matches {pattern} (a newer wheel or Tesseract?)")
        for hit in hits:
            size = _size(hit)
            for f in ([hit] if hit.is_file() else hit.rglob("*")):
                if f.suffix.lower() in (".dll", ".pyd", ".exe"):
                    removed.add(f.name.lower())
            if hit.is_dir():
                shutil.rmtree(hit)
            else:
                hit.unlink()
            saved += size
    # Per process (SEARCH), not by name across the folder: MEASURED 2026-10-26,
    # python\_ctypes.pyd imports libffi-8.dll and finds python's own copy, which
    # stays; a binary left in tesseract\ importing libffi-8.dll would fail.
    broken = _missing(app, removed)
    if broken:
        raise RuntimeError("pruned a DLL that is still needed:\n  " + "\n  ".join(broken))
    for pattern in STRIP:
        for p in sorted(app.glob(pattern)):
            cut = strip_debug(p, drop_signature=True)
            saved += cut
            say(f"prune: cut {cut / 1e6:.1f} MB of debug sections off {p.name}")
    say(f"prune: {saved / 1e6:.0f} MB removed from {app}")
    return saved


if __name__ == "__main__":
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_dir():
        sys.exit("usage: python installer/prune.py <the app folder>")
    prune(sys.argv[1])
