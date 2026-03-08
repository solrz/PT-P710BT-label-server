# Label Print Server

A minimal web service and API for printing labels on:

- **Brother PT-P710BT** — via USB (`/dev/usb/lp0`)
- **AIMO P12 Pro / Phomemo P12** — via Bluetooth Low Energy (BLE)

Runs as a Docker container on Linux (tested on Unraid). Provides a clean web UI and a simple JSON API.

## Features

- 🖨️ Print text labels via web UI or API
- 🀄 Full CJK (Chinese/Japanese/Korean) support
- 📏 Adjustable font size (16–128)
- ↕️ Vertical and horizontal orientation
- ✂️ Auto-cut toggle (chain printing support)
- 👁️ Live preview with auto-update
- 🔵 P12 Pro BLE printing (via `p12_printer.py`)
- 🐳 Single Docker container, auto-restarts

## Supported Printers

| Printer | Connection | Print Head | Tape |
|---------|-----------|-----------|------|
| Brother PT-P710BT | USB | 128 dots (16 bytes/line) | 24mm TZe |
| AIMO P12 Pro / Phomemo P12 | BLE | 96 dots (12 bytes/line) | 12mm |

## Quick Start (Brother PT-P710BT)

### 1. Connect printer via USB

```bash
lsusb | grep Brother
# Bus 001 Device 005: ID 04f9:20af Brother Industries, Ltd PT-P710BT

ls /dev/usb/lp0
```

### 2. Build and run

```bash
docker build -t label-service .
docker run -d \
  --name label-service \
  --restart unless-stopped \
  --device /dev/usb/lp0:/dev/usb/lp0 \
  -p 9100:9100 \
  label-service
```

### 3. Open the web UI

Navigate to `http://your-server:9100`

## P12 Pro (BLE)

The P12 Pro uses Bluetooth Low Energy only (no USB data). Use `p12_printer.py` as a standalone module or integrate into a Flask service.

### Standalone usage

```bash
pip install bleak Pillow
export P12_ADDRESS="XX:XX:XX:XX:XX:XX"  # BLE address
python3 p12_printer.py "Hello 你好"
```

### Python API

```python
from p12_printer import print_to_p12

result = await print_to_p12("XX:XX:XX:XX:XX:XX", "Hello", font_size=48)
```

### BLE GATT Protocol

| UUID | Purpose |
|------|---------|
| `0000ff00` | Primary Service |
| `0000ff01` | Read |
| `0000ff02` | Write (commands + image data) |
| `0000ff03` | Notify (responses) |

Print sequence: Init packets → `ESC @ GS v 0 00` + dimensions → raw image bytes → tape feed.

## API

### Print text (Brother)

```bash
curl -X POST http://your-server:9100/print \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello", "size": 48, "cut": true, "orientation": "vertical"}'
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `text` | string | — | Text to print (required) |
| `size` | int | 48 | Font size (16–128) |
| `cut` | bool | true | Auto-cut after printing |
| `orientation` | string | "vertical" | "vertical" or "horizontal" |

### Preview

```bash
curl -X POST http://your-server:9100/preview \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello", "size": 48}' \
  -o preview.png
```

### Home Assistant Integration

```yaml
rest_command:
  print_label:
    url: "http://your-server:9100/print"
    method: POST
    content_type: "application/json"
    payload: '{"text": "{{ text }}", "size": {{ size | default(48) }}}'
```

## Protocol Notes

### Brother PT-P710BT

Uses **raster command set** (PTCBP mode). Image is 128px tall (24mm tape), rotated 90° CW, TIFF/PackBits compressed.

Key commands:
- Chain printing: `ESC i K 0x00` (chain on) / `0x08` (chain off)
- Auto-cut: `ESC i M 0x40`
- Print + feed: `0x1A`

### AIMO P12 Pro / Phomemo P12

Uses **Phomemo protocol** over BLE. Image is 96px wide, rotated 270°, sent as raw uncompressed bitmap.

Key commands:
- Init: `1F 11 38` + additional handshake packets
- Print: `ESC @ GS v 0 00` + width/height + raw data
- Feed: `ESC d 0D`

## References

- [robby-cornelissen/pt-p710bt-label-maker](https://github.com/robby-cornelissen/pt-p710bt-label-maker)
- [PepperPhil/phomemo_p12](https://github.com/PepperPhil/phomemo_p12) — P12 Python tools
- [Brother PT-9500PC Command Reference](https://archive.stecman.co.nz/files/datasheets/P-Touch-Cube/Brother-PT-9500PC-CBP-Raster-Mode-Command-Reference.pdf)

## License

MIT
