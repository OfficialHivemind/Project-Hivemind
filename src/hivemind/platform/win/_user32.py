"""The Win32 calls win/input, win/capture, win/gameguard and win/panic share,
through ctypes: no dependency. Nothing is loaded at import, so this module
imports on Linux and the tests hand the users a fake `user32`.

Every behaviour relied on is tagged [verified] (a Microsoft doc, linked in
docs/pending/windows-port.md section 7) or [assumed].
"""
from __future__ import annotations

import ctypes

# Fixed-width types, not c_ulong: DWORD is 32-bit on Windows but c_ulong is
# 64-bit on Linux, and the tests check the struct layout there.
DWORD, WORD, LONG = ctypes.c_uint32, ctypes.c_uint16, ctypes.c_int32
ULONG_PTR = ctypes.c_size_t
HWND = ctypes.c_void_p


class POINT(ctypes.Structure):
    _fields_ = [("x", LONG), ("y", LONG)]


class RECT(ctypes.Structure):
    _fields_ = [("left", LONG), ("top", LONG), ("right", LONG), ("bottom", LONG)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", DWORD), ("rcMonitor", RECT), ("rcWork", RECT),
                ("dwFlags", DWORD)]


# SendInput's INPUT [verified: winuser.h INPUT / MOUSEINPUT / KEYBDINPUT].
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", LONG), ("dy", LONG), ("mouseData", DWORD),
                ("dwFlags", DWORD), ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", WORD), ("wScan", WORD), ("dwFlags", DWORD),
                ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", DWORD), ("wParamL", WORD), ("wParamH", WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", DWORD), ("u", _INPUTUNION)]


INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
# GetSystemMetrics: the virtual screen spans every monitor [verified].
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79
MONITOR_DEFAULTTONEAREST = 2
DWMWA_EXTENDED_FRAME_BOUNDS = 9          # [verified: DWMWINDOWATTRIBUTE, NCRENDERING_ENABLED = 1]
# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 is ((DPI_AWARENESS_CONTEXT)-4) [verified].
PER_MONITOR_AWARE_V2 = -4

_SIGNATURES = {
    "user32": {
        "SendInput": (ctypes.c_uint, [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]),
        "GetForegroundWindow": (HWND, []),
        "SetForegroundWindow": (ctypes.c_int, [HWND]),
        "ClientToScreen": (ctypes.c_int, [HWND, ctypes.POINTER(POINT)]),
        "GetClientRect": (ctypes.c_int, [HWND, ctypes.POINTER(RECT)]),
        "GetWindowRect": (ctypes.c_int, [HWND, ctypes.POINTER(RECT)]),
        "GetSystemMetrics": (ctypes.c_int, [ctypes.c_int]),
        "GetAsyncKeyState": (ctypes.c_short, [ctypes.c_int]),
        "GetWindowTextW": (ctypes.c_int, [HWND, ctypes.c_wchar_p, ctypes.c_int]),
        "GetWindowThreadProcessId": (DWORD, [HWND, ctypes.POINTER(DWORD)]),
        "MonitorFromWindow": (ctypes.c_void_p, [HWND, DWORD]),
        "GetMonitorInfoW": (ctypes.c_int, [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]),
        "SetProcessDpiAwarenessContext": (ctypes.c_int, [ctypes.c_void_p]),
        # win/session [verified: each one's winuser.h signature]
        "EnumWindows": (ctypes.c_int, [ctypes.c_void_p, ctypes.c_void_p]),
        "IsWindow": (ctypes.c_int, [HWND]),
        "IsWindowVisible": (ctypes.c_int, [HWND]),
        "IsIconic": (ctypes.c_int, [HWND]),
        "ShowWindow": (ctypes.c_int, [HWND, ctypes.c_int]),
        "SetWindowPos": (ctypes.c_int, [HWND, HWND, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_uint]),
        "GetWindowLongW": (LONG, [HWND, ctypes.c_int]),
        "SetWindowLongW": (LONG, [HWND, ctypes.c_int, LONG]),
    },
    "dwmapi": {
        "DwmGetWindowAttribute": (ctypes.c_long, [HWND, DWORD, ctypes.c_void_p, DWORD]),
    },
}
_loaded: dict = {}


def dll(name: str):
    """user32 or dwmapi, loaded once with its signatures declared. OSError off
    Windows, so a caller can say why instead of crashing on an AttributeError."""
    if name not in _loaded:
        loader = getattr(ctypes, "WinDLL", None)
        if loader is None:
            raise OSError(f"{name}.dll: not Windows")
        lib = loader(name, use_last_error=True)
        for fn, (restype, argtypes) in _SIGNATURES[name].items():
            proc = getattr(lib, fn, None)
            if proc is not None:                 # SetProcessDpiAwarenessContext: 1703+
                proc.restype, proc.argtypes = restype, argtypes
        _loaded[name] = lib
    return _loaded[name]


def dpi_aware(user32) -> bool:
    """Per-monitor v2 DPI awareness, so window rectangles, ClientToScreen and
    the captured pixels are all physical pixels. FALSE when it was already set
    (ERROR_ACCESS_DENIED [verified]) or the call is missing (before Windows 10
    1703): harmless either way, the first caller wins."""
    try:
        return bool(user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(PER_MONITOR_AWARE_V2)))
    except (AttributeError, OSError):
        return False


# EnumWindows' callback: BOOL CALLBACK(HWND, LPARAM), stdcall on Windows.
# CFUNCTYPE stands in off Windows so the tests can call it (no WINFUNCTYPE there).
_ENUMPROC = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(ctypes.c_int, HWND, ctypes.c_void_p)


def top_windows(user32) -> list[int]:
    """Every top-level window, in z-order (EnumWindows [verified])."""
    found: list[int] = []

    def each(hwnd, _):
        if hwnd:
            found.append(int(hwnd))
        return 1
    user32.EnumWindows(_ENUMPROC(each), None)
    return found


def monitor_rect(user32, hwnd) -> tuple[int, int, int, int] | None:
    """x, y, w, h of the monitor the window is on, or None."""
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    m = info.rcMonitor
    return m.left, m.top, m.right - m.left, m.bottom - m.top


def window_rect(user32, hwnd) -> tuple[int, int, int, int] | None:
    rc = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rc)):
        return None
    return rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top


def foreground(user32) -> int | None:
    return user32.GetForegroundWindow() or None


def window_title(user32, hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    try:
        user32.GetWindowTextW(hwnd, buf, 256)
    except OSError:
        return ""
    return buf.value


def window_pid(user32, hwnd) -> int | None:
    pid = DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value or None


def client_origin(user32, hwnd) -> tuple[int, int]:
    """The client area's top-left in screen pixels."""
    pt = POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        raise OSError("ClientToScreen failed: the window is gone")
    return pt.x, pt.y


def client_size(user32, hwnd) -> tuple[int, int]:
    rc = RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rc)):
        raise OSError("GetClientRect failed: the window is gone")
    return rc.right - rc.left, rc.bottom - rc.top


def virtual_screen(user32) -> tuple[int, int, int, int]:
    """x, y, w, h of the rectangle spanning every monitor."""
    return tuple(user32.GetSystemMetrics(i) for i in (
        SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN))


def fills_its_monitor(user32, hwnd) -> bool:
    """The window covers the whole monitor it is on: what a fullscreen game
    (exclusive or borderless) looks like from outside."""
    rc, info = RECT(), MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetWindowRect(hwnd, ctypes.byref(rc)):
        return False
    monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return False
    m = info.rcMonitor
    return (rc.left <= m.left and rc.top <= m.top
            and rc.right >= m.right and rc.bottom >= m.bottom)
