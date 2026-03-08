#!/usr/bin/env python3
"""
Brother PT-P710BT Label Print Service

API:
  POST /print  {"text": "Hello", "size": 48}
  GET  /       Web UI

Writes directly to /dev/usb/lp0
"""

import struct
import os

import packbits
from flask import Flask, request, jsonify, send_from_directory
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

DEVICE = os.environ.get("PRINTER_DEVICE", "/dev/usb/lp0")
PRINT_HEAD_PIXELS = 128
RASTER_LINE_BYTES = 16

FONT_PATHS = [
    "/usr/share/fonts/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def get_font(size):
    for fp in FONT_PATHS:
        try:
            return ImageFont.truetype(fp, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def text_to_raster(text, font_size=48, tape_mm=24):
    """Text → raster bytes ready for printer."""
    font = get_font(font_size)
    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    margin = 40
    img = Image.new("RGBA", (tw + margin * 2, PRINT_HEAD_PIXELS), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    draw.text((margin, (PRINT_HEAD_PIXELS - th) // 2 - bbox[1]), text,
              font=font, fill=(0, 0, 0, 255))

    # Encode: RGBA → alpha → rotate → bits
    pixels = img.load()
    w, h = img.size
    alpha_rows = [[pixels[x, y][3] for x in range(w)] for y in range(h)]
    rotated = list(zip(*alpha_rows))
    raster = bytearray()
    for line in rotated:
        for i in range(0, len(line), 8):
            byte = 0
            for j in range(8):
                if i + j < len(line) and line[i + j] > 0:
                    byte |= (1 << (7 - j))
            raster.append(byte)

    return build_print_data(raster, tape_mm)


def build_print_data(raster_data, tape_mm=24):
    n_lines = len(raster_data) // RASTER_LINE_BYTES
    buf = bytearray()
    buf.extend(b"\x00" * 100)
    buf.extend(b"\x1b\x40")
    buf.extend(b"\x1b\x69\x61\x01")
    buf.extend(b"\x00" * 64)
    buf.extend(b"\x1b\x40")
    buf.extend(b"\x1b\x69\x61\x01")
    buf.extend(b"\x1b\x69\x7a\xc4\x01")
    buf.extend(bytes([tape_mm]))
    buf.extend(b"\x00")
    buf.extend(struct.pack("<H", n_lines))
    buf.extend(b"\x00\x00\x00\x00")
    buf.extend(b"\x1b\x69\x4b\x08")
    buf.extend(b"\x1b\x69\x4d\x40")
    buf.extend(b"\x1b\x69\x64\x1c\x00")
    buf.extend(b"\x4d\x02")

    zero_line = b"\x00" * RASTER_LINE_BYTES
    for i in range(0, len(raster_data), RASTER_LINE_BYTES):
        line = bytes(raster_data[i:i + RASTER_LINE_BYTES])
        if line == zero_line:
            buf.extend(b"\x5a")
        else:
            compressed = packbits.encode(line)
            buf.extend(b"\x47")
            buf.extend(struct.pack("<H", len(compressed)))
            buf.extend(compressed)

    buf.extend(b"\x1a")
    return bytes(buf)


def send_to_printer(data):
    with open(DEVICE, "wb") as f:
        f.write(data)


@app.route("/")
def index():
    return """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>🖨️ Label Printer</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, sans-serif; background: #f5f5f5; 
         display: flex; justify-content: center; align-items: center; 
         min-height: 100vh; }
  .card { background: white; border-radius: 16px; padding: 32px; 
          box-shadow: 0 4px 24px rgba(0,0,0,0.1); width: 90%; max-width: 400px; }
  h1 { font-size: 24px; margin-bottom: 24px; text-align: center; }
  input, select, button { width: 100%; padding: 12px 16px; border-radius: 10px; 
         font-size: 16px; border: 2px solid #e0e0e0; margin-bottom: 12px; 
         outline: none; transition: border-color 0.2s; }
  input:focus, select:focus { border-color: #007AFF; }
  button { background: #007AFF; color: white; border: none; cursor: pointer; 
           font-weight: 600; font-size: 18px; margin-top: 8px; }
  button:hover { background: #0056CC; }
  button:active { transform: scale(0.98); }
  button:disabled { background: #ccc; cursor: not-allowed; }
  .size-row { display: flex; gap: 8px; }
  .size-row select { flex: 1; }
  #status { text-align: center; margin-top: 16px; font-size: 14px; 
            color: #666; min-height: 20px; }
  #status.ok { color: #34C759; }
  #status.err { color: #FF3B30; }
</style>
</head>
<body>
<div class="card">
  <h1>🖨️ Label Printer</h1>
  <input type="text" id="text" placeholder="輸入要列印的文字..." autofocus>
  <div class="size-row">
    <select id="size">
      <option value="32">小 (32)</option>
      <option value="48" selected>中 (48)</option>
      <option value="64">大 (64)</option>
      <option value="80">特大 (80)</option>
    </select>
  </div>
  <button id="btn" onclick="doPrint()">列印 🖨️</button>
  <div id="status"></div>
</div>
<script>
async function doPrint() {
  const text = document.getElementById('text').value.trim();
  if (!text) return;
  const size = parseInt(document.getElementById('size').value);
  const btn = document.getElementById('btn');
  const status = document.getElementById('status');
  
  btn.disabled = true;
  btn.textContent = '列印中...';
  status.className = '';
  status.textContent = '⏳ 傳送中...';
  
  try {
    const res = await fetch('/print', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text, size})
    });
    const data = await res.json();
    if (data.ok) {
      status.className = 'ok';
      status.textContent = '✅ ' + data.message;
      document.getElementById('text').value = '';
    } else {
      status.className = 'err';
      status.textContent = '❌ ' + data.error;
    }
  } catch(e) {
    status.className = 'err';
    status.textContent = '❌ ' + e.message;
  }
  
  btn.disabled = false;
  btn.textContent = '列印 🖨️';
}

document.getElementById('text').addEventListener('keydown', e => {
  if (e.key === 'Enter') doPrint();
});
</script>
</body>
</html>"""


@app.route("/print", methods=["POST"])
def do_print():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    size = int(data.get("size", 48))

    if not text:
        return jsonify(ok=False, error="沒有文字"), 400

    if size < 16 or size > 128:
        return jsonify(ok=False, error="字型大小需在 16-128 之間"), 400

    try:
        print_data = text_to_raster(text, font_size=size)
        send_to_printer(print_data)
        n_lines = len(print_data) // RASTER_LINE_BYTES
        return jsonify(ok=True, message=f"已列印「{text}」({n_lines} lines)")
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9100, debug=False)
