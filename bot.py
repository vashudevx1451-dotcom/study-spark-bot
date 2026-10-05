#!/usr/bin/env python3
"""
Study Spark Official Video Downloader Bot
- Clean, consistent normal font with bold header and minimal friendly emojis
- 100% RGB Colored Inline Buttons (primary Blue, success Green, danger Red)
- Simple User Flow: Only Channel, Group, and Continue buttons
- Auto-Delete Everything (both user and bot messages) so ONLY videos remain in chat
- Smart Quality Detection: Asks for quality ONLY if link has multiple qualities; otherwise simple Confirm & Download
- Button-Driven Admin Panel: All admin features work via interactive RGB buttons (no command text clutter)
"""

import os
import sys
import time
import math
import json
import re
import html
import asyncio
import shutil
import urllib.parse
from datetime import datetime
import aiohttp
import uuid

pending_confirmations: dict[str, dict] = {}
active_task_controllers: dict[str, dict] = {}
pending_join_messages: dict[int, tuple[int, int]] = {}
join_prompt_shown_at: dict[int, float] = {}
join_verify_attempts: dict[int, int] = {}
admin_pending_input: dict[int, dict] = {}

# Bot Configuration & Credentials
BOT_TOKEN = os.getenv("BOT_TOKEN", "8556372017:AAEZkll20Z4WEWYJPG1iS0pvX-YVymH_J20")
API_ID = int(os.getenv("API_ID", "39902940"))
API_HASH = os.getenv("API_HASH", "9f37fc6282079681fd4c1bb55916a758")

DOWNLOAD_DIR = "/tmp/tg_bot_downloads"
STATUS_FILE = "/tmp/tg_bot_status.json"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "data", "bot_config.json")
USERS_PATH = os.path.join(BASE_DIR, "data", "users.json")

os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ----------------- Configuration & Storage ----------------- #

def load_config() -> dict:
    defaults = {
        "owners": ["i_am_athexcs", "uhtkarshh", "6672896116"],
        "admins": [],
        "channel_link": "https://t.me/+MTEe8PsICfIzNjll",
        "channel_title": "STUDYSPARK TEAM OFFICIAL",
        "channel_id": "",
        "group_link": "https://t.me/+70B18PiliPhkNDdk",
        "group_title": "Studyspark leech group",
        "group_id": "",
        "allowed_patterns": []
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                data = json.load(f)
                return {**defaults, **data}
        except Exception:
            pass
    return defaults

def save_config(cfg: dict):
    global bot_config
    bot_config = cfg
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"[Save Config Error] {e}")

bot_config = load_config()

def is_url_allowed(url: str) -> tuple[bool, str]:
    cfg = load_config()
    patterns = cfg.get("allowed_patterns", [])
    if not patterns:
        return True, ""
    url_lower = url.lower()
    for p in patterns:
        p_clean = p.strip().lower()
        if p_clean and p_clean in url_lower:
            return True, ""
    return False, ", ".join(patterns)

def load_users() -> dict:
    defaults = {"all_users": [], "verified_users": []}
    if os.path.exists(USERS_PATH):
        try:
            with open(USERS_PATH, "r") as f:
                data = json.load(f)
                return {
                    "all_users": list(set(data.get("all_users", []))),
                    "verified_users": list(set(data.get("verified_users", [])))
                }
        except Exception:
            pass
    return defaults

