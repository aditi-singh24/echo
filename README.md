# ECHO Mesh Chat

ECHO is a small peer-to-peer LAN chat project. Peers communicate over TCP, discover routes through distance-vector updates, and use heartbeats to track neighbours. Chat messages are encrypted end-to-end, and delivery is acknowledged and retried.

## Requirements

- Python 3
- No third-party packages are needed for the desktop peer or crypto demo.
- The Android app uses Kivy 2.3.0 and Buildozer (see `buildozer.spec`).

## Run the desktop chat

Configure each peer's direct neighbours in `peers.json`. Update IP addresses and ports to match the machines and network where you are running the app. Each peer must use the same group password configured in `peer.py`.

Start a peer in a terminal:

```sh
python peer.py --id A --port 5001 --config peers.json
```

Start another peer in a separate terminal, using an ID and port that match its entry in the configuration:

```sh
python peer.py --id B --port 5002 --config peers.json
```

On Windows, use `py` in place of `python` if that is how Python is installed. Enter a message at the peer prompt to send it; enter `quit` to exit.

The Tkinter interface can be started with the same arguments:

```sh
python echoTK.py --id A --port 5001 --config peers.json
```

## Run the crypto demo

```sh
python demo_crypto.py
```

The demo encrypts the same text twice, decrypts one ciphertext, then demonstrates rejection of a modified ciphertext and a message checked with a different MAC key. It uses the encryption helpers in `peer.py`.

## Android

`main.py` is the Buildozer entry point. The project is configured for Android API 33, supports Android 5.0+ (API 21), and builds for ARM64 and ARMv7. Buildozer is intended to run in Linux; on Windows, use WSL with a supported Linux distribution rather than running these commands in PowerShell.

### Configure the phone peer

The current entry point starts the phone as peer `D` on port `5004`. Set the phone's neighbours in `peers_phone.json` and replace `LAPTOP_WIFI_IP` and any `xxxx` placeholders with the actual LAN addresses of those computers. Update the corresponding neighbour entries in `peers.json` with the phone's Wi-Fi IP address. Keep the peer IDs and ports consistent in both files, and use the same `SHARED_SECRET` in `peer.py` on every peer.

The phone and computers must be able to reach each other over the same network. Allow inbound TCP traffic on the configured peer ports in the computer's firewall, and avoid guest Wi-Fi or network settings that isolate wireless clients.

### Build and install

In WSL/Linux, install Buildozer and its Android build dependencies following the [Buildozer installation guide](https://buildozer.readthedocs.io/en/latest/installation.html). From the repository directory, build the debug APK:

```sh
buildozer android debug
```

The first build downloads the Android SDK/NDK and can take a while. The APK is written under `bin/`. To install it on a USB-connected Android device with USB debugging enabled and `adb` available:

```sh
adb install -r bin/echomesh-*-debug.apk
```

Alternatively, copy the APK from `bin/` to the phone and open it to install (you may need to allow installs from that source). Launch **ECHO Mesh Chat** and start the desktop peers configured as the phone's neighbours. To change the phone's peer ID or listening port, edit `PEER_ID` or `PORT` in `main.py`, then rebuild the APK.

## Security note

The encryption in `peer.py` is a learning/demo implementation, not a vetted cryptographic protocol. The shared password is stored in the source code, so anyone with access to the code can recover it. Do not use this project to protect sensitive messages.
