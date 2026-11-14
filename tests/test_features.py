"""Hardware-free checks for Bluetooth, Now Playing, and reconnect logic."""

from __future__ import annotations

import asyncio
import pathlib
import sys
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from seblue.media_session import (  # noqa: E402
    friendly_app_name, resolve_artwork, select_session, timeline_values,
    valid_media_text,
)
from seblue.radio import _read_bluetooth_state, _set_bluetooth_state  # noqa: E402
from seblue.routing import listener_targets  # noqa: E402


class RadioKind(Enum):
    BLUETOOTH = 1
    WIFI = 2


class RadioState(Enum):
    ON = 1
    OFF = 2


class RadioAccessStatus(Enum):
    ALLOWED = 1
    DENIED_BY_SYSTEM = 2


class FakeRadio:
    def __init__(self, state=RadioState.OFF, kind=RadioKind.BLUETOOTH,
                 transition_delay=0.0):
        self._state = state
        self.kind = kind
        self.transition_delay = transition_delay
        self._target = None
        self._transition_at = 0.0

    @property
    def state(self):
        if self._target is not None and time.monotonic() >= self._transition_at:
            self._state = self._target
            self._target = None
        return self._state

    async def set_state_async(self, state):
        self._target = state
        self._transition_at = time.monotonic() + self.transition_delay
        return RadioAccessStatus.ALLOWED


class FakeRadioApi:
    radios = []
    access = RadioAccessStatus.ALLOWED

    @classmethod
    async def get_radios_async(cls):
        return cls.radios

    @classmethod
    async def request_access_async(cls):
        return cls.access


def install_fake_radio_winrt():
    names = (
        "winrt", "winrt.windows", "winrt.windows.devices",
        "winrt.windows.devices.radios",
    )
    modules = {name: types.ModuleType(name) for name in names}
    modules["winrt.windows.devices.radios"].Radio = FakeRadioApi
    modules["winrt.windows.devices.radios"].RadioKind = RadioKind
    modules["winrt.windows.devices.radios"].RadioState = RadioState
    modules["winrt.windows.devices.radios"].RadioAccessStatus = RadioAccessStatus
    return patch.dict(sys.modules, modules)


class BluetoothRadioTests(unittest.TestCase):
    def setUp(self):
        FakeRadioApi.radios = []
        FakeRadioApi.access = RadioAccessStatus.ALLOWED
        self.fake_winrt = install_fake_radio_winrt()
        self.fake_winrt.__enter__()

    def tearDown(self):
        self.fake_winrt.__exit__(None, None, None)

    def test_reads_on_and_off_states(self):
        radio = FakeRadio(RadioState.ON)
        FakeRadioApi.radios = [radio]
        self.assertEqual(asyncio.run(_read_bluetooth_state()),
                         {"available": True, "enabled": True})
        radio._state = RadioState.OFF
        self.assertEqual(asyncio.run(_read_bluetooth_state()),
                         {"available": True, "enabled": False})

    def test_no_radio_reports_unavailable(self):
        result = asyncio.run(_read_bluetooth_state())
        self.assertEqual(result, {"available": False, "enabled": None})

    def test_denied_access_does_not_change_state(self):
        radio = FakeRadio(RadioState.OFF)
        FakeRadioApi.radios = [radio]
        FakeRadioApi.access = RadioAccessStatus.DENIED_BY_SYSTEM
        result = asyncio.run(_set_bluetooth_state(True))
        self.assertFalse(result["enabled"])
        self.assertIn("denied permission", result["error"])
        self.assertEqual(radio.state, RadioState.OFF)

    def test_waits_for_delayed_windows_state_change(self):
        radio = FakeRadio(RadioState.OFF, transition_delay=0.25)
        FakeRadioApi.radios = [radio]
        result = asyncio.run(_set_bluetooth_state(True))
        self.assertTrue(result["available"])
        self.assertTrue(result["enabled"])
        self.assertNotIn("error", result)


