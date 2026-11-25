# CKB DAO Watchdog 🐕

[中文版](./README_CN.md)

Community-driven tools for auditing and verifying CKB DAO governance voting results.

## Overview

CKB DAO Watchdog is a collection of open-source tools that enable community members to independently verify DAO voting results. By comparing on-chain data with platform-recorded weights, these tools help ensure transparency and integrity in CKB DAO governance.

## Features

- **Independent Verification**: Verify voting weights against on-chain Nervos DAO deposits
- **Multi-Platform Support**: Currently supports Metaforo (DAO v1.0), with DAO v1.1 coming soon
- **Transparent Auditing**: Export detailed JSON/CSV reports for community review
- **Bilingual**: Available in both English and Chinese

## Directory Structure

```
ckb-dao-watchdog/
├── .gitignore                   # Git ignore file
├── LICENSE                      # MIT License
├── README.md                    # English documentation
├── README_CN.md                 # Chinese documentation
│
├── dao-v1.0/                    # DAO v1.0 (Metaforo) auditing tools
│   ├── metaforo_watchdog_en.py  # English version script
│   ├── metaforo_watchdog_cn.py  # Chinese version script
│   ├── README.md                # Detailed English guide
│   └── README_CN.md             # Detailed Chinese guide
│
└── dao-v1.1/                    # DAO v1.1 tools (coming soon)
    └── README.md                # Coming soon notice
```

## Quick Start

### Prerequisites

- Python 3.11+
- Required packages:

```bash
pip install -r dao-v1.0/requirements.txt
```

### Usage

#### 1. Web Frontend (Browser UI)

For an interactive visual experience with live progress, discrepancy filters, and export buttons:

```bash
# Launch from repository root
python app.py
```
Then open **`http://localhost:5000`** in your browser.

#### 2. Command Line (CLI)

For running audits directly in your terminal:

```bash
# Navigate to dao-v1.0 directory
cd dao-v1.0

# Run with Metaforo voting page URL (English)
python metaforo_watchdog_en.py https://dao.ckb.community/thread/vot-ckb-integration-for-rosen-bridge-66568

# Or Chinese version
python metaforo_watchdog_cn.py https://dao.ckb.community/thread/vot-ckb-integration-for-rosen-bridge-66568
```

#### 3. Docker & Docker Compose

```bash
cd dao-v1.0

# Run Web UI in Docker
docker-compose up watchdog-web

# Or run CLI in Docker
docker-compose run watchdog-en <metaforo_url>
```

See [dao-v1.0/README.md](./dao-v1.0/README.md) for detailed usage instructions.

## How It Works

1. **Parse URL**: Extract thread ID from Metaforo voting page URL
2. **Fetch Poll Options**: Get all voting options (e.g., Yes/No) via Metaforo API
3. **Get Voter Data**: Retrieve all voters and their recorded weights for each option
4. **Query On-Chain Data**: For each voter:
   - Get their bound CKB addresses (Neuron + MetaMask/PW Lock)
   - Query Nervos DAO deposits via Explorer API
   - Calculate actual on-chain weight
5. **Compare & Report**: Compare Metaforo weights with on-chain weights, flag discrepancies

## Output Files

For each voting option, the tool generates:
- `vote_result_{thread_id}_{option}_{timestamp}.json`
- `vote_result_{thread_id}_{option}_{timestamp}.csv`

Fields include:
- `nickname`, `userid`
- `total weight(metaforo)` - Weight recorded by Metaforo
- `total weight(on chain, floored)` - Calculated on-chain weight
- `address`, `address weight(floored)`
- `need_review` - Flag for discrepancies requiring manual review
- `explorer_url` - Link to address on CKB Explorer

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## License

MIT License - see [LICENSE](./LICENSE) for details.

## Related Links

- [CKB Community Fund DAO](https://dao.ckb.community)
- [Nervos CKB Explorer](https://explorer.nervos.org)
- [CKBFans](https://github.com/ckbfans)
## Deploying the web app

The browser interface and API run together as one Python web service. Push your changes to your own fork, then connect that fork and branch to a host such as Render. For a Render Docker web service use:

- **Runtime:** Docker
- **Root directory:** `dao-v1.0`
- **Dockerfile path:** `./Dockerfile.web`
- **Docker build context:** `.`
- **Docker command:** leave blank to use the Dockerfile's startup command

The web image starts Gunicorn on the port supplied by Render. The existing `Dockerfile` remains the CLI image.

The app uses in-memory jobs and progress streams: run exactly **one worker and one service instance**. Up to two audits can run at once, and a short interval between new jobs protects the service and upstream APIs. A restart interrupts running audits. These limits are shared by all visitors and are not a substitute for host-level rate limiting or authentication on a larger public deployment.

Generated reports default to `dao-v1.0/vote_result/`. Set `WATCHDOG_REPORT_DIR` to a writable persistent directory to retain new reports across restarts or deploys. For example, on a paid Render service, mount a persistent disk at `/var/data` and set `WATCHDOG_REPORT_DIR=/var/data/vote_result`. Without persistent storage, reports generated on an ephemeral host will be lost when it restarts or redeploys; packaged historical reports remain in the repository. Configure one instance when using a disk.

For local use run `python app.py` from the repository root; it binds to localhost by default. To run the web app through Docker Compose, use `docker compose up watchdog-web` in `dao-v1.0`.
