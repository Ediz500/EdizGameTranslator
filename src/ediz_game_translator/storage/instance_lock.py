"""Windows process locks: one app instance per user session, one writer per profile."""
import msvcrt

APP_MUTEX_NAME = 'Local\\EdizGameTranslator.SingleInstance'
ERROR_ALREADY_EXISTS = 183


class AppInstanceMutex:
    """Named Win32 mutex shared by every EXE/profile of this app (not per profile folder)."""
    def __init__(self, name=APP_MUTEX_NAME):
        import ctypes
        from ctypes import wintypes
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateMutexW(None, False, name)
        error = ctypes.get_last_error()
        if not self.handle:
            raise OSError(error, 'Uygulama kilidi oluşturulamadı.')
        if error == ERROR_ALREADY_EXISTS:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
            raise OSError(ERROR_ALREADY_EXISTS, 'Ediz Game Translator zaten açık.')

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class InstanceLock:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open('a+b')
        if self.stream.tell() == 0:
            self.stream.write(b'0')
            self.stream.flush()
        self.stream.seek(0)
        try:
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.stream.close()
            raise

    def close(self):
        self.stream.seek(0)
        msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        self.stream.close()
