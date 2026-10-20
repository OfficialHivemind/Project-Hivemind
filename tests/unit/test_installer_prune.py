"""U15c, shrinking the Windows app folder (installer/prune.py): the debug
strip on hand-made PE files, the prune on a fake app folder, and that both
build scripts prune before the selftest. The real folder is checked by the
build's selftest on Windows (installer/README.md)."""
from __future__ import annotations

import importlib.util
import struct
from pathlib import Path

import pytest

from hivemind import selftest

ROOT = Path(__import__("hivemind").__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("prune", ROOT / "installer/prune.py")
prune = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prune)


def make_pe(path, imports=(), debug=0, cert=b"", import_into_debug=False):
    """A minimal PE32+ file: .text, .idata (importing `imports`), then `debug`
    .debug_* sections named through the COFF string table, the symbol table
    after them, and an optional certificate at the very end."""
    names = [".text", ".idata"] + [f".debug_{i}" for i in range(debug)]
    raw = 0x200
    body = bytearray(0x400 + raw * len(names))
    body[:2] = b"MZ"
    struct.pack_into("<I", body, 0x3C, 0x40)
    body[0x40:0x44] = b"PE\0\0"
    opt, headers = 0x58, 0x58 + 240
    struct.pack_into("<H", body, opt, 0x20B)
    struct.pack_into("<II", body, opt + 32, 0x1000, 0x200)       # section, file alignment
    struct.pack_into("<I", body, opt + 56, 0x1000 * (len(names) + 1))
    struct.pack_into("<I", body, opt + 60, 0x400)
    struct.pack_into("<I", body, opt + 108, 16)
    strtab = bytearray(4)
    for i, name in enumerate(names):
        va, ptr = 0x1000 * (i + 1), 0x400 + raw * i
        if len(name) > 8:
            short = f"/{len(strtab)}".encode()
            strtab += name.encode() + b"\0"
        else:
            short = name.encode()
        at = headers + 40 * i
        body[at:at + 8] = short.ljust(8, b"\0")
        struct.pack_into("<IIII", body, at + 8, raw, va, raw, ptr)
        if name == ".idata":
            for j, dll in enumerate(imports):                    # 20-byte descriptors
                name_at = 0x100 + 0x20 * j
                struct.pack_into("<IIIII", body, ptr + 20 * j, 0, 0, 0, va + name_at, va + 0x1F0)
                body[ptr + name_at:ptr + name_at + len(dll)] = dll.encode()
            table_va = 0x1000 * len(names) if import_into_debug else va   # the last section's
            struct.pack_into("<II", body, opt + 112 + 8, table_va, 20 * (len(imports) + 1))
    symptr = len(body)
    struct.pack_into("<HHIIIHH", body, 0x44, 0x8664, len(names), 0, symptr, 1, 240, 0x2022)
    struct.pack_into("<I", strtab, 0, len(strtab))
    body += bytes(18) + strtab
    if cert:
        body += bytes(-len(body) % 8)
        struct.pack_into("<II", body, opt + 112 + 8 * 4, len(body), len(cert))
        body += cert
    Path(path).write_bytes(bytes(body))
    return Path(path)


def test_strip_debug_cuts_the_trailing_debug_sections(tmp_path):
    exe = make_pe(tmp_path / "a.dll", imports=("libleptonica-6.dll",), debug=3)
    assert [s["name"] for s in prune._headers(exe.read_bytes())["sections"]][-1] == ".debug_2"
    saved = prune.strip_debug(exe)
    b = exe.read_bytes()
    h = prune._headers(b)
    assert [s["name"] for s in h["sections"]] == [".text", ".idata"]
    assert len(b) == 0x400 + 2 * 0x200 and saved > 3 * 0x200
    assert h["symptr"] == 0 and struct.unpack_from("<I", b, h["opt"] + 56)[0] == 0x3000
    assert prune.imports(exe) == ["libleptonica-6.dll"]       # still a readable PE
    assert prune.strip_debug(exe) == 0                         # nothing left to cut


