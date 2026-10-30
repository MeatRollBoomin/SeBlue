<h1 align="center">Seblue</h1>

<p align="center">
  Play the same audio through several pairs of headphones at once, so two or
  more people can listen together.<br>
  No virtual sound-card driver, no admin rights, no changes to your audio setup.
</p>

<p align="center">
  <img src="docs/screenshot.png" alt="Seblue" width="420">
</p>

---

## Download

Grab **Seblue.exe** from the [latest release](https://github.com/shreyasmandem/multi-blu/releases/latest).
It is a single file — no installer, no Python, nothing to set up. Double-click it.

> **Windows 10/11 only.** The whole thing is built on WASAPI loopback and the
> Windows Core Audio API. It cannot work on macOS, Linux, Android or iOS — see
> [Why Windows only](#why-windows-only).

## What it does

Windows sends audio to exactly one output device at a time, and there is no
setting anywhere to change that. Seblue adds the missing one.

1. **Playing from** shows the device Windows is already using. Whoever is on
   that device keeps hearing everything exactly as before.
2. **Also playing to** lists every other output device. Flip a switch and that
   device starts playing the same audio.
3. Each device that is switched on gets its **own volume**, so two people can
   listen at different levels — something Windows cannot do at all.
4. A **four-bar quality indicator** reflects recent playback underruns. It
   measures stream stability, not Bluetooth radio signal strength.
5. Each device has a **mute** button and a **delay** slider, to line it up by ear
   with the others (see [Getting them in sync](#getting-them-in-sync)).
6. **Test sound** plays the bundled Sony DTS clip through that selected device.
7. **+ Add a Bluetooth device** opens Windows Bluetooth pairing. Once a device
   connects it appears in the list on its own — no restart needed.
8. The window follows Windows **light/dark mode and accent colour**, and uses
   the **Mica** backdrop on Windows 11.

Use **Tab** to focus a device switch and **Space** or **Enter** to toggle it.
If a selected device cannot connect, use its **Retry** action after resolving
the issue. Other active devices keep playing while that device retries.

There is nothing to start or stop. Flip a switch on and audio follows; flip it
off and it stops. Your choices and volumes are remembered for next time.

## How it works

- **WASAPI loopback** is used to listen in on the output device you are already
  playing to — the same mechanism screen recorders use to capture desktop audio.
- That audio is copied into a ring buffer per extra device and rendered out to
  all of them simultaneously.
- **No virtual audio driver or persistent routing changes.** Seblue uses
  Windows endpoint controls for source selection, per-device volume, and mute.
  If the app is closed or killed, its audio streams stop.

Each listener runs off its own sound-card clock, so their buffers drift apart
over time. Three details keep it clean:

| Problem | What Seblue does |
| --- | --- |
| Buffers drift apart | Corrects by **resampling a block by a few samples**, never by duplicating or dropping raw ones. A duplicated sample is a step change, and at 50 blocks a second that is audible as a buzz. |
| A device can't keep up | Its cushion grows automatically, **and every other device grows with it**, so they stay aligned instead of sliding apart. |
| Devices have different latency | Each stream's reported output latency is measured and the quicker devices are **delayed to match the slowest**. |
| A device stalls or vanishes | Its buffer is resynced, and a short starve is **time-stretched** rather than filled with silence, so it stumbles instead of cracking. |

## Getting them in sync

Seblue automatically aligns devices using the latency PortAudio reports.
That covers the host buffer, but it **cannot see the delay a Bluetooth codec
adds after that**, which differs between devices — an SBC speaker and an aptX
headset can be over a hundred milliseconds apart, and nothing in Windows exposes
that number.

So there is a **delay slider** on each device. Play something with a strong
beat, stand between the two listeners, and drag the slider on whichever device
is *early* until the two line up. It applies instantly and is remembered.

The device under **Playing from** is always the earliest, because its audio
never passes through Seblue at all. If you want everyone perfectly level,
set *Playing from* to a device nobody is listening on (your laptop speakers,
turned down) and switch on every pair of headphones instead.

## Two Bluetooth headphones at once

This is a limit of your **Bluetooth adapter**, not of this app. Most modern
adapters hold two audio devices at once; some refuse the second connection.
Seblue was developed and tested with two connected simultaneously.

If Windows itself will not connect a second pair, a cheap USB Bluetooth dongle
for the second one works — Seblue treats it like any other output device.

## Why Windows only

The app is roughly 1,000 lines, and nearly all the interesting parts are
Windows-specific:

- **WASAPI loopback** to capture what another device is playing. macOS has no
  equivalent without a kernel extension (BlackHole, Loopback); Linux uses
  PulseAudio/PipeWire monitor sources, a completely different API.
- **Windows Core Audio (IMMDevice, IAudioEndpointVolume, IPolicyConfig)** to
  enumerate endpoints, read and set per-device volume, and switch the default
  output device.

On phones this is not possible at all — Android and iOS do not let an app
capture another app's audio or drive several Bluetooth sinks. Android 13+ has
built-in **Auracast** / dual audio for some devices, which is the right tool
there.

## Running from source

```bash
pip install -r requirements.txt
python Seblue.pyw
```

Offline tests — fan-out, format adaptation, drift correction, alignment — need
no audio hardware:

```bash
python tests/test_fanout.py
python tests/test_theme.py
```

Build the standalone executable:

```bash
pip install pyinstaller
python -m PyInstaller --noconfirm --clean Seblue.spec
```

The result is `dist/Seblue.exe`; PyInstaller's work files stay in `build/`.

## Layout

    multiblu/endpoints.py   Core Audio: device list, default device, per-device volume
    multiblu/engine.py      loopback capture, ring buffers, drift, alignment, fan-out
    multiblu/app.py         the window
    multiblu/theme.py       Windows palette, accent, and Mica backdrop
    tools/make_icon.py      regenerates assets/seblue.ico
    tests/test_fanout.py    offline checks, no hardware needed
    tests/test_theme.py     palette and accent checks, no hardware needed

## Troubleshooting

| What you see | What it means |
| --- | --- |
| *In use by something else* | Another app holds that device exclusively. Close it and flip the switch again. |
| *Not reachable* | The device disconnected. It drops off the list within a couple of seconds. |
| Audio breaks up on one device | It is out of radio range or the adapter is saturated. The cushion grows automatically; moving closer helps. |
| One device is behind the other | Drag its **delay** slider — see [Getting them in sync](#getting-them-in-sync). |
| A second Bluetooth headset won't connect | Your adapter only supports one audio link. Use a USB Bluetooth dongle for the second pair. |
| No sound on an extra device | Check its volume slider in the app, and its volume in Windows. |

## Licence

MIT

The device icons use Font Awesome Free, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
