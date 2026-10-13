"""
main.py - Android entry point for Echo (Buildozer needs a file with this name).

On the phone there is no command line, so this file fills in the three
arguments that echokivy.py normally reads: --id, --port and --config.

Desktop test (same file works):
    python main.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# This phone's identity in the mesh. Must match the "D" section in
# peers_phone.json, and must not clash with A, B or C on the laptop.
PEER_ID = "D"
PORT = 5004
CONFIG = os.path.join(HERE, "peers_phone.json")

sys.argv = ["echo", "--id", PEER_ID, "--port", str(PORT), "--config", CONFIG]

import echokivy  # noqa: E402

echokivy.main()