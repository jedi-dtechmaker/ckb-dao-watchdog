#!/usr/bin/env python3
"""
CKB DAO Watchdog - Web UI Entrypoint
Launch the web interface from repository root.
"""
import os
import sys

# Change working directory and sys.path to dao-v1.0
root_dir = os.path.dirname(os.path.abspath(__file__))
dao_dir = os.path.join(root_dir, "dao-v1.0")

if dao_dir not in sys.path:
    sys.path.insert(0, dao_dir)

os.chdir(dao_dir)

from app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "127.0.0.1")
    print("=" * 60)
    print("CKB DAO Watchdog - Web Interface")
    print(f"Local Access: http://localhost:{port}")
    print(f"Network:      http://{host}:{port}")
    print("=" * 60)
    app.run(host=host, port=port, debug=False)
