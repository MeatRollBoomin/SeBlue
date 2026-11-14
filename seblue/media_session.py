"""Read the current Windows media session without blocking the UI thread."""

from __future__ import annotations

import asyncio
import queue
import threading
from datetime import datetime, timezone


_FRIENDLY_APP_NAMES = {
    "microsoft.zunemusic": "Media Player",
    "microsoft.zunevideo": "Movies & TV",
    "spotifyab.spotifymusic": "Spotify",
    "spotify": "Spotify",
    "chrome": "Google Chrome",
    "msedge": "Microsoft Edge",
    "brave": "Brave",
    "vlc": "VLC media player",
    "firefox": "Mozilla Firefox",
    "opera": "Opera",
    "obs64": "OBS Studio",
}


def friendly_app_name(source_app_user_model_id: str) -> str:
    name = str(source_app_user_model_id or "").rsplit("!", 1)[-1]
    if name.casefold().endswith(".exe"):
        name = name[:-4]
    return _FRIENDLY_APP_NAMES.get(name.casefold(), name)


def valid_media_text(value) -> str:
    value = str(value or "").strip()
    if value.casefold() in {"unknown", "unknown artist", "<unknown>", "n/a"}:
        return ""
    if value.isdecimal():
        return ""
    return value


def resolve_artwork(artwork: bytes | None, fallback):
    """Select session artwork when present, otherwise the bundled fallback."""
    return ("session", artwork) if artwork else ("fallback", fallback)


def timeline_values(timeline, playing: bool, playback_rate: float = 1.0,
                    now: datetime | None = None) -> tuple[float, float]:
    """Return elapsed position and duration, accounting for Windows' update time."""
    duration = max(0.0, timeline.end_time.total_seconds())
    position = max(0.0, timeline.position.total_seconds())
    updated_at = timeline.last_updated_time
    if playing and updated_at:
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        now = now or datetime.now(timezone.utc)
        age = max(0.0, (now - updated_at).total_seconds())
        position += age * float(playback_rate or 1.0)
    return min(position, duration) if duration else position, duration


def select_session(sessions, current, playing_status):
    """Prefer an actively playing session, otherwise return Windows' current one."""
    for session in sessions:
        if session.get_playback_info().playback_status == playing_status:
            return session
    return current


async def _read_session() -> dict | None:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
    )
    from winrt.windows.storage.streams import Buffer, DataReader

    manager = await SessionManager.request_async()
    sessions = list(manager.get_sessions())
    current = manager.get_current_session()
    session = select_session(sessions, current, PlaybackStatus.PLAYING)
    if session is None:
        return None

    properties = await session.try_get_media_properties_async()
    playback = session.get_playback_info()
    timeline = session.get_timeline_properties()
    position, duration = timeline_values(
        timeline, playback.playback_status == PlaybackStatus.PLAYING,
        playback.playback_rate)
    artwork = None
    if properties.thumbnail is not None:
        stream = await properties.thumbnail.open_read_async()
        size = min(int(stream.size), 8 * 1024 * 1024)
        if size:
            buffer = Buffer(size)
            await stream.read_async(buffer, size, 0)
            reader = DataReader.from_buffer(buffer)
            artwork = bytearray(size)
            reader.read_bytes(artwork)
            reader.close()
        stream.close()

    app_name = friendly_app_name(session.source_app_user_model_id)
    title = valid_media_text(properties.title)
    artist = valid_media_text(properties.artist) or valid_media_text(properties.album_artist)
    return {
        "title": title,
        "artist": artist,
        "app": app_name,
        "state": str(playback.playback_status).rsplit(".", 1)[-1].title(),
        "duration": duration,
        "position": position,
        "artwork": artwork,
    }


class MediaSessionReader:
    def __init__(self) -> None:
        self.results: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="SeBlueMediaSession")

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                result = asyncio.run(_read_session())
                self.results.put(result)
            except Exception:
                self.results.put(None)
            self._stop.wait(2.0)

    def stop(self) -> None:
        self._stop.set()
