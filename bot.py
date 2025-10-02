import os
import threading
import subprocess
import zipfile
import random
import shutil
import re
from time import time
from pathlib import Path
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait
from dotenv import load_dotenv
import aria2p
from flask import Flask
import asyncio
import logging
import sys
import contextlib
import aiohttp
from urllib.parse import urlparse, unquote

logging.getLogger("pyrogram").setLevel(logging.WARNING)
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

# ------------------- Pyrogram & Flask -------------------
app = Client("url_upload_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "✅ Bot is running!"

def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

# ------------------- Paths & Cleanup -------------------
downloads_path = Path("downloads")
os.makedirs(downloads_path, exist_ok=True)
for f in downloads_path.iterdir():
    try:
        if f.is_file():
            f.unlink()
        elif f.is_dir():
            shutil.rmtree(f)
    except Exception as e:
        print(f"Error deleting {f}: {e}")

default_thumbnail_path = "https://i.ibb.co/zVQ7zJyS/image-2025-09-24-163452620.png"

# ------------------- Aria2c -------------------
aria2_process = subprocess.Popen([
    "aria2c",
    "--enable-rpc",
    "--rpc-listen-all=false",
    "--rpc-allow-origin-all",
    "--rpc-listen-port=6806",
    "--dir=downloads",
    "--max-concurrent-downloads=5",
    "--continue=true",
    "--split=5",
    "--max-connection-per-server=5",
    "--min-split-size=1M"
])
import time as t; t.sleep(2)
aria2 = aria2p.API(aria2p.Client(host="http://localhost", port=6806))

# ------------------- Globals -------------------
downloads = {}  # cancel_code: { "gid": str, "cancelled": False, "file_path": str, "status_msg": Message, "uploading": False }

# ------------------- Helpers -------------------
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

def progress_bar(percent: float, length: int = 12) -> str:
    filled = int(length * percent / 100)
    bar = "■" * filled + "□" * (length - filled)
    return f"[{bar}] {percent:.2f}%"

def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    name = re.sub(r'^\s*www\.[^ ]+\s*-\s*', '', name, flags=re.IGNORECASE)
    return name

def random_folder_name(length=5) -> str:
    return str(random.randint(10**(length-1), 10**length - 1))

async def get_filename_from_url(url: str) -> str:
    path = urlparse(url).path
    name = Path(unquote(path)).name
    if name:
        return sanitize_filename(name)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(url, allow_redirects=True) as resp:
                cd = resp.headers.get("Content-Disposition")
                if cd:
                    match = re.search(r'filename="?([^"]+)"?', cd)
                    if match:
                        return sanitize_filename(match.group(1))
    except:
        pass
    ext = Path(path).suffix or ".file"
    return f"{random_folder_name()}{ext}"

@contextlib.contextmanager
def suppress_stdout_stderr():
    with open(os.devnull, "w") as devnull:
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = devnull, devnull
        try:
            yield
        finally:
            sys.stdout, sys.stderr = old_out, old_err

# ------------------- Hachoir Media Info -------------------
LANGUAGE_MAP = {
    "en": "English", "hi": "Hindi", "ta": "Tamil", "te": "Telugu",
    "kn": "Kannada", "ml": "Malayalam", "mr": "Marathi", "bn": "Bengali",
    "gu": "Gujarati", "pa": "Punjabi", "ja": "Japanese", "ko": "Korean",
    "zh": "Chinese", "fr": "French", "de": "German", "es": "Spanish",
    "it": "Italian", "ru": "Russian", "ar": "Arabic",
}

def map_language(code: str) -> str:
    return LANGUAGE_MAP.get(code.lower().strip(), code.capitalize()) if code else ""

def detect_quality(height: int) -> str:
    if height >= 2160: return "4K"
    if height >= 1440: return "2K"
    if height >= 1080: return "1080p"
    if height >= 720: return "720p"
    if height >= 480: return "480p"
    return f"{height}p"

def get_media_info(file_path: str) -> str:
    parser = createParser(file_path)
    if not parser:
        return "**Could not parse file**"
    metadata = extractMetadata(parser)
    if not metadata:
        return "**Could not extract metadata**"

    video_qualities = set()
    audios = []
    subtitles = set()
    duration_str = "Unknown"

    try:
        dur = metadata.get('duration').seconds if metadata.has('duration') else 0
        if dur:
            hours = dur // 3600
            minutes = (dur % 3600) // 60
            seconds = dur % 60
            duration_str = f"{hours}h{minutes}m{seconds}s" if hours else f"{minutes}m{seconds}s"
    except:
        pass

    lines = metadata.exportPlaintext()
    current_track = None
    for line in lines:
        line = line.strip()
        if line.startswith("Video stream"): current_track = "video"
        elif line.startswith("Audio stream"): current_track = "audio"
        elif line.startswith("Subtitle"): current_track = "subtitle"
        else:
            if current_track == "video":
                m = re.search(r"Image height:\s*(\d+)", line)
                if m: video_qualities.add(detect_quality(int(m.group(1))))
            elif current_track == "audio":
                m = re.search(r"Language:\s*(\w+)", line)
                if m:
                    lang = map_language(m.group(1))
                    if lang not in audios: audios.append(lang)
            elif current_track == "subtitle":
                m = re.search(r"Language:\s*(\w+)", line)
                if m: subtitles.add(map_language(m.group(1)))

    video_text = ", ".join(sorted(video_qualities)) or "Unknown"
    audio_text = ", ".join(audios) if audios else "Unknown"
    subtitle_text = ", ".join(sorted(subtitles)) if subtitles else "None"

    return f"**🎬 {video_text} | ⏳ {duration_str}\n🔊 {audio_text}\n💬 {subtitle_text}**"

# ------------------- Upload File -------------------
async def upload_file(client: Client, chat_id: int, file_path: str, status_message: Message, cancel_code: str):
    file_name = Path(file_path).stem
    media_caption = get_media_info(file_path)
    start_time = time()
    last_update = 0

    downloads[cancel_code]["uploading"] = True

    async def progress(current, total, _):
        nonlocal last_update
        now = time()
        if now - last_update >= 3:
            if cancel_code not in downloads or downloads[cancel_code]["cancelled"]:
                raise asyncio.CancelledError
            percent = current * 100 / total if total else 0
            elapsed = int(now - start_time)
            speed = current / elapsed if elapsed > 0 else 0
            try:
                cancel_button = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{cancel_code}")]]
                )
                await status_message.edit(
                    f"⬆️ Uploading `{file_name}`\n"
                    f"{progress_bar(percent)}\n"
                    f"Uploaded: {current/1024/1024:.2f} MB / {total/1024/1024:.2f} MB\n"
                    f"Speed: {speed/1024/1024:.2f} MB/s | Elapsed: {elapsed}s",
                    reply_markup=cancel_button
                )
            except:
                pass
            last_update = now

    try:
        with suppress_stdout_stderr():
            await client.send_document(
                chat_id=chat_id,
                document=file_path,
                caption=f"**{file_name}**\n\n{media_caption}",
                thumb=None,  # no tgcrypto thumbnail check
                progress=progress,
                progress_args=(os.path.getsize(file_path),)
            )
    except asyncio.CancelledError:
        await status_message.edit(f"❌ Upload cancelled: `{file_name}`", reply_markup=None)
    finally:
        downloads.pop(cancel_code, None)

