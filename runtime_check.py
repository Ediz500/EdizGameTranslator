"""Validate Windows wheel and Tk compatibility."""
import platform
import struct
import sys
import sysconfig


def supported():
    return (sys.platform == 'win32' and sys.version_info[:2] == (3, 12)
            and platform.python_implementation() == 'CPython'
            and struct.calcsize('P') == 8
            and sysconfig.get_platform() == 'win-amd64')


if __name__ == '__main__':
    if not supported():
        print('Gerekli: resmi Windows CPython 3.12 x64; MSYS2/ARM/32-bit desteklenmez.')
        sys.exit(1)
    import tkinter
    print('CPython 3.12 x64 + Tk OK')
