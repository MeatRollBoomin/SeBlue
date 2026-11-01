"""Keep one SeBlue process per Windows session and signal it to show its window."""

from __future__ import annotations

import ctypes
from ctypes import wintypes


_MUTEX_NAME = r"Local\SeBlue.SingleInstance.Mutex"
_EVENT_NAME = r"Local\SeBlue.SingleInstance.Activate"
_ERROR_ALREADY_EXISTS = 183
_EVENT_MODIFY_STATE = 0x0002
_WAIT_OBJECT_0 = 0


class SingleInstanceGuard:
    """Own the app mutex or signal the existing process to restore its window."""

    def __init__(self) -> None:
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateEventW.argtypes = (
            wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
        self._kernel32.CreateEventW.restype = wintypes.HANDLE
        self._kernel32.CreateMutexW.argtypes = (
            wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        self._kernel32.CreateMutexW.restype = wintypes.HANDLE
        self._kernel32.SetEvent.argtypes = (wintypes.HANDLE,)
        self._kernel32.SetEvent.restype = wintypes.BOOL
        self._kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        self._kernel32.WaitForSingleObject.restype = wintypes.DWORD
        self._kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
        self._kernel32.ReleaseMutex.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._mutex = None
        self._event = None
        self._owns_mutex = False

    def acquire_or_signal(self) -> bool:
        """Return True for the primary process; signal and return False otherwise."""
        event = self._kernel32.CreateEventW(None, False, False, _EVENT_NAME)
        if not event:
            raise ctypes.WinError(ctypes.get_last_error())

        ctypes.set_last_error(0)
        mutex = self._kernel32.CreateMutexW(None, True, _MUTEX_NAME)
        if not mutex:
            error = ctypes.get_last_error()
            self._kernel32.CloseHandle(event)
            raise ctypes.WinError(error)

        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            self._kernel32.SetEvent(event)
            self._kernel32.CloseHandle(mutex)
            self._kernel32.CloseHandle(event)
            return False

        self._event = event
        self._mutex = mutex
        self._owns_mutex = True
        return True

    def consume_activation_request(self) -> bool:
        if not self._event:
            return False
        return self._kernel32.WaitForSingleObject(self._event, 0) == _WAIT_OBJECT_0

    def close(self) -> None:
        if self._event:
            self._kernel32.CloseHandle(self._event)
            self._event = None
        if self._mutex:
            if self._owns_mutex:
                self._kernel32.ReleaseMutex(self._mutex)
                self._owns_mutex = False
            self._kernel32.CloseHandle(self._mutex)
            self._mutex = None
