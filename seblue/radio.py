"""Control and monitor the Windows Bluetooth radio off the UI thread."""

from __future__ import annotations

import asyncio
import queue
import threading
import time


async def _read_bluetooth_state() -> dict:
    from winrt.windows.devices.radios import Radio, RadioKind, RadioState

    radios = [radio for radio in await Radio.get_radios_async()
              if radio.kind == RadioKind.BLUETOOTH]
    if not radios:
        return {"available": False, "enabled": None}
    return {"available": True,
            "enabled": all(radio.state == RadioState.ON for radio in radios)}


async def _set_bluetooth_state(enabled: bool) -> dict:
    from winrt.windows.devices.radios import (
        Radio, RadioAccessStatus, RadioKind, RadioState,
    )

    radios = [radio for radio in await Radio.get_radios_async()
              if radio.kind == RadioKind.BLUETOOTH]
    if not radios:
        return {"available": False, "enabled": None,
                "error": "No Bluetooth radio was found."}

    access = await Radio.request_access_async()
    if access != RadioAccessStatus.ALLOWED:
        return {"available": True,
                "enabled": all(radio.state == RadioState.ON for radio in radios),
                "error": "Windows denied permission to change Bluetooth."}

    target = RadioState.ON if enabled else RadioState.OFF
    results = [await radio.set_state_async(target) for radio in radios]
    if any(result != RadioAccessStatus.ALLOWED for result in results):
        return {"available": True,
                "enabled": all(radio.state == RadioState.ON for radio in radios),
                "error": "Windows could not change the Bluetooth radio state."}

    # SetStateAsync queues the change; wait briefly for Windows to report it.
    deadline = time.monotonic() + 8.0
    state = await _read_bluetooth_state()
    while state["enabled"] != enabled and time.monotonic() < deadline:
        await asyncio.sleep(0.2)
        state = await _read_bluetooth_state()
    if state["enabled"] != enabled:
        state["error"] = "Bluetooth state did not change. Check Windows settings or hardware controls."
    return state


class BluetoothRadioController:
    """Poll radio state and serialize toggle requests on a worker thread."""

    def __init__(self) -> None:
        self.results: queue.Queue[dict] = queue.Queue()
        self._requests: queue.Queue[bool] = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="SeBlueBluetoothRadio")

    def start(self) -> None:
        self._thread.start()

    def set_enabled(self, enabled: bool) -> None:
        # Keep only the latest requested target so rapid clicks cannot queue
        # conflicting radio transitions.
        while True:
            try:
                self._requests.get_nowait()
            except queue.Empty:
                break
        self._requests.put(bool(enabled))

    def _run(self) -> None:
        next_poll = 0.0
        while not self._stop.is_set():
            timeout = max(0.0, min(0.5, next_poll - time.monotonic()))
            try:
                target = self._requests.get(timeout=timeout)
            except queue.Empty:
                target = None

            if target is not None:
                try:
                    result = asyncio.run(_set_bluetooth_state(target))
                except Exception as exc:
                    result = {"available": False, "enabled": None,
                              "error": str(exc) or "Bluetooth control is unavailable."}
                result["request"] = True
                self.results.put(result)
                next_poll = time.monotonic() + 0.5

            if time.monotonic() >= next_poll:
                try:
                    result = asyncio.run(_read_bluetooth_state())
                except Exception as exc:
                    result = {"available": False, "enabled": None,
                              "error": str(exc) or "Bluetooth control is unavailable."}
                result["request"] = False
                self.results.put(result)
                next_poll = time.monotonic() + 2.0

    def stop(self) -> None:
        self._stop.set()
