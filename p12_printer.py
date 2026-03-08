#!/usr/bin/env python3
"""
AIMO P12 Pro / Phomemo P12 BLE Label Printer Driver

Uses Bluetooth Low Energy (GATT) to print on P12-series label printers.
Print head: 96 dots wide (12 bytes per line).

Protocol reverse-engineered from "Print Master" Android app.

GATT Service: 0000ff00
  ff01 - read
  ff02 - write (commands + image data)
  ff03 - notify (responses)

Usage:
  from p12_printer import P12Printer

  printer = P12Printer("61F4D059-...")  # BLE address
  await printer.print_text("Hello", font_size=48)
"""

import asyncio
import io
import os

from bleak import BleakClient, BleakScanner
from PIL import Image, ImageDraw, ImageFont

WRITE_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000ff03-0000-1000-8000-00805f9b34fb"

P12_DOTS = 96
P12_BYTES = P12_DOTS // 8  # 12

# Init packets from Print Master app
INIT_PACKETS = [
    bytes.fromhex("1f1138"),
    bytes.fromhex("1f11111f11121f11091f1113"),
    bytes.fromhex("1f1109"),
    bytes.fromhex("1f11191f1111"),
    bytes.fromhex("1f1119"),
    bytes.fromhex("1f1107"),
]

# Font search paths (Linux + macOS)
FONT_PATHS = [
    # Linux (Docker)
    "/usr/share/fonts/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    # macOS
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]


def _get_font(size):
    for fp in FONT_PATHS:
        try:
            return ImageFont.truetype(fp, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def render_p12_label(text, font_size=48):
    """Render text to a 1-bit image suitable for P12 Pro (96 dots wide)."""
    font = _get_font(font_size)
    dummy = Image.new("1", (1, 1), 0)
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    img_h = P12_DOTS
    img = Image.new("1", (tw, img_h), 0)  # black background
    draw = ImageDraw.Draw(img)
    y = (img_h - th) // 2 - bbox[1]
    draw.text((-bbox[0], y), text, font=font, fill=1)  # white text

    # Rotate 270° for printing (text along tape)
    rotated = img.rotate(270, expand=True)

    # Ensure width matches P12_DOTS
    if rotated.width != P12_DOTS:
        padded = Image.new("1", (P12_DOTS, rotated.height), 0)
        offset = P12_DOTS - rotated.width
        padded.paste(rotated, (offset, 0))
        rotated = padded

    return rotated


def _image_to_bytes(image):
    """Convert 1-bit image to raw bytes for printing."""
    width, height = image.size
    output = bytearray()
    for y_pos in range(height):
        byte = 0
        for x in range(width):
            pixel = 1 if image.getpixel((x, y_pos)) != 0 else 0
            byte |= (pixel & 0x1) << (7 - (x % 8))
            if (x % 8) == 7:
                output.append(byte)
                byte = 0
    return output


def render_p12_preview(text, font_size=48):
    """Render a preview PNG and return as BytesIO."""
    img = render_p12_label(text, font_size)
    # Convert to RGB for display
    rgb = Image.new("RGB", img.size, (255, 255, 255))
    for y in range(img.height):
        for x in range(img.width):
            if img.getpixel((x, y)):
                rgb.putpixel((x, y), (0, 0, 0))

    border = 2
    preview = Image.new("RGB",
        (rgb.width + border * 2, rgb.height + border * 2), (200, 200, 200))
    preview.paste(rgb, (border, border))

    buf = io.BytesIO()
    preview.save(buf, format="PNG")
    buf.seek(0)
    return buf, img.width, img.height


async def print_to_p12(address, text, font_size=48, scan_timeout=15):
    """
    Print text on a P12 Pro via BLE.

    Args:
        address: BLE address (UUID on macOS, MAC on Linux)
        text: text to print
        font_size: font size in pixels
        scan_timeout: BLE scan timeout in seconds

    Returns:
        dict with ok, message, or error
    """
    try:
        device = await BleakScanner.find_device_by_address(address, timeout=scan_timeout)
        if not device:
            return {"ok": False, "error": "P12Pro 找不到，請確認已開機"}

        async with BleakClient(device) as client:
            # Subscribe to notifications
            await client.start_notify(NOTIFY_UUID, lambda s, d: None)

            # Send init packets
            for packet in INIT_PACKETS:
                await client.write_gatt_char(WRITE_UUID, packet, response=False)
                await asyncio.sleep(0.1)

            # Render image
            img = render_p12_label(text, font_size)
            width, height = img.size

            # Print command: ESC @ GS v 0 00
            header = bytearray.fromhex("1b401d763000")
            header.extend((width // 8).to_bytes(2, byteorder="little"))
            header.extend(height.to_bytes(2, byteorder="little"))

            await client.write_gatt_char(WRITE_UUID, bytes(header), response=False)
            await asyncio.sleep(0.2)

            # Send image data in chunks
            raw = _image_to_bytes(img)
            chunk_size = 100
            for i in range(0, len(raw), chunk_size):
                chunk = raw[i:i + chunk_size]
                await client.write_gatt_char(WRITE_UUID, bytes(chunk), response=False)
                await asyncio.sleep(0.02)

            # Tape feed
            feed = bytearray.fromhex("1b640d1b640d")
            await client.write_gatt_char(WRITE_UUID, bytes(feed), response=False)
            await asyncio.sleep(1)

            await client.stop_notify(NOTIFY_UUID)

            return {"ok": True, "message": f"已列印「{text}」(P12 Pro, {height} lines)"}

    except Exception as e:
        return {"ok": False, "error": str(e)}


# CLI test
if __name__ == "__main__":
    import sys
    addr = os.environ.get("P12_ADDRESS", "61F4D059-21F7-6A9F-58CA-6ECC4DEF5896")
    text = sys.argv[1] if len(sys.argv) > 1 else "Hello 測試"
    result = asyncio.run(print_to_p12(addr, text))
    print(result)