# ------------------- Extract & Upload -------------------
async def extract_and_upload(client, channel_id: int, zip_path: str, status_message: Message, cancel_code: str):
    if not zipfile.is_zipfile(zip_path):
        await status_message.edit(f"❌ `{Path(zip_path).name}` is not a valid zip file.", reply_markup=None)
        downloads.pop(cancel_code, None)
        return

    extract_dir = Path("downloads") / random_folder_name()
    os.makedirs(extract_dir, exist_ok=True)
    await status_message.edit(f"🗜 Extracting `{Path(zip_path).name}` to `{extract_dir.name}`...")

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    for f in Path(extract_dir).rglob("*"):
        if cancel_code not in downloads or downloads[cancel_code]["cancelled"]:
            shutil.rmtree(extract_dir)
            os.remove(zip_path)
            return
        if f.is_file():
            safe_name = sanitize_filename(f.name)
            safe_path = f.parent / safe_name
            if f != safe_path: f.rename(safe_path)
            await upload_file(client, channel_id, str(safe_path), status_message, cancel_code)
            os.remove(safe_path)

    shutil.rmtree(extract_dir)
    os.remove(zip_path)
    if cancel_code in downloads:
        await status_message.edit("✅ Zip extracted and all files uploaded successfully.", reply_markup=None)
        downloads.pop(cancel_code, None)

