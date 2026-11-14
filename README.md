# SeBlue Connect
<p align="center">
  <img src="docs/seblue.png" alt="SeBlue">
</p>

SeBlue routes audio from the current Windows output to other connected audio
devices at the same time. Use it to let several people listen through separate
headphones or speakers.


| Windows Flow | Windows Dark |
| :---: | :---: |
| ![Image 1](docs/screenshot-light.png) | ![Image 2](docs/screenshot-dark.png) |


## Run SeBlue

Download **`SeBlue-Setup.exe`** from the [latest GitHub release](https://github.com/shreyasmandem/multi-blu/releases/latest) and run it. It sets up SeBlue for the current Windows user. During setup, you can choose whether to create a desktop shortcut and launch SeBlue when you sign in. Both options are enabled by default; sign-in launch starts the app in the system tray.

## Using the app

1. **Playing from** shows the output Windows is using as the audio source.
   Select **Change** to choose another source.
2. Under **Also playing to**, turn on each device that should receive the audio.
3. Set each device’s volume and mute state independently. Use **Test Sound** to
   check an output.
4. Adjust a device’s delay slider to bring it into sync with the source.

SeBlue scans for output devices while it is open. A selected device remains
remembered while disconnected and starts receiving audio again when it returns.
Use **Retry** on a device row if its output fails to open.

The four-bar indicator reports playback stability from recent audio underruns.
It does not report Bluetooth radio signal strength.
The **Now Playing** card identifies the source app and displays the details
and artwork it shares with Windows. It uses a bundled cover image when the
session does not provide artwork.

![SeBlue window](docs/tray.png)

Minimize the window to keep it on the taskbar. Close it to hide SeBlue in the
notification area. Choose **Open SeBlue** from the tray menu to show the window
again, or choose **Exit** to stop routing and close the app.

### Keyboard controls

- **Tab** / **Shift+Tab** moves focus between controls.
- **Space** or **Enter** activates the focused button or switch.
- On a focused slider, **Left/Right** adjusts in small steps;
  **Page Up/Page Down** adjusts in larger steps; **Home/End** selects minimum
  or maximum.

## Audio and timing

SeBlue captures the current output using WASAPI loopback and sends it to each
selected endpoint. Each endpoint has its own playback stream and volume control.
SeBlue aligns streams using the output latency reported by Windows and provides
a per-device delay adjustment for additional tuning.

Bluetooth codec latency occurs after Windows’ reported output latency, so the
app cannot measure that part automatically. To sync listeners, play a steady
beat and increase the delay on whichever device sounds early. The delay setting
is saved for that device.

The source device plays directly from Windows and will generally be ahead of
the routed devices. For the closest timing match, choose a source that nobody
is listening to and route all listening devices through SeBlue.

Bluetooth adapter limits still apply. Some adapters cannot maintain multiple
Bluetooth audio connections at once; SeBlue can route to endpoints that Windows
has connected.

## Build from source

Install Python and the project dependencies, then launch the app:

```powershell
pip install -r requirements.txt
python Seblue.pyw
```

The launcher checks for missing dependencies and installs them for the current
user. To build the standalone executable:

```powershell
pip install pyinstaller
python -m PyInstaller --noconfirm --clean Seblue.spec
```

PyInstaller writes `dist/SeBlue.exe` and its work files to `build/`.

The GitHub release download is `SeBlue-Setup.exe`.

## Run tests

After installing the dependencies, run the offline checks from the project
folder:

```powershell
python tests/test_fanout.py
python tests/test_theme.py
python tests/test_features.py
```

The feature checks mock Bluetooth radios and use synthetic media/session data;
they do not toggle a radio or require audio hardware.

## Libraries

- **NumPy** handles audio sample buffers and signal processing.
- **PyAudioWPatch** and **PortAudio** capture Windows output and play to other
  audio endpoints.
- **PyCAW** and **comtypes** access Windows Core Audio devices and controls.
- **miniaudio** decodes the bundled MP3 test sound.
- **pystray** provides the notification-area icon and menu.
- **Pillow** handles app and tray images, Now Playing artwork, and image
  processing.
- **tkinter-icons** supplies the Font Awesome device and control icons.
- **WinRT media control** (`winrt-Windows.Media.Control` and
  `winrt-Windows.Storage.Streams`) reads the current media session, timeline,
  and artwork shared by Windows apps.
- **WinRT radios** (`winrt-Windows.Devices.Radios`) reads and changes the
  Windows Bluetooth radio state.
- **Tkinter** provides the desktop interface; it is included with standard
  Windows Python distributions.

The interface uses the bundled **Satoshi Variable** font when Windows can load
it; otherwise, it falls back to Segoe UI.

## Source map

| Path | Purpose |
| --- | --- |
| `Seblue.pyw` | Application entry point |
| `seblue/app.py` | Window, controls, device scanning, Now Playing card, and tray behavior |
| `seblue/engine.py` | Audio capture, buffering, timing, and output streams |
| `seblue/endpoints.py` | Windows audio endpoint discovery and controls |
| `seblue/media_session.py` | Reads Windows media-session metadata, position, and artwork |
| `seblue/radio.py` | Reads and controls the Windows Bluetooth radio |
| `seblue/routing.py` | Builds listener targets while preserving selected devices that are disconnected |
| `seblue/single_instance.py` | Prevents duplicate app instances and activates the existing window |
| `seblue/theme.py` | Theme colors, Windows appearance detection, and Mica backdrop |
| `assets/` | App icons, cover art, Satoshi font, and test-sound MP3 |
| `requirements.txt` | Python packages required to run the source app |
| `Seblue.spec` | PyInstaller configuration for the standalone executable |
| `tests/` | Automated checks for audio fan-out, themes, Bluetooth control, Now Playing, and reconnect routing |

## Troubleshooting

- **No sound from a selected output:** check its SeBlue volume and Windows
  output volume. If it reports an error, reconnect the device and use **Retry**.
- **Audio stutters:** move closer to the Bluetooth adapter or reduce the number
  of active Bluetooth streams.
- **Devices sound out of sync:** increase the delay on the device that sounds
  early.
- **Second headset will not connect:** check whether the Bluetooth adapter and
  Windows can connect to both headsets simultaneously.

## License

 Forked from [Multi-Blu](https://github.com/shreyasmandem/multi-blu). SeBlue is distributed under the MIT License; see [LICENSE](LICENSE). The
device icons use Font Awesome Free under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
