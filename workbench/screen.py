"""A picture of the screen, for a model to look at. Windows only.

View only: nothing here clicks, types, moves the pointer or changes a window.
The picture is of the primary screen as it is at that moment, made smaller so
that its longest side is at most ``MAX_EDGE`` pixels, and returned as PNG bytes.
It is not written to a file.
"""
import os
import struct
import zlib

MAX_EDGE = 1568  # the longest side of the picture a model is given
MEDIA_TYPE = 'image/png'


class ScreenError(ValueError):
    """The screen could not be pictured."""


def scaled(width: int, height: int, max_edge: int = MAX_EDGE) -> tuple[int, int]:
    """The size of the picture for a screen of this size: the same shape, the longest side within ``max_edge``."""
    longest = max(width, height)
    if longest <= max_edge:
        return width, height
    return max(1, round(width * max_edge / longest)), max(1, round(height * max_edge / longest))


def png_from_bgra(pixels: bytes, width: int, height: int) -> bytes:
    """An RGB PNG from top-down rows of 32-bit BGRA pixels (what GetDIBits gives)."""
    if width <= 0 or height <= 0 or len(pixels) != width * height * 4:
        raise ScreenError('The picture of the screen has an unexpected size')
    rgb = bytearray(width * height * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = pixels[2::4], pixels[1::4], pixels[0::4]
    stride, rows = width * 3, bytearray()
    for top in range(0, len(rgb), stride):
        rows.append(0)  # filter type "none" for this row
        rows += rgb[top:top + stride]

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)

    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(rows), 6)) + chunk(b'IEND', b''))


def available() -> bool:
    return os.name == 'nt'


def capture(max_edge: int = MAX_EDGE) -> dict:
    """Picture the primary screen now: {png, width, height, screen_width, screen_height}."""
    if not available():
        raise ScreenError('The screen can be looked at on Windows only')
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG),
                    ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                    ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG),
                    ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD)]

    # Handles are pointer-sized: without these declarations ctypes would cut them to 32 bits.
    user32.GetDC.restype, user32.GetDC.argtypes = wintypes.HDC, [wintypes.HWND]
    user32.ReleaseDC.restype, user32.ReleaseDC.argtypes = ctypes.c_int, [wintypes.HWND, wintypes.HDC]
    user32.GetSystemMetrics.restype, user32.GetSystemMetrics.argtypes = ctypes.c_int, [ctypes.c_int]
    gdi32.CreateCompatibleDC.restype, gdi32.CreateCompatibleDC.argtypes = wintypes.HDC, [wintypes.HDC]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype, gdi32.SelectObject.argtypes = wintypes.HGDIOBJ, [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SetStretchBltMode.restype, gdi32.SetStretchBltMode.argtypes = ctypes.c_int, [wintypes.HDC, ctypes.c_int]
    gdi32.SetBrushOrgEx.restype = wintypes.BOOL
    gdi32.SetBrushOrgEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    gdi32.StretchBlt.restype = wintypes.BOOL
    gdi32.StretchBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                 wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                ctypes.c_void_p, wintypes.UINT]
    gdi32.DeleteObject.restype, gdi32.DeleteObject.argtypes = wintypes.BOOL, [wintypes.HGDIOBJ]
    gdi32.DeleteDC.restype, gdi32.DeleteDC.argtypes = wintypes.BOOL, [wintypes.HDC]

    # The real pixels of the screen, not the enlarged ones a program unaware of display scaling is shown.
    # Set for this thread only and put back afterwards; older Windows without the call still gives a picture.
    previous = None
    try:
        user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        previous = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # per monitor, version 2
    except AttributeError:
        pass
    screen = memory = bitmap = old = None
    try:
        screen_width, screen_height = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)  # the primary screen
        if screen_width <= 0 or screen_height <= 0:
            raise ScreenError('There is no screen to look at in this session')
        width, height = scaled(screen_width, screen_height, max_edge)
        screen = user32.GetDC(None)
        if not screen:
            raise ScreenError('The screen is not available to this program')
        memory = gdi32.CreateCompatibleDC(screen)
        bitmap = gdi32.CreateCompatibleBitmap(screen, width, height)
        if not memory or not bitmap:
            raise ScreenError('The picture of the screen could not be prepared')
        old = gdi32.SelectObject(memory, bitmap)
        gdi32.SetStretchBltMode(memory, 4)  # HALFTONE: averaged, so small text stays readable
        gdi32.SetBrushOrgEx(memory, 0, 0, None)
        if not gdi32.StretchBlt(memory, 0, 0, width, height, screen, 0, 0, screen_width, screen_height,
                                0x00CC0020 | 0x40000000):  # SRCCOPY | CAPTUREBLT (layered windows too)
            raise ScreenError('The screen could not be copied (it may be locked or belong to another session)')
        header = BITMAPINFOHEADER()
        header.biSize, header.biWidth, header.biHeight = ctypes.sizeof(BITMAPINFOHEADER), width, -height  # top-down
        header.biPlanes, header.biBitCount, header.biCompression = 1, 32, 0
        pixels = ctypes.create_string_buffer(width * height * 4)
        gdi32.SelectObject(memory, old)  # a bitmap must not be selected into a context while its bits are read
        old = None
        if gdi32.GetDIBits(screen, bitmap, 0, height, pixels, ctypes.byref(header), 0) != height:
            raise ScreenError('The picture of the screen could not be read')
        return {'png': png_from_bgra(pixels.raw, width, height), 'width': width, 'height': height,
                'screen_width': screen_width, 'screen_height': screen_height}
    finally:
        if old:
            gdi32.SelectObject(memory, old)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory:
            gdi32.DeleteDC(memory)
        if screen:
            user32.ReleaseDC(None, screen)
        if previous:
            user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(previous))
