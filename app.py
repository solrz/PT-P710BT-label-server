#!/usr/bin/env python3
"""
Brother PT-P710BT Label Print Service

API:
  POST /print    {"text": "Hello", "size": 48, "cut": true}
  POST /preview  {"text": "Hello", "size": 48}  → PNG image
  GET  /         Web UI

Writes directly to /dev/usb/lp0
"""

import io
import struct
import os

import packbits
from flask import Flask, request, jsonify, send_file
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


def render_label(text, font_size=48):
    """Render text to a 128px-tall RGBA image."""
    font = get_font(font_size)
    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    margin = 8
    img = Image.new("RGBA", (tw + margin * 2, PRINT_HEAD_PIXELS), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    draw.text((margin, (PRINT_HEAD_PIXELS - th) // 2 - bbox[1]), text,
              font=font, fill=(0, 0, 0, 255))
    return img


def image_to_raster(img):
    """RGBA image → raster byte array."""
    img = img.convert("RGBA")
    if img.height != PRINT_HEAD_PIXELS:
        ratio = PRINT_HEAD_PIXELS / img.height
        img = img.resize((int(img.width * ratio), PRINT_HEAD_PIXELS), Image.LANCZOS)
    pixels = img.load()
    w, h = img.size
    alpha_rows = [[pixels[x, y][3] for x in range(w)] for y in range(h)]
    rotated = list(zip(*alpha_rows))
    buf = bytearray()
    for line in rotated:
        for i in range(0, len(line), 8):
            byte = 0
            for j in range(8):
                if i + j < len(line) and line[i + j] > 0:
                    byte |= (1 << (7 - j))
            buf.append(byte)
    return buf


def build_print_data(raster_data, tape_mm=24, auto_cut=True):
    n_lines = len(raster_data) // RASTER_LINE_BYTES
    buf = bytearray()

    # Invalidate
    buf.extend(b"\x00" * 100)
    # Init
    buf.extend(b"\x1b\x40")
    # Raster mode
    buf.extend(b"\x1b\x69\x61\x01")
    # Flush + re-init + raster
    buf.extend(b"\x00" * 64)
    buf.extend(b"\x1b\x40")
    buf.extend(b"\x1b\x69\x61\x01")
    # Media & quality
    buf.extend(b"\x1b\x69\x7a\xc4\x01")
    buf.extend(bytes([tape_mm]))
    buf.extend(b"\x00")
    buf.extend(struct.pack("<H", n_lines))
    buf.extend(b"\x00\x00\x00\x00")
    # Advanced mode:
    #   0x08 = no chain (last page, cut after)
    #   0x00 = chain (more pages, cut previous but not this one)
    buf.extend(b"\x1b\x69\x4b")
    buf.extend(bytes([0x08 if auto_cut else 0x00]))
    # Mode: auto-cut always on (0x40) — chain mode controls whether it actually cuts
    buf.extend(b"\x1b\x69\x4d\x40")
    # Margin = 0 dots
    buf.extend(b"\x1b\x69\x64\x00\x00")
    # TIFF compression
    buf.extend(b"\x4d\x02")

    # Raster data
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

    # Always use 0x1A (print with feeding) — chain mode handles cut behavior
    buf.extend(b"\x1a")
    return bytes(buf)


def send_to_printer(data):
    with open(DEVICE, "wb") as f:
        f.write(data)


def image_to_preview_png(img):
    """Convert RGBA label image to a displayable PNG with white background."""
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bg.paste(img, mask=img.split()[3])

    # Add a thin border to simulate label tape
    border = 2
    preview = Image.new("RGB",
        (bg.width + border * 2, bg.height + border * 2), (200, 200, 200))
    preview.paste(bg, (border, border))

    buf = io.BytesIO()
    preview.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ─── Routes ───

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
  body { font-family: -apple-system, "PingFang TC", sans-serif; background: #f5f5f5;
         display: flex; justify-content: center; padding: 32px 16px; }
  .card { background: white; border-radius: 16px; padding: 28px;
          box-shadow: 0 4px 24px rgba(0,0,0,0.1); width: 100%; max-width: 440px; }
  h1 { font-size: 22px; margin-bottom: 20px; text-align: center; }
  label { display: block; font-size: 13px; color: #666; margin-bottom: 4px; font-weight: 500; }
  input[type=text], select { width: 100%; padding: 10px 14px; border-radius: 10px;
         font-size: 16px; border: 2px solid #e0e0e0; margin-bottom: 14px;
         outline: none; transition: border-color 0.2s; }
  input:focus, select:focus { border-color: #007AFF; }
  .row { display: flex; gap: 10px; align-items: end; }
  .row > div { flex: 1; }
  .toggle { display: flex; align-items: center; gap: 8px; margin-bottom: 14px;
            font-size: 14px; color: #333; cursor: pointer; user-select: none; }
  .toggle input { width: 18px; height: 18px; accent-color: #007AFF; }
  .btn-row { display: flex; gap: 10px; margin-top: 4px; }
  button { flex: 1; padding: 12px 16px; border-radius: 10px; font-size: 16px;
           border: none; cursor: pointer; font-weight: 600; transition: all 0.15s; }
  button:active { transform: scale(0.97); }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-print { background: #007AFF; color: white; }
  .btn-print:hover { background: #0056CC; }
  .btn-preview { background: #E5E5EA; color: #333; }
  .btn-preview:hover { background: #D1D1D6; }
  #preview-box { margin-top: 16px; text-align: center; display: none; }
  #preview-box img { max-width: 100%; border: 1px solid #ddd; border-radius: 8px;
                     image-rendering: pixelated; }
  #preview-label { font-size: 12px; color: #999; margin-top: 4px; }
  #status { text-align: center; margin-top: 14px; font-size: 14px;
            color: #666; min-height: 20px; }
  #status.ok { color: #34C759; }
  #status.err { color: #FF3B30; }
</style>
</head>
<body>
<div class="card">
  <h1>🖨️ Label Printer</h1>

  <label for="text">文字</label>
  <input type="text" id="text" placeholder="輸入要列印的文字..." autofocus>

  <div class="row">
    <div>
      <label for="size">字型大小</label>
      <select id="size" onchange="autoPreview()">
        <option value="24">迷你 (24)</option>
        <option value="32">小 (32)</option>
        <option value="48" selected>中 (48)</option>
        <option value="64">大 (64)</option>
        <option value="80">特大 (80)</option>
        <option value="96">巨大 (96)</option>
      </select>
    </div>
  </div>

  <label class="toggle">
    <input type="checkbox" id="cut" checked>
    自動裁切
  </label>

  <div id="preview-box">
    <img id="preview-img" alt="preview">
    <div id="preview-label"></div>
  </div>

  <div class="btn-row">
    <button class="btn-preview" onclick="doPreview()">預覽 👁️</button>
    <button class="btn-print" id="btn" onclick="doPrint()">列印 🖨️</button>
  </div>

  <div id="status"></div>
</div>

<script>
let previewTimer = null;

function autoPreview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(() => {
    if (document.getElementById('text').value.trim()) doPreview();
  }, 300);
}

document.getElementById('text').addEventListener('input', autoPreview);

async function doPreview() {
  const text = document.getElementById('text').value.trim();
  if (!text) return;
  const size = parseInt(document.getElementById('size').value);
  const box = document.getElementById('preview-box');
  const img = document.getElementById('preview-img');
  const label = document.getElementById('preview-label');

  try {
    const res = await fetch('/preview', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text, size})
    });
    if (res.ok) {
      const blob = await res.blob();
      img.src = URL.createObjectURL(blob);
      const w = res.headers.get('X-Label-Width');
      const h = res.headers.get('X-Label-Height');
      label.textContent = w && h ? w + ' × ' + h + ' px' : '';
      box.style.display = 'block';
    }
  } catch(e) {}
}

async function doPrint() {
  const text = document.getElementById('text').value.trim();
  if (!text) return;
  const size = parseInt(document.getElementById('size').value);
  const cut = document.getElementById('cut').checked;
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
      body: JSON.stringify({text, size, cut})
    });
    const data = await res.json();
    if (data.ok) {
      status.className = 'ok';
      status.textContent = '✅ ' + data.message;
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


@app.route("/preview", methods=["POST"])
def do_preview():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    size = int(data.get("size", 48))

    if not text:
        return jsonify(ok=False, error="沒有文字"), 400

    size = max(16, min(128, size))

    try:
        img = render_label(text, font_size=size)
        png_buf = image_to_preview_png(img)
        resp = send_file(png_buf, mimetype="image/png")
        resp.headers["X-Label-Width"] = str(img.width)
        resp.headers["X-Label-Height"] = str(img.height)
        return resp
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@app.route("/print", methods=["POST"])
def do_print():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    size = int(data.get("size", 48))
    auto_cut = data.get("cut", True)

    if not text:
        return jsonify(ok=False, error="沒有文字"), 400

    size = max(16, min(128, size))

    try:
        img = render_label(text, font_size=size)
        raster = image_to_raster(img)
        print_data = build_print_data(raster, auto_cut=auto_cut)
        send_to_printer(print_data)
        n_lines = len(raster) // RASTER_LINE_BYTES
        cut_text = "自動裁切" if auto_cut else "不裁切"
        return jsonify(ok=True, message=f"已列印「{text}」({n_lines} lines, {cut_text})")
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9100, debug=False)
