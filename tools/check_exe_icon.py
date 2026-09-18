# -*- coding: utf-8 -*-
"""
检查 exe 里嵌入的图标资源（尺寸清单），用于确认 PyInstaller 是否写入了多尺寸图标。

用法：.venv\\Scripts\\python.exe tools\\check_exe_icon.py [exe路径]
"""
import ctypes
import os
import struct
import sys

RT_ICON = 3
RT_GROUP_ICON = 14
LOAD_LIBRARY_AS_DATAFILE = 0x00000002

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p)

# 必须显式声明参数/返回类型，否则 64 位下句柄会被截断成 32 位而失效
kernel32.LoadLibraryExW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_ulong]
kernel32.LoadLibraryExW.restype = ctypes.c_void_p
kernel32.EnumResourceNamesW.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                        ENUMPROC, ctypes.c_void_p]
kernel32.EnumResourceNamesW.restype = ctypes.c_bool
kernel32.FindResourceW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
kernel32.FindResourceW.restype = ctypes.c_void_p
kernel32.SizeofResource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
kernel32.SizeofResource.restype = ctypes.c_ulong
kernel32.LoadResource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
kernel32.LoadResource.restype = ctypes.c_void_p
kernel32.LockResource.argtypes = [ctypes.c_void_p]
kernel32.LockResource.restype = ctypes.c_void_p
kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
kernel32.FreeLibrary.restype = ctypes.c_bool


def _load_res(h, name, typ):
    res = kernel32.FindResourceW(h, name, typ)
    if not res:
        return None
    size = kernel32.SizeofResource(h, res)
    data = kernel32.LoadResource(h, res)
    ptr = kernel32.LockResource(data)
    if not ptr:
        return None
    return ctypes.string_at(ptr, size)


def inspect(path):
    h = kernel32.LoadLibraryExW(path, None, LOAD_LIBRARY_AS_DATAFILE)
    if not h:
        raise OSError("LoadLibraryExW 失败，错误码 %s" % ctypes.get_last_error())

    groups = []

    def cb(hmod, typ, name, param):
        groups.append(name)
        return True

    kernel32.EnumResourceNamesW(h, RT_GROUP_ICON, ENUMPROC(cb), None)

    print("图标组数量: %d" % len(groups))
    for nm in list(groups):
        data = _load_res(h, nm, RT_GROUP_ICON)
        if not data or len(data) < 6:
            continue
        reserved, ictype, count = struct.unpack_from("<HHH", data, 0)
        sizes = []
        off = 6
        for _ in range(count):
            w, hh = data[off], data[off + 1]
            bpp = struct.unpack_from("<H", data, off + 6)[0]
            sizes.append((w or 256, hh or 256, bpp))
            off += 14
        print("  组 id=%s  类型=%d  条目=%d" % (nm, ictype, count))
        for w, hh, bpp in sizes:
            print("     %3dx%-3d  %d位" % (w, hh, bpp))

    kernel32.FreeLibrary(h)
    return groups


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "dist", "江门金量化", "江门金量化.exe")
    print("检查文件: %s" % target)
    print("=" * 50)
    inspect(target)