def test_strip_debug_drops_a_signature_only_when_told(tmp_path):
    exe = make_pe(tmp_path / "signed.dll", debug=1, cert=b"\x01" * 64)
    with pytest.raises(ValueError, match="signed"):
        prune.strip_debug(exe)
    assert prune.strip_debug(exe, drop_signature=True) > 0
    h = prune._headers(exe.read_bytes())
    assert h["dirs"][4] == (0, 0) and len(h["sections"]) == 2


def test_strip_debug_refuses_a_table_inside_the_cut(tmp_path):
    exe = make_pe(tmp_path / "odd.dll", debug=1, import_into_debug=True)
    before = exe.read_bytes()
    with pytest.raises(ValueError, match="data directory 1"):
        prune.strip_debug(exe)
    assert exe.read_bytes() == before


SITE = prune.SITE
KEPT = (f"{SITE}/PySide6/QtCore.pyd", f"{SITE}/PySide6/QtGui.pyd",
        f"{SITE}/PySide6/QtWidgets.pyd", f"{SITE}/PySide6/QtSvg.pyd",
        f"{SITE}/PySide6/Qt6Core.dll", f"{SITE}/PySide6/Qt6Gui.dll",
        f"{SITE}/PySide6/Qt6Widgets.dll", f"{SITE}/PySide6/Qt6Svg.dll",
        f"{SITE}/PySide6/Qt6Network.dll", f"{SITE}/PySide6/pyside6.abi3.dll",
        f"{SITE}/PySide6/plugins/platforms/qwindows.dll",
        f"{SITE}/PySide6/plugins/platforms/qoffscreen.dll",
        f"{SITE}/PySide6/plugins/imageformats/qjpeg.dll",
        f"{SITE}/PySide6/plugins/iconengines/qsvgicon.dll",
        f"{SITE}/cv2/cv2.pyd", f"{SITE}/numpy/_core/_multiarray_umath.pyd",
        "python/_ctypes.pyd", "python/libffi-8.dll",
        "tesseract/libtesseract-5.dll", "tesseract/libleptonica-6.dll",
        "tesseract/libarchive-13.dll", "tesseract/libcrypto-3-x64.dll")
GONE = (f"{SITE}/PySide6/opengl32sw.dll", f"{SITE}/PySide6/Qt6Quick.dll",
        f"{SITE}/PySide6/Qt6QmlCore.dll", f"{SITE}/PySide6/QtOpenGL.pyd",
        f"{SITE}/PySide6/designer.exe", f"{SITE}/PySide6/plugins/sqldrivers/qsqlite.dll",
        f"{SITE}/cv2/opencv_videoio_ffmpeg500_64.dll",
        "tesseract/libicudt75.dll", "tesseract/libcairo-2.dll", "tesseract/libffi-8.dll")


def _fake_app(tmp_path, leptonica_imports=("libarchive-13.dll",)):
    app = tmp_path / "app"
    for rel in KEPT + GONE:
        (app / rel).parent.mkdir(parents=True, exist_ok=True)
        imports = leptonica_imports if rel.endswith("libleptonica-6.dll") else ()
        if rel == "python/_ctypes.pyd":
            imports = ("libffi-8.dll",)          # its own python\ copy, not tesseract's
        make_pe(app / rel, imports=imports)
    make_pe(app / "tesseract/tesseract.exe", imports=("libtesseract-5.dll",), debug=2,
            cert=b"\x02" * 32)
    for rel in (f"{SITE}/PySide6/qml/QtQuick/qmldir", f"{SITE}/PySide6/translations/qt_de.qm",
                f"{SITE}/numpy/_core/tests/test_a.py", "tesseract/tessdata/afr.traineddata",
                f"{SITE}/numpy/testing/__init__.py"):
        (app / rel).parent.mkdir(parents=True, exist_ok=True)
        (app / rel).write_bytes(b"x")
    return app


