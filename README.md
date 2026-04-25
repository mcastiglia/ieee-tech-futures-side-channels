# Power Analysis Demo (Flask)

This project converts your notebook workflow into a Flask web app that runs in a browser.

## What Firmware Do You Need?

Use the same firmware from the notebook:

- Firmware project: `firmware/mcu/basic-passwdcheck`
- Build target: `PLATFORM=CWHUSKY`
- Crypto target: `CRYPTO_TARGET=NONE`
- SimpleSerial version: `SS_VER=SS_VER_2_1`
- Output hex expected by app: `basic-passwdcheck-CWHUSKY.hex`

The app builds and flashes this firmware in Step 1.

## Prerequisites

- Python 3.10+
- `chipwhisperer` Python package installed
- ARM GCC toolchain available in PATH (for `make`), typically `arm-none-eabi-gcc`
- Access to ChipWhisperer setup notebook (`Setup_Generic.ipynb`)
- Access to firmware folder (`firmware/mcu/basic-passwdcheck`)

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Path Configuration

If your ChipWhisperer repo layout differs from defaults, set:

- `CW_SETUP_NOTEBOOK` = full path to `Setup_Generic.ipynb`
- `CW_FIRMWARE_DIR` = full path to `firmware/mcu/basic-passwdcheck`

Example:

```bash
export CW_SETUP_NOTEBOOK=/path/to/chipwhisperer/jupyter/Setup_Scripts/Setup_Generic.ipynb
export CW_FIRMWARE_DIR=/path/to/chipwhisperer/firmware/mcu/basic-passwdcheck
```

## Run

```bash
python app.py
```

Open:

- `http://127.0.0.1:5000`

## Workflow in Browser

1. Step 1 initializes scope/target, builds firmware, flashes target, and checks trace capture.
2. Steps 2-6 run the same attack flow as the notebook with Plotly charts.
