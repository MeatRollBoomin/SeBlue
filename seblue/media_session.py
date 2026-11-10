"""Read the current Windows media session without blocking the UI thread."""

from __future__ import annotations

import asyncio
import queue
import threading
from datetime import datetime, timezone


async def _read_session() -> dict | None:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
    )
    from winrt.windows.storage.streams import Buffer, DataReader

    manager = await SessionManager.request_async()
    sessions = list(manager.get_sessions())
    current = manager.get_current_session()
    playing = [s for s in sessions
               if s.get_playback_info().playback_status == PlaybackStatus.PLAYING]
    session = playing[0] if playing else current
    if session is None:
        return None

    properties = await session.try_get_media_properties_async()
    playback = session.get_playback_info()
    timeline = session.get_timeline_properties()
    duration = max(0.0, timeline.end_time.total_seconds())
    position = max(0.0, timeline.position.total_seconds())
    rate = float(playback.playback_rate or 1.0)
    updated_at = timeline.last_updated_time
    if playback.playback_status == PlaybackStatus.PLAYING and updated_at:
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        age = max(0.0, (datetime.now(timezone.utc) - updated_at).total_seconds())
        position += age * rate
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

    app_name = session.source_app_user_model_id.rsplit("!", 1)[-1]
    if app_name.lower().endswith(".exe"):
        app_name = app_name[:-4]
    friendly_names = {
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
    app_name = friendly_names.get(app_name.casefold(), app_name)
    def valid_text(value) -> str:
        value = str(value or "").strip()
        if value.casefold() in {"unknown", "unknown artist", "<unknown>", "n/a"}:
            return ""
        if value.isdecimal():
            return ""
        return value

    title = valid_text(properties.title)
    artist = valid_text(properties.artist) or valid_text(properties.album_artist)
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