def save_users(data: dict):
    try:
        with open(USERS_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[Save Users Error] {e}")

users_store = load_users()

def register_user(user_id: int):
    if not user_id:
        return
    if user_id not in users_store["all_users"]:
        users_store["all_users"].append(user_id)
        save_users(users_store)

def mark_verified(user_id: int):
    if not user_id:
        return
    register_user(user_id)
    if user_id not in users_store["verified_users"]:
        users_store["verified_users"].append(user_id)
        save_users(users_store)

def unmark_verified(user_id: int):
    if not user_id:
        return
    if user_id in users_store["verified_users"]:
        users_store["verified_users"].remove(user_id)
        save_users(users_store)

def is_verified(user_id: int) -> bool:
    return user_id in users_store["verified_users"]

def is_owner(user_obj) -> bool:
    if not user_obj:
        return False
    cfg = load_config()
    user_id = user_obj.get("id") if isinstance(user_obj, dict) else getattr(user_obj, "id", None)
    username = (user_obj.get("username") if isinstance(user_obj, dict) else getattr(user_obj, "username", None)) or ""
    username = username.lower().lstrip("@")
    owners = [str(o).lower().lstrip("@") for o in cfg.get("owners", ["i_am_athexcs", "uhtkarshh", "6672896116"])]
    if username and username in owners:
        return True
    if user_id and (str(user_id) in owners or user_id == 6672896116):
        return True
    return False

def is_admin(user_obj) -> bool:
    if not user_obj:
        return False
    if is_owner(user_obj):
        return True
    cfg = load_config()
    user_id = user_obj.get("id") if isinstance(user_obj, dict) else getattr(user_obj, "id", None)
    username = (user_obj.get("username") if isinstance(user_obj, dict) else getattr(user_obj, "username", None)) or ""
    username = username.lower().lstrip("@")
    admins = [str(a).lower().lstrip("@") for a in cfg.get("admins", [])]
    if username and username in admins:
        return True
    if user_id and str(user_id) in admins:
        return True
    return False

# ----------------- Downloader & State Helpers ----------------- #

def find_ytdlp_bin():
    candidates = [
        "/tmp/bot_venv/bin/yt-dlp",
        os.path.join(BASE_DIR, "venv", "bin", "yt-dlp"),
        shutil.which("yt-dlp")
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return "/tmp/bot_venv/bin/yt-dlp"

def is_hls_url(url: str) -> bool:
    u = url.lower()
    clean = u.split("?")[0]
    return (
        clean.endswith(".m3u8")
        or ".m3u8" in u
        or "m3u8" in u
        or "/hls/" in u
    )

def is_direct_media_url(url: str) -> bool:
    if is_hls_url(url):
        return False
    clean = url.split("?")[0].lower()
    exts = ('.mp4', '.mkv', '.webm', '.avi', '.mov', '.m4v', '.ts', '.flv')
    if any(clean.endswith(ext) for ext in exts):
        return True
    parsed = urllib.parse.urlparse(url)
    if any(ext in parsed.path.lower() for ext in exts):
        return True
    return False

YTDLP_BIN = find_ytdlp_bin()
MAX_CONCURRENT_DOWNLOADS = 5
semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

bot_state = {
    "status": "online",
    "started_at": time.time(),
    "active_downloads": 0,
    "completed_downloads": 0,
    "total_bytes_processed": 0,
    "bot_username": "AuraOTP_robot",
    "bot_name": "Study Spark Downloader 🔥",
    "current_tasks": [],
    "recent_activity": []
}

def save_bot_state():
    try:
        data = {
            "status": bot_state["status"],
            "started_at": bot_state["started_at"],
            "active_downloads": bot_state["active_downloads"],
            "completed_downloads": bot_state["completed_downloads"],
            "total_bytes_processed": bot_state["total_bytes_processed"],
            "bot_username": bot_state["bot_username"],
            "bot_name": bot_state["bot_name"],
            "current_tasks": bot_state["current_tasks"],
            "recent_activity": bot_state["recent_activity"][:25]
        }
        with open(STATUS_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"[State Error] {e}", file=sys.stderr)

def log_activity(action: str, details: str):
    entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "action": action,
        "details": details
    }
    bot_state["recent_activity"].insert(0, entry)
    bot_state["recent_activity"] = bot_state["recent_activity"][:25]
    print(f"[{entry['time']}] [{action}] {details}")
    save_bot_state()

def format_size(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {units[i]}"

def format_time(seconds: float) -> str:
    if seconds <= 0 or math.isinf(seconds):
        return "--"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    else:
        return f"{s}s"

async def safe_delete(chat_id: int, message_id: int):
    if not chat_id or not message_id:
        return
    try:
        await tg.delete_message(chat_id, message_id)
    except Exception:
        pass

async def auto_delete_message(chat_id: int, message_id: int, delay_seconds: float = 3.5):
    if not chat_id or not message_id:
        return
    try:
        await asyncio.sleep(delay_seconds)
        await tg.delete_message(chat_id, message_id)
    except Exception:
        pass

async def send_temp_message(chat_id: int, text: str, delay_seconds: float = 3.5, reply_markup: dict = None):
    try:
        resp = await tg.send_message(chat_id, text, reply_markup=reply_markup)
        mid = resp.get("result", {}).get("message_id")
        if mid and delay_seconds > 0:
            asyncio.create_task(auto_delete_message(chat_id, mid, delay_seconds))
        return mid
    except Exception:
        return None

def make_progress_bar(percentage: float, length: int = 10) -> str:
    filled = int(round(length * percentage / 100))
    filled = max(0, min(length, filled))
    return "█" * filled + "░" * (length - filled)

def get_clean_title_and_filename(filepath: str, probed_title: str = "", quality_hint: str = "") -> tuple[str, str]:
    raw_base = os.path.basename(filepath)
    name_no_ext, ext = os.path.splitext(raw_base)
    if not ext:
        ext = ".mp4"

    quality_match = re.search(r'(1080p|720p|480p|360p|240p|2k|4k)', name_no_ext, re.IGNORECASE)
    quality = quality_match.group(1).lower() if quality_match else (quality_hint if quality_hint in ("1080p", "720p", "480p", "360p") else "")

    is_uuid = bool(re.search(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', name_no_ext))
    is_hex_hash = bool(re.search(r'^[0-9a-fA-F]{24,64}', name_no_ext))
    is_generic_hls = name_no_ext.lower() in ("playlist", "master", "index", "video", "hls_video", "study_spark_hls_video")
    is_random = is_uuid or is_hex_hash or is_generic_hls or len(re.sub(r'[^0-9a-fA-F]', '', name_no_ext)) >= 24

    if probed_title and len(probed_title) > 2 and not re.search(r'[0-9a-fA-F]{16,}', probed_title):
        clean_title = probed_title.strip()
    elif not is_random:
        clean = re.sub(r'[_\-]+', ' ', name_no_ext).strip()
        clean = re.sub(r'\[[a-zA-Z0-9_\-]+\]', '', clean).strip()
        clean_title = clean if len(clean) > 3 else "Study Spark Video"
    else:
        if quality:
            clean_title = f"Study Spark Video ({quality})"
        else:
            clean_title = "Study Spark Video"

    if quality and quality.lower() not in clean_title.lower():
        clean_title = f"{clean_title} ({quality})"

    safe_name = re.sub(r'[^\w\-]', '_', clean_title).strip('_')
    safe_name = re.sub(r'_+', '_', safe_name)
    clean_filename = f"{safe_name}{ext}"

    return clean_title, clean_filename

async def probe_video_metadata(filepath: str):
    width, height, duration = 1280, 720, 0
    title = ""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration:stream=width,height:format_tags=title",
            "-of", "default=noprint_wrappers=1",
            filepath
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode().splitlines()
        for line in lines:
            if line.startswith("width="):
                try:
                    width = int(line.split("=")[1])
                except Exception:
                    pass
            elif line.startswith("height="):
                try:
                    height = int(line.split("=")[1])
                except Exception:
                    pass
            elif line.startswith("duration="):
                try:
                    duration = int(float(line.split("=")[1]))
                except Exception:
                    pass
            elif line.startswith("TAG:title="):
                title = line.split("=", 1)[1].strip()
    except Exception as e:
        print(f"[ffprobe error] {e}")
    return width, height, duration, title

async def extract_thumbnail(filepath: str, out_thumb_path: str) -> str:
    try:
        cmd = [
            "ffmpeg", "-y",
            "-ss", "00:00:01",
            "-i", filepath,
            "-vframes", "1",
            "-q:v", "2",
            out_thumb_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        if os.path.exists(out_thumb_path) and os.path.getsize(out_thumb_path) > 100:
            return out_thumb_path
    except Exception as e:
        print(f"[ffmpeg thumb error] {e}")
    return None

# ----------------- Smart Multi-Quality Detection ----------------- #

async def detect_available_qualities(url: str) -> list[str]:
    """
    Checks if the link actually offers multiple selectable video qualities.
    - Direct .mp4 / single-file links -> returns [] (only simple Confirm & Download is shown)
    - Master .m3u8 playlist with multiple resolutions -> returns available qualities (e.g. ['1080p', '720p', '480p', '360p'])
    """
    if is_direct_media_url(url):
        return []
    if is_hls_url(url):
        try:
            sess = await tg.get_session()
            async with sess.get(url, timeout=aiohttp.ClientTimeout(total=3.5)) as resp:
                if resp.status == 200:
                    body = await resp.text(errors="ignore")
                    if "#EXT-X-STREAM-INF" in body:
                        found = set()
                        for m in re.finditer(r'RESOLUTION=\d+x(\d+)', body):
                            h = int(m.group(1))
                            if h >= 1000:
                                found.add("1080p")
                            elif h >= 700:
                                found.add("720p")
                            elif h >= 450:
                                found.add("480p")
                            elif h >= 200:
                                found.add("360p")
                        order = [q for q in ("1080p", "720p", "480p", "360p") if q in found]
                        if len(order) >= 2:
                            return order
        except Exception:
            pass
    return []

# ----------------- RGB Inline Keyboards ----------------- #

def build_join_markup() -> dict:
    """
    User Panel: ONLY Channel, Group, and Continue in RGB colors.
    Row 1: [ 📢 Channel ↗ ] (Blue primary) | [ 💬 Group ↗ ] (Blue primary)
    Row 2: [ ✅ Continue ] (Green success)
    """
    cfg = load_config()
    channel_url = cfg.get("channel_link", "https://t.me/+MTEe8PsICfIzNjll")
    group_url = cfg.get("group_link", "https://t.me/+70B18PiliPhkNDdk")
    return {
        "inline_keyboard": [
            [
                {"text": "📢 Channel ↗", "url": channel_url, "style": "primary"},
                {"text": "💬 Group ↗", "url": group_url, "style": "primary"}
            ],
            [
                {"text": "✅ Continue", "callback_data": "continue_start", "style": "success"}
            ]
        ]
    }

def build_confirm_markup(token: str, qualities: list[str] = None) -> dict:
    """
    If multiple qualities exist in the stream, shows RGB quality buttons + Cancel.
    Otherwise shows ONLY [ ✅ Download ] (Green) and [ ✖ Cancel ] (Red).
    """
    if qualities and len(qualities) >= 2:
        rows = []
        row = []
        for idx, q in enumerate(qualities):
            style = "success" if idx == 0 else "primary"
            row.append({"text": f"🎬 {q}", "callback_data": f"confirm_dl:{token}:{q}", "style": style})
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([{"text": "✖ Cancel", "callback_data": f"cancel_confirm:{token}", "style": "danger"}])
        return {"inline_keyboard": rows}

    return {
        "inline_keyboard": [
            [
                {"text": "✅ Download", "callback_data": f"confirm_dl:{token}:best", "style": "success"},
                {"text": "✖ Cancel", "callback_data": f"cancel_confirm:{token}", "style": "danger"}
            ]
        ]
    }

def build_admin_panel_markup() -> dict:
    """
    Rich RGB Button-Driven Admin Panel (No command text clutter, all actions on buttons).
    Uses only RGB styles: primary (Blue), success (Green), danger (Red).
    """
    return {
        "inline_keyboard": [
            [
                {"text": "📊 Live Stats", "callback_data": "adm_stats", "style": "primary"},
                {"text": "👥 Team & Admins", "callback_data": "adm_team", "style": "primary"}
            ],
            [
                {"text": "📢 Broadcast", "callback_data": "adm_broadcast", "style": "success"},
                {"text": "⚡ System Status", "callback_data": "adm_ping", "style": "success"}
            ],
            [
                {"text": "➕ Add Admin", "callback_data": "adm_add_admin", "style": "success"},
                {"text": "➖ Remove Admin", "callback_data": "adm_del_admin", "style": "danger"}
            ],
            [
                {"text": "📢 Set Channel", "callback_data": "adm_set_channel", "style": "primary"},
                {"text": "💬 Set Group", "callback_data": "adm_set_group", "style": "primary"}
            ],
            [
                {"text": "🔗 Set Domain", "callback_data": "adm_set_domain", "style": "primary"},
                {"text": "🔓 Allow All Links", "callback_data": "adm_clear_domain", "style": "success"}
            ],
            [
                {"text": "🔄 Reset Verify", "callback_data": "adm_reset_verify", "style": "danger"},
                {"text": "🧹 Clean Cache", "callback_data": "adm_clean_cache", "style": "danger"}
            ],
            [
                {"text": "✖ Close", "callback_data": "adm_close", "style": "danger"}
            ]
        ]
    }

def build_admin_back_markup() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "🔙 Back to Panel", "callback_data": "adm_back", "style": "primary"},
                {"text": "✖ Close", "callback_data": "adm_close", "style": "danger"}
            ]
        ]
    }

def build_admin_cancel_input_markup() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "🔙 Cancel", "callback_data": "adm_back", "style": "danger"}
            ]
        ]
    }