def test_prune_removes_the_list_and_keeps_what_the_app_loads(tmp_path):
    app = _fake_app(tmp_path)
    said = []
    assert prune.prune(app, say=said.append) > 0
    for rel in KEPT + ("tesseract/tesseract.exe", "tesseract/tessdata/afr.traineddata",
                       f"{SITE}/numpy/testing/__init__.py"):
        assert (app / rel).exists(), rel
    for rel in GONE + (f"{SITE}/PySide6/qml", f"{SITE}/PySide6/translations",
                       f"{SITE}/numpy/_core/tests"):
        assert not (app / rel).exists(), rel
    assert len(prune._headers((app / "tesseract/tesseract.exe").read_bytes())["sections"]) == 2
    assert any("debug sections off tesseract.exe" in line for line in said)


def test_prune_fails_when_a_kept_binary_imports_a_removed_one(tmp_path):
    app = _fake_app(tmp_path, leptonica_imports=("libarchive-13.dll", "libcairo-2.dll"))
    with pytest.raises(RuntimeError, match="libleptonica-6.dll imports libcairo-2.dll"):
        prune.prune(app, say=lambda _line: None)


def test_a_twin_in_another_process_folder_does_not_count(tmp_path):
    # libffi-8.dll is pruned from tesseract\ but python\ keeps its own copy:
    # python\_ctypes.pyd is fine (the fake app has it), a tesseract binary is not.
    app = _fake_app(tmp_path, leptonica_imports=("libarchive-13.dll", "libffi-8.dll"))
    with pytest.raises(RuntimeError) as err:
        prune.prune(app, say=lambda _line: None)
    assert "tesseract/libleptonica-6.dll imports libffi-8.dll" in str(err.value)
    assert "_ctypes" not in str(err.value)


def test_python_binaries_find_dlls_in_the_added_dll_folders(tmp_path):
    # A plugin under PySide6\plugins importing a DLL that only numpy.libs holds
    # resolves (os.add_dll_directory), even though its own folder lacks it.
    app = tmp_path / "app"
    plugin = make_pe(_mk(app / f"{SITE}/PySide6/plugins/styles/qmodernwindowsstyle.dll"),
                     imports=("libscipy_openblas.dll",))
    make_pe(_mk(app / f"{SITE}/numpy.libs/libscipy_openblas.dll"))
    assert prune._missing(app, {"libscipy_openblas.dll"}) == []
    (app / f"{SITE}/numpy.libs/libscipy_openblas.dll").unlink()
    assert prune._missing(app, {"libscipy_openblas.dll"}) == [
        f"{plugin.relative_to(app).as_posix()} imports libscipy_openblas.dll"]


def _mk(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def test_every_prune_line_says_why_and_what_it_saves():
    for pattern, why, mb in prune.PRUNE:
        assert pattern.startswith((f"{SITE}/", "tesseract/")), pattern
        assert len(why) > 10 and mb > 0, pattern
        assert "QtCore" not in pattern and "QtWidgets" not in pattern and "afr" not in pattern


def test_both_builds_prune_before_the_selftest():
    ps1 = (ROOT / "installer/build.ps1").read_text(encoding="utf-8")
    assert ps1.index('"prune.py"') < ps1.index('"--selftest"')
    sh = (ROOT / "installer/build-linux.sh").read_text(encoding="utf-8")
    assert sh.index('prune.py" "$A"') < sh.index("--selftest")
    musts = sh[sh.index("for must in"):sh.index("; do", sh.index("for must in"))]
    assert '"ok    tesseract reads"' in musts      # the check that runs the cut library


class _Done:
    def __init__(self, out):
        self.stdout = out


def test_the_selftest_reads_a_line_with_tesseract():
    assert ("tesseract reads", selftest._tesseract_reads) in selftest.CHECKS
    seen = {}

    def run(cmd, **kw):
        seen.update(cmd=cmd, png=kw["input"][:8])
        return _Done(b"Hivemind 2468\r\n")
    assert selftest._tesseract_reads(run) == "read 'Hivemind 2468'"
    assert seen["cmd"][-4:] == ["-l", "afr", "--psm", "7"] and seen["png"] == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(RuntimeError, match="expected 'Hivemind 2468'"):
        selftest._tesseract_reads(lambda cmd, **kw: _Done(b"Hivernind 2A68\n"))
