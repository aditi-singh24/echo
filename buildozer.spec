[app]
title = ECHO Mesh Chat
package.name = echomesh
package.domain = org.echo

source.dir = .
source.include_exts = py,json,png,jpg,kv,atlas
source.include_patterns = assets/*,images/*.png
source.exclude_dirs = __pycache__,.github,bin,.buildozer,.git
source.exclude_patterns = echoTK.py,peers.json
version = 0.43

requirements = python3,kivy==2.3.0
orientation = portrait
fullscreen = 0

android.permissions = INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, WAKE_LOCK
android.api = 33
android.minapi = 21
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True

# Pin python-for-android so the build does not pick up Python 3.14,
# which Kivy 2.3.0 cannot compile against.
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