# ----------------- Telegram Bot API Client ----------------- #

class TelegramClient:
    def __init__(self, token: str):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.session = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def request(self, method: str, data: dict = None, files: dict = None, timeout: int = 35) -> dict:
        sess = await self.get_session()
        url = f"{self.base_url}/{method}"
        try:
            if files:
                form = aiohttp.FormData()
                if data:
                    for k, v in data.items():
                        if v is not None:
                            form.add_field(k, str(v))
                for field_name, file_tuple in files.items():
                    filename, file_obj, content_type = file_tuple
                    form.add_field(field_name, file_obj, filename=filename, content_type=content_type)
                async with sess.post(url, data=form, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    return await resp.json()
            elif data:
                async with sess.post(url, json=data, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    return await resp.json()
            else:
                async with sess.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    return await resp.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def send_message(self, chat_id: int, text: str, reply_markup: dict = None, parse_mode: str = "HTML") -> dict:
        payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if parse_mode:
            payload["parse_mode"] = parse_mode
        res = await self.request("sendMessage", data=payload)
        if not res.get("ok") and parse_mode:
            plain = re.sub(r'<[^>]+>', '', text)
            payload["text"] = html.escape(plain)
            res = await self.request("sendMessage", data=payload)
        return res

    async def edit_message_text(self, chat_id: int, message_id: int, text: str, reply_markup: dict = None, parse_mode: str = "HTML") -> dict:
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "disable_web_page_preview": True}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if parse_mode:
            payload["parse_mode"] = parse_mode
        res = await self.request("editMessageText", data=payload)
        if not res.get("ok") and parse_mode and "message is not modified" not in str(res.get("description", "")):
            plain = re.sub(r'<[^>]+>', '', text)
            payload["text"] = html.escape(plain)
            res = await self.request("editMessageText", data=payload)
        return res

    async def delete_message(self, chat_id: int, message_id: int) -> dict:
        return await self.request("deleteMessage", data={"chat_id": chat_id, "message_id": message_id})

    async def answer_callback_query(self, callback_query_id: str, text: str = None, show_alert: bool = False) -> dict:
        payload = {"callback_query_id": callback_query_id, "show_alert": show_alert}
        if text:
            payload["text"] = text
        return await self.request("answerCallbackQuery", data=payload)

    async def get_chat_member(self, chat_id, user_id: int) -> dict:
        return await self.request("getChatMember", data={"chat_id": chat_id, "user_id": user_id})

    async def set_my_commands(self, commands: list) -> dict:
        return await self.request("setMyCommands", data={"commands": commands})

    async def set_chat_menu_button(self, chat_id: int = None, menu_button: dict = None) -> dict:
        payload = {"menu_button": menu_button or {"type": "commands"}}
        if chat_id:
            payload["chat_id"] = chat_id
        return await self.request("setChatMenuButton", data=payload)

    async def send_video(self, chat_id: int, video_path: str, caption: str = None, duration: int = None, width: int = None, height: int = None, thumb_path: str = None) -> dict:
        data = {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "HTML",
            "supports_streaming": True,
            "duration": duration,
            "width": width,
            "height": height
        }
        files = {
            "video": (os.path.basename(video_path), open(video_path, "rb"), "video/mp4")
        }
        if thumb_path and os.path.exists(thumb_path):
            files["thumb"] = ("thumb.jpg", open(thumb_path, "rb"), "image/jpeg")

        return await self.request("sendVideo", data=data, files=files, timeout=600)

tg = TelegramClient(BOT_TOKEN)
pyro_client = None

# ----------------- Real Channel & Group Membership Verification ----------------- #

def extract_public_username(link: str) -> str:
    if not link:
        return ""
    parsed = urllib.parse.urlparse(link.strip())
    path = parsed.path.strip("/")
    if not path or path.startswith("+") or path.startswith("joinchat/"):
        return ""
    if re.match(r'^[a-zA-Z0-9_]{4,}$', path):
        return f"@{path}"
    return ""

async def check_single_chat_membership(target_chat, user_id: int) -> tuple[bool, bool]:
    if not target_chat:
        return False, False
    try:
        chat_ref = int(target_chat) if str(target_chat).lstrip("-").isdigit() else str(target_chat)
        res = await tg.get_chat_member(chat_ref, user_id)
        if not res.get("ok"):
            return False, False
        member_info = res.get("result", {})
        status = member_info.get("status", "")
        if status in ("creator", "administrator", "member"):
            return True, True
        if status == "restricted":
            return True, bool(member_info.get("is_member", False))
        return True, False
    except Exception:
        return False, False

async def verify_user_joined(user_id: int, is_button_click: bool = False) -> tuple[bool, str]:
    cfg = load_config()
    raw_ch_id = str(cfg.get("channel_id") or "").strip()
    raw_gr_id = str(cfg.get("group_id") or "").strip()
    if raw_gr_id.startswith("-207"):
        raw_gr_id = ""

    channel_target = extract_public_username(cfg.get("channel_link", "")) or raw_ch_id
    group_target = extract_public_username(cfg.get("group_link", "")) or raw_gr_id

    ch_active, ch_joined = await check_single_chat_membership(channel_target, user_id)
    gr_active, gr_joined = await check_single_chat_membership(group_target, user_id)

    if ch_active or gr_active:
        if ch_active and gr_active:
            if not ch_joined and not gr_joined:
                unmark_verified(user_id)
                return False, "Please join both Channel and Group first!"
            if not ch_joined:
                unmark_verified(user_id)
                return False, "Please join the Channel first!"
            if not gr_joined:
                unmark_verified(user_id)
                return False, "Please join the Group first!"
            mark_verified(user_id)
            return True, ""
        elif ch_active:
            if not ch_joined:
                unmark_verified(user_id)
                return False, "Please join the Channel first!"
            mark_verified(user_id)
            return True, ""
        elif gr_active:
            if not gr_joined:
                unmark_verified(user_id)
                return False, "Please join the Group first!"
            mark_verified(user_id)
            return True, ""

    if not is_button_click:
        if is_verified(user_id):
            return True, ""
        return False, "Please join both Channel and Group first!"

    shown_time = join_prompt_shown_at.get(user_id, 0.0)
    attempts = join_verify_attempts.get(user_id, 0) + 1
    join_verify_attempts[user_id] = attempts
    elapsed = time.time() - shown_time

    if attempts == 1 and elapsed < 6.0:
        return (
            False,
            "Please join both Channel and Group first, then tap Continue!"
        )

    mark_verified(user_id)
    return True, ""

# ----------------- Bot Menu Commands ----------------- #

MENU_COMMANDS = [
    {"command": "start", "description": "Start the bot"},
    {"command": "help", "description": "How to download videos"},
    {"command": "admin", "description": "Admin control panel"},
]

async def sync_menu_commands():
    try:
        await tg.set_my_commands(MENU_COMMANDS)
        await tg.set_chat_menu_button()
        print("[Menu Setup] Bot menu commands registered successfully.")
    except Exception as e:
        print(f"[Menu Setup Error] {e}")

# ----------------- Consistent, Friendly Message Templates ----------------- #

def get_join_prompt_text() -> str:
    return (
        "<b>Study Spark Downloader 🔥</b>\n\n"
        "Welcome! Please join our official channel and group to use this bot.\n\n"
        "Tap <b>Continue</b> once you have joined."
    )

def get_direct_welcome_text() -> str:
    return (
        "<b>Study Spark Downloader 🔥</b>\n\n"
        "You are all set! Send your Study Spark video link below to download."
    )

def get_admin_panel_text() -> str:
    cfg = load_config()
    total_u = len(users_store["all_users"])
    ver_u = len(users_store["verified_users"])
    active = bot_state["active_downloads"]
    done = bot_state["completed_downloads"]
    patterns = cfg.get("allowed_patterns", [])
    dom_str = ", ".join(patterns) if patterns else "All links allowed"

    return (
        "<b>Study Spark Admin Panel 🔥</b>\n\n"
        f"• <b>Total Users:</b> {total_u} (Verified: {ver_u})\n"
        f"• <b>Videos Sent:</b> {done} (Active: {active})\n"
        f"• <b>Allowed Domains:</b> {html.escape(dom_str)}\n\n"
        "Select an option below:"
    )

# ----------------- Command & Event Handlers ----------------- #

async def handle_start(message: dict):
    from_user = message.get("from", {})
    user_id = from_user.get("id")
    chat_id = message.get("chat", {}).get("id")
    msg_id = message.get("message_id")
    register_user(user_id)

    # Delete user's /start command immediately
    await safe_delete(chat_id, msg_id)

    # Delete previous pending join/welcome prompt if any
    old_chat, old_mid = pending_join_messages.pop(user_id, (None, None))
    if old_chat and old_mid:
        await safe_delete(old_chat, old_mid)

    joined_ok, _ = await verify_user_joined(user_id, is_button_click=False)
    if joined_ok:
        # Keep the bot's first response in chat so Telegram does not reset to the START loop!
        resp = await tg.send_message(chat_id, get_direct_welcome_text())
        mid = resp.get("result", {}).get("message_id")
        if mid:
            pending_join_messages[user_id] = (chat_id, mid)
        return

    join_prompt_shown_at[user_id] = time.time()
    join_verify_attempts[user_id] = 0
    resp = await tg.send_message(
        chat_id,
        get_join_prompt_text(),
        reply_markup=build_join_markup()
    )
    mid = resp.get("result", {}).get("message_id")
    if mid:
        pending_join_messages[user_id] = (chat_id, mid)

async def handle_help(message: dict):
    from_user = message.get("from", {})
    user_id = from_user.get("id")
    chat_id = message.get("chat", {}).get("id")
    msg_id = message.get("message_id")
    register_user(user_id)

    await safe_delete(chat_id, msg_id)

    text = (
        "<b>Study Spark Downloader 🔥</b>\n\n"
        "1. Copy your Study Spark video or stream link.\n"
        "2. Send the link in this chat.\n"
        "3. Tap <b>Download</b> to receive your video."
    )
    await send_temp_message(chat_id, text, delay_seconds=6.0)

async def handle_admin(message: dict):
    from_user = message.get("from", {})
    user_id = from_user.get("id")
    chat_id = message.get("chat", {}).get("id")
    msg_id = message.get("message_id")

    await safe_delete(chat_id, msg_id)
    admin_pending_input.pop(user_id, None)

    if not is_admin(from_user):
        await send_temp_message(chat_id, "<b>Study Spark Downloader 🔥</b>\n\nAccess denied. Admins only.", delay_seconds=3.0)
        return

    await tg.send_message(chat_id, get_admin_panel_text(), reply_markup=build_admin_panel_markup())

async def handle_admin_text_input(message: dict) -> bool:
    """
    Handles interactive text input after an Admin clicks a button like
    Set Channel, Set Group, Set Domain, Add Admin, Remove Admin, or Broadcast.
    Immediately deletes both the user's message and the prompt message!
    """
    from_user = message.get("from", {})
    user_id = from_user.get("id")
    chat_id = message.get("chat", {}).get("id")
    msg_id = message.get("message_id")
    text = (message.get("text") or "").strip()

    state = admin_pending_input.pop(user_id, None)
    if not state:
        return False

    prompt_mid = state.get("prompt_mid")
    action = state.get("action")

    # Immediately delete both admin's reply and bot's prompt
    await safe_delete(chat_id, msg_id)
    if prompt_mid:
        await safe_delete(chat_id, prompt_mid)

    cfg = load_config()

    if action == "add_admin":
        target = text.lstrip("@").strip().lower()
        if target:
            existing = [a.lower() for a in cfg.get("admins", [])]
            if target not in existing:
                cfg["admins"].append(target)
                save_config(cfg)
            await send_temp_message(chat_id, f"<b>Study Spark Admin 🔥</b>\n\n@{html.escape(target)} added as Admin.", delay_seconds=3.5)

    elif action == "del_admin":
        target = text.lstrip("@").strip().lower()
        cfg["admins"] = [a for a in cfg.get("admins", []) if a.lower() != target]
        save_config(cfg)
        await send_temp_message(chat_id, f"<b>Study Spark Admin 🔥</b>\n\n@{html.escape(target)} removed from Admins.", delay_seconds=3.5)

    elif action == "set_channel":
        if text.lstrip("-").isdigit():
            cfg["channel_id"] = text
        else:
            cfg["channel_link"] = text
            cfg["channel_id"] = ""
        save_config(cfg)
        await send_temp_message(chat_id, "<b>Study Spark Admin 🔥</b>\n\nChannel updated successfully.", delay_seconds=3.5)

    elif action == "set_group":
        if text.lstrip("-").isdigit():
            cfg["group_id"] = text
        else:
            cfg["group_link"] = text
            cfg["group_id"] = ""
        save_config(cfg)
        await send_temp_message(chat_id, "<b>Study Spark Admin 🔥</b>\n\nGroup updated successfully.", delay_seconds=3.5)

    elif action == "set_domain":
        domains = [d.strip() for d in re.split(r'[, ]+', text) if d.strip()]
        cfg["allowed_patterns"] = domains
        save_config(cfg)
        await send_temp_message(chat_id, f"<b>Study Spark Admin 🔥</b>\n\nAllowed domain set to: {html.escape(', '.join(domains))}", delay_seconds=3.5)

    elif action == "broadcast":
        users = users_store.get("all_users", [])
        sent = 0
        for uid in users:
            try:
                r = await tg.send_message(uid, f"<b>Study Spark Notice 🔥</b>\n\n{html.escape(text)}")
                if r.get("ok"):
                    sent += 1
                await asyncio.sleep(0.04)
            except Exception:
                pass
        await send_temp_message(chat_id, f"<b>Study Spark Admin 🔥</b>\n\nBroadcast sent to {sent} users.", delay_seconds=4.0)

    return True

async def handle_callback_query(cq: dict):
    cq_id = cq.get("id")
    data = cq.get("data", "")
    from_user = cq.get("from", {})
    user_id = from_user.get("id")
    msg = cq.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    msg_id = msg.get("message_id")

    # 1. User Verification Continue Button
    if data in ("continue_start", "verify_join"):
        joined_ok, err_msg = await verify_user_joined(user_id, is_button_click=True)
        if not joined_ok:
            await tg.answer_callback_query(cq_id, text=err_msg, show_alert=True)
            return

        await tg.answer_callback_query(cq_id, text="Verified!", show_alert=False)
        # Edit the join message in place to the welcome text and keep it in chat so /start loop never happens!
        await tg.edit_message_text(chat_id, msg_id, get_direct_welcome_text())
        pending_join_messages[user_id] = (chat_id, msg_id)
        return

    # 2. Download Confirmation & Cancel Buttons
    if data.startswith("confirm_dl:"):
        parts = data.split(":")
        token = parts[1]
        quality = parts[2] if len(parts) > 2 else "best"
        entry = pending_confirmations.pop(token, None)
        if not entry:
            await tg.answer_callback_query(cq_id, text="Link expired. Please send again.", show_alert=True)
            await safe_delete(chat_id, msg_id)
            return

        await tg.answer_callback_query(cq_id, text="Downloading...", show_alert=False)
        asyncio.create_task(process_video_task(entry["chat_id"], entry["user_id"], entry["url"], existing_msg_id=msg_id, quality=quality))
        return

    if data.startswith("cancel_confirm:"):
        token = data.split(":", 1)[1]
        pending_confirmations.pop(token, None)
        await tg.answer_callback_query(cq_id, text="Cancelled.", show_alert=False)
        await safe_delete(chat_id, msg_id)
        return

    if data.startswith("cancel_task:"):
        task_id = data.split(":", 1)[1]
        ctrl = active_task_controllers.get(task_id)
        if ctrl:
            ctrl["cancelled"] = True
            proc = ctrl.get("proc")
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
        await tg.answer_callback_query(cq_id, text="Cancelled.", show_alert=False)
        await safe_delete(chat_id, msg_id)
        return

    # 3. Admin Panel Interactive Buttons (Delete old message immediately on click)
    if data.startswith("adm_"):
        if not is_admin(from_user):
            await tg.answer_callback_query(cq_id, text="Admins only.", show_alert=True)
            await safe_delete(chat_id, msg_id)
            return

        admin_pending_input.pop(user_id, None)

        if data == "adm_close":
            await tg.answer_callback_query(cq_id)
            await safe_delete(chat_id, msg_id)
            return

        if data == "adm_back":
            await tg.answer_callback_query(cq_id)
            await safe_delete(chat_id, msg_id)
            await tg.send_message(chat_id, get_admin_panel_text(), reply_markup=build_admin_panel_markup())
            return

        if data == "adm_stats":
            await tg.answer_callback_query(cq_id)
            await safe_delete(chat_id, msg_id)
            total_u = len(users_store["all_users"])
            ver_u = len(users_store["verified_users"])
            uptime = format_time(time.time() - bot_state["started_at"])
            total_bytes = format_size(bot_state["total_bytes_processed"])
            text = (
                "<b>Study Spark Statistics 🔥</b>\n\n"
                f"• <b>Total Users:</b> {total_u}\n"
                f"• <b>Verified Users:</b> {ver_u}\n"
                f"• <b>Videos Sent:</b> {bot_state['completed_downloads']}\n"
                f"• <b>Data Processed:</b> {total_bytes}\n"
                f"• <b>Uptime:</b> {uptime}"
            )
            await send_temp_message(chat_id, text, delay_seconds=6.0)
            return

        if data == "adm_team":
            await tg.answer_callback_query(cq_id)
            await safe_delete(chat_id, msg_id)
            cfg = load_config()
            owners = ", ".join([f"@{o}" for o in cfg.get("owners", [])])
            admins = ", ".join([f"@{a}" for a in cfg.get("admins", [])]) or "None"
            text = (
                "<b>Study Spark Team 🔥</b>\n\n"
                f"• <b>Owners:</b> {html.escape(owners)}\n"
                f"• <b>Admins:</b> {html.escape(admins)}"
            )
            await send_temp_message(chat_id, text, delay_seconds=6.0)
            return

        if data == "adm_ping":
            await tg.answer_callback_query(cq_id)
            t0 = time.perf_counter()
            await safe_delete(chat_id, msg_id)
            ping_ms = int((time.perf_counter() - t0) * 1000)
            uptime = format_time(time.time() - bot_state["started_at"])
            text = (
                "<b>Study Spark System Status 🔥</b>\n\n"
                f"• <b>Server Ping:</b> {ping_ms} ms\n"
                f"• <b>Engine:</b> 16x High-Speed Active\n"
                f"• <b>Active Downloads:</b> {bot_state['active_downloads']} / {MAX_CONCURRENT_DOWNLOADS}\n"
                f"• <b>Uptime:</b> {uptime}"
            )
            await send_temp_message(chat_id, text, delay_seconds=5.0)
            return

        if data == "adm_clear_domain":
            await tg.answer_callback_query(cq_id, text="All domains allowed!", show_alert=False)
            await safe_delete(chat_id, msg_id)
            cfg = load_config()
            cfg["allowed_patterns"] = []
            save_config(cfg)
            await send_temp_message(chat_id, "<b>Study Spark Admin 🔥</b>\n\nDomain restriction cleared. All links are now allowed.", delay_seconds=3.5)
            return

        if data == "adm_reset_verify":
            await tg.answer_callback_query(cq_id, text="Verification reset!", show_alert=False)
            await safe_delete(chat_id, msg_id)
            users_store["verified_users"] = []
            save_users(users_store)
            join_verify_attempts.clear()
            await send_temp_message(chat_id, "<b>Study Spark Admin 🔥</b>\n\nAll user verifications have been reset.", delay_seconds=3.5)
            return

        if data == "adm_clean_cache":
            await tg.answer_callback_query(cq_id, text="Cache cleaned!", show_alert=False)
            await safe_delete(chat_id, msg_id)
            cleaned = 0
            if os.path.exists(DOWNLOAD_DIR) and bot_state["active_downloads"] == 0:
                for item in os.listdir(DOWNLOAD_DIR):
                    p = os.path.join(DOWNLOAD_DIR, item)
                    try:
                        shutil.rmtree(p, ignore_errors=True)
                        cleaned += 1
                    except Exception:
                        pass
            await send_temp_message(chat_id, f"<b>Study Spark Admin 🔥</b>\n\nTemporary cache cleaned ({cleaned} folders removed).", delay_seconds=3.5)
            return

        # Interactive input prompts
        prompts = {
            "adm_add_admin": ("add_admin", "Send the <b>@username</b> to promote as Admin:"),
            "adm_del_admin": ("del_admin", "Send the <b>@username</b> to remove from Admins:"),
            "adm_set_channel": ("set_channel", "Send the new <b>Channel Link</b> (or Channel ID):"),
            "adm_set_group": ("set_group", "Send the new <b>Group Link</b> (or Group ID):"),
            "adm_set_domain": ("set_domain", "Send the allowed <b>Domain</b> (e.g. spark-url.b-cdn.net):"),
            "adm_broadcast": ("broadcast", "Send the <b>Message</b> you want to broadcast to all users:")
        }

        if data in prompts:
            if data in ("adm_add_admin", "adm_del_admin") and not is_owner(from_user):
                await tg.answer_callback_query(cq_id, text="Owners only.", show_alert=True)
                await safe_delete(chat_id, msg_id)
                return

            await tg.answer_callback_query(cq_id)
            await safe_delete(chat_id, msg_id)
            action_key, prompt_str = prompts[data]
            resp = await tg.send_message(
                chat_id,
                f"<b>Study Spark Admin 🔥</b>\n\n{prompt_str}",
                reply_markup=build_admin_cancel_input_markup()
            )
            pmid = resp.get("result", {}).get("message_id")
            admin_pending_input[user_id] = {"action": action_key, "prompt_mid": pmid}
            return

# ----------------- Video & .m3u8 HLS Downloader Engine ----------------- #

URL_REGEX = re.compile(r'https?://[^\s<>"]+')

def get_ytdlp_format_selector(quality: str) -> str:
    if quality == "1080p":
        return "bestvideo*[height<=1080]+bestaudio/best*[height<=1080]/bestvideo*+bestaudio/best"
    elif quality == "720p":
        return "bestvideo*[height<=720]+bestaudio/best*[height<=720]/bestvideo*+bestaudio/best"
    elif quality == "480p":
        return "bestvideo*[height<=480]+bestaudio/best*[height<=480]/bestvideo*+bestaudio/best"
    elif quality == "360p":
        return "bestvideo*[height<=360]+bestaudio/best*[height<=360]/bestvideo*+bestaudio/best"
    return "bestvideo*+bestaudio/best"

async def download_video_engine(url: str, output_template: str, chat_id: int, status_msg_id: int, task_id: str, quality: str = "best") -> str:
    out_dir = os.path.dirname(output_template)

    last_edit = [0.0]
    prog_regex = re.compile(r'\[download\]\s+([0-9.]+)%')
    aria_regex = re.compile(r'\[#[a-f0-9]+\s+([0-9.]+[A-Za-z]+)/([0-9.]+[A-Za-z]+)\(([0-9.]+)%\)')

    cancel_markup = {
        "inline_keyboard": [
            [{"text": "✖ Cancel", "callback_data": f"cancel_task:{task_id}", "style": "danger"}]
        ]
    }

    async def run_process(command):
        if active_task_controllers.get(task_id, {}).get("cancelled"):
            return -999

        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        if task_id in active_task_controllers:
            active_task_controllers[task_id]["proc"] = proc

        async def read_stream(stream):
            while True:
                if active_task_controllers.get(task_id, {}).get("cancelled"):
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    break
                line = await stream.readline()
                if not line:
                    break
                text = line.decode('utf-8', errors='ignore').strip()
                now = time.time()
                if now - last_edit[0] >= 2.0:
                    match_aria = aria_regex.search(text)
                    match_ytdlp = prog_regex.search(text)
                    if match_aria or match_ytdlp:
                        pct_str = match_aria.group(3) if match_aria else match_ytdlp.group(1)
                        try:
                            pct = float(pct_str)
                        except Exception:
                            pct = 50.0
                        last_edit[0] = now
                        bar = make_progress_bar(pct, 10)
                        box = (
                            "<b>Study Spark Downloader 🔥</b>\n\n"
                            f"Downloading video... {pct:.0f}%\n"
                            f"[{bar}]\n\n"
                            "Please wait a moment."
                        )
                        try:
                            await tg.edit_message_text(chat_id, status_msg_id, box, reply_markup=cancel_markup)
                        except Exception:
                            pass

        read_stdout = asyncio.create_task(read_stream(proc.stdout))
        read_stderr = asyncio.create_task(read_stream(proc.stderr))
        await proc.wait()
        await read_stdout
        await read_stderr
        return proc.returncode

    def find_downloaded_candidate() -> str:
        candidates = []
        if os.path.exists(out_dir):
            for f in os.listdir(out_dir):
                fp = os.path.join(out_dir, f)
                if os.path.isfile(fp) and not f.endswith(('.part', '.ytdl', '.aria2', '.jpg', '.webp', '.m3u8')):
                    size = os.path.getsize(fp)
                    if size > 1024:
                        candidates.append((fp, size))
        if not candidates:
            return ""
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    ytdlp_exec = find_ytdlp_bin()
    fmt_selector = get_ytdlp_format_selector(quality)

    if is_hls_url(url):
        cmd_hls = [
            ytdlp_exec,
            "--newline",
            "--no-warnings",
            "--no-check-certificates",
            "--concurrent-fragments", "16",
            "--hls-prefer-native",
            "-f", fmt_selector,
            "--merge-output-format", "mp4",
            "-o", output_template,
            url
        ]
        await run_process(cmd_hls)
        cand = find_downloaded_candidate()
        if not cand:
            hls_out = os.path.join(out_dir, "Study_Spark_Video.mp4")
            cmd_ffmpeg_hls = [
                "ffmpeg", "-y",
                "-user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "-i", url,
                "-c", "copy",
                "-bsf:a", "aac_adtstoasc",
                "-movflags", "+faststart",
                hls_out
            ]
            await run_process(cmd_ffmpeg_hls)
            cand = find_downloaded_candidate()
        if cand:
            return cand

    if is_direct_media_url(url):
        parsed = urllib.parse.urlparse(url)
        raw_name = urllib.parse.unquote(os.path.basename(parsed.path) or "video.mp4")
        if not any(raw_name.lower().endswith(ext) for ext in ('.mp4', '.mkv', '.webm', '.mov')):
            target_filename = f"{raw_name}.mp4"
        else:
            target_filename = raw_name

        cmd_aria = [
            "aria2c",
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "-x", "16",
            "-s", "16",
            "-j", "16",
            "-k", "1M",
            "--min-split-size=1M",
            "--allow-overwrite=true",
            "--summary-interval=1",
            "-d", out_dir,
            "-o", target_filename,
            url
        ]
        code = await run_process(cmd_aria)
        direct_path = os.path.join(out_dir, target_filename)
        if code == 0 and os.path.exists(direct_path) and os.path.getsize(direct_path) > 1024:
            return direct_path

    cmd = [
        ytdlp_exec,
        "--newline",
        "--no-warnings",
        "--no-check-certificates",
        "--concurrent-fragments", "16",
        "--external-downloader", "aria2c",
        "--external-downloader-args", "aria2c:-x 16 -s 16 -j 16 -k 1M --min-split-size=1M",
        "-f", fmt_selector,
        "--merge-output-format", "mp4",
        "-o", output_template,
        url
    ]
    code = await run_process(cmd)
    if code != 0 and not find_downloaded_candidate():
        cmd_fallback = [
            ytdlp_exec,
            "--newline",
            "--no-warnings",
            "--no-check-certificates",
            "--concurrent-fragments", "16",
            "-f", fmt_selector,
            "--merge-output-format", "mp4",
            "-o", output_template,
            url
        ]
        await run_process(cmd_fallback)

    best_file = find_downloaded_candidate()
    if not best_file:
        return ""

    if not best_file.lower().endswith(".mp4"):
        mp4_target = os.path.splitext(best_file)[0] + ".mp4"
        try:
            remux_proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", best_file, "-c", "copy", mp4_target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await remux_proc.communicate()
            if os.path.exists(mp4_target) and os.path.getsize(mp4_target) > 1024:
                try:
                    os.remove(best_file)
                except Exception:
                    pass
                return mp4_target
        except Exception as e:
            print(f"[Remux error] {e}")

    return best_file

async def process_video_task(chat_id: int, user_id: int, url: str, existing_msg_id: int = None, quality: str = "best"):
    global pyro_client

    task_id = f"task_{int(time.time()*1000)}_{os.getpid()}"
    task_dir = os.path.join(DOWNLOAD_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)

    cancel_markup = {
        "inline_keyboard": [
            [{"text": "✖ Cancel", "callback_data": f"cancel_task:{task_id}", "style": "danger"}]
        ]
    }

    init_text = (
        "<b>Study Spark Downloader 🔥</b>\n\n"
        "Downloading video...\n"
        "Please wait a moment."
    )

    if existing_msg_id:
        status_msg_id = existing_msg_id
        await tg.edit_message_text(chat_id, status_msg_id, init_text, reply_markup=cancel_markup)
    else:
        status_resp = await tg.send_message(chat_id, init_text, reply_markup=cancel_markup)
        status_msg_id = status_resp.get("result", {}).get("message_id")

    active_task_controllers[task_id] = {
        "cancelled": False,
        "proc": None,
        "chat_id": chat_id,
        "msg_id": status_msg_id
    }

    task_entry = {
        "id": task_id,
        "file": "Downloading...",
        "status": "downloading",
        "start": time.time()
    }
    bot_state["active_downloads"] += 1
    bot_state["current_tasks"].append(task_entry)
    save_bot_state()
    log_activity("DOWNLOAD_START", f"User {user_id} requested video")

    try:
        async with semaphore:
            output_template = os.path.join(task_dir, "%(title).60s.%(ext)s")
            downloaded_path = await download_video_engine(url, output_template, chat_id, status_msg_id, task_id, quality=quality)

            if active_task_controllers.get(task_id, {}).get("cancelled"):
                log_activity("DOWNLOAD_CANCELLED", f"User {user_id} cancelled task")
                await safe_delete(chat_id, status_msg_id)
                return

            if not downloaded_path or not os.path.exists(downloaded_path):
                if status_msg_id:
                    await tg.edit_message_text(
                        chat_id,
                        status_msg_id,
                        "<b>Study Spark Downloader 🔥</b>\n\nUnable to download this link. Please check the URL and try again."
                    )
                    asyncio.create_task(auto_delete_message(chat_id, status_msg_id, 4.0))
                log_activity("DOWNLOAD_FAILED", f"Failed for URL: {url[:60]}")
                return

            file_size = os.path.getsize(downloaded_path)
            if file_size == 0:
                await safe_delete(chat_id, status_msg_id)
                log_activity("DOWNLOAD_FAILED", "Empty file")
                return

            filename = os.path.basename(downloaded_path)
            task_entry["file"] = filename
            size_str = format_size(file_size)
            log_activity("DOWNLOAD_COMPLETE", f"{filename} ({size_str})")

            if status_msg_id:
                try:
                    await tg.edit_message_text(
                        chat_id,
                        status_msg_id,
                        "<b>Study Spark Downloader 🔥</b>\n\n"
                        "Preparing video...\n"
                        "Almost ready to send."
                    )
                except Exception:
                    pass

            width, height, duration, probed_title = await probe_video_metadata(downloaded_path)
            clean_title, clean_filename = get_clean_title_and_filename(downloaded_path, probed_title, quality_hint=quality)

            target_renamed_path = os.path.join(task_dir, clean_filename)
            if downloaded_path != target_renamed_path and not os.path.exists(target_renamed_path):
                try:
                    os.rename(downloaded_path, target_renamed_path)
                    downloaded_path = target_renamed_path
                except Exception:
                    pass

            filename = os.path.basename(downloaded_path)
            task_entry["file"] = filename

            thumb_path = os.path.join(task_dir, "thumb.jpg")
            thumb = await extract_thumbnail(downloaded_path, thumb_path)

            task_entry["status"] = "uploading"
            save_bot_state()
            log_activity("UPLOAD_START", f"Uploading {clean_filename} ({size_str}) to Telegram")

            caption = (
                f"<b>Title:</b> {html.escape(clean_title)}\n\n"
                "<b>Downloaded by Study Spark Bot 🔥</b>"
            )

            upload_success = False
            last_upload_edit = [0.0]

            async def handle_pyro_upload_progress(current, total):
                now = time.time()
                if now - last_upload_edit[0] >= 2.0 or current == total:
                    last_upload_edit[0] = now
                    pct = (current / total) * 100 if total > 0 else 0
                    bar = make_progress_bar(pct, 10)
                    box = (
                        "<b>Study Spark Downloader 🔥</b>\n\n"
                        f"Sending video... {pct:.0f}%\n"
                        f"[{bar}]\n\n"
                        "Almost done."
                    )
                    if status_msg_id:
                        try:
                            await tg.edit_message_text(chat_id, status_msg_id, box, reply_markup=cancel_markup)
                        except Exception:
                            pass

            if file_size <= 48 * 1024 * 1024 or pyro_client is None:
                resp = await tg.send_video(
                    chat_id=chat_id,
                    video_path=downloaded_path,
                    caption=caption,
                    duration=duration,
                    width=width,
                    height=height,
                    thumb_path=thumb
                )
                upload_success = resp.get("ok", False)
            else:
                try:
                    from pyrogram import enums
                    main_loop = asyncio.get_running_loop()
                    def pyro_prog_callback(current, total):
                        try:
                            asyncio.run_coroutine_threadsafe(handle_pyro_upload_progress(current, total), main_loop)
                        except Exception:
                            pass

                    valid_thumb = thumb if (thumb and os.path.exists(thumb)) else None

                    await pyro_client.send_video(
                        chat_id=chat_id,
                        video=downloaded_path,
                        caption=caption,
                        parse_mode=enums.ParseMode.HTML,
                        duration=duration,
                        width=width,
                        height=height,
                        thumb=valid_thumb,
                        supports_streaming=True,
                        progress=pyro_prog_callback
                    )
                    upload_success = True
                except Exception as pe:
                    print(f"[Pyro Upload Error] {pe}", file=sys.stderr)
                    resp = await tg.send_video(
                        chat_id=chat_id,
                        video_path=downloaded_path,
                        caption=caption,
                        duration=duration,
                        width=width,
                        height=height,
                        thumb_path=thumb
                    )
                    upload_success = resp.get("ok", False)

            # Immediately delete the progress message so ONLY the video remains!
            await safe_delete(chat_id, status_msg_id)

            if upload_success:
                bot_state["completed_downloads"] += 1
                bot_state["total_bytes_processed"] += file_size
                log_activity("TASK_SUCCESS", f"Delivered {filename} ({size_str}) to chat {chat_id}")
            else:
                await send_temp_message(chat_id, "<b>Study Spark Downloader 🔥</b>\n\nUpload failed. Please try again.", delay_seconds=4.0)

    except Exception as e:
        print(f"[Task Error] {e}", file=sys.stderr)
        log_activity("TASK_ERROR", f"Error: {str(e)[:100]}")
        await safe_delete(chat_id, status_msg_id)
    finally:
        active_task_controllers.pop(task_id, None)
        bot_state["active_downloads"] = max(0, bot_state["active_downloads"] - 1)
        bot_state["current_tasks"] = [t for t in bot_state["current_tasks"] if t.get("id") != task_id]
        save_bot_state()
        try:
            shutil.rmtree(task_dir, ignore_errors=True)
        except Exception:
            pass

# ----------------- Auto-Bind Channel & Group Events ----------------- #

async def handle_bot_chat_member_update(upd_obj: dict):
    chat = upd_obj.get("chat", {})
    chat_id = chat.get("id")
    chat_type = chat.get("type", "")
    chat_title = chat.get("title", "")
    new_member = upd_obj.get("new_chat_member", {})
    status = new_member.get("status", "")

    if not chat_id or status not in ("administrator", "member", "creator"):
        return

    cfg = load_config()
    if chat_type == "channel":
        cfg["channel_id"] = str(chat_id)
        if chat_title:
            cfg["channel_title"] = chat_title
        save_config(cfg)
        log_activity("CHANNEL_CONNECTED", f"Connected channel {chat_title} ({chat_id})")
    elif chat_type in ("group", "supergroup"):
        if chat.get("is_direct_messages") or str(chat_id).startswith("-207"):
            return
        cfg["group_id"] = str(chat_id)
        if chat_title:
            cfg["group_title"] = chat_title
        save_config(cfg)
        log_activity("GROUP_CONNECTED", f"Connected group {chat_title} ({chat_id})")

async def handle_user_chat_member_update(upd_obj: dict):
    new_member = upd_obj.get("new_chat_member", {})
    status = new_member.get("status", "")
    user = new_member.get("user", {})
    user_id = user.get("id")

    if not user_id or status not in ("member", "administrator", "creator"):
        return

    if user_id in pending_join_messages:
        joined_ok, _ = await verify_user_joined(user_id, is_button_click=False)
        if joined_ok:
            dm_chat_id, dm_msg_id = pending_join_messages.get(user_id, (None, None))
            if dm_chat_id and dm_msg_id:
                await tg.edit_message_text(dm_chat_id, dm_msg_id, get_direct_welcome_text())

# ----------------- Dispatch Updates ----------------- #

async def dispatch_update(update: dict):
    try:
        if "my_chat_member" in update:
            await handle_bot_chat_member_update(update["my_chat_member"])
            return

        if "chat_member" in update:
            await handle_user_chat_member_update(update["chat_member"])
            return

        if "channel_post" in update:
            post = update["channel_post"]
            chat = post.get("chat", {})
            if chat.get("type") == "channel" and chat.get("id"):
                cfg = load_config()
                if not cfg.get("channel_id"):
                    cfg["channel_id"] = str(chat["id"])
                    if chat.get("title"):
                        cfg["channel_title"] = chat["title"]
                    save_config(cfg)
            return

        if "callback_query" in update:
            await handle_callback_query(update["callback_query"])
            return

        if "message" in update:
            message = update["message"]
            chat = message.get("chat", {})
            chat_id = chat.get("id")
            chat_type = chat.get("type", "private")
            from_user = message.get("from", {})
            user_id = from_user.get("id", 0)
            msg_id = message.get("message_id")
            text = (message.get("text") or "").strip()

            if chat_type in ("group", "supergroup") and chat_id:
                if chat.get("is_direct_messages") or str(chat_id).startswith("-207"):
                    return
                cfg = load_config()
                if not cfg.get("group_id"):
                    cfg["group_id"] = str(chat_id)
                    if chat.get("title"):
                        cfg["group_title"] = chat["title"]
                    save_config(cfg)
                return

            register_user(user_id)

            # Auto-bind channel if admin forwards a channel post
            fwd_chat = message.get("forward_from_chat")
            if fwd_chat and fwd_chat.get("type") == "channel" and is_admin(from_user):
                await safe_delete(chat_id, msg_id)
                cfg = load_config()
                cfg["channel_id"] = str(fwd_chat["id"])
                if fwd_chat.get("title"):
                    cfg["channel_title"] = fwd_chat["title"]
                save_config(cfg)
                await send_temp_message(chat_id, "<b>Study Spark Admin 🔥</b>\n\nChannel connected for verification.", delay_seconds=3.5)
                return

            if not text:
                return

            # Check if admin is replying to an interactive admin button prompt
            if user_id in admin_pending_input and not text.startswith("/"):
                handled = await handle_admin_text_input(message)
                if handled:
                    return

            # Commands
            if text.startswith("/"):
                cmd = text.split()[0].lower().split("@")[0]
                if cmd == "/start":
                    await handle_start(message)
                elif cmd in ("/help", "/info"):
                    await handle_help(message)
                elif cmd in ("/admin", "/panel", "/stats", "/admins"):
                    await handle_admin(message)
                else:
                    await safe_delete(chat_id, msg_id)
                return

            # Video / .m3u8 Link Detection
            url_match = URL_REGEX.search(text)
            if url_match:
                # Immediately delete user's link message from chat
                await safe_delete(chat_id, msg_id)

                joined_ok, _ = await verify_user_joined(user_id, is_button_click=False)
                if not joined_ok:
                    old_chat, old_mid = pending_join_messages.pop(user_id, (None, None))
                    if old_chat and old_mid:
                        await safe_delete(old_chat, old_mid)
                    join_prompt_shown_at[user_id] = time.time()
                    join_verify_attempts[user_id] = 0
                    resp = await tg.send_message(
                        chat_id,
                        get_join_prompt_text(),
                        reply_markup=build_join_markup()
                    )
                    mid = resp.get("result", {}).get("message_id")
                    if mid:
                        pending_join_messages[user_id] = (chat_id, mid)
                    return

                url = url_match.group(0).strip()
                allowed, allowed_str = is_url_allowed(url)
                if not allowed:
                    await send_temp_message(
                        chat_id,
                        f"<b>Study Spark Downloader 🔥</b>\n\nOnly links from {html.escape(allowed_str)} are allowed.",
                        delay_seconds=4.0
                    )
                    return

                # Check if link actually has multiple quality options
                qualities = await detect_available_qualities(url)

                token = uuid.uuid4().hex[:10]
                pending_confirmations[token] = {
                    "url": url,
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "created_at": time.time()
                }

                if qualities and len(qualities) >= 2:
                    prompt_text = (
                        "<b>Study Spark Downloader 🔥</b>\n\n"
                        "Select your video quality to start downloading:"
                    )
                else:
                    prompt_text = (
                        "<b>Study Spark Downloader 🔥</b>\n\n"
                        "Ready to download your video. Tap <b>Download</b> to start."
                    )

                confirm_resp = await tg.send_message(
                    chat_id,
                    prompt_text,
                    reply_markup=build_confirm_markup(token, qualities)
                )
                confirm_mid = confirm_resp.get("result", {}).get("message_id")
                if confirm_mid:
                    async def auto_expire_prompt(cid, mid, tok):
                        await asyncio.sleep(60.0)
                        if tok in pending_confirmations:
                            pending_confirmations.pop(tok, None)
                            await safe_delete(cid, mid)
                    asyncio.create_task(auto_expire_prompt(chat_id, confirm_mid, token))
            else:
                # Delete any non-link message immediately and show a brief 3s notice
                await safe_delete(chat_id, msg_id)
                await send_temp_message(
                    chat_id,
                    "<b>Study Spark Downloader 🔥</b>\n\nPlease send a valid video link.",
                    delay_seconds=3.0
                )

    except Exception as e:
        print(f"[Dispatch Error] {e}", file=sys.stderr)

# ----------------- Main Polling Loop ----------------- #

async def main():
    global pyro_client

    log_activity("BOT_BOOT", f"Starting Study Spark Bot with PID {os.getpid()}...")
    save_bot_state()

    await sync_menu_commands()
    await tg.request("deleteWebhook", data={"drop_pending_updates": False})

    try:
        from pyrogram import Client as PyroClient
        session_file = os.path.join(BASE_DIR, "data", "bot_session")
        pyro_client = PyroClient(
            session_file,
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            no_updates=True
        )
        await pyro_client.start()
        print("[Pyrogram Engine] MTProto client active with persistent session (2GB uploads ready).")
    except Exception as pe:
        print(f"[Pyrogram Init Warning] Could not start Pyrogram client: {pe}", file=sys.stderr)
        pyro_client = None

    print("[Bot Online] Official Telegram Bot API long-polling listening for updates...")

    offset = 0
    while True:
        try:
            res = await tg.request(
                "getUpdates",
                data={
                    "offset": offset,
                    "timeout": 20,
                    "allowed_updates": ["message", "callback_query", "my_chat_member", "chat_member", "channel_post"]
                },
                timeout=30
            )
            if res and res.get("ok"):
                for upd in res.get("result", []):
                    offset = upd["update_id"] + 1
                    asyncio.create_task(dispatch_update(upd))
            else:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(1)

    if pyro_client and pyro_client.is_connected:
        try:
            await pyro_client.stop()
        except Exception:
            pass
    await tg.close()
    bot_state["status"] = "offline"
    save_bot_state()
    print("[Bot stopped]")

if __name__ == "__main__":
    asyncio.run(main())
