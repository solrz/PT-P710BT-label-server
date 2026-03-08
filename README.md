# PT-P710BT Label Server

A minimal web service and API for printing labels on the **Brother P-Touch Cube Plus (PT-P710BT)** label maker.

Runs as a Docker container on any Linux host (tested on Unraid) with the printer connected via USB. Provides a clean web UI and a simple JSON API.

![Brother PT-P710BT](https://www.brother-usa.com/-/media/brother/product-catalog/images/models/ptp710bt.png?w=400)

## Features

- 🖨️ Print text labels via web UI or API
- 🀄 Full CJK (Chinese/Japanese/Korean) support via Noto fonts
- 📏 Adjustable font size (16–128)
- 🔌 USB connection (stable, no Bluetooth hassle)
- 🐳 Single Docker container, auto-restarts
- ⚡ ~2 second print time

## Quick Start

### 1. Connect printer via USB

Plug the PT-P710BT into your server. Verify it shows up:

```bash
lsusb | grep Brother
# Bus 001 Device 005: ID 04f9:20af Brother Industries, Ltd PT-P710BT

ls /dev/usb/lp0
# /dev/usb/lp0
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

## API

### Print text

```bash
curl -X POST http://your-server:9100/print \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello World", "size": 48}'
```

**Request body:**

| Field  | Type   | Default | Description              |
|--------|--------|---------|--------------------------|
| `text` | string | —       | Text to print (required) |
| `size` | int    | 48      | Font size (16–128)       |

**Response:**

```json
{"ok": true, "message": "已列印「Hello World」(355 lines)"}
```

### Home Assistant Integration

Add a REST command in `configuration.yaml`:

```yaml
rest_command:
  print_label:
    url: "http://your-server:9100/print"
    method: POST
    content_type: "application/json"
    payload: '{"text": "{{ text }}", "size": {{ size | default(48) }}}'
```

Then call it from automations:

```yaml
service: rest_command.print_label
data:
  text: "客廳燈開關"
  size: 64
```

## Protocol Notes

The PT-P710BT uses Brother's **raster command set** (PTCBP mode), originally documented for the PT-9500PC. Key findings from reverse engineering:

### USB

- Shows up as `/dev/usb/lp0` on Linux (usblp driver)
- Write-only via the lp device; status reads require opening separately
- Vendor ID: `04f9`, Product ID: `20af`

### Bluetooth (for reference)

The PT-P710BT exposes **two RFCOMM channels** over Bluetooth Classic (not BLE):

| Channel | UUID | Purpose |
|---------|------|---------|
| 1 | `00000000-deca-fade-deca-deafdecacaff` | Heartbeat/control — sends `ff550200ee10` repeatedly |
| 2 | `00001101-0000-1000-8000-00805f9b34fb` (SPP) | **Data channel** — accepts raster commands, returns 32-byte status |

**macOS note:** The `/dev/tty.PT-P710BT*` serial port that appears after Bluetooth pairing maps to Channel 1 (heartbeat only). To actually print via Bluetooth on macOS, you must use `IOBluetooth` framework to open RFCOMM Channel 2 directly.

**Linux note:** Use `bluetoothctl` to pair, then connect via `AF_BLUETOOTH` socket to channel 2. Do **not** run `bluetoothd` inside a Docker container with `--privileged` — it will conflict with the host's Bluetooth stack and may crash the system.

### Raster Command Sequence

```
1. Invalidate:    00 * 100         (clear buffer)
2. Initialize:    1B 40            (ESC @)
3. Raster mode:   1B 69 61 01      (ESC i a 1)
4. Media info:    1B 69 7A C4 01 18 00 [lines_le16] 00 00 00 00
5. Chaining off:  1B 69 4B 08
6. Auto-cut:      1B 69 4D 40
7. Margin:        1B 69 64 1C 00   (28 dots)
8. Compression:   4D 02            (TIFF/packbits)
9. Raster data:   47 [len_le16] [compressed_line]  (per line)
                  5A                                (empty line)
10. Print+feed:   1A
```

- Image is 128px tall (24mm tape), width = label length
- Image must be rotated 90° CW before rasterizing
- Each raster line is 16 bytes (128 pixels, 1 bit per pixel, MSB first)
- TIFF compression uses PackBits encoding

### References

- [robby-cornelissen/pt-p710bt-label-maker](https://github.com/robby-cornelissen/pt-p710bt-label-maker) — Original Linux Bluetooth implementation
- [stecman's PT-P300BT driver](https://gist.github.com/stecman/ee1fd9a8b1b6f0fdd170ee87ba2ddafd) — Reverse-engineered protocol documentation
- [treideme/brother_pt](https://github.com/treideme/brother_pt) — Python package for Brother PT raster protocol
- [Brother PT-9500PC Command Reference](https://archive.stecman.co.nz/files/datasheets/P-Touch-Cube/Brother-PT-9500PC-CBP-Raster-Mode-Command-Reference.pdf) — Official raster command documentation

## Tape Support

Currently hardcoded for **24mm** continuous tape (TZe-251, TZe-151, etc.). The `tape_mm` parameter in the code can be changed for other widths (12mm, 18mm).

## License

MIT