class NowPlayingTests(unittest.TestCase):
    def test_friendly_app_names_and_unknown_apps(self):
        self.assertEqual(
            friendly_app_name("Microsoft.ZuneMusic!Microsoft.ZuneMusic"),
            "Media Player")
        self.assertEqual(friendly_app_name("brave.exe"), "Brave")
        self.assertEqual(friendly_app_name("SamplePlayer"), "SamplePlayer")

    def test_unknown_and_empty_track_text_is_removed(self):
        self.assertEqual(valid_media_text("  Unknown Artist "), "")
        self.assertEqual(valid_media_text("0000"), "")
        self.assertEqual(valid_media_text("  Song title  "), "Song title")
        self.assertEqual(valid_media_text(None), "")

    def test_missing_artwork_selects_the_bundled_cover(self):
        fallback = pathlib.Path("assets/cover-art.png")
        self.assertEqual(resolve_artwork(None, fallback), ("fallback", fallback))
        self.assertEqual(resolve_artwork(b"image-bytes", fallback),
                         ("session", b"image-bytes"))

    def test_playing_time_advances_using_windows_update_time(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        timeline = SimpleNamespace(
            position=timedelta(seconds=20),
            end_time=timedelta(seconds=90),
            last_updated_time=now - timedelta(seconds=10),
        )
        self.assertEqual(timeline_values(timeline, True, 1.5, now), (35.0, 90.0))

    def test_paused_time_does_not_advance_and_position_is_bounded(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        timeline = SimpleNamespace(
            position=timedelta(seconds=100),
            end_time=timedelta(seconds=90),
            last_updated_time=now - timedelta(seconds=10),
        )
        self.assertEqual(timeline_values(timeline, False, 1.0, now), (90.0, 90.0))

    def test_prefers_playing_session_then_falls_back_to_current(self):
        playing_status = "playing"
        current = SimpleNamespace(get_playback_info=lambda: SimpleNamespace(
            playback_status="paused"))
        playing = SimpleNamespace(get_playback_info=lambda: SimpleNamespace(
            playback_status=playing_status))
        self.assertIs(select_session([current, playing], current, playing_status), playing)
        self.assertIs(select_session([current], current, playing_status), current)
        self.assertIsNone(select_session([], None, playing_status))


class RememberedDeviceTests(unittest.TestCase):
    def test_disconnected_selection_is_skipped_but_retained_for_reconnect(self):
        selected = {"headphones"}
        source = SimpleNamespace(id="speakers", name="Speakers")
        self.assertEqual(listener_targets(selected, [source], source.id), [])
        self.assertEqual(selected, {"headphones"})

        headphones = SimpleNamespace(id="headphones", name="Headphones")
        self.assertEqual(
            listener_targets(selected, [source, headphones], source.id),
            [("headphones", "Headphones")])

    def test_source_is_never_added_as_a_listener(self):
        selected = {"speakers", "headphones"}
        devices = [SimpleNamespace(id="speakers", name="Speakers"),
                   SimpleNamespace(id="headphones", name="Headphones")]
        self.assertEqual(listener_targets(selected, devices, "speakers"),
                         [("headphones", "Headphones")])


class PassFailResult(unittest.TextTestResult):
    @staticmethod
    def _label(test):
        return test._testMethodName.removeprefix("test_").replace("_", " ").capitalize()

    def addSuccess(self, test):
        super().addSuccess(test)
        self.stream.writeln("  %-48s PASS" % self._label(test))

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.stream.writeln("  %-48s FAIL %s" % (self._label(test), err[1]))

    def addError(self, test, err):
        super().addError(test, err)
        self.stream.writeln("  %-48s ERROR %s" % (self._label(test), err[1]))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(
        stream=sys.stdout, verbosity=0, resultclass=PassFailResult)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("\nALL PASS", flush=True)
    else:
        print("\nFAILURES: %d" % (len(result.failures) + len(result.errors)),
              flush=True)
    sys.exit(not result.wasSuccessful())
