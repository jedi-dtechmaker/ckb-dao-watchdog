#!/usr/bin/env python3
"""Launch the CKB DAO Watchdog browser interface from the repository root."""
import importlib.util
import os
from pathlib import Path
import sys

backend_path = Path(__file__).resolve().parent / 'dao-v1.0' / 'app.py'
spec = importlib.util.spec_from_file_location('watchdog_web', backend_path)
backend = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backend
spec.loader.exec_module(backend)
app = backend.app

if __name__ == '__main__':
    app.run(host=os.environ.get('HOST', '127.0.0.1'),
            port=int(os.environ.get('PORT', 5000)), debug=False)