# ------------------- Monitor Download -------------------
async def monitor_download(cancel_code: str, client: Client):
    while cancel_code in downloads:
        gid = downloads[cancel_code]["gid"]
        status_msg = downloads[cancel_code]["status_msg"]
        try:
            download = aria2.get_download(gid)
            if downloads[cancel_code]["cancelled"]:
                aria2.remove([download], force=True, files=True)
                await status_msg.edit("❌ Download cancelled by user.", reply_markup=None)
                downloads.pop(cancel_code)
                return

            percent = download.progress
            speed = download.download_speed / 1024 / 1024
            total = download.total_length / 1024 / 1024 if download.total_length else 0
            done = download.completed_length / 1024 / 1024

            cancel_button = InlineKeyboardMarkup(
                [[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{cancel_code}")]]
            )

            await status_msg.edit(
                f"{Path(downloads[cancel_code]['file_path']).name}\n"
                f"┃ {progress_bar(percent)}\n"
                f"┠ Processed: {done:.2f} MiB of {total:.2f} MiB\n"
                f"┠ Status: {download.status}  | Speed: {speed:.2f} MB/s",
                reply_markup=cancel_button
            )

            if download.is_complete:
                if cancel_code not in downloads or downloads[cancel_code]["cancelled"]:
                    return
                file_path = downloads[cancel_code]["file_path"]
                if zipfile.is_zipfile(file_path):
                    await extract_and_upload(client, CHANNEL_ID, file_path, status_msg, cancel_code)
                else:
                    await upload_file(client, CHANNEL_ID, file_path, status_msg, cancel_code)
                    if os.path.exists(file_path):
                        os.remove(file_path)
                return
        except Exception:
            pass
        await asyncio.sleep(2)

# ------------------- Callback Query Handler -------------------
@app.on_callback_query()
async def handle_cancel(client, callback_query):
    data = callback_query.data
    if not data.startswith("cancel_"):
        return

    cancel_code = data.split("_", 1)[1]
    if cancel_code in downloads:
        downloads[cancel_code]["cancelled"] = True
        await callback_query.answer("❌ Cancel requested!")
        status_msg = downloads[cancel_code]["status_msg"]
        await status_msg.edit(f"❌ Cancel requested by user", reply_markup=None)
    else:
        await callback_query.answer("❌ Already completed or invalid.", show_alert=True)

# ------------------- Command Handlers -------------------
@app.on_message(filters.command("start") & filters.private)
async def start_handler(client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply("🚫 Not authorized.")
        return
    await message.reply("👋 Send a file URL. Append `-e` to extract zip or `newname` to rename.")

@app.on_message(filters.private & filters.text)
async def url_handler(client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply("🚫 Not authorized.")
        return

    text = message.text.strip()
    extract_zip = False
    new_filename = None

    if text.endswith(" -e"):
        extract_zip = True
        text = text[:-3].strip()
    if " " in text:
        parts = text.split()
        url = parts[0]
        new_filename = parts[1]
    else:
        url = text

    basename = Path(unquote(urlparse(url).path)).name
    if basename:
        filename = sanitize_filename(basename)
    elif new_filename:
        filename = sanitize_filename(new_filename)
    else:
        filename = await get_filename_from_url(url)

    file_path = downloads_path / filename
    status_message = await message.reply(f"📥 Starting download: `{filename}`")

    download = aria2.add_uris([url], {"dir": str(downloads_path), "out": filename})

    cancel_code = str(random.randint(1000000, 9999999))
    downloads[cancel_code] = {
        "gid": download.gid,
        "cancelled": False,
        "file_path": str(file_path),
        "status_msg": status_message,
        "uploading": False
    }

    asyncio.create_task(monitor_download(cancel_code, client))

# ------------------- Run Bot -------------------
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("Starting bot...")
    app.run()
