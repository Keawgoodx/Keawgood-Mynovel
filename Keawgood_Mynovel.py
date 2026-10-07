# -*- coding: utf-8 -*-
"""
Keawgood_Mynovel — Batch Draft Scheduler for MyNovel (PyQt6 + Selenium)

ตั้งเวลาเผยแพร่ + ติดเหรียญ ให้ตอนที่เป็น "ฉบับร่าง" ในหน้าคลังตอนของ MyNovel ทีละหลายเรื่องอัตโนมัติ
UI สไตล์ VS Code Modern Dark: Sidebar (รายชื่อเรื่อง) + Workspace (ตั้งค่าเรื่องที่เลือก) + Output panel

การตั้งค่าและรายการเรื่องทั้งหมดถูกบันทึกอัตโนมัติใน config.json (ข้างไฟล์นี้)
"""
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field, asdict, fields
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QDate, QDateTime, QObject, QThread, QTime, QTimer, Qt, QUrl, pyqtSignal, QByteArray, QSize
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap, QTextCursor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QStatusBar,
    QTextBrowser,
    QProgressDialog,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

# ---------------------------------------------------------------------------
# App info / paths / constants
# ---------------------------------------------------------------------------
# ชื่อ/เวอร์ชัน/ช่องทางอัปเดต แก้ที่ไฟล์ version.py ที่เดียว
from version import (  # noqa: E402
    APP_NAME,
    APP_DISPLAY_NAME,
    APP_USER_MODEL_ID,
    GITHUB_REPO,
    RELEASE_ASSET_NAME,
    UPDATE_MANIFEST_URL,
    __version__ as APP_VERSION,
)
GITHUB_URL = f"https://github.com/{GITHUB_REPO}"
RELEASE_ASSET_SUFFIX = "-windows.zip"
EXE_NAME = f"{APP_NAME}.exe"
IS_FROZEN = bool(getattr(sys, "frozen", False))
# ข้อมูลผู้ใช้ (config.json, automation_profile, logs) เก็บไว้ข้างโปรแกรม (.exe หรือ .py)
APP_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
USER_DATA_NAMES = {"config.json", "config_v1_backup.json", "automation_profile", "logs", ".venv", ".git"}
MAX_PARALLEL_LIMIT = 10
CONFIG_FILE = APP_DIR / "config.json"
CONFIG_V1_BACKUP = APP_DIR / "config_v1_backup.json"
LOG_DIR = APP_DIR / "logs"
CONFIG_VERSION = 2
DEFAULT_PRICE = 20
MYNOVEL_WORKINGS_URL = "https://mynovel.co/dashboard/workings"
MYNOVEL_LOGIN_URL = "https://mynovel.co/auth"

WORKING_URL_RE = re.compile(r"https?://(?:www\.)?mynovel\.co/dashboard/workings/([A-Za-z0-9_-]+)", re.IGNORECASE)

FREE_RULES = [
    "ตอนที่ลงท้ายด้วย 5, 0 (เช่น 5, 10, 15, 20...)",
    "ตอนที่ลงท้ายด้วย 0 (เช่น 10, 20, 30...)",
    "ตอนที่ลงท้ายด้วย 5 (เช่น 5, 15, 25...)",
    "ทุก 3 ตอน (เช่น 3, 6, 9, 12...)",
    "ทุก 5 ตอน (เช่น 5, 10, 15, 20...)",
    "ทุก 10 ตอน (เช่น 10, 20, 30...)",
    "กำหนดเอง",
]

PRICE_MODES = {
    "paid_all": "ติดเหรียญทุกตอน",
    "auto_free": "ติดเหรียญ + ฟรีอัตโนมัติตามกฎ",
    "free_all": "ฟรีทุกตอน",
    "keep": "ไม่แก้ราคา (คงค่าเดิม)",
}

PUBLISH_MODES = {
    "scheduled": "ตั้งเวลาล่วงหน้า (ตามตาราง)",
    "published": "เผยแพร่ทันที",
    "keep": "ไม่แก้สถานะ (แก้ราคาอย่างเดียว)",
}

TARGET_MODES = {
    "draft": "เฉพาะตอนที่เป็น 'ฉบับร่าง'",
    "draft_scheduled": "ฉบับร่าง + ตอนที่ 'ตั้งเวลา' แล้ว (จัดเวลาใหม่ทั้งหมด)",
}

STATUS_DRAFT = "ฉบับร่าง"
STATUS_SCHEDULED = "ตั้งเวลา"
STATUS_PUBLISHED = "เผยแพร่แล้ว"
SITE_STATUSES = [STATUS_DRAFT, STATUS_SCHEDULED, STATUS_PUBLISHED, "เผยแพร่"]

JOB_STATUS_META = {
    # status: (label, color)
    "ready": ("Ready", "#3794ff"),
    "running": ("Running", "#cca700"),
    "done": ("Done", "#89d185"),
    "failed": ("Failed", "#f48771"),
    "stopped": ("Stopped", "#c586c0"),
}

THAI_MONTHS = {
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4, "พฤษภาคม": 5, "มิถุนายน": 6,
    "กรกฎาคม": 7, "สิงหาคม": 8, "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
    "ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4, "พ.ค.": 5, "มิ.ย.": 6,
    "ก.ค.": 7, "ส.ค.": 8, "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12,
}
EN_MONTHS = {
    m.lower(): i + 1
    for i, m in enumerate([
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ])
}
EN_MONTHS.update({k[:3]: v for k, v in list(EN_MONTHS.items())})


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class StopRequested(Exception):
    """ผู้ใช้กดหยุด"""


class NotLoggedInError(RuntimeError):
    """ยังไม่ได้ล็อกอิน MyNovel"""


class EditEpisodeError(RuntimeError):
    """แก้ไขตอนไม่สำเร็จ (ตอนเดียว ไม่ทำให้ทั้งงานล้ม)"""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class BrowserProfile:
    label: str
    user_data_dir: str
    profile_dir_name: str


@dataclass
class ScheduleConfig:
    start_date: str
    start_time: str
    chapters_per_day: int
    interval_minutes: int
    limit_per_day_enabled: bool
    skip_enabled: bool
    skip_start: str
    skip_end: str


@dataclass
class NovelJob:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    working_url: str = ""
    enabled: bool = True
    status: str = "ready"
    last_message: str = ""
    # pricing
    price_mode: str = "auto_free"
    price_value: int = DEFAULT_PRICE
    free_rule: str = FREE_RULES[0]
    free_custom: str = ""
    # publishing / schedule
    publish_mode: str = "scheduled"
    start_date: str = ""
    start_time: str = "12:00"
    per_day_enabled: bool = True
    chapters_per_day: int = 3
    interval_value: int = 4
    interval_unit: str = "hours"  # minutes | hours
    skip_enabled: bool = False
    skip_start: str = "00:00"
    skip_end: str = "06:00"
    # advanced
    max_episodes: int = 0  # 0 = ทุกตอนที่เป็นฉบับร่าง
    continue_after_last: bool = True  # ต่อเวลาจากตอนที่ตั้งเวลาไว้ล่าสุด (รอบก่อน)
    target_mode: str = "draft"  # draft = เฉพาะฉบับร่าง | draft_scheduled = ฉบับร่าง + ตอนที่ตั้งเวลาแล้ว (จัดเวลาใหม่)
    min_order: int = 0  # แก้เฉพาะตอนที่ลำดับ >= ค่านี้ (0 = ไม่จำกัด)
    last_scheduled_at: str = ""  # "YYYY-MM-DD HH:MM" เวลาเผยแพร่ล่าสุดที่โปรแกรมตั้งไว้
    # stats
    last_run_at: str = ""
    last_done: int = 0
    last_total: int = 0

    def display_name(self) -> str:
        return (self.title or "").strip() or short_url_label(self.working_url) or "นิยายใหม่"

    def interval_minutes(self) -> int:
        value = max(1, int(self.interval_value or 1))
        return value * 60 if self.interval_unit == "hours" else value

    def schedule_config(self) -> ScheduleConfig:
        return ScheduleConfig(
            start_date=self.start_date or datetime.now().strftime("%Y-%m-%d"),
            start_time=self.start_time or "12:00",
            chapters_per_day=max(1, int(self.chapters_per_day or 1)),
            interval_minutes=self.interval_minutes(),
            limit_per_day_enabled=bool(self.per_day_enabled),
            skip_enabled=bool(self.skip_enabled),
            skip_start=self.skip_start or "00:00",
            skip_end=self.skip_end or "06:00",
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NovelJob":
        allowed = {f.name for f in fields(cls)}
        clean = {k: v for k, v in (data or {}).items() if k in allowed}
        job = cls(**clean)
        if job.status not in JOB_STATUS_META or job.status == "running":
            job.status = "ready"
        if job.price_mode not in PRICE_MODES:
            job.price_mode = "auto_free"
        if job.publish_mode not in PUBLISH_MODES:
            job.publish_mode = "scheduled"
        if job.interval_unit not in ("minutes", "hours"):
            job.interval_unit = "minutes"
        if job.target_mode not in TARGET_MODES:
            job.target_mode = "draft"
        if job.free_rule not in FREE_RULES:
            job.free_rule = FREE_RULES[0]
        return job

    # fields that "Apply to All" copies
    SETTINGS_PRICING = ("price_mode", "price_value", "free_rule", "free_custom")
    SETTINGS_SCHEDULE = (
        "publish_mode", "start_date", "start_time", "per_day_enabled", "chapters_per_day",
        "interval_value", "interval_unit", "skip_enabled", "skip_start", "skip_end", "max_episodes",
        "continue_after_last", "target_mode",
    )


@dataclass
class PlanItem:
    order: int
    title: str
    episode_number: int
    publish_dt: Optional[datetime]
    price_mode: Optional[str]  # "free" | "paid" | None(keep)
    price_value: int


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def read_json(path: Path, default=None):
    if default is None:
        default = {}
    try:
        if not path.exists():
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json_atomic(path: Path, data):
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def normalize_episode_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    match = WORKING_URL_RE.search(raw)
    if match:
        return f"https://mynovel.co/dashboard/workings/{match.group(1)}?tab=episode"
    return raw.split("?")[0] + "?tab=episode"


def is_valid_working_url(url: str) -> bool:
    return bool(WORKING_URL_RE.search(url or ""))


def short_url_label(url: str) -> str:
    match = WORKING_URL_RE.search(url or "")
    return f"…/{match.group(1)}" if match else ""


def extract_episode_number_from_text(text: str) -> Optional[int]:
    source = (text or "").strip()
    if not source:
        return None
    patterns = [
        r"ตอนที่\s*(\d+)",
        r"ตอน\s*(\d+)",
        r"chapter\s*(\d+)",
        r"ep(?:isode)?\.?\s*(\d+)",
        r"(?:^|\D)(\d{1,6})(?:\D|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, source, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except Exception:
                continue
    return None


def parse_custom_numbers(text: str) -> set:
    """รองรับ '1,2,3' และช่วง '1-10, 15, 20-22'"""
    result = set()
    for part in re.split(r"[,\s]+", (text or "").strip()):
        if not part:
            continue
        range_match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if range_match:
            a, b = int(range_match.group(1)), int(range_match.group(2))
            if a > b:
                a, b = b, a
            if b - a <= 100000:
                result.update(range(a, b + 1))
        elif part.isdigit():
            result.add(int(part))
    return result


def is_episode_free_by_rule(episode_number: Optional[int], rule_text: str, custom_text: str = "") -> bool:
    if episode_number is None:
        return False
    rule_text = (rule_text or "").strip()
    if "กำหนดเอง" in rule_text:
        return episode_number in parse_custom_numbers(custom_text)
    if "ลงท้ายด้วย 5, 0" in rule_text:
        return episode_number % 5 == 0
    if "ลงท้ายด้วย 0" in rule_text:
        return episode_number % 10 == 0
    if "ลงท้ายด้วย 5" in rule_text:
        return episode_number % 10 == 5
    if "ทุก 3 ตอน" in rule_text:
        return episode_number % 3 == 0
    if "ทุก 5 ตอน" in rule_text:
        return episode_number % 5 == 0
    if "ทุก 10 ตอน" in rule_text:
        return episode_number % 10 == 0
    return False


def resolve_price_for_episode(job: NovelJob, episode_number: int):
    """คืนค่า (price_mode, price_value) ; price_mode=None หมายถึงไม่แก้ราคา"""
    if job.price_mode == "keep":
        return None, job.price_value
    if job.price_mode == "free_all":
        return "free", 0
    if job.price_mode == "paid_all":
        return "paid", int(job.price_value)
    is_free = is_episode_free_by_rule(episode_number, job.free_rule, job.free_custom)
    return ("free", 0) if is_free else ("paid", int(job.price_value))


def is_time_in_skip_window(time_text: str, skip_start: str, skip_end: str) -> bool:
    if not skip_start or not skip_end or skip_start == skip_end:
        return False
    if skip_start < skip_end:
        return skip_start <= time_text < skip_end
    return time_text >= skip_start or time_text < skip_end


def advance_out_of_skip_window(current_dt: datetime, skip_start: str, skip_end: str) -> datetime:
    end_hour, end_minute = [int(part) for part in skip_end.split(":")]
    adjusted = current_dt.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    if skip_start > skip_end and current_dt.strftime("%H:%M") >= skip_start:
        adjusted += timedelta(days=1)
    return adjusted


def compute_schedule_datetimes(count: int, cfg: ScheduleConfig) -> List[datetime]:
    """
    คำนวณวัน-เวลาเผยแพร่ต่อเนื่องทีละตอน
    - จำกัดวันละ N ตอน = 1 ชุด เริ่มที่ 'เวลาเริ่ม' ปล่อยห่างกันตามระยะห่างจนครบ N ตอน
      (ชุดเดียวกันข้ามเที่ยงคืนได้ ไม่ถูกตัดตามวันที่ปฏิทิน) แล้วชุดถัดไปเริ่มวันถัดไปที่ 'เวลาเริ่ม'
      เช่น 10 ตอน/วัน ห่าง 1 ชม. เริ่ม 15:00 → 15:00…00:00 แล้ววันถัดไป 15:00
    - ไม่จำกัดต่อวัน = ปล่อยต่อเนื่องตามระยะห่างไปเรื่อยๆ
    """
    result: List[datetime] = []
    if count <= 0:
        return result
    hour, minute = [int(x) for x in (cfg.start_time or "12:00").split(":")[:2]]
    base_dt = datetime.strptime(cfg.start_date, "%Y-%m-%d").replace(hour=hour, minute=minute)
    skip_start = cfg.skip_start if cfg.skip_enabled else None
    skip_end = cfg.skip_end if cfg.skip_enabled else None
    daily_limit = max(1, int(cfg.chapters_per_day or 1)) if cfg.limit_per_day_enabled else None
    interval = max(1, int(cfg.interval_minutes or 1))
    current_dt = base_dt
    batch_start = base_dt
    in_batch = 0
    for _ in range(count):
        guard = 0
        while skip_start and skip_end and is_time_in_skip_window(current_dt.strftime("%H:%M"), skip_start, skip_end):
            current_dt = advance_out_of_skip_window(current_dt, skip_start, skip_end)
            guard += 1
            if guard > 3:
                break
        result.append(current_dt)
        in_batch += 1
        if daily_limit is not None and in_batch >= daily_limit:
            next_batch = (batch_start + timedelta(days=1)).replace(hour=hour, minute=minute)
            while next_batch <= current_dt:
                next_batch += timedelta(days=1)
            current_dt = next_batch
            batch_start = next_batch
            in_batch = 0
        else:
            current_dt += timedelta(minutes=interval)
    return result


def parse_last_scheduled(text: str) -> Optional[datetime]:
    try:
        return datetime.strptime((text or "").strip(), "%Y-%m-%d %H:%M")
    except Exception:
        return None


def job_schedule_slots(job: "NovelJob", count: int) -> List[datetime]:
    """ช่องเวลาเผยแพร่ count ช่อง — ถ้าเปิด 'ต่อจากรอบก่อน' จะข้ามช่องที่ <= เวลาล่าสุดที่เคยตั้ง"""
    if count <= 0:
        return []
    cfg = job.schedule_config()
    last = parse_last_scheduled(job.last_scheduled_at) if job.continue_after_last else None
    if last is None:
        return compute_schedule_datetimes(count, cfg)
    n = count + 50
    for _ in range(12):
        slots = [d for d in compute_schedule_datetimes(n, cfg) if d > last]
        if len(slots) >= count:
            return slots[:count]
        n *= 4
    return slots[:count]


def format_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}ชม. {minutes:02d}น."
    if minutes:
        return f"{minutes:d}น. {secs:02d}วิ"
    return f"{secs:d}วิ"


def format_thai_dt(dt: Optional[datetime]) -> str:
    if dt is None:
        return "-"
    return f"{dt.day:02d}/{dt.month:02d}/{dt.year + 543} {dt.strftime('%H:%M')}"


def parse_calendar_caption(caption: str):
    """แปลงข้อความหัวปฏิทิน เช่น 'October 2026' / 'ตุลาคม 2569' เป็น (year, month)"""
    text = (caption or "").strip()
    if not text:
        return None
    year_match = re.search(r"(\d{4})", text)
    if not year_match:
        return None
    year = int(year_match.group(1))
    if year > 2400:
        year -= 543
    lowered = text.lower()
    for name, month in sorted(EN_MONTHS.items(), key=lambda kv: -len(kv[0])):
        if name in lowered:
            return year, month
    for name, month in sorted(THAI_MONTHS.items(), key=lambda kv: -len(kv[0])):
        if name in text:
            return year, month
    num_match = re.search(r"\b(\d{1,2})\s*/\s*\d{4}", text)
    if num_match:
        return year, int(num_match.group(1))
    return None


# ---------------------------------------------------------------------------
# Chrome helpers
# ---------------------------------------------------------------------------
def detect_chrome_path() -> str:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return ""


def build_automation_profile() -> BrowserProfile:
    root = APP_DIR / "automation_profile"
    root.mkdir(parents=True, exist_ok=True)
    return BrowserProfile(label="Automation Profile", user_data_dir=str(root), profile_dir_name="Default")


def build_guest_profile() -> BrowserProfile:
    return BrowserProfile(label="Guest", user_data_dir="", profile_dir_name="")


def build_profile_from_custom_path(custom_path: str) -> BrowserProfile:
    return BrowserProfile(label=f"Custom: {Path(custom_path).name}", user_data_dir=custom_path, profile_dir_name="Default")


def load_chrome_profiles() -> List[BrowserProfile]:
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if not local_app_data:
        return []
    user_data_dir = Path(local_app_data) / "Google" / "Chrome" / "User Data"
    if not user_data_dir.exists():
        return []
    local_state = read_json(user_data_dir / "Local State", {})
    info_cache = ((local_state or {}).get("profile") or {}).get("info_cache") or {}
    profiles = []
    try:
        entries = sorted(user_data_dir.iterdir())
    except Exception:
        return []
    for profile_dir in entries:
        if not profile_dir.is_dir():
            continue
        if profile_dir.name not in info_cache and not profile_dir.name.startswith("Profile") and profile_dir.name != "Default":
            continue
        cache_entry = info_cache.get(profile_dir.name, {}) if isinstance(info_cache, dict) else {}
        display_name = (cache_entry.get("name") or profile_dir.name or "").strip()
        email = (cache_entry.get("user_name") or cache_entry.get("email") or "").strip()
        label = f"{display_name} ({email})" if email else display_name
        profiles.append(BrowserProfile(label=label, user_data_dir=str(user_data_dir), profile_dir_name=profile_dir.name))
    return profiles


# ---------------------------------------------------------------------------
# Selenium bot
# ---------------------------------------------------------------------------
JS_READ_ROWS = r"""
const STATUSES = ['ฉบับร่าง', 'ตั้งเวลา', 'เผยแพร่แล้ว', 'เผยแพร่'];
const out = [];
const rows = Array.from(document.querySelectorAll('table tbody tr'));
rows.forEach((tr, i) => {
  if (tr.getClientRects().length === 0) return;
  const tds = Array.from(tr.querySelectorAll('td'));
  if (tds.length < 3) return;
  let order = null, orderIdx = -1;
  for (let k = 0; k < tds.length; k++) {
    const t = (tds[k].innerText || '').trim();
    if (/^\d{1,6}$/.test(t)) { order = parseInt(t, 10); orderIdx = k; break; }
  }
  let title = '';
  if (orderIdx >= 0 && tds[orderIdx + 1]) {
    title = ((tds[orderIdx + 1].innerText || '').trim().split('\n')[0] || '').trim();
  }
  let status = '';
  outer:
  for (const td of tds) {
    const els = [td, ...td.querySelectorAll('span,div,p')];
    for (const el of els) {
      const t = (el.innerText || '').trim();
      if (STATUSES.includes(t)) { status = t; break outer; }
    }
  }
  if (!status) {
    const txt = tr.innerText || '';
    for (const s of STATUSES) { if (txt.includes(s)) { status = s; break; } }
  }
  out.push({index: i, order: order, title: title, status: status});
});
return out;
"""

JS_LIST_SIGNATURE = r"""
const rows = Array.from(document.querySelectorAll('table tbody tr')).filter(r => r.getClientRects().length > 0);
const head = rows.slice(0, 3).map(r => (r.innerText || '').replace(/\s+/g, ' ').slice(0, 80)).join('|');
const tail = rows.length ? (rows[rows.length - 1].innerText || '').replace(/\s+/g, ' ').slice(0, 80) : '';
return rows.length + '#' + head + '#' + tail;
"""

JS_FIND_EDIT_BUTTON = r"""
const order = String(arguments[0]);
const rows = Array.from(document.querySelectorAll('table tbody tr'));
for (const tr of rows) {
  if (tr.getClientRects().length === 0) continue;
  const tds = Array.from(tr.querySelectorAll('td'));
  let rowOrder = null;
  for (const td of tds) {
    const t = (td.innerText || '').trim();
    if (/^\d{1,6}$/.test(t)) { rowOrder = t.replace(/^0+(?=\d)/, ''); break; }
  }
  if (rowOrder !== order) continue;
  const candidates = Array.from(tr.querySelectorAll('button, a, [role="button"]'))
    .filter(el => el.getClientRects().length > 0 && el.getAttribute('role') !== 'checkbox' && !el.querySelector('input[type=checkbox]'));
  const byText = candidates.find(el => ((el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('title') || '')).includes('แก้ไข'));
  if (byText) return byText;
  const byIcon = candidates.find(el => {
    const svg = el.querySelector('svg');
    const cls = svg ? (svg.getAttribute('class') || '') : '';
    return /pencil|pen|edit|square-pen/i.test(cls);
  });
  if (byIcon) return byIcon;
  if (candidates.length) return candidates[candidates.length - 1];
  return null;
}
return null;
"""

JS_FIND_NEXT_PAGE = r"""
// กลยุทธ์ 1: ปุ่มลูกศร "ถัดไป" (chevron-right / aria-label next) ที่อยู่ใต้ตาราง
const table = document.querySelector('table');
const tableBottom = table ? table.getBoundingClientRect().bottom + window.scrollY - 5 : 0;
const isDisabled = (el) => {
  if (el.disabled) return true;
  if ((el.getAttribute('aria-disabled') || '') === 'true') return true;
  if (el.hasAttribute('data-disabled')) return true;
  if (/cursor-not-allowed/.test(el.getAttribute('class') || '')) return true;
  const st = window.getComputedStyle(el);
  if (st.pointerEvents === 'none' || parseFloat(st.opacity || '1') < 0.45) return true;
  return false;
};
const isNextLike = (el) => {
  const label = ((el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('title') || '') + ' ' + (el.innerText || '')).toLowerCase();
  if (/next|ถัดไป|หน้าถัด/.test(label)) return true;
  const txt = (el.innerText || '').trim();
  if (txt === '>' || txt === '›' || txt === '»' || txt === '→') return true;
  const svg = el.querySelector('svg');
  if (!svg) return false;
  const cls = (svg.getAttribute('class') || '') + ' ' + (svg.getAttribute('data-icon') || '');
  if (/chevron-right|chevronright|arrow-right|angle-right/i.test(cls)) return true;
  const html = svg.innerHTML || '';
  return html.includes('m9 18 6-6-6-6') || html.includes('M9 18l6-6-6-6');
};
const all = Array.from(document.querySelectorAll('button, a, [role="button"], li[class*="next"]'))
  .filter(el => el.getClientRects().length > 0 && !el.closest('table') && !el.closest('[role="dialog"]'));
let cands = all.filter(isNextLike);
const below = cands.filter(el => (el.getBoundingClientRect().top + window.scrollY) >= tableBottom);
if (below.length) cands = below;
if (!cands.length) return null;
cands.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top || b.getBoundingClientRect().left - a.getBoundingClientRect().left);
const best = cands[0];
return isDisabled(best) ? 'DISABLED' : best;
"""

JS_FIND_PAGE_NUMBER_NEXT = r"""
// กลยุทธ์ 2: หาเลขหน้าปัจจุบันแล้วกดเลขถัดไป
const table = document.querySelector('table');
const tableBottom = table ? table.getBoundingClientRect().bottom + window.scrollY - 5 : 0;
const nums = Array.from(document.querySelectorAll('button, a, [role="button"]'))
  .filter(el => el.getClientRects().length > 0 && !el.closest('table') && /^\d{1,4}$/.test((el.innerText || '').trim()))
  .filter(el => (el.getBoundingClientRect().top + window.scrollY) >= tableBottom);
if (nums.length < 2) return null;
let current = nums.find(el => el.getAttribute('aria-current') === 'page' || el.getAttribute('data-active') === 'true' || el.getAttribute('aria-pressed') === 'true' || el.getAttribute('data-state') === 'active');
if (!current) {
  const counts = {};
  nums.forEach(el => { const c = el.className || ''; counts[c] = (counts[c] || 0) + 1; });
  const unique = nums.filter(el => counts[el.className || ''] === 1);
  if (unique.length === 1) current = unique[0];
}
if (!current) return null;
const want = String(parseInt((current.innerText || '').trim(), 10) + 1);
return nums.find(el => (el.innerText || '').trim() === want) || null;
"""

JS_PAGINATION_DEBUG = r"""
const table = document.querySelector('table');
const tableBottom = table ? table.getBoundingClientRect().bottom + window.scrollY - 5 : 0;
const els = Array.from(document.querySelectorAll('button, a, [role="button"], nav'))
  .filter(el => el.getClientRects().length > 0 && !el.closest('table'))
  .filter(el => (el.getBoundingClientRect().top + window.scrollY) >= tableBottom);
let container = els.length ? els[0].parentElement : null;
for (let i = 0; i < 4 && container && container.querySelectorAll('button, a').length < 3; i++) container = container.parentElement;
const html = container ? container.outerHTML : '(no pagination found under table)';
return html.replace(/<path[^>]*>/g, '').replace(/\s+/g, ' ').slice(0, 2500);
"""

JS_DRAFT_TOTAL = r"""
const label = arguments[0] || 'ฉบับร่าง';
const hits = [];
for (const el of document.querySelectorAll('div, span, p, button, li')) {
  if (el.closest('table')) continue;
  const t = (el.innerText || '').replace(/\s+/g, ' ').trim();
  if (!t.startsWith(label)) continue;
  const m = t.slice(label.length).match(/^\s*:?\s*([\d,]+)$/);
  if (m) hits.push(parseInt(m[1].replace(/,/g, ''), 10));
}
return hits.length ? hits[0] : null;
"""

JS_EDIT_ROOT = r"""
const markers = ['กำหนดราคา', 'สถานะเผยแพร่', 'ราคาตอน', 'เผยแพร่ทันที', 'ตั้งเวลา'];
const dialogs = Array.from(document.querySelectorAll('[role="dialog"], [role="alertdialog"]'))
  .filter(d => d.getClientRects().length > 0);
for (let i = dialogs.length - 1; i >= 0; i--) {
  const d = dialogs[i];
  const hasTitle = d.querySelector('[name="chapterTitle"]') !== null;
  const txt = d.innerText || '';
  const isCalendarOnly = d.querySelector('.rdp-caption_label') !== null && !hasTitle && !txt.includes('กำหนดราคา');
  if (isCalendarOnly) continue;
  if (hasTitle || markers.some(m => txt.includes(m))) return d;
}
return null;
"""

JS_DIALOG_ERRORS = r"""
const root = arguments[0] || document;
const sel = '[role="alert"], .text-destructive, [class*="text-red"], [class*="destructive"], [data-slot="form-message"], p[id$="-form-item-message"]';
return Array.from(root.querySelectorAll(sel))
  .filter(el => el.getClientRects().length > 0)
  .map(el => (el.innerText || '').trim())
  .filter(t => t && t.length < 300)
  .slice(0, 5)
  .join(' | ');
"""


_SKIPPED_PROFILE_FILES: List[str] = []


def short_error(error: Exception) -> str:
    """ข้อความ error บรรทัดเดียว (ตัด Stacktrace ของ chromedriver ทิ้ง)"""
    text = str(error).strip().split("\n")[0].replace("Message: ", "").strip()
    return f"{type(error).__name__}: {text[:200]}" if text else type(error).__name__


def _tolerant_copy2(src, dst, *args, **kwargs):
    """คัดลอกไฟล์โปรไฟล์ ถ้าไฟล์ถูกล็อก (Chrome เปิดอยู่) ให้ข้ามไป ไม่ล้มทั้งงาน"""
    try:
        return shutil.copy2(src, dst)
    except (PermissionError, OSError):
        _SKIPPED_PROFILE_FILES.append(os.path.basename(str(src)))
        return dst


OFFSCREEN_POS = -10000

JS_PAGE_MESSAGES = r"""
const sel = '[role="status"], [role="alert"], [data-sonner-toast], .toast, [class*="toast"], [class*="Toastify"]';
return Array.from(document.querySelectorAll(sel))
  .filter(el => el.getClientRects().length > 0)
  .map(el => (el.innerText || '').replace(/\s+/g, ' ').trim())
  .filter(t => t && t.length < 300)
  .slice(0, 5).join(' | ');
"""


class MyNovelBot:
    def __init__(self, log_func: Callable[[str], None] = print, should_stop: Optional[Callable[[], bool]] = None):
        self.log_func = log_func
        self.should_stop = should_stop or (lambda: False)
        self._driver_temp_dirs: Dict[int, Path] = {}
        self.use_draft_filter = True
        self.last_saved_dt: Optional[datetime] = None
        self.debug_tag = ""
        self._debug_dumps = 0

    # ------------------------------------------------------------- logging
    def log(self, msg: str, level: str = "info"):
        try:
            self.log_func(msg, level)
        except TypeError:
            self.log_func(msg)

    def debug(self, msg: str):
        self.log(msg, "dim")

    def check_stop(self):
        if self.should_stop():
            raise StopRequested("ผู้ใช้สั่งหยุด")

    def sleep(self, seconds: float):
        end = time.time() + seconds
        while time.time() < end:
            self.check_stop()
            time.sleep(min(0.1, max(0.0, end - time.time())))

    # ------------------------------------------------------------- driver
    def prepare_profile_runtime_copy(self, profile: BrowserProfile):
        if not profile.user_data_dir:
            return profile, None
        source_user_data_dir = Path(profile.user_data_dir)
        if not source_user_data_dir.exists():
            raise RuntimeError(f"ไม่พบโฟลเดอร์ Chrome profile: {source_user_data_dir}")
        profile_dir_name = profile.profile_dir_name or "Default"
        source_profile_dir = source_user_data_dir / profile_dir_name
        if not source_profile_dir.exists() and (source_user_data_dir / "Preferences").exists():
            source_profile_dir = source_user_data_dir
            profile_dir_name = "Default"
        if not source_profile_dir.exists():
            raise RuntimeError(f"ไม่พบโฟลเดอร์โปรไฟล์ย่อย: {source_profile_dir}")
        temp_root = Path(tempfile.mkdtemp(prefix="keawgood_profile_"))
        temp_user_data_dir = temp_root / "User Data"
        temp_user_data_dir.mkdir(parents=True, exist_ok=True)
        local_state_path = source_user_data_dir / "Local State"
        if local_state_path.exists():
            shutil.copy2(local_state_path, temp_user_data_dir / "Local State")
        shutil.copytree(
            source_profile_dir,
            temp_user_data_dir / profile_dir_name,
            ignore=shutil.ignore_patterns(
                "Singleton*", "LOCK", "lockfile", "DevToolsActivePort", "Current Session", "Current Tabs",
                "Last Session", "Last Tabs", "Sessions", "Crashpad*", "BrowserMetrics*", "Cache", "Code Cache",
                "GPUCache", "Service Worker", "*.log",
            ),
            dirs_exist_ok=True,
            copy_function=_tolerant_copy2,
        )
        return BrowserProfile(profile.label, str(temp_user_data_dir), profile_dir_name), temp_root

    def create_driver(self, chrome_path: str, profile: BrowserProfile, headless: bool = False, use_runtime_copy: bool = True):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from selenium.webdriver.chrome.service import Service as ChromeService

        if use_runtime_copy:
            _SKIPPED_PROFILE_FILES.clear()
            runtime_profile, temp_root = self.prepare_profile_runtime_copy(profile)
            if _SKIPPED_PROFILE_FILES:
                self.log(
                    f"⚠ คัดลอกไฟล์โปรไฟล์ไม่ได้ {len(_SKIPPED_PROFILE_FILES)} ไฟล์ "
                    f"(เช่น {', '.join(_SKIPPED_PROFILE_FILES[:4])}) — มี Chrome เปิดโปรไฟล์นี้อยู่หรือไม่?",
                    "warn",
                )
        else:
            runtime_profile, temp_root = profile, None
        # headless: False/"show" = แสดงหน้าต่าง · "offscreen" = หน้าต่างจริงแต่ย้ายออกนอกจอ · True/"headless" = headless
        window_mode = "headless" if headless is True else (headless or "show")
        options = ChromeOptions()
        if chrome_path and os.path.exists(chrome_path):
            options.binary_location = chrome_path
        if window_mode == "headless":
            options.add_argument("--headless=new")
        elif window_mode == "offscreen":
            options.add_argument(f"--window-position={OFFSCREEN_POS},{OFFSCREEN_POS}")
        for arg in (
            "--window-size=1600,1200",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-debugging-port=0",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
            "--disable-features=CalculateNativeWinOcclusion",
            "--disable-blink-features=AutomationControlled",
            "--lang=th-TH",
        ):
            options.add_argument(arg)
        if runtime_profile.user_data_dir:
            options.add_argument(f"--user-data-dir={runtime_profile.user_data_dir}")
        if runtime_profile.profile_dir_name:
            options.add_argument(f"--profile-directory={runtime_profile.profile_dir_name}")
        try:
            service_kwargs = {}
            if os.name == "nt":
                service_kwargs["popen_kw"] = {"creation_flags": 0x08000000}  # CREATE_NO_WINDOW: ไม่ให้ chromedriver เปิดหน้าต่างดำ
            service = ChromeService(**service_kwargs)
            if os.name == "nt":
                try:
                    service.creation_flags = 0x08000000
                except Exception:
                    pass
            driver = webdriver.Chrome(service=service, options=options)
        except Exception as error:
            if temp_root:
                shutil.rmtree(temp_root, ignore_errors=True)
            raise RuntimeError(
                "เปิด Chrome ไม่สำเร็จ — โปรไฟล์อาจถูกเปิดใช้งานอยู่ (ปิด Chrome ที่ใช้โปรไฟล์นี้ก่อน) "
                f"หรือ Chrome/ChromeDriver มีปัญหา\nรายละเอียด: {error}"
            )
        if temp_root:
            self._driver_temp_dirs[id(driver)] = temp_root
        driver.set_page_load_timeout(60)
        if window_mode == "headless":
            # ซ่อนคำว่า HeadlessChrome ใน user-agent ให้เว็บเห็นเหมือน Chrome ปกติ
            try:
                ua = driver.execute_script("return navigator.userAgent") or ""
                if "Headless" in ua:
                    driver.execute_cdp_cmd("Network.setUserAgentOverride", {
                        "userAgent": ua.replace("HeadlessChrome", "Chrome"),
                        "acceptLanguage": "th-TH,th;q=0.9,en;q=0.8",
                    })
            except Exception:
                pass
        try:
            if window_mode == "offscreen":
                driver.set_window_rect(OFFSCREEN_POS, OFFSCREEN_POS, 1600, 1200)
            else:
                driver.set_window_rect(0, 0, 1600, 1200)
        except Exception:
            pass
        return driver

    def cleanup_driver(self, driver):
        if driver is None:
            return
        temp_root = self._driver_temp_dirs.pop(id(driver), None)
        try:
            driver.quit()
        except Exception:
            pass
        if temp_root:
            shutil.rmtree(temp_root, ignore_errors=True)

    def open_login_browser(self, chrome_path: str, profile: BrowserProfile, persistent_profile: bool = False):
        driver = self.create_driver(chrome_path, profile, headless=False, use_runtime_copy=not persistent_profile)
        driver.get(MYNOVEL_LOGIN_URL)
        return driver

    # ------------------------------------------------------------- low level ui helpers
    def is_alive(self, driver) -> bool:
        try:
            _ = driver.current_url
            return True
        except Exception:
            return False

    def scroll_into_view(self, driver, element):
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'nearest'});", element)
        except Exception:
            pass

    def native_click(self, driver, element):
        """คลิกแบบ native (มี pointer events) แล้ว fallback เป็น ActionChains / JS"""
        self.scroll_into_view(driver, element)
        try:
            element.click()
            return
        except StaleElementReferenceException:
            raise
        except Exception:
            pass
        try:
            ActionChains(driver).move_to_element(element).pause(0.05).click().perform()
            return
        except StaleElementReferenceException:
            raise
        except Exception:
            pass
        driver.execute_script("arguments[0].click();", element)

    def js_click(self, driver, element):
        try:
            driver.execute_script("arguments[0].click();", element)
        except Exception:
            self.native_click(driver, element)

    def set_react_input_value(self, driver, element, value: str):
        driver.execute_script(
            """
            const el = arguments[0];
            const val = arguments[1];
            const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
            setter.call(el, val);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            """,
            element,
            value,
        )

    def blur_active_element(self, driver):
        try:
            driver.execute_script("const a=document.activeElement; if(a && a.blur) a.blur();")
        except Exception:
            pass

    def press_escape(self, driver):
        try:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            try:
                driver.execute_script(
                    "document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));"
                )
            except Exception:
                pass

    def scroll_modal_element_into_view(self, driver, element):
        try:
            driver.execute_script(
                """
                const element = arguments[0];
                if (!element) return;
                let cur = element.parentElement;
                while (cur) {
                    const st = window.getComputedStyle(cur);
                    const oy = st.overflowY || '';
                    if ((oy.includes('auto') || oy.includes('scroll')) && cur.scrollHeight > cur.clientHeight) {
                        const cr = cur.getBoundingClientRect();
                        const er = element.getBoundingClientRect();
                        cur.scrollTop += er.top - cr.top - (cur.clientHeight / 2) + (er.height / 2);
                    }
                    cur = cur.parentElement;
                }
                element.scrollIntoView({ block: 'center', inline: 'nearest' });
                """,
                element,
            )
        except Exception:
            pass

    def visible(self, elements):
        result = []
        for el in elements:
            try:
                if el.is_displayed():
                    result.append(el)
            except Exception:
                continue
        return result

    # ------------------------------------------------------------- list page
    def ensure_logged_in(self, driver):
        url = (driver.current_url or "").lower()
        if any(k in url for k in ("/auth", "/login", "/signin", "/sign-in")):
            raise NotLoggedInError("ยังไม่ได้ล็อกอิน MyNovel — กดปุ่ม 'เปิดหน้า Login' แล้วล็อกอินก่อน จากนั้นค่อยเริ่มใหม่")

    def wait_for_table(self, driver, timeout: float = 30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.check_stop()
            self.ensure_logged_in(driver)
            try:
                rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
                if self.visible(rows):
                    return True
                body_text = driver.execute_script("return (document.body && document.body.innerText) || ''") or ""
                if "ไม่พบตอน" in body_text or "ยังไม่มีตอน" in body_text:
                    return False
            except WebDriverException:
                pass
            time.sleep(0.3)
        raise TimeoutException("รอตารางรายการตอนไม่สำเร็จ (หน้าเว็บโหลดช้า หรือ URL ไม่ถูกต้อง)")

    def list_signature(self, driver) -> str:
        try:
            return driver.execute_script(JS_LIST_SIGNATURE) or ""
        except Exception:
            return ""

    def wait_list_settle(self, driver, previous_signature: Optional[str] = None, timeout: float = 10.0, quiet: float = 0.7):
        """รอจนตารางเปลี่ยน (ถ้าระบุ previous) และนิ่งอย่างน้อย quiet วินาที"""
        deadline = time.time() + timeout
        changed = previous_signature is None
        last = self.list_signature(driver)
        last_change = time.time()
        while time.time() < deadline:
            self.check_stop()
            time.sleep(0.2)
            sig = self.list_signature(driver)
            if previous_signature is not None and sig != previous_signature:
                changed = True
            if sig != last:
                last = sig
                last_change = time.time()
                continue
            if changed and time.time() - last_change >= quiet:
                return True
        return changed

    def read_rows(self, driver) -> List[Dict[str, Any]]:
        for _ in range(3):
            try:
                rows = driver.execute_script(JS_READ_ROWS) or []
                return [r for r in rows if r.get("order") is not None]
            except WebDriverException:
                time.sleep(0.3)
        return []

    def open_episode_list(self, driver, list_url: str):
        self.check_stop()
        driver.get(list_url)
        time.sleep(0.8)
        self.ensure_logged_in(driver)
        has_rows = self.wait_for_table(driver)
        return has_rows

    def read_novel_title(self, driver) -> str:
        try:
            title = driver.execute_script(
                """
                const skip = ['ผลงานของฉัน','คลังตอน','ข้อมูลผลงาน','จัดการตอน','รายได้','ภาพรวม'];
                const els = Array.from(document.querySelectorAll('main h1, main h2, h1, h2'));
                for (const el of els) {
                  const t = (el.innerText || '').trim();
                  if (t && t.length > 3 && !skip.some(s => t.startsWith(s))) return t;
                }
                return '';
                """
            ) or ""
            return title.strip().split("\n")[0][:200]
        except Exception:
            return ""

    def find_comboboxes(self, driver):
        try:
            return self.visible(driver.find_elements(By.CSS_SELECTOR, "button[role='combobox'], [role='combobox']"))
        except Exception:
            return []

    def select_combobox_option(self, driver, trigger_match: Callable[[str], bool], option_pick: Callable[[List[str]], Optional[int]], label: str) -> bool:
        """เปิด Select (Radix/shadcn) ที่ trigger_match(text) และเลือก option ตาม option_pick(texts)->index"""
        trigger = None
        for el in self.find_comboboxes(driver):
            try:
                if trigger_match((el.text or "").strip()):
                    trigger = el
                    break
            except StaleElementReferenceException:
                continue
        if trigger is None:
            # fallback: native <select>
            try:
                for sel in self.visible(driver.find_elements(By.TAG_NAME, "select")):
                    texts = [o.text.strip() for o in sel.find_elements(By.TAG_NAME, "option")]
                    if trigger_match(" ".join(texts)):
                        idx = option_pick(texts)
                        if idx is not None:
                            from selenium.webdriver.support.ui import Select
                            Select(sel).select_by_index(idx)
                            return True
            except Exception:
                pass
            self.debug(f"ไม่พบตัวเลือก '{label}' บนหน้าเว็บ")
            return False

        for attempt in range(3):
            try:
                if attempt == 0:
                    self.native_click(driver, trigger)
                elif attempt == 1:
                    ActionChains(driver).move_to_element(trigger).click().perform()
                else:
                    trigger.send_keys(Keys.ENTER)
            except Exception:
                pass
            options = []
            deadline = time.time() + 2.5
            while time.time() < deadline:
                options = self.visible(driver.find_elements(By.CSS_SELECTOR, "[role='option']"))
                if options:
                    break
                time.sleep(0.15)
            if not options:
                continue
            texts = []
            for o in options:
                try:
                    texts.append((o.text or "").strip())
                except Exception:
                    texts.append("")
            idx = option_pick(texts)
            if idx is None:
                self.press_escape(driver)
                self.debug(f"ไม่พบตัวเลือกที่ต้องการใน '{label}': {texts}")
                return False
            target = options[idx]
            try:
                self.native_click(driver, target)
            except Exception:
                self.js_click(driver, target)
            time.sleep(0.3)
            if self.visible(driver.find_elements(By.CSS_SELECTOR, "[role='option']")):
                self.press_escape(driver)
            return True
        self.debug(f"เปิดตัวเลือก '{label}' ไม่สำเร็จ")
        return False

    def apply_list_view(self, driver):
        """ปรับมุมมอง: แสดงต่อหน้ามากสุด, เรียงตอนแรก→ตอนล่าสุด, (กรองฉบับร่าง)"""
        # 1) items per page -> max
        def is_page_size(text):
            return bool(re.fullmatch(r"\d+\s*รายการ", text or ""))

        def pick_max(texts):
            best_idx, best_val = None, -1
            for i, t in enumerate(texts):
                m = re.search(r"(\d+)", t or "")
                if m and int(m.group(1)) > best_val:
                    best_idx, best_val = i, int(m.group(1))
            return best_idx

        sig = self.list_signature(driver)
        if self.select_combobox_option(driver, is_page_size, pick_max, "จำนวนรายการต่อหน้า"):
            self.wait_list_settle(driver, sig, timeout=8)
            self.debug("ตั้งจำนวนรายการต่อหน้าเป็นค่าสูงสุดแล้ว")

        # 2) sort oldest -> newest
        def is_sort(text):
            return "ตอนแรก" in (text or "") and "ตอนล่าสุด" in (text or "")

        def oldest_first(text):
            t = text or ""
            return "ตอนแรก" in t and "ตอนล่าสุด" in t and t.index("ตอนแรก") < t.index("ตอนล่าสุด")

        current_sort = ""
        for el in self.find_comboboxes(driver):
            try:
                if is_sort(el.text):
                    current_sort = el.text.strip()
                    break
            except Exception:
                continue
        if current_sort and oldest_first(current_sort):
            self.debug("เรียงลำดับ ตอนแรก → ตอนล่าสุด อยู่แล้ว")
        else:
            sig = self.list_signature(driver)
            ok = self.select_combobox_option(
                driver,
                is_sort,
                lambda texts: next((i for i, t in enumerate(texts) if oldest_first(t)), None),
                "เรียงลำดับ",
            )
            if ok:
                self.wait_list_settle(driver, sig, timeout=8)
                self.log("เรียงลำดับเป็น ตอนแรก → ตอนล่าสุด แล้ว")
            else:
                self.log("สลับการเรียงลำดับไม่สำเร็จ — จะใช้การเรียงตามเลขลำดับภายในโปรแกรมแทน (ผลลัพธ์ยังถูกต้อง)", "warn")

        # 3) filter drafts only (optional)
        if self.use_draft_filter:
            def is_status_filter(text):
                return (text or "").strip() in ("ทุกสถานะ", STATUS_DRAFT, STATUS_SCHEDULED, STATUS_PUBLISHED, "เผยแพร่")

            sig = self.list_signature(driver)
            ok = self.select_combobox_option(
                driver,
                is_status_filter,
                lambda texts: next((i for i, t in enumerate(texts) if STATUS_DRAFT in t), None),
                "ตัวกรองสถานะ",
            )
            if ok:
                self.wait_list_settle(driver, sig, timeout=8)
                self.debug("กรองเฉพาะ 'ฉบับร่าง' แล้ว")

    def go_next_page(self, driver) -> bool:
        """ไปหน้าถัดไปของตาราง (ลองทั้งปุ่มลูกศรและปุ่มเลขหน้า) คืนค่า False ถ้าเป็นหน้าสุดท้าย/หาไม่เจอ"""
        disabled_seen = False
        for name, js in (("ลูกศรถัดไป", JS_FIND_NEXT_PAGE), ("เลขหน้าถัดไป", JS_FIND_PAGE_NUMBER_NEXT)):
            self.check_stop()
            try:
                target = driver.execute_script(js)
            except Exception:
                target = None
            if target == "DISABLED":
                disabled_seen = True
                continue
            if target is None:
                continue
            sig = self.list_signature(driver)
            for clicker in (self.native_click, self.js_click):
                try:
                    clicker(driver, target)
                except Exception:
                    continue
                if self.wait_list_settle(driver, sig, timeout=15):
                    self.debug(f"เปลี่ยนหน้าด้วย{name}สำเร็จ")
                    return True
        if not disabled_seen:
            self.log_pagination_debug(driver)
        return False

    def log_pagination_debug(self, driver):
        try:
            html = driver.execute_script(JS_PAGINATION_DEBUG) or ""
        except Exception as error:
            html = f"(อ่าน pagination ไม่ได้: {error})"
        self.debug(f"[pagination-debug] {html}")

    def read_draft_total(self, driver, label: str = STATUS_DRAFT) -> Optional[int]:
        try:
            value = driver.execute_script(JS_DRAFT_TOTAL, label)
            return int(value) if value is not None else None
        except Exception:
            return None

    def go_first_page_via_reload(self, driver, list_url: str):
        has_rows = self.open_episode_list(driver, list_url)
        if has_rows:
            self.apply_list_view(driver)
        return has_rows

    def scan_all_drafts(self, driver) -> List[Dict[str, Any]]:
        drafts: Dict[int, Dict[str, Any]] = {}
        seen_signatures = set()
        page = 1
        while True:
            self.check_stop()
            sig = self.list_signature(driver)
            if sig in seen_signatures:
                break
            seen_signatures.add(sig)
            rows = self.read_rows(driver)
            page_drafts = [r for r in rows if r.get("status") == STATUS_DRAFT]
            for r in page_drafts:
                drafts.setdefault(int(r["order"]), r)
            self.debug(f"สแกนหน้า {page}: {len(rows)} แถว, ฉบับร่าง {len(page_drafts)} ตอน (รวม {len(drafts)})")
            if page > 400 or not self.go_next_page(driver):
                break
            page += 1
        return sorted(drafts.values(), key=lambda r: int(r["order"]))

    # ------------------------------------------------------------- edit form
    def find_edit_root(self, driver):
        try:
            return driver.execute_script(JS_EDIT_ROOT)
        except Exception:
            return None

    def find_section_by_text(self, root, label_text: str):
        xpath = (
            f".//label[contains(normalize-space(.), '{label_text}')]/ancestor::div[contains(@class, 'space-y')][1]"
            f" | .//*[self::p or self::span or self::h3 or self::h4 or self::div][normalize-space(text())='{label_text}']/ancestor::div[contains(@class, 'space-y')][1]"
        )
        try:
            for section in root.find_elements(By.XPATH, xpath):
                try:
                    if section.is_displayed():
                        return section
                except Exception:
                    continue
        except Exception:
            pass
        return root

    def find_radio_control(self, root, value: str):
        selectors = [
            (By.CSS_SELECTOR, f"button[role='radio'][value='{value}']"),
            (By.CSS_SELECTOR, f"input[type='radio'][value='{value}']"),
            (By.CSS_SELECTOR, f"[role='radio'][value='{value}']"),
        ]
        for by, selector in selectors:
            try:
                elements = root.find_elements(by, selector)
            except Exception:
                continue
            for element in elements:
                try:
                    if element.is_displayed() or (element.get_attribute("type") or "") == "radio":
                        return element
                except Exception:
                    return element
        return None

    def radio_is_checked(self, control) -> bool:
        try:
            if (control.get_attribute("aria-checked") or "").lower() == "true":
                return True
            if (control.get_attribute("data-state") or "").lower() == "checked":
                return True
            if (control.get_attribute("type") or "").lower() == "radio" and control.is_selected():
                return True
        except Exception:
            pass
        return False

    def click_choice_by_keywords(self, driver, root, keywords) -> bool:
        lowered = [k.lower() for k in keywords if k]
        try:
            candidates = root.find_elements(By.XPATH, ".//label | .//button | .//*[@role='radio']")
        except Exception:
            return False
        for candidate in candidates:
            try:
                text = ((candidate.text or "") + " " + (candidate.get_attribute("aria-label") or "")).strip().lower()
                if not text or not any(k in text for k in lowered):
                    continue
                if not candidate.is_displayed():
                    continue
                self.scroll_modal_element_into_view(driver, candidate)
                self.native_click(driver, candidate)
                return True
            except Exception:
                continue
        return False

    def select_radio_value(self, driver, root, value: str, label_text: str, fallback_keywords: List[str]):
        control = self.find_radio_control(root, value)
        if control is None and root is not driver:
            control = self.find_radio_control(driver, value)
        if control is None:
            if self.click_choice_by_keywords(driver, root, fallback_keywords):
                return
            raise EditEpisodeError(f"ไม่พบตัวเลือก {label_text}: {value}")
        if self.radio_is_checked(control):
            return
        click_target = control
        try:
            label = control.find_element(By.XPATH, "ancestor::label[1]")
            if label.is_displayed():
                click_target = label
        except Exception:
            try:
                control_id = control.get_attribute("id")
                if control_id:
                    labels = root.find_elements(By.CSS_SELECTOR, f"label[for='{control_id}']")
                    if labels and labels[0].is_displayed():
                        click_target = labels[0]
            except Exception:
                pass
        self.scroll_modal_element_into_view(driver, click_target)
        self.native_click(driver, click_target)
        try:
            WebDriverWait(driver, 3).until(lambda d: self.radio_is_checked(control))
        except Exception:
            self.js_click(driver, control)
            time.sleep(0.3)
            if not self.radio_is_checked(control):
                if not self.click_choice_by_keywords(driver, root, fallback_keywords):
                    raise EditEpisodeError(f"เลือก {label_text}={value} ไม่สำเร็จ")

    def set_price(self, driver, root, price_mode: Optional[str], price_value: int):
        if price_mode is None:
            return
        section = self.find_section_by_text(root, "กำหนดราคา")
        self.scroll_modal_element_into_view(driver, section)
        target = "paid" if price_mode == "paid" else "free"
        self.select_radio_value(
            driver, section, target, "กำหนดราคา",
            ["ติดเหรียญ", "ขาย", "coin"] if target == "paid" else ["ฟรี", "ไม่ขาย"],
        )
        if target != "paid":
            return
        price_input = None
        selectors = [
            (By.NAME, "chapterPrice"),
            (By.CSS_SELECTOR, "input[name*='rice']"),
            (By.XPATH, ".//label[contains(., 'ราคา')]/following::input[1]"),
            (By.XPATH, ".//input[@type='number']"),
        ]
        deadline = time.time() + 5.0
        while time.time() < deadline and price_input is None:
            for search_root in (section, root):
                for by, sel in selectors:
                    try:
                        found = self.visible(search_root.find_elements(by, sel))
                    except Exception:
                        found = []
                    if found:
                        price_input = found[0]
                        break
                if price_input is not None:
                    break
            if price_input is None:
                time.sleep(0.2)
        if price_input is None:
            raise EditEpisodeError("ไม่พบช่องกรอกราคาตอน")
        self.scroll_modal_element_into_view(driver, price_input)
        try:
            price_input.click()
        except Exception:
            pass
        expected = str(int(price_value))
        deadline = time.time() + 5.0
        while time.time() < deadline:
            self.set_react_input_value(driver, price_input, expected)
            time.sleep(0.15)
            actual = (driver.execute_script("return arguments[0].value;", price_input) or "").strip()
            if actual == expected:
                break
        else:
            # fallback: keyboard
            try:
                price_input.send_keys(Keys.CONTROL, "a")
                price_input.send_keys(expected)
            except Exception:
                pass
            actual = (driver.execute_script("return arguments[0].value;", price_input) or "").strip()
            if actual != expected:
                raise EditEpisodeError(f"ตั้งราคาไม่สำเร็จ (ต้องการ {expected} ได้ {actual})")
        self.blur_active_element(driver)

    def get_visible_schedule_popover(self, driver):
        try:
            popovers = driver.find_elements(By.CSS_SELECTOR, "[data-radix-popper-content-wrapper], div[id^='radix-'], [role='dialog']")
        except Exception:
            popovers = []
        for popover in reversed(popovers):
            try:
                if popover.is_displayed() and popover.find_elements(By.CSS_SELECTOR, ".rdp-caption_label, [class*='caption_label']"):
                    return popover
            except Exception:
                continue
        return None

    def find_schedule_day_button(self, popover, dt: datetime):
        iso_day = dt.strftime("%Y-%m-%d")
        short_day = f"{dt.month}/{dt.day}/{dt.year}"
        selectors = [
            f"button[data-day='{short_day}']",
            f"button[data-day='{iso_day}']",
            f"td[data-day='{iso_day}'] button",
            f"[data-day='{iso_day}'] button",
            f"[data-day='{iso_day}']",
        ]
        for selector in selectors:
            try:
                for cand in popover.find_elements(By.CSS_SELECTOR, selector):
                    if cand.is_displayed() and not cand.get_attribute("disabled"):
                        return cand
            except Exception:
                continue
        # fallback: day number text, not an outside-month day
        try:
            for cand in popover.find_elements(By.CSS_SELECTOR, "button[name='day'], td button, [role='gridcell'] button, [role='gridcell']"):
                try:
                    if (cand.text or "").strip() != str(dt.day) or not cand.is_displayed():
                        continue
                    cls = (cand.get_attribute("class") or "") + " " + (cand.find_element(By.XPATH, "./ancestor-or-self::td[1]").get_attribute("class") or "")
                    if "outside" in cls or cand.get_attribute("disabled"):
                        continue
                    return cand
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def set_schedule_datetime(self, driver, root, schedule_dt: datetime):
        trigger_selectors = [
            (By.XPATH, ".//label[contains(., 'กำหนดเวลาเผยแพร่')]/following-sibling::button"),
            (By.XPATH, ".//label[contains(., 'เวลาเผยแพร่')]/following::button[1]"),
            (By.XPATH, ".//button[contains(., 'เลือกวันและเวลา')]"),
            (By.XPATH, ".//button[@aria-haspopup='dialog']"),
        ]
        trigger = None
        section = self.find_section_by_text(root, "ตั้งค่าสถานะเผยแพร่")
        for search_root in (section, root):
            for by, sel in trigger_selectors:
                try:
                    found = self.visible(search_root.find_elements(by, sel))
                except Exception:
                    found = []
                if found:
                    trigger = found[0]
                    break
            if trigger is not None:
                break
        if trigger is None:
            raise EditEpisodeError("ไม่พบปุ่มเลือกวัน-เวลาเผยแพร่")

        self.scroll_modal_element_into_view(driver, trigger)
        popover = None
        for attempt in range(3):
            try:
                self.native_click(driver, trigger)
            except Exception:
                self.js_click(driver, trigger)
            deadline = time.time() + 4.0
            while time.time() < deadline:
                popover = self.get_visible_schedule_popover(driver)
                if popover is not None:
                    break
                time.sleep(0.15)
            if popover is not None:
                break
        if popover is None:
            raise EditEpisodeError("เปิดปฏิทินตั้งเวลาไม่สำเร็จ")

        target = (schedule_dt.year, schedule_dt.month)
        for _ in range(36):
            try:
                caption = popover.find_element(By.CSS_SELECTOR, ".rdp-caption_label, [class*='caption_label']").text.strip()
            except Exception:
                caption = ""
            current = parse_calendar_caption(caption)
            if current is None:
                raise EditEpisodeError(f"อ่านเดือนในปฏิทินไม่ได้: '{caption}'")
            if current == target:
                break
            selector = ".rdp-button_next, button[name='next-month'], button[aria-label*='next' i]" if current < target else \
                ".rdp-button_previous, button[name='previous-month'], button[aria-label*='previous' i]"
            navs = self.visible(popover.find_elements(By.CSS_SELECTOR, selector))
            if not navs:
                raise EditEpisodeError("ไม่พบปุ่มเลื่อนเดือนในปฏิทิน")
            self.js_click(driver, navs[0])
            time.sleep(0.2)
            popover = self.get_visible_schedule_popover(driver) or popover
        else:
            raise EditEpisodeError("เลื่อนปฏิทินไปยังเดือนที่ต้องการไม่สำเร็จ")

        day_button = self.find_schedule_day_button(popover, schedule_dt)
        if day_button is None:
            raise EditEpisodeError(f"ไม่พบวันที่ {schedule_dt:%Y-%m-%d} ในปฏิทิน (อาจเป็นวันในอดีตที่ถูกปิดไว้)")
        try:
            day_button.click()
        except Exception:
            self.js_click(driver, day_button)
        time.sleep(0.25)

        popover = self.get_visible_schedule_popover(driver) or popover
        inputs = self.visible(popover.find_elements(By.CSS_SELECTOR, "input[type='number']"))
        if len(inputs) < 2:
            inputs = self.visible(popover.find_elements(By.CSS_SELECTOR, "input"))
        if len(inputs) < 2:
            raise EditEpisodeError("ไม่พบช่องกรอกชั่วโมง/นาทีในปฏิทิน")
        for box, expected in ((inputs[0], f"{schedule_dt.hour:02d}"), (inputs[1], f"{schedule_dt.minute:02d}")):
            try:
                box.click()
            except Exception:
                pass
            deadline = time.time() + 3.0
            ok = False
            while time.time() < deadline:
                self.set_react_input_value(driver, box, expected)
                time.sleep(0.1)
                actual = (driver.execute_script("return arguments[0].value;", box) or "").strip()
                if actual.zfill(2) == expected or (actual.isdigit() and int(actual) == int(expected)):
                    ok = True
                    break
            if not ok:
                raise EditEpisodeError(f"กรอกเวลาไม่สำเร็จ (ต้องการ {expected})")
        self.blur_active_element(driver)
        # ปิดเฉพาะ popover (Escape จะปิด layer บนสุดเท่านั้น)
        for _ in range(3):
            if self.get_visible_schedule_popover(driver) is None:
                break
            try:
                driver.execute_script(
                    "document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));"
                )
            except Exception:
                pass
            time.sleep(0.3)
        if self.get_visible_schedule_popover(driver) is not None:
            self.press_escape(driver)
            time.sleep(0.3)
        try:
            self.debug(f"ปุ่มวันเวลาแสดง: {(trigger.text or '').strip()}")
        except Exception:
            pass

    def set_publish_mode(self, driver, root, publish_mode: str, schedule_dt: Optional[datetime]):
        if publish_mode == "keep":
            return
        section = self.find_section_by_text(root, "ตั้งค่าสถานะเผยแพร่")
        self.scroll_modal_element_into_view(driver, section)
        target = "scheduled" if publish_mode == "scheduled" else "published"
        self.select_radio_value(
            driver, section, target, "สถานะเผยแพร่",
            ["ตั้งเวลา"] if target == "scheduled" else ["เผยแพร่ทันที"],
        )
        if target == "scheduled":
            if schedule_dt is None:
                raise EditEpisodeError("ไม่มีวัน-เวลาสำหรับตั้งเวลาเผยแพร่")
            time.sleep(0.2)
            self.set_schedule_datetime(driver, root, schedule_dt)

    def find_save_button(self, driver, root):
        priorities = ["บันทึก", "อัปเดต", "อัพเดต", "ยืนยัน", "สร้างตอน", "Save"]
        try:
            buttons = self.visible(root.find_elements(By.XPATH, ".//button"))
        except Exception:
            buttons = []
        for word in priorities:
            for btn in reversed(buttons):
                try:
                    text = ((btn.text or "") + " " + (btn.get_attribute("aria-label") or "")).strip()
                    if word in text and "ยกเลิก" not in text and btn.is_enabled():
                        return btn
                except Exception:
                    continue
        for btn in reversed(buttons):
            try:
                if (btn.get_attribute("type") or "").lower() == "submit" and btn.is_enabled():
                    return btn
            except Exception:
                continue
        return None

    def close_edit_form(self, driver):
        for _ in range(3):
            root = self.find_edit_root(driver)
            if root is None:
                return
            try:
                cancel = None
                for btn in self.visible(root.find_elements(By.XPATH, ".//button")):
                    t = (btn.text or "") + " " + (btn.get_attribute("aria-label") or "")
                    if "ยกเลิก" in t or "ปิด" in t or "Close" in t:
                        cancel = btn
                        break
                if cancel is not None:
                    self.js_click(driver, cancel)
                else:
                    self.press_escape(driver)
            except Exception:
                self.press_escape(driver)
            time.sleep(0.5)
        # alert "ยืนยันการปิด/ละทิ้ง"
        try:
            for dlg in self.visible(driver.find_elements(By.CSS_SELECTOR, "[role='alertdialog']")):
                for btn in self.visible(dlg.find_elements(By.XPATH, ".//button")):
                    if any(w in (btn.text or "") for w in ("ละทิ้ง", "ปิด", "ยืนยัน", "ตกลง")):
                        self.js_click(driver, btn)
                        break
        except Exception:
            pass

    def click_confirm_if_present(self, driver) -> bool:
        try:
            for dlg in self.visible(driver.find_elements(By.CSS_SELECTOR, "[role='alertdialog']")):
                for btn in self.visible(dlg.find_elements(By.XPATH, ".//button")):
                    if any(w in (btn.text or "") for w in ("ยืนยัน", "ตกลง", "บันทึก")):
                        self.js_click(driver, btn)
                        return True
        except Exception:
            pass
        return False

    def dump_debug(self, driver, label: str):
        """บันทึกภาพหน้าจอ + HTML ของหน้าเว็บตอนที่เกิดปัญหา ไว้ใน logs/debug (สูงสุด 3 ชุดต่อเรื่อง)"""
        messages = ""
        try:
            messages = driver.execute_script(JS_PAGE_MESSAGES) or ""
        except Exception:
            pass
        if messages:
            self.log(f"  ข้อความบนหน้าเว็บ: {messages}", "warn")
        if self._debug_dumps >= 3:
            return
        self._debug_dumps += 1
        try:
            folder = LOG_DIR / "debug"
            folder.mkdir(parents=True, exist_ok=True)
            safe_tag = re.sub(r"[^0-9A-Za-zก-๙_-]+", "_", self.debug_tag or "job")[:30]
            base = folder / f"{datetime.now():%Y%m%d_%H%M%S}_{safe_tag}_{label}"
            driver.save_screenshot(str(base) + ".png")
            with open(str(base) + ".html", "w", encoding="utf-8") as f:
                f.write(f"<!-- url: {driver.current_url} -->\n")
                f.write(driver.page_source or "")
            self.log(f"  บันทึกภาพหน้าจอไว้ที่ logs/debug/{base.name}.png", "dim")
        except Exception as error:
            self.debug(f"บันทึก debug ไม่สำเร็จ: {error}")

    def open_edit_for(self, driver, order: int) -> str:
        """คลิกปุ่มแก้ไขของตอนตามลำดับ คืนค่า 'dialog' หรือ 'page'"""
        button = None
        for _ in range(3):
            try:
                button = driver.execute_script(JS_FIND_EDIT_BUTTON, int(order))
            except Exception:
                button = None
            if button is not None:
                break
            time.sleep(0.4)
        if button is None:
            raise EditEpisodeError(f"ไม่พบปุ่ม 'แก้ไข' ของตอนลำดับ {order}")
        url_before = driver.current_url
        handles_before = set(driver.window_handles)
        for attempt in range(3):
            try:
                if attempt == 0:
                    self.native_click(driver, button)
                elif attempt == 1:
                    self.js_click(driver, button)
                else:
                    driver.execute_script(
                        """
                        const el = arguments[0];
                        el.scrollIntoView({block: 'center'});
                        for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                          el.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
                        }
                        """,
                        button,
                    )
            except StaleElementReferenceException:
                button = driver.execute_script(JS_FIND_EDIT_BUTTON, int(order))
                if button is None:
                    raise EditEpisodeError(f"ปุ่มแก้ไขของตอน {order} หายไปหลังรีเฟรชตาราง")
                continue
            except Exception:
                pass
            # บางครั้งปุ่มแก้ไขเปิดเป็นแท็บใหม่ → ใช้หน้านั้นแก้แทน
            new_handles = [h for h in driver.window_handles if h not in handles_before]
            if new_handles:
                driver.switch_to.window(new_handles[-1])
                self.log("  ปุ่มแก้ไขเปิดเป็นแท็บใหม่ — แก้ในแท็บนั้น", "dim")
                return "tab"
            deadline = time.time() + (12 if attempt == 0 else 6)
            while time.time() < deadline:
                self.check_stop()
                root = self.find_edit_root(driver)
                if root is not None:
                    time.sleep(0.4)  # ให้ฟอร์มเติมค่าเดิมเสร็จ
                    return "dialog"
                if driver.current_url != url_before and "tab=episode" not in driver.current_url:
                    try:
                        WebDriverWait(driver, 15).until(
                            lambda d: "กำหนดราคา" in (d.execute_script("return document.body.innerText") or "")
                            or len(d.find_elements(By.NAME, "chapterTitle")) > 0
                        )
                    except Exception:
                        pass
                    time.sleep(0.5)
                    return "page"
                time.sleep(0.2)
            try:
                button = driver.execute_script(JS_FIND_EDIT_BUTTON, int(order)) or button
            except Exception:
                pass
        self.dump_debug(driver, f"edit{order}")
        raise EditEpisodeError(f"กดแก้ไขตอน {order} แล้วไม่พบฟอร์มแก้ไข")

    def save_edit(self, driver, mode: str, root, list_url: str):
        save_btn = self.find_save_button(driver, root if mode == "dialog" else driver)
        if save_btn is None:
            raise EditEpisodeError("ไม่พบปุ่ม 'บันทึก'")
        self.blur_active_element(driver)
        self.scroll_modal_element_into_view(driver, save_btn)
        url_before = driver.current_url
        try:
            self.native_click(driver, save_btn)
        except Exception:
            self.js_click(driver, save_btn)
        deadline = time.time() + 20
        confirmed = False
        while time.time() < deadline:
            self.check_stop()
            time.sleep(0.25)
            if not confirmed and self.click_confirm_if_present(driver):
                confirmed = True
                continue
            if mode == "dialog":
                if self.find_edit_root(driver) is None:
                    return
            else:
                if driver.current_url != url_before:
                    return
        current_root = self.find_edit_root(driver) if mode == "dialog" else None
        errors = ""
        try:
            errors = driver.execute_script(JS_DIALOG_ERRORS, current_root) or ""
        except Exception:
            pass
        if mode == "page":
            # บางระบบบันทึกโดยไม่เปลี่ยนหน้า: กลับไปหน้ารายการเอง
            if not errors:
                return
        raise EditEpisodeError("บันทึกไม่สำเร็จ" + (f": {errors}" if errors else " (ฟอร์มยังไม่ปิดภายใน 20 วินาที)"))

    def edit_episode(self, driver, item: PlanItem, publish_mode: str, list_url: str, original_status: str = STATUS_DRAFT) -> bool:
        """แก้ไขตอนเดียว คืนค่า True ถ้ายืนยันได้ว่าสถานะเปลี่ยนแล้ว"""
        main_handle = driver.current_window_handle
        mode = self.open_edit_for(driver, item.order)
        if mode == "tab":
            try:
                WebDriverWait(driver, 20).until(
                    lambda d: "กำหนดราคา" in (d.execute_script("return document.body ? document.body.innerText : ''") or "")
                    or self.find_edit_root(d) is not None
                )
            except Exception:
                pass
            time.sleep(0.5)
        root = self.find_edit_root(driver)
        if root is None:
            root = driver
        save_mode = "dialog" if (mode == "dialog" or (mode == "tab" and root is not driver)) else "page"

        def back_to_list():
            if mode == "tab":
                try:
                    driver.close()
                except Exception:
                    pass
                driver.switch_to.window(main_handle)
            self.go_first_page_via_reload(driver, list_url)

        try:
            self.set_price(driver, root, item.price_mode, item.price_value)
            self.set_publish_mode(driver, root, publish_mode, item.publish_dt)
            self.save_edit(driver, save_mode, root, list_url)
        except (StopRequested, NotLoggedInError):
            raise
        except Exception:
            self.dump_debug(driver, f"save{item.order}")
            if mode == "dialog":
                self.close_edit_form(driver)
            else:
                try:
                    back_to_list()
                except Exception:
                    pass
            raise
        if mode in ("page", "tab"):
            back_to_list()
            return original_status != STATUS_DRAFT
        if original_status != STATUS_DRAFT:
            return True  # ตอนที่ตั้งเวลาอยู่แล้ว สถานะไม่เปลี่ยน — ฟอร์มปิดแล้วถือว่าบันทึกสำเร็จ
        # verify row status
        deadline = time.time() + 6
        while time.time() < deadline:
            rows = {int(r["order"]): r for r in self.read_rows(driver)}
            row = rows.get(int(item.order))
            if row is None and self.use_draft_filter:
                return True  # ถูกกรองออกเพราะไม่ใช่ฉบับร่างแล้ว
            if row is not None and row.get("status") and row.get("status") != STATUS_DRAFT:
                return True
            time.sleep(0.4)
        return False

    def recover(self, driver, list_url: str):
        try:
            self.close_edit_form(driver)
        except Exception:
            pass
        try:
            self.go_first_page_via_reload(driver, list_url)
        except StopRequested:
            raise
        except NotLoggedInError:
            raise
        except Exception as error:
            self.log(f"กู้คืนหน้าไม่สำเร็จ: {error}", "warn")

    # ------------------------------------------------------------- main feature
    def make_plan_item(self, job: NovelJob, row: Dict[str, Any], publish_dt: Optional[datetime]) -> PlanItem:
        order = int(row["order"])
        number = extract_episode_number_from_text(row.get("title", "")) or order
        price_mode, price_value = resolve_price_for_episode(job, number)
        return PlanItem(order=order, title=row.get("title", ""), episode_number=number,
                        publish_dt=publish_dt, price_mode=price_mode, price_value=price_value)

    def batch_edit_drafts(
        self,
        job: NovelJob,
        profile: Optional[BrowserProfile] = None,
        driver=None,
        chrome_path: str = "",
        headless: bool = False,
        persistent_profile: bool = False,
        dry_run: bool = False,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        title_cb: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        เปิดหน้าคลังตอน → เรียงตอนแรก→ล่าสุด (+กรองฉบับร่าง) → แก้ฉบับร่างทีละตอนจากเก่าไปใหม่
        (ตั้งราคา + ตั้งเวลาเผยแพร่ต่อเนื่อง) → ไปหน้าถัดไป / โหลดหน้าใหม่ซ้ำ จนไม่เหลือฉบับร่าง
        เวลาเผยแพร่ถูกจองให้ตอนตามลำดับที่พบ (เก่า→ใหม่) และคงเดิมแม้ต้องลองซ้ำ
        """
        own_driver = driver is None
        if own_driver:
            if profile is None:
                raise RuntimeError("ไม่ได้ระบุ browser profile")
            driver = self.create_driver(chrome_path, profile, headless=headless, use_runtime_copy=not persistent_profile)
        summary = {"total": 0, "done": 0, "unverified": 0, "failed": 0, "failures": {}, "remaining": None}
        try:
            list_url = normalize_episode_url(job.working_url)
            if not is_valid_working_url(list_url):
                raise RuntimeError(f"ลิงก์ไม่ถูกต้อง: {job.working_url}")
            self.log(f"เปิดหน้าคลังตอน: {list_url}")
            has_rows = self.open_episode_list(driver, list_url)
            if title_cb:
                title = self.read_novel_title(driver)
                if title:
                    title_cb(title)
            if not has_rows:
                self.log("ไม่พบตอนในเรื่องนี้", "warn")
                return summary
            include_scheduled = job.target_mode == "draft_scheduled"
            target_statuses = {STATUS_DRAFT, STATUS_SCHEDULED} if include_scheduled else {STATUS_DRAFT}
            min_order = max(0, int(job.min_order or 0))
            saved_filter = self.use_draft_filter
            if include_scheduled:
                self.use_draft_filter = False  # ต้องเห็นทั้งฉบับร่างและตั้งเวลา
            self.apply_list_view(driver)

            limit = int(job.max_episodes) if job.max_episodes and job.max_episodes > 0 else None
            draft_total = self.read_draft_total(driver)
            scheduled_total = self.read_draft_total(driver, STATUS_SCHEDULED) if include_scheduled else 0
            target = None
            if draft_total is not None and min_order <= 0 and (not include_scheduled or scheduled_total is not None):
                target = draft_total + (scheduled_total or 0)
            if include_scheduled or min_order:
                self.log(
                    "โหมดแก้: " + TARGET_MODES[job.target_mode]
                    + (f" | เฉพาะลำดับ ≥ {min_order}" if min_order else "")
                )
            if limit is not None:
                target = min(limit, target) if target is not None else limit
            self.log(
                f"ฉบับร่างบนเว็บ: {draft_total if draft_total is not None else '? (อ่านตัวเลขสรุปไม่ได้)'} ตอน"
                + (f" | จำกัดรอบนี้ {limit} ตอน" if limit else "")
            )

            # จองเวลาเผยแพร่แบบต่อเนื่อง (คำนวณเผื่อไว้ แล้วขยายเมื่อไม่พอ)
            slots: List[datetime] = []

            def slot_at(index: int) -> Optional[datetime]:
                if job.publish_mode != "scheduled":
                    return None
                nonlocal slots
                if index >= len(slots):
                    slots = job_schedule_slots(job, max(index + 1, (target or 0) + 50, len(slots) * 2, 200))
                return slots[index]

            if job.publish_mode == "scheduled" and job.continue_after_last and parse_last_scheduled(job.last_scheduled_at):
                self.log(f"ต่อเวลาจากรอบก่อน: เริ่มหลัง {format_thai_dt(parse_last_scheduled(job.last_scheduled_at))}")
            if job.publish_mode == "scheduled" and target:
                first_dt, last_dt = slot_at(0), slot_at(target - 1)
                self.log(f"ตารางเผยแพร่: {format_thai_dt(first_dt)} → {format_thai_dt(last_dt)} ({target} ตอน)")
                if first_dt and first_dt < datetime.now():
                    self.log("⚠ เวลาเผยแพร่ตอนแรกอยู่ในอดีต เว็บอาจไม่ยอมรับ — ตรวจสอบวันที่เริ่ม", "warn")

            if dry_run:
                rows = [r for r in self.read_rows(driver)
                        if r.get("status") in target_statuses and int(r["order"]) >= min_order]
                rows.sort(key=lambda r: int(r["order"]))
                if limit:
                    rows = rows[:limit]
                for i, row in enumerate(rows[:20]):
                    p = self.make_plan_item(job, row, slot_at(i))
                    price_text = "คงเดิม" if p.price_mode is None else ("ฟรี" if p.price_mode == "free" else f"{p.price_value} เหรียญ")
                    self.log(f"  [DRY] #{p.order:<4} {p.title[:40]:<40} | {price_text:<10} | {format_thai_dt(p.publish_dt)}", "dim")
                self.log(f"Dry run: แสดงตัวอย่าง {min(20, len(rows))} ตอนแรก (ทั้งหมดประมาณ {target if target is not None else '?'} ตอน) — ไม่ได้บันทึกอะไรบนเว็บ", "ok")
                summary["total"] = target or len(rows)
                return summary

            assigned: Dict[int, PlanItem] = {}
            status_by_order: Dict[int, str] = {}
            attempts: Dict[int, int] = {}
            consecutive_failures = 0
            started = time.perf_counter()
            processed_count = 0

            def finished_count():
                return sum(1 for st in status_by_order.values() if st in ("ok", "ok?"))

            def report():
                if progress_cb:
                    total = max(target or 0, len(assigned), finished_count())
                    progress_cb(finished_count(), total)

            report()
            round_no = 0
            while round_no < 300:
                self.check_stop()
                round_no += 1
                if round_no > 1:
                    if not self.go_first_page_via_reload(driver, list_url):
                        break
                processed_in_round = 0
                tried_this_round = set()
                page_moves = 0
                while True:
                    self.check_stop()
                    rows = self.read_rows(driver)
                    for r in rows:
                        o = int(r["order"])
                        if status_by_order.get(o) == "ok?" and r.get("status") and r.get("status") != STATUS_DRAFT:
                            status_by_order[o] = "ok"
                    limit_reached = limit is not None and len(assigned) >= limit
                    pending = [
                        r for r in rows
                        if r.get("status") in target_statuses
                        and int(r["order"]) >= min_order
                        and int(r["order"]) not in tried_this_round
                        and status_by_order.get(int(r["order"])) != "ok"
                        and attempts.get(int(r["order"]), 0) < 2
                        and (not limit_reached or int(r["order"]) in assigned)
                    ]
                    if not pending:
                        if limit_reached and all(status_by_order.get(o) in ("ok", "ok?") for o in assigned):
                            break
                        page_moves += 1
                        if page_moves > 5000 or not self.go_next_page(driver):
                            break
                        continue
                    pending.sort(key=lambda r: int(r["order"]))
                    row = pending[0]
                    order = int(row["order"])
                    tried_this_round.add(order)
                    item = assigned.get(order)
                    if item is None:
                        item = self.make_plan_item(job, row, slot_at(len(assigned)))
                        assigned[order] = item
                    attempts[order] = attempts.get(order, 0) + 1
                    price_text = "คงราคาเดิม" if item.price_mode is None else ("ฟรี" if item.price_mode == "free" else f"{item.price_value} เหรียญ")
                    when_text = format_thai_dt(item.publish_dt) if job.publish_mode == "scheduled" else PUBLISH_MODES[job.publish_mode]
                    self.log(f"✎ #{order} {item.title[:50]} → {price_text} | {when_text}" + (" (ลองซ้ำ)" if attempts[order] > 1 else ""))
                    t0 = time.perf_counter()
                    try:
                        try:
                            verified = self.edit_episode(driver, item, job.publish_mode, list_url, row.get("status") or STATUS_DRAFT)
                        except (StopRequested, NotLoggedInError):
                            raise
                        except Exception as first_error:
                            # เว็บรีเฟรชตารางระหว่างเปิดฟอร์ม (stale) หรือฟอร์มโหลดช้า → ลองใหม่ทันทีอีก 1 ครั้ง
                            self.log(f"  ↻ ตอน #{order} สะดุด ({short_error(first_error)}) — ลองใหม่อีกครั้ง", "warn")
                            self.recover(driver, list_url)
                            fresh = {int(r["order"]): r for r in self.read_rows(driver)}
                            current = fresh.get(order)
                            if current is None and self.use_draft_filter and (row.get("status") or STATUS_DRAFT) == STATUS_DRAFT:
                                verified = True  # ไม่อยู่ในรายการฉบับร่างแล้ว = ครั้งแรกบันทึกสำเร็จจริง
                                self.log(f"  ✓ ตรวจแล้ว: ตอน #{order} ถูกบันทึกไปแล้วตั้งแต่ครั้งแรก", "dim")
                            elif current is not None and current.get("status") not in target_statuses:
                                verified = True
                            else:
                                if current is None:
                                    raise first_error
                                verified = self.edit_episode(driver, item, job.publish_mode, list_url, current.get("status") or STATUS_DRAFT)
                        status_by_order[order] = "ok" if verified else "ok?"
                        if item.publish_dt and (self.last_saved_dt is None or item.publish_dt > self.last_saved_dt):
                            self.last_saved_dt = item.publish_dt
                        summary["failures"].pop(order, None)
                        consecutive_failures = 0
                        processed_count += 1
                        processed_in_round += 1
                        done_count = finished_count()
                        total_now = max(target or 0, len(assigned))
                        avg = (time.perf_counter() - started) / max(1, processed_count)
                        eta = avg * max(0, total_now - done_count)
                        self.log(
                            f"  ✓ บันทึกแล้ว ({time.perf_counter() - t0:.1f}s)"
                            + ("" if verified else " — ยังไม่เห็นสถานะเปลี่ยน จะตรวจซ้ำรอบถัดไป")
                            + f" | {done_count}/{total_now} | เหลือ ~{format_duration(eta)}",
                            "ok" if verified else "warn",
                        )
                    except (StopRequested, NotLoggedInError):
                        raise
                    except Exception as error:
                        consecutive_failures += 1
                        status_by_order[order] = "fail"
                        summary["failures"][order] = str(error)
                        self.log(f"  ✗ ตอน #{order} ไม่สำเร็จ: {short_error(error)}", "err")
                        self.recover(driver, list_url)
                        if consecutive_failures >= 5:
                            raise RuntimeError("ล้มเหลวติดกัน 5 ตอน — หยุดเรื่องนี้เพื่อความปลอดภัย (ตรวจสอบหน้าเว็บ/การล็อกอิน)")
                    report()
                if processed_in_round == 0:
                    break
                if limit is not None and len(assigned) >= limit and all(
                    status_by_order.get(o) == "ok" or attempts.get(o, 0) >= 2 for o in assigned
                ):
                    break
                self.debug(f"จบรอบที่ {round_no} (แก้ {processed_in_round} ตอน) — โหลดหน้าใหม่เพื่อหาฉบับร่างที่เหลือ")

            # ตรวจยอดคงเหลือ
            remaining = None
            try:
                if self.go_first_page_via_reload(driver, list_url):
                    remaining = self.read_draft_total(driver)
                    rows = self.read_rows(driver)
                    for r in rows:
                        o = int(r["order"])
                        if status_by_order.get(o) == "ok?" and r.get("status") and r.get("status") != STATUS_DRAFT:
                            status_by_order[o] = "ok"
            except (StopRequested, NotLoggedInError):
                raise
            except Exception:
                pass
            summary["remaining"] = remaining
            if remaining == 0 and not include_scheduled and min_order <= 0 and limit is None:
                # ไม่เหลือฉบับร่างบนเว็บแล้ว = ตอนที่เคยแจ้งพลาดถูกบันทึกสำเร็จจริง (เช่น error เกิดหลังกดบันทึก)
                fixed = [o for o, st in status_by_order.items() if st in ("fail", "ok?")]
                for o in fixed:
                    status_by_order[o] = "ok"
                    summary["failures"].pop(o, None)
                if fixed:
                    self.log(f"ตรวจซ้ำแล้ว: ตอน {', '.join('#' + str(o) for o in sorted(fixed))} ถูกบันทึกเรียบร้อย (ไม่เหลือฉบับร่างบนเว็บ)", "ok")
            saved_dts = [assigned[o].publish_dt for o, st in status_by_order.items()
                         if st in ("ok", "ok?") and o in assigned and assigned[o].publish_dt]
            if saved_dts:
                summary["last_scheduled_at"] = max(saved_dts).strftime("%Y-%m-%d %H:%M")

            ok = sum(1 for st in status_by_order.values() if st == "ok")
            unverified = sum(1 for st in status_by_order.values() if st == "ok?")
            failed = sum(1 for st in status_by_order.values() if st == "fail")
            expected_remaining = 0
            if draft_total is not None and limit is not None:
                expected_remaining = max(0, draft_total - limit)
            leftover = (remaining - expected_remaining - failed) if (remaining is not None and not include_scheduled and min_order <= 0) else 0
            summary.update({
                "total": len(assigned),
                "done": ok + unverified,
                "unverified": unverified,
                "failed": failed + max(0, leftover),
            })
            self.log(
                f"สรุป: สำเร็จ {ok} | บันทึกแล้วแต่ยังไม่ยืนยัน {unverified} | ล้มเหลว {failed}"
                + (f" | ฉบับร่างคงเหลือบนเว็บ {remaining}" if remaining is not None else "")
                + f" | ใช้เวลา {format_duration(time.perf_counter() - started)}",
                "ok" if failed == 0 and leftover <= 0 else "warn",
            )
            if leftover > 0:
                self.log(
                    f"⚠ ยังเหลือฉบับร่างที่ไม่ได้แตะ {leftover} ตอน — น่าจะเปลี่ยนหน้าตารางไม่สำเร็จ "
                    "(ดูบรรทัด [pagination-debug] ในไฟล์ log แล้วส่งมาให้ตรวจได้) — กดเริ่มใหม่อีกครั้งจะทำต่อจากตอนที่เหลือ",
                    "warn",
                )
            return summary
        finally:
            if "saved_filter" in locals():
                self.use_draft_filter = saved_filter
            if own_driver:
                self.cleanup_driver(driver)


# ---------------------------------------------------------------------------
# Config persistence (config.json v2 + migration from v1)
# ---------------------------------------------------------------------------
DEFAULT_BROWSER_CONFIG = {
    "mode": "automation",  # automation | installed | custom | guest
    "profile_label": "",
    "custom_profile_path": "",
    "chrome_path": "",
    "headless": False,
    "window_mode": "show",  # show | offscreen | headless
}
DEFAULT_RUN_CONFIG = {
    "draft_filter": True,
    "dry_run": False,
    "scope": "checked",  # checked | current
    "max_parallel": 3,
}


def migrate_v1_config(data: Dict[str, Any]) -> Dict[str, Any]:
    jobs: List[Dict[str, Any]] = []
    seen_urls = set()
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    price_map = {"paid": "paid_all", "free": "free_all", "auto_free": "auto_free"}

    def convert(task: Dict[str, Any], fallback_url: str = "") -> Optional[Dict[str, Any]]:
        url = (task.get("working_url_override") or fallback_url or "").strip()
        if not is_valid_working_url(url):
            return None
        norm = normalize_episode_url(url)
        if norm in seen_urls:
            return None
        seen_urls.add(norm)
        sched = task.get("schedule") or {}
        minutes = int(sched.get("interval_minutes") or 10)
        unit = sched.get("interval_unit") or "minutes"
        if unit == "hours" and minutes % 60 == 0:
            interval_value, interval_unit = max(1, minutes // 60), "hours"
        else:
            interval_value, interval_unit = minutes, "minutes"
        details = task.get("auto_free_details") or {}
        job = NovelJob(
            title=(task.get("title_keyword") or "").strip(),
            working_url=norm,
            enabled=True,
            price_mode=price_map.get(task.get("price_mode") or "", "auto_free"),
            price_value=int(task.get("price_value") or DEFAULT_PRICE),
            free_rule=details.get("rule") if details.get("rule") in FREE_RULES else FREE_RULES[0],
            free_custom=details.get("custom_numbers") or "",
            publish_mode="scheduled",
            start_date=tomorrow,
            start_time=sched.get("start_time") or "12:00",
            per_day_enabled=bool(sched.get("limit_per_day_enabled", True)),
            chapters_per_day=int(sched.get("chapters_per_day") or 3),
            interval_value=interval_value,
            interval_unit=interval_unit,
            skip_enabled=bool(sched.get("skip_enabled", False)),
            skip_start=sched.get("skip_start") or "00:00",
            skip_end=sched.get("skip_end") or "06:00",
        )
        return job.to_dict()

    for task in data.get("tasks") or []:
        converted = convert(task)
        if converted:
            jobs.append(converted)
    if data.get("work_url"):
        converted = convert({
            "working_url_override": data.get("work_url"),
            "price_mode": data.get("price_mode"),
            "price_value": data.get("price_value"),
            "auto_free_details": {"rule": data.get("free_rule"), "custom_numbers": data.get("custom_free_input")},
            "schedule": {
                "start_time": data.get("schedule_time"),
                "chapters_per_day": data.get("chapters_per_day"),
                "limit_per_day_enabled": data.get("limit_per_day", True),
                "interval_minutes": (data.get("interval_value") or 10) * (60 if data.get("interval_unit") == "hours" else 1),
                "interval_unit": data.get("interval_unit"),
                "skip_enabled": data.get("time_filter_enabled", False),
                "skip_start": data.get("skip_start"),
                "skip_end": data.get("skip_end"),
            },
        })
        if converted:
            jobs.append(converted)

    browser = dict(DEFAULT_BROWSER_CONFIG)
    browser.update({
        "mode": data.get("browser_mode") if data.get("browser_mode") in ("automation", "installed", "custom", "guest") else "automation",
        "profile_label": data.get("selected_profile_label") or "",
        "custom_profile_path": data.get("custom_profile_path") or "",
        "chrome_path": data.get("chrome_path") or "",
        "headless": bool(data.get("headless", False)),
        "window_mode": "offscreen" if data.get("headless") else "show",
    })
    return {"version": CONFIG_VERSION, "jobs": jobs, "browser": browser, "run": dict(DEFAULT_RUN_CONFIG), "ui": {}}


def load_config() -> Dict[str, Any]:
    data = read_json(CONFIG_FILE, {})
    if not isinstance(data, dict):
        data = {}
    if data and data.get("version") != CONFIG_VERSION:
        try:
            if CONFIG_FILE.exists() and not CONFIG_V1_BACKUP.exists():
                shutil.copy2(CONFIG_FILE, CONFIG_V1_BACKUP)
        except Exception:
            pass
        data = migrate_v1_config(data)
    data.setdefault("version", CONFIG_VERSION)
    data.setdefault("jobs", [])
    browser = dict(DEFAULT_BROWSER_CONFIG)
    browser.update(data.get("browser") or {})
    data["browser"] = browser
    run = dict(DEFAULT_RUN_CONFIG)
    run.update(data.get("run") or {})
    data["run"] = run
    data.setdefault("ui", {})
    return data


# ---------------------------------------------------------------------------
# Worker (runs in QThread)
# ---------------------------------------------------------------------------
class BatchWorker(QObject):
    log = pyqtSignal(str, str)              # message, level
    job_state = pyqtSignal(str, str, str)   # job_id, status, message
    job_title = pyqtSignal(str, str)        # job_id, title
    progress = pyqtSignal(str, int, int)    # job_id, done, total
    job_last_dt = pyqtSignal(str, str)      # job_id, "YYYY-MM-DD HH:MM"
    job_result = pyqtSignal(str, bool, str) # job_id, ok, abort_message
    overall = pyqtSignal(int, int)          # current job (1-based), total jobs
    finished = pyqtSignal(bool, str)

    def __init__(self, jobs: List[NovelJob], profile: Optional[BrowserProfile], chrome_path: str, headless: bool,
                 persistent_profile: bool, dry_run: bool, draft_filter: bool, existing_driver=None, tag: str = ""):
        super().__init__()
        self.jobs = jobs
        self.profile = profile
        self.chrome_path = chrome_path
        self.headless = headless
        self.persistent_profile = persistent_profile
        self.dry_run = dry_run
        self.draft_filter = draft_filter
        self.existing_driver = existing_driver
        self.tag = tag
        self._stop = False

    def stop(self):
        self._stop = True

    def _emit_last_dt(self, bot, job):
        if bot.last_saved_dt is not None and not self.dry_run:
            self.job_last_dt.emit(job.id, bot.last_saved_dt.strftime("%Y-%m-%d %H:%M"))
            bot.last_saved_dt = None

    def _log(self, message, level="info"):
        text = str(message)
        if self.tag:
            text = "\n".join(f"[{self.tag}] {line}" for line in text.splitlines() or [""])
        self.log.emit(text, level)

    def run(self):
        bot = MyNovelBot(log_func=self._log, should_stop=lambda: self._stop)
        bot.use_draft_filter = self.draft_filter
        bot.debug_tag = self.tag or (self.jobs[0].display_name() if self.jobs else "")
        driver = self.existing_driver
        own_driver = driver is None
        ok_jobs, failed_jobs = 0, 0
        aborted_message = ""
        try:
            for index, job in enumerate(self.jobs):
                if self._stop:
                    self.job_state.emit(job.id, "stopped", "หยุดก่อนเริ่ม")
                    continue
                self.overall.emit(index + 1, len(self.jobs))
                self._log("─" * 70, "dim")
                self._log(f"▶ เรื่อง {index + 1}/{len(self.jobs)}: {job.display_name()}", "head")
                self.job_state.emit(job.id, "running", "กำลังทำงาน...")
                bot.last_saved_dt = None
                try:
                    if driver is None or not bot.is_alive(driver):
                        if not own_driver:
                            raise RuntimeError("หน้าต่าง Chrome ที่ใช้ล็อกอินถูกปิดไปแล้ว")
                        self._log("เปิด Chrome...")
                        driver = bot.create_driver(
                            self.chrome_path, self.profile, headless=self.headless,
                            use_runtime_copy=not self.persistent_profile,
                        )
                    summary = bot.batch_edit_drafts(
                        job,
                        driver=driver,
                        dry_run=self.dry_run,
                        progress_cb=lambda done, total, jid=job.id: self.progress.emit(jid, done, total),
                        title_cb=lambda title, jid=job.id: self.job_title.emit(jid, title),
                    )
                    self._emit_last_dt(bot, job)
                    total = summary.get("total", 0)
                    if self.dry_run:
                        self.job_state.emit(job.id, "ready", f"Dry run: พบ {total} ตอนที่จะแก้")
                        ok_jobs += 1
                        self.job_result.emit(job.id, True, "")
                    elif summary.get("failed", 0):
                        failed_jobs += 1
                        self.job_state.emit(job.id, "failed", f"สำเร็จ {summary.get('done', 0)}/{total} · ล้มเหลว {summary.get('failed')}")
                        self.job_result.emit(job.id, False, "")
                    else:
                        ok_jobs += 1
                        msg = f"สำเร็จ {summary.get('done', 0)}/{total} ตอน" if total else "ไม่มีฉบับร่าง"
                        self.job_state.emit(job.id, "done", msg)
                        self.job_result.emit(job.id, True, "")
                except StopRequested:
                    self._emit_last_dt(bot, job)
                    self.job_state.emit(job.id, "stopped", "ผู้ใช้สั่งหยุด")
                    self._log("■ หยุดตามคำสั่ง", "warn")
                    aborted_message = "หยุดการทำงานแล้ว"
                    self.job_result.emit(job.id, False, "")
                    for rest in self.jobs[index + 1:]:
                        self.job_state.emit(rest.id, "stopped", "ยังไม่ได้เริ่ม")
                    break
                except NotLoggedInError as error:
                    failed_jobs += 1
                    self.job_state.emit(job.id, "failed", "ยังไม่ได้ล็อกอิน")
                    self._log(str(error), "err")
                    aborted_message = str(error)
                    self.job_result.emit(job.id, False, aborted_message)
                    for rest in self.jobs[index + 1:]:
                        self.job_state.emit(rest.id, "ready", "ยังไม่ได้เริ่ม (ต้องล็อกอินก่อน)")
                    break
                except Exception as error:
                    failed_jobs += 1
                    message = short_error(error)
                    self.job_state.emit(job.id, "failed", message[:160])
                    self._log(f"✗ เรื่องนี้ล้มเหลว: {message}", "err")
                    self.job_result.emit(job.id, False, "")
                    self._emit_last_dt(bot, job)
                    if driver is not None and not bot.is_alive(driver):
                        if own_driver:
                            bot.cleanup_driver(driver)
                        driver = None
        except Exception as error:
            aborted_message = f"{type(error).__name__}: {error}"
            self._log(aborted_message, "err")
        finally:
            if own_driver and driver is not None:
                bot.cleanup_driver(driver)
        if aborted_message:
            self.finished.emit(False, aborted_message)
        else:
            self.finished.emit(failed_jobs == 0, f"เสร็จสิ้น: สำเร็จ {ok_jobs} เรื่อง · ล้มเหลว {failed_jobs} เรื่อง")


# ---------------------------------------------------------------------------
# Auto update (GitHub Releases)
# ---------------------------------------------------------------------------
def version_tuple(text: str) -> tuple:
    nums = [int(x) for x in re.findall(r"\d+", text or "")[:3]]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def is_newer_version(remote: str, local: Optional[str] = None) -> bool:
    return version_tuple(remote) > version_tuple(local or APP_VERSION)


def _http_get(url: str, timeout: float = 20, accept: str = "application/vnd.github+json"):
    import urllib.request
    request = urllib.request.Request(url, headers={
        "Accept": accept,
        "User-Agent": f"{APP_NAME}/{APP_VERSION}",
    })
    return urllib.request.urlopen(request, timeout=timeout)


def notes_newer_than(notes_all: str, local_version: Optional[str] = None) -> str:
    """ตัดเฉพาะหัวข้อใน release_notes.md ที่ใหม่กว่าเวอร์ชันในเครื่อง"""
    parts = re.split(r"(?m)^(?=#{2,3} )", notes_all or "")
    keep = []
    for part in parts:
        match = re.match(r"#{2,3} [^\n]*?v?(\d+\.\d+(?:\.\d+)?)", part)
        if match and is_newer_version(match.group(1), local_version):
            keep.append(part.strip())
    return "\n\n".join(keep)


class UpdateChecker(QObject):
    """อ่าน version.json จาก Release ล่าสุด (สำรอง: GitHub API) — ทำงานใน background thread"""
    done = pyqtSignal(object, str)  # info dict | None, error message

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _from_manifest(self):
        with _http_get(UPDATE_MANIFEST_URL, timeout=15, accept="application/json") as response:
            data = json.loads(response.read().decode("utf-8-sig"))
        version = str(data.get("version") or "").lstrip("vV")
        if not version:
            raise ValueError("version.json ไม่มีเลขเวอร์ชัน")
        notes_all = data.get("notes_all") or ""
        return {
            "version": version,
            "tag": data.get("tag") or f"v{version}",
            "name": data.get("name") or f"{APP_DISPLAY_NAME} v{version}",
            "notes": notes_newer_than(notes_all) or data.get("notes") or "",
            "url": data.get("release_url") or f"{GITHUB_URL}/releases/latest",
            "asset_url": data.get("asset_url") or "",
            "asset_size": int(data.get("size") or 0),
            "sha256": (data.get("sha256") or "").lower(),
            "mandatory": bool(data.get("mandatory")),
            "min_version": data.get("min_version") or "",
            "published_at": data.get("published_at") or "",
        }

    def _from_api(self):
        with _http_get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest") as response:
            data = json.loads(response.read().decode("utf-8"))
        tag = (data.get("tag_name") or "").strip()
        asset = next((a for a in data.get("assets") or [] if (a.get("name") or "") == RELEASE_ASSET_NAME), None) or next((a for a in data.get("assets") or [] if (a.get("name") or "").endswith(RELEASE_ASSET_SUFFIX)), None)
        return {
            "version": tag.lstrip("vV"), "tag": tag, "name": data.get("name") or tag,
            "notes": data.get("body") or "", "url": data.get("html_url") or f"{GITHUB_URL}/releases",
            "asset_url": (asset or {}).get("browser_download_url", ""),
            "asset_size": int((asset or {}).get("size") or 0), "sha256": "", "mandatory": False,
            "min_version": "", "published_at": data.get("published_at") or "",
        }

    def _run(self):
        import urllib.error
        errors = []
        for source in (self._from_manifest, self._from_api):
            try:
                info = source()
                if info.get("min_version") and is_newer_version(info["min_version"]):
                    info["mandatory"] = True  # เวอร์ชันในเครื่องเก่ากว่าขั้นต่ำที่รองรับ
                self.done.emit(info, "")
                return
            except urllib.error.HTTPError as error:
                errors.append("ยังไม่มี Release บน GitHub" if error.code == 404 else f"GitHub ตอบกลับ {error.code}")
            except Exception as error:
                errors.append(f"เชื่อมต่อ GitHub ไม่ได้: {error}")
        self.done.emit(None, errors[0] if errors else "ตรวจหาอัปเดตไม่สำเร็จ")


class UpdateDownloader(QObject):
    """ดาวน์โหลด + แตกไฟล์ zip ของเวอร์ชันใหม่ (background thread)"""
    progress = pyqtSignal(int, int)
    done = pyqtSignal(bool, str, str)  # ok, new_app_dir | error, temp_root

    def __init__(self, url: str, sha256: str = ""):
        super().__init__()
        self.url = url
        self.sha256 = (sha256 or "").lower()
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        import zipfile
        temp_root = ""
        try:
            temp_root = tempfile.mkdtemp(prefix="keawgood_update_")
            zip_path = Path(temp_root) / "update.zip"
            with _http_get(self.url, timeout=60, accept="application/octet-stream") as response, open(zip_path, "wb") as f:
                total = int(response.headers.get("Content-Length") or 0)
                received = 0
                while True:
                    if self._cancel:
                        raise StopRequested("ยกเลิกการอัปเดต")
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    received += len(chunk)
                    self.progress.emit(received, total)
            if self.sha256:
                import hashlib
                digest = hashlib.sha256()
                with open(zip_path, "rb") as f:
                    for block in iter(lambda: f.read(1024 * 1024), b""):
                        digest.update(block)
                if digest.hexdigest().lower() != self.sha256:
                    raise RuntimeError("ไฟล์ที่ดาวน์โหลดไม่สมบูรณ์ (checksum ไม่ตรง) — ลองใหม่อีกครั้ง")
            extract_dir = Path(temp_root) / "new"
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(extract_dir)
            app_dir = None
            for root, _dirs, files in os.walk(extract_dir):
                if EXE_NAME in files:
                    app_dir = root
                    break
            if not app_dir:
                raise RuntimeError(f"ไม่พบ {EXE_NAME} ในไฟล์อัปเดต")
            self.done.emit(True, str(app_dir), temp_root)
        except Exception as error:
            if temp_root:
                shutil.rmtree(temp_root, ignore_errors=True)
            self.done.emit(False, str(error), "")


def launch_updater_and_quit(new_app_dir: str, temp_root: str):
    """เปิด exe ตัวใหม่ (ในโฟลเดอร์ชั่วคราว) ให้รอโปรแกรมนี้ปิด แล้วคัดลอกทับโฟลเดอร์เดิม"""
    import subprocess
    exe = Path(new_app_dir) / EXE_NAME
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [str(exe), "--apply-update", str(new_app_dir), str(APP_DIR), str(os.getpid()), str(temp_root)],
        cwd=str(new_app_dir),
        creationflags=flags,
        close_fds=True,
    )


def _wait_for_pid_exit(pid: int, timeout: float = 120):
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
            if handle:
                kernel32.WaitForSingleObject(handle, int(timeout * 1000))
                kernel32.CloseHandle(handle)
            return
        except Exception:
            pass
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.5)


def _retry(func, attempts: int = 15, delay: float = 1.0):
    last_error = None
    for _ in range(attempts):
        try:
            return func()
        except (PermissionError, OSError) as error:
            last_error = error
            time.sleep(delay)
    raise last_error


def run_apply_update(src: str, dst: str, pid: int, temp_root: str):
    """โหมดพิเศษของ exe ตัวใหม่: คัดลอกไฟล์โปรแกรมทับของเดิม (ไม่แตะข้อมูลผู้ใช้) แล้วเปิดโปรแกรมใหม่"""
    import subprocess
    from PyQt6.QtWidgets import QProgressDialog
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    dialog = QProgressDialog("กำลังอัปเดต Keawgood MyNovel…", None, 0, 0)
    dialog.setWindowTitle("อัปเดตโปรแกรม")
    dialog.setMinimumWidth(380)
    dialog.show()
    app.processEvents()
    src_path, dst_path = Path(src), Path(dst)
    error_text = ""
    try:
        _wait_for_pid_exit(pid)
        time.sleep(1.0)
        app.processEvents()
        internal = dst_path / "_internal"
        if (src_path / "_internal").exists() and internal.exists():
            _retry(lambda: shutil.rmtree(internal))
        for item in src_path.iterdir():
            app.processEvents()
            if item.name in USER_DATA_NAMES:
                continue
            target = dst_path / item.name
            if item.is_dir():
                _retry(lambda i=item, t=target: shutil.copytree(i, t, dirs_exist_ok=True))
            else:
                _retry(lambda i=item, t=target: shutil.copy2(i, t))
    except Exception as error:
        error_text = str(error)
    dialog.close()
    if error_text:
        QMessageBox.critical(
            None, "อัปเดตไม่สำเร็จ",
            f"คัดลอกไฟล์ใหม่ไม่สำเร็จ: {error_text}\n\nดาวน์โหลดเวอร์ชันล่าสุดเองได้ที่\n{GITHUB_URL}/releases",
        )
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0
    try:
        subprocess.Popen([str(dst_path / EXE_NAME), "--cleanup-update", temp_root], cwd=str(dst_path),
                         creationflags=flags, close_fds=True)
    except Exception:
        pass
    sys.exit(0)


def handle_special_args(argv: List[str]) -> bool:
    """คืน True ถ้าเป็นโหมดพิเศษที่จัดการเสร็จแล้ว (ไม่ต้องเปิดหน้าหลัก)"""
    if "--apply-update" in argv:
        i = argv.index("--apply-update")
        src, dst, pid, temp_root = argv[i + 1], argv[i + 2], int(argv[i + 3]), argv[i + 4]
        run_apply_update(src, dst, pid, temp_root)
        return True
    if "--cleanup-update" in argv:
        i = argv.index("--cleanup-update")
        path = argv[i + 1] if i + 1 < len(argv) else ""
        if path and "keawgood_update_" in path:
            def cleanup():
                for _ in range(20):
                    time.sleep(2)
                    shutil.rmtree(path, ignore_errors=True)
                    if not os.path.exists(path):
                        return
            threading.Thread(target=cleanup, daemon=True).start()
    return False


# ---------------------------------------------------------------------------
# UI — VS Code Modern Dark
# ---------------------------------------------------------------------------
C = {
    "bg": "#1e1e1e",
    "sidebar": "#252526",
    "panel": "#181818",
    "titlebar": "#2d2d2d",
    "border": "#2b2b2b",
    "border2": "#3c3c3c",
    "input": "#313131",
    "text": "#cccccc",
    "muted": "#8b8b8b",
    "accent": "#0078d4",
    "accent_hover": "#1a8ae6",
    "select": "#04395e",
    "hover": "#2a2d2e",
    "ok": "#89d185",
    "warn": "#cca700",
    "err": "#f48771",
    "purple": "#c586c0",
}

STYLESHEET = f"""
* {{ font-family: 'Segoe UI', 'Leelawadee UI', 'Tahoma', sans-serif; font-size: 10pt; }}
QMainWindow, QWidget#Root {{ background: {C['bg']}; color: {C['text']}; }}
QWidget {{ color: {C['text']}; }}
QToolTip {{ background: #252526; color: {C['text']}; border: 1px solid #454545; padding: 4px; }}

/* sidebar */
QFrame#Sidebar {{ background: {C['sidebar']}; border-right: 1px solid {C['border']}; }}
QLabel#SidebarHeader {{ color: {C['muted']}; font-size: 8.5pt; font-weight: 600; letter-spacing: 1px; padding: 10px 12px 6px 12px; }}
QListWidget#JobList {{ background: {C['sidebar']}; border: none; outline: none; padding: 2px 0; }}
QListWidget#JobList::item {{ padding: 6px 10px; border: 1px solid transparent; color: {C['text']}; }}
QListWidget#JobList::item:hover {{ background: {C['hover']}; }}
QListWidget#JobList::item:selected {{ background: {C['select']}; border: 1px solid {C['accent']}; color: #ffffff; }}
QLineEdit#Filter {{ margin: 0 10px 6px 10px; }}

/* editor */
QScrollArea#EditorScroll, QWidget#EditorBody {{ background: {C['bg']}; border: none; }}
QLabel#EditorTitle {{ font-size: 16pt; font-weight: 600; color: #e7e7e7; }}
QLabel#EditorSub {{ color: {C['muted']}; }}
QFrame#Card {{ background: #202020; border: 1px solid {C['border2']}; border-radius: 6px; }}
QLabel#CardTitle {{ font-size: 10.5pt; font-weight: 600; color: #e7e7e7; }}
QLabel#CardHint {{ color: {C['muted']}; font-size: 9pt; }}
QLabel#Preview {{ background: {C['panel']}; border: 1px solid {C['border2']}; border-radius: 4px; padding: 8px;
                  font-family: 'Cascadia Mono', 'Consolas', 'Tahoma', monospace; font-size: 9pt; color: #b5cea8; }}
QLabel#Empty {{ color: {C['muted']}; font-size: 12pt; }}

/* tabs-like breadcrumb */
QFrame#EditorTabBar {{ background: {C['titlebar']}; border-bottom: 1px solid {C['border']}; }}
QLabel#EditorTab {{ background: {C['bg']}; color: #ffffff; padding: 8px 14px; border-top: 1px solid {C['accent']}; }}

/* inputs */
QLineEdit, QSpinBox, QDateEdit, QTimeEdit, QDateTimeEdit, QComboBox, QPlainTextEdit#Import {{
    background: {C['input']}; border: 1px solid {C['border2']}; border-radius: 3px; padding: 5px 7px; color: {C['text']};
    selection-background-color: {C['select']};
}}
QLineEdit:focus, QSpinBox:focus, QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus, QComboBox:focus {{ border: 1px solid {C['accent']}; }}
QLineEdit:disabled, QSpinBox:disabled, QDateEdit:disabled, QTimeEdit:disabled, QDateTimeEdit:disabled, QComboBox:disabled {{ color: #6b6b6b; background: #2a2a2a; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: #252526; border: 1px solid #454545; selection-background-color: {C['select']}; color: {C['text']}; }}
QSpinBox::up-button, QSpinBox::down-button, QDateEdit::up-button, QDateEdit::down-button, QTimeEdit::up-button, QTimeEdit::down-button {{ width: 16px; background: transparent; border: none; }}
QCalendarWidget QWidget {{ background: #252526; color: {C['text']}; alternate-background-color: #2a2a2a; }}
QCalendarWidget QToolButton {{ background: transparent; color: {C['text']}; padding: 4px; }}
QCalendarWidget QAbstractItemView:enabled {{ selection-background-color: {C['accent']}; selection-color: white; }}

QCheckBox, QRadioButton {{ spacing: 7px; color: {C['text']}; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px; }}
QCheckBox::indicator {{ border: 1px solid #6b6b6b; border-radius: 3px; background: {C['input']}; }}
QCheckBox::indicator:checked {{ background: {C['accent']}; border: 1px solid {C['accent']}; image: none; }}
QRadioButton::indicator {{ border: 1px solid #6b6b6b; border-radius: 8px; background: {C['input']}; }}
QRadioButton::indicator:checked {{ background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 white, stop:0.35 white, stop:0.45 {C['accent']}, stop:1 {C['accent']}); border: 1px solid {C['accent']}; }}

/* buttons */
QPushButton, QToolButton {{ background: #313131; border: 1px solid {C['border2']}; border-radius: 3px; padding: 6px 12px; color: {C['text']}; }}
QPushButton:hover, QToolButton:hover {{ background: #3a3d41; }}
QPushButton:pressed {{ background: #2a2d2e; }}
QPushButton:disabled {{ color: #6b6b6b; background: #2a2a2a; border-color: #333; }}
QPushButton#Primary {{ background: {C['accent']}; border: 1px solid {C['accent']}; color: white; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {C['accent_hover']}; }}
QPushButton#Primary:disabled {{ background: #264f78; color: #9db7cf; }}
QPushButton#Run {{ background: #16825d; border: 1px solid #16825d; color: white; font-weight: 700; padding: 9px 18px; font-size: 10.5pt; }}
QPushButton#Run:hover {{ background: #1a9a6e; }}
QPushButton#Run:disabled {{ background: #2b4a3f; color: #8fb3a5; border-color: #2b4a3f; }}
QPushButton#Danger {{ background: transparent; border: 1px solid #5a2d2d; color: {C['err']}; }}
QPushButton#Danger:hover {{ background: #3a1f1f; }}
QPushButton#Stop {{ background: #a1260d; border: 1px solid #a1260d; color: white; font-weight: 600; padding: 9px 14px; }}
QPushButton#Stop:hover {{ background: #be2e10; }}
QPushButton#Stop:disabled {{ background: #3a2a27; color: #8a6b66; border-color: #3a2a27; }}
QPushButton#Ghost, QToolButton#Ghost {{ background: transparent; border: 1px solid transparent; padding: 4px 8px; }}
QPushButton#Ghost:hover, QToolButton#Ghost:hover {{ background: {C['hover']}; border: 1px solid {C['border2']}; }}

/* output panel */
QFrame#PanelHeader {{ background: {C['bg']}; border-top: 1px solid {C['border2']}; }}
QLabel#PanelTab {{ color: #e7e7e7; font-size: 8.5pt; font-weight: 600; letter-spacing: 1px; padding: 6px 4px; border-bottom: 1px solid {C['accent']}; }}
QPlainTextEdit#Output {{ background: {C['bg']}; border: none; color: {C['text']};
    font-family: 'Cascadia Mono', 'Consolas', 'Tahoma', monospace; font-size: 9pt; padding: 4px 10px; }}
QProgressBar {{ background: #2a2a2a; border: none; border-radius: 2px; height: 6px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {C['accent']}; border-radius: 2px; }}

/* action bar */
QFrame#ActionBar {{ background: {C['sidebar']}; border-top: 1px solid {C['border']}; }}
QLabel#BarLabel {{ color: {C['muted']}; }}

/* status bar */
QStatusBar {{ background: {C['accent']}; color: white; }}
QStatusBar QLabel {{ color: white; padding: 0 8px; }}
QStatusBar::item {{ border: none; }}

QFrame#UpdateBar {{ background: #094771; border-bottom: 1px solid #0e639c; }}
QFrame#UpdateBar QLabel {{ color: #ffffff; }}
QFrame#UpdateBar QPushButton {{ background: transparent; border: 1px solid #5a9fd6; color: white; padding: 4px 10px; }}
QFrame#UpdateBar QPushButton:hover {{ background: #0e639c; }}
QFrame#UpdateBar QPushButton#Primary {{ background: #ffffff; color: #094771; border: 1px solid white; }}
QPushButton#VersionBtn {{ background: transparent; border: none; color: white; padding: 0 8px; }}
QPushButton#VersionBtn:hover {{ background: rgba(255,255,255,0.15); }}
QTextBrowser {{ background: {C['panel']}; border: 1px solid {C['border2']}; color: {C['text']}; padding: 8px; }}
QSplitter::handle {{ background: {C['border']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: rgba(121,121,121,0.4); min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(100,100,100,0.7); }}
QScrollBar:horizontal {{ background: transparent; height: 12px; }}
QScrollBar::handle:horizontal {{ background: rgba(121,121,121,0.4); min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QMenu {{ background: #252526; border: 1px solid #454545; padding: 4px; }}
QMenu::item {{ padding: 5px 22px; }}
QMenu::item:selected {{ background: {C['select']}; }}
QMessageBox, QDialog {{ background: {C['sidebar']}; }}
"""

LOG_COLORS = {
    "info": C["text"],
    "ok": C["ok"],
    "warn": C["warn"],
    "err": C["err"],
    "dim": "#7a7a7a",
    "head": "#4fc1ff",
}


def dot_icon(color: str, size: int = 12) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return QIcon(pix)


def html_escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def make_card(title: str, hint: str = ""):
    card = QFrame()
    card.setObjectName("Card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 16)
    layout.setSpacing(10)
    title_label = QLabel(title)
    title_label.setObjectName("CardTitle")
    layout.addWidget(title_label)
    if hint:
        hint_label = QLabel(hint)
        hint_label.setObjectName("CardHint")
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)
    return card, layout


class JobItemDelegate(QStyledItemDelegate):
    """วาดรายการเรื่อง 2 บรรทัด: ชื่อเรื่อง + สถานะ (สี)"""
    STATUS_ROLE = Qt.ItemDataRole.UserRole + 1
    SUB_ROLE = Qt.ItemDataRole.UserRole + 2

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        title = opt.text
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget)
        status = index.data(self.STATUS_ROLE) or "ready"
        sub = index.data(self.SUB_ROLE) or ""
        label, color = JOB_STATUS_META.get(status, JOB_STATUS_META["ready"])
        painter.save()
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        fm = opt.fontMetrics
        line_h = fm.height()
        top = text_rect.top() + max(0, (text_rect.height() - line_h * 2 - 2) // 2)
        painter.setPen(QColor("#ffffff" if selected else "#d4d4d4"))
        painter.drawText(text_rect.left(), top, text_rect.width(), line_h,
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                         fm.elidedText(title, Qt.TextElideMode.ElideRight, text_rect.width()))
        small = QFont(opt.font)
        small.setPointSizeF(max(7.0, opt.font.pointSizeF() - 1.0))
        painter.setFont(small)
        sfm = painter.fontMetrics()
        y2 = top + line_h + 2
        painter.setPen(QColor(color))
        painter.drawText(text_rect.left(), y2, text_rect.width(), sfm.height(),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)
        lw = sfm.horizontalAdvance(label + "  ")
        if sub:
            painter.setPen(QColor("#9d9d9d"))
            painter.drawText(text_rect.left() + lw, y2, max(0, text_rect.width() - lw), sfm.height(),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                             sfm.elidedText(sub, Qt.TextElideMode.ElideRight, max(0, text_rect.width() - lw)))
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(46, option.fontMetrics.height() * 2 + 18))


class AddLinkDialog(QDialog):
    def __init__(self, parent=None, url: str = ""):
        super().__init__(parent)
        self.setWindowTitle("วางลิงก์เพิ่มเรื่อง")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        hint = QLabel("ลิงก์หน้าคลังตอน เช่น https://mynovel.co/dashboard/workings/xxxx?tab=episode")
        hint.setObjectName("CardHint")
        layout.addWidget(hint)
        form = QFormLayout()
        self.url_edit = QLineEdit(url)
        self.url_edit.setPlaceholderText("https://mynovel.co/dashboard/workings/...?tab=episode")
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("(ไม่บังคับ) ชื่อเรื่อง — ถ้าเว้นว่าง โปรแกรมจะพยายามอ่านจากหน้าเว็บตอนรัน")
        form.addRow("ลิงก์", self.url_edit)
        form.addRow("ชื่อเรื่อง", self.title_edit)
        layout.addLayout(form)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet(f"color: {C['err']};")
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("เพิ่มเรื่อง")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("Primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("ยกเลิก")
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def validate_and_accept(self):
        if not is_valid_working_url(self.url_edit.text()):
            self.error_label.setText("ลิงก์ไม่ถูกต้อง — ต้องเป็นลิงก์ mynovel.co/dashboard/workings/<id>")
            return
        self.accept()


class ImportLinksDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("นำเข้ารายการลิงก์หลายเรื่อง")
        self.setMinimumSize(680, 420)
        layout = QVBoxLayout(self)
        hint = QLabel(
            "วางลิงก์ทีละบรรทัด (ใส่ชื่อเรื่องต่อท้ายได้ เช่น  <url> | ชื่อเรื่อง)\n"
            "ลิงก์ที่ซ้ำกับรายการเดิมจะถูกข้ามอัตโนมัติ"
        )
        hint.setObjectName("CardHint")
        layout.addWidget(hint)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setObjectName("Import")
        self.text_edit.setPlaceholderText(
            "https://mynovel.co/dashboard/workings/AAAA?tab=episode | เรื่องที่ 1\n"
            "https://mynovel.co/dashboard/workings/BBBB?tab=episode\n"
        )
        layout.addWidget(self.text_edit, 1)
        row = QHBoxLayout()
        load_btn = QPushButton("โหลดจากไฟล์ .txt")
        load_btn.clicked.connect(self.load_file)
        row.addWidget(load_btn)
        row.addStretch(1)
        self.count_label = QLabel("")
        self.count_label.setObjectName("CardHint")
        row.addWidget(self.count_label)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("นำเข้า")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("Primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("ยกเลิก")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.text_edit.textChanged.connect(self.update_count)

    def load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "เลือกไฟล์รายการลิงก์", "", "Text files (*.txt);;All files (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                self.text_edit.setPlainText(f.read())
        except UnicodeDecodeError:
            with open(path, "r", encoding="cp874", errors="replace") as f:
                self.text_edit.setPlainText(f.read())

    def parsed(self) -> List[tuple]:
        result = []
        for line in self.text_edit.toPlainText().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = WORKING_URL_RE.search(line)
            if not match:
                continue
            url = normalize_episode_url(match.group(0))
            rest = (line[: match.start()] + " " + line[match.end():])
            rest = re.sub(r"^\S*\?tab=\S*", "", rest.strip())
            title = rest.strip(" \t|,;-–").strip()
            result.append((url, title))
        return result

    def update_count(self):
        self.count_label.setText(f"พบลิงก์ที่ถูกต้อง {len(self.parsed())} รายการ")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_DISPLAY_NAME} v{APP_VERSION} — Batch Draft Scheduler")
        self.resize(1440, 900)
        self.config = load_config()
        self.jobs: List[NovelJob] = [NovelJob.from_dict(j) for j in self.config.get("jobs", [])]
        self.current_job: Optional[NovelJob] = None
        self._loading = False
        self.runs: Dict[str, tuple] = {}
        self.run_queue: List[NovelJob] = []
        self.run_ctx: Optional[Dict[str, Any]] = None
        self.job_progress: Dict[str, tuple] = {}
        self.login_bot: Optional[MyNovelBot] = None
        self.login_driver = None
        self.login_driver_mode = ""
        self.profile_map: Dict[str, BrowserProfile] = {}
        self.run_job_ids: List[str] = []
        self.log_file_path = None

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(400)
        self.save_timer.timeout.connect(self.save_config)

        self.build_ui()
        self.load_browser_settings()
        self.refresh_job_list()
        self.restore_ui_state()
        if self.jobs:
            row = min(max(0, int(self.config.get("ui", {}).get("selected_index", 0) or 0)), len(self.jobs) - 1)
            self.job_list.setCurrentRow(row)
        else:
            self.show_job(None)
        self.update_counts()
        icon_path = RESOURCE_DIR / "assets" / "icon.ico"
        if not icon_path.exists():
            icon_path = APP_DIR / "assets" / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.update_info: Optional[Dict[str, Any]] = None
        self.update_checker: Optional[UpdateChecker] = None
        self.update_downloader: Optional[UpdateDownloader] = None
        if IS_FROZEN:  # เปิดจากโค้ด (run.bat) ไม่ต้องเด้งแจ้งอัปเดต — กดเลขเวอร์ชันมุมขวาล่างเพื่อเช็กเองได้
            QTimer.singleShot(2500, lambda: self.check_for_updates(silent=True))
        self.append_log("พร้อมใช้งาน — วางลิงก์หน้าคลังตอน ตั้งค่า แล้วกด ⚡ เริ่ม", "dim")
        if CONFIG_V1_BACKUP.exists() and self.config.get("ui", {}).get("migrated_notice") is not True:
            self.append_log(f"ย้ายข้อมูลจาก config เวอร์ชันเก่าแล้ว (สำรองไว้ที่ {CONFIG_V1_BACKUP.name})", "dim")
            self.config.setdefault("ui", {})["migrated_notice"] = True
            self.schedule_save()

    # ================================================================== UI build
    def build_ui(self):
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.v_splitter = QSplitter(Qt.Orientation.Vertical)
        self.v_splitter.setChildrenCollapsible(False)
        self.h_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.h_splitter.setChildrenCollapsible(False)
        self.h_splitter.addWidget(self.build_sidebar())
        self.h_splitter.addWidget(self.build_editor())
        self.h_splitter.setStretchFactor(0, 0)
        self.h_splitter.setStretchFactor(1, 1)
        self.h_splitter.setSizes([340, 1100])
        self.v_splitter.addWidget(self.h_splitter)
        self.v_splitter.addWidget(self.build_output_panel())
        self.v_splitter.setStretchFactor(0, 1)
        self.v_splitter.setStretchFactor(1, 0)
        self.v_splitter.setSizes([640, 220])
        root_layout.addWidget(self.build_update_bar())
        root_layout.addWidget(self.v_splitter, 1)
        root_layout.addWidget(self.build_action_bar())

        status = QStatusBar()
        self.setStatusBar(status)
        self.status_state = QLabel("● Ready")
        self.status_counts = QLabel("")
        self.status_saved = QLabel("")
        self.status_saved.setMinimumWidth(150)
        self.status_counts.setMinimumWidth(140)
        status.addWidget(self.status_state)
        status.addPermanentWidget(self.status_saved)
        status.addPermanentWidget(self.status_counts)
        self.version_btn = QPushButton(f"v{APP_VERSION}")
        self.version_btn.setObjectName("VersionBtn")
        self.version_btn.setToolTip("ตรวจหาเวอร์ชันใหม่บน GitHub")
        self.version_btn.clicked.connect(lambda: self.check_for_updates(silent=False))
        status.addPermanentWidget(self.version_btn)

    def build_sidebar(self):
        frame = QFrame()
        frame.setObjectName("Sidebar")
        frame.setMinimumWidth(260)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(0)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 6, 0)
        header = QLabel("NOVELS — นิยายที่จัดการ")
        header.setObjectName("SidebarHeader")
        header_row.addWidget(header)
        header_row.addStretch(1)
        self.toggle_all_btn = QToolButton()
        self.toggle_all_btn.setObjectName("Ghost")
        self.toggle_all_btn.setText("☑")
        self.toggle_all_btn.setToolTip("ติ๊ก/เลิกติ๊ก ทุกเรื่อง")
        self.toggle_all_btn.clicked.connect(self.toggle_all_enabled)
        header_row.addWidget(self.toggle_all_btn)
        layout.addLayout(header_row)

        btn_box = QVBoxLayout()
        btn_box.setContentsMargins(10, 2, 10, 8)
        btn_box.setSpacing(6)
        self.add_link_btn = QPushButton("＋  วางลิงก์เพิ่มเรื่อง")
        self.add_link_btn.setObjectName("Primary")
        self.add_link_btn.clicked.connect(self.add_link)
        btn_box.addWidget(self.add_link_btn)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.import_btn = QPushButton("⇪  นำเข้าหลายลิงก์")
        self.import_btn.clicked.connect(self.import_links)
        self.remove_btn = QPushButton("🗑  ลบ")
        self.remove_btn.setObjectName("Danger")
        self.remove_btn.clicked.connect(self.remove_selected_job)
        row.addWidget(self.import_btn, 1)
        row.addWidget(self.remove_btn)
        btn_box.addLayout(row)
        layout.addLayout(btn_box)

        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("Filter")
        self.filter_edit.setPlaceholderText("ค้นหาเรื่อง...")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self.apply_list_filter)
        layout.addWidget(self.filter_edit)

        self.job_list = QListWidget()
        self.job_list.setObjectName("JobList")
        self.job_list.setIconSize(QSize(10, 10))
        self.job_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.job_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.job_list.setItemDelegate(JobItemDelegate(self.job_list))
        self.job_list.setUniformItemSizes(True)
        self.job_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.job_list.currentRowChanged.connect(self.on_job_selected)
        self.job_list.itemChanged.connect(self.on_job_item_changed)
        self.job_list.model().rowsMoved.connect(self.on_rows_moved)
        self.job_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.job_list.customContextMenuRequested.connect(self.show_job_context_menu)
        layout.addWidget(self.job_list, 1)

        self.sidebar_footer = QLabel("")
        self.sidebar_footer.setObjectName("CardHint")
        self.sidebar_footer.setContentsMargins(12, 6, 12, 0)
        layout.addWidget(self.sidebar_footer)
        return frame

    def build_editor(self):
        container = QWidget()
        container.setObjectName("Root")
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        tab_bar = QFrame()
        tab_bar.setObjectName("EditorTabBar")
        tab_layout = QHBoxLayout(tab_bar)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        self.editor_tab_label = QLabel("⚙  settings")
        self.editor_tab_label.setObjectName("EditorTab")
        tab_layout.addWidget(self.editor_tab_label)
        tab_layout.addStretch(1)
        outer.addWidget(tab_bar)

        self.editor_stack = QStackedWidget()
        outer.addWidget(self.editor_stack, 1)

        # empty page
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch(1)
        empty_label = QLabel("ยังไม่มีเรื่องที่เลือก\n\nกด  ＋ วางลิงก์เพิ่มเรื่อง  ทางซ้ายเพื่อเริ่มต้น")
        empty_label.setObjectName("Empty")
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_label)
        empty_btn = QPushButton("＋  วางลิงก์เพิ่มเรื่อง")
        empty_btn.setObjectName("Primary")
        empty_btn.setFixedWidth(220)
        empty_btn.clicked.connect(self.add_link)
        empty_layout.addWidget(empty_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(2)
        self.editor_stack.addWidget(empty)

        # form page
        scroll = QScrollArea()
        scroll.setObjectName("EditorScroll")
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("EditorBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(28, 20, 28, 28)
        body_layout.setSpacing(14)
        scroll.setWidget(body)
        self.editor_stack.addWidget(scroll)

        self.editor_title = QLabel("")
        self.editor_title.setObjectName("EditorTitle")
        self.editor_title.setWordWrap(True)
        self.editor_sub = QLabel("")
        self.editor_sub.setObjectName("EditorSub")
        self.editor_sub.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body_layout.addWidget(self.editor_title)
        body_layout.addWidget(self.editor_sub)

        # --- card 1: novel info
        card, lay = make_card("1 · ข้อมูลเรื่อง", "ลิงก์หน้าคลังตอนของเรื่อง (…/dashboard/workings/<id>?tab=episode)")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel("ลิงก์คลังตอน"), 0, 0)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://mynovel.co/dashboard/workings/...?tab=episode")
        grid.addWidget(self.url_edit, 0, 1)
        self.open_url_btn = QPushButton("เปิดในเบราว์เซอร์ ↗")
        self.open_url_btn.clicked.connect(self.open_current_url)
        grid.addWidget(self.open_url_btn, 0, 2)
        grid.addWidget(QLabel("ชื่อเรื่อง"), 1, 0)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("(เว้นว่างได้ — จะอ่านจากหน้าเว็บตอนรัน)")
        grid.addWidget(self.title_edit, 1, 1, 1, 2)
        self.enabled_chk = QCheckBox("รวมเรื่องนี้ในการรันแบบ Batch")
        grid.addWidget(self.enabled_chk, 2, 1, 1, 2)
        self.url_error = QLabel("")
        self.url_error.setStyleSheet(f"color: {C['err']};")
        grid.addWidget(self.url_error, 3, 1, 1, 2)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        body_layout.addWidget(card)

        # --- card 2: pricing
        card, lay = make_card("2 · การตั้งราคา (Pricing Rules)", "เลขตอนอ่านจากชื่อตอน (เช่น 'ตอนที่ 015') ถ้าไม่มีจะใช้เลขลำดับในตาราง")
        self.price_group = QButtonGroup(self)
        price_row = QGridLayout()
        price_row.setHorizontalSpacing(18)
        self.price_radios: Dict[str, QRadioButton] = {}
        for i, (key, label) in enumerate(PRICE_MODES.items()):
            radio = QRadioButton(label)
            self.price_group.addButton(radio)
            self.price_radios[key] = radio
            price_row.addWidget(radio, i // 2, i % 2)
        lay.addLayout(price_row)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel("ราคาเหรียญ / ตอน"), 0, 0)
        self.price_spin = QSpinBox()
        self.price_spin.setRange(1, 9999)
        self.price_spin.setSuffix("  เหรียญ")
        self.price_spin.setFixedWidth(150)
        grid.addWidget(self.price_spin, 0, 1)
        self.free_rule_label = QLabel("กฎตอนฟรี")
        grid.addWidget(self.free_rule_label, 1, 0)
        self.free_rule_combo = QComboBox()
        self.free_rule_combo.addItems(FREE_RULES)
        grid.addWidget(self.free_rule_combo, 1, 1, 1, 2)
        self.free_custom_label = QLabel("ตอนฟรี (กำหนดเอง)")
        grid.addWidget(self.free_custom_label, 2, 0)
        self.free_custom_edit = QLineEdit()
        self.free_custom_edit.setPlaceholderText("เช่น 1-10, 15, 20, 25-27")
        grid.addWidget(self.free_custom_edit, 2, 1, 1, 2)
        grid.setColumnStretch(2, 1)
        lay.addLayout(grid)
        self.price_preview = QLabel("")
        self.price_preview.setObjectName("CardHint")
        self.price_preview.setWordWrap(True)
        lay.addWidget(self.price_preview)
        body_layout.addWidget(card)

        # --- card 3: scheduling
        card, lay = make_card("3 · การตั้งเวลา (Scheduling)", "ไล่เวลาจากตอนเก่าสุดที่เป็นฉบับร่าง → ตอนใหม่สุด ต่อเนื่องทีละตอน")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel("สถานะหลังแก้ไข"), 0, 0)
        self.publish_combo = QComboBox()
        for key, label in PUBLISH_MODES.items():
            self.publish_combo.addItem(label, key)
        grid.addWidget(self.publish_combo, 0, 1, 1, 3)

        grid.addWidget(QLabel("วันที่เริ่ม"), 1, 0)
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDisplayFormat("dd/MM/yyyy")
        grid.addWidget(self.start_date_edit, 1, 1)
        date_btns = QHBoxLayout()
        date_btns.setSpacing(4)
        for text, days in (("วันนี้", 0), ("พรุ่งนี้", 1)):
            b = QPushButton(text)
            b.setObjectName("Ghost")
            b.clicked.connect(lambda _=False, d=days: self.start_date_edit.setDate(QDate.currentDate().addDays(d)))
            date_btns.addWidget(b)
        date_btns.addStretch(1)
        grid.addLayout(date_btns, 1, 2, 1, 2)

        grid.addWidget(QLabel("เวลาเริ่ม"), 2, 0)
        self.start_time_edit = QTimeEdit()
        self.start_time_edit.setDisplayFormat("HH:mm")
        grid.addWidget(self.start_time_edit, 2, 1)

        self.per_day_chk = QCheckBox("จำกัดวันละ")
        grid.addWidget(self.per_day_chk, 3, 0)
        self.per_day_spin = QSpinBox()
        self.per_day_spin.setRange(1, 500)
        self.per_day_spin.setSuffix("  ตอน / วัน")
        grid.addWidget(self.per_day_spin, 3, 1)
        per_day_hint = QLabel("ครบจำนวนแล้วขึ้นวันใหม่ที่ 'เวลาเริ่ม'")
        per_day_hint.setObjectName("CardHint")
        grid.addWidget(per_day_hint, 3, 2, 1, 2)

        grid.addWidget(QLabel("ระยะห่างระหว่างตอน"), 4, 0)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 10000)
        grid.addWidget(self.interval_spin, 4, 1)
        self.interval_unit_combo = QComboBox()
        self.interval_unit_combo.addItem("นาที", "minutes")
        self.interval_unit_combo.addItem("ชั่วโมง", "hours")
        self.interval_unit_combo.setFixedWidth(120)
        grid.addWidget(self.interval_unit_combo, 4, 2)

        self.skip_chk = QCheckBox("ข้ามช่วงเวลา (Skip window)")
        grid.addWidget(self.skip_chk, 5, 0)
        skip_row = QHBoxLayout()
        self.skip_start_edit = QTimeEdit()
        self.skip_start_edit.setDisplayFormat("HH:mm")
        self.skip_end_edit = QTimeEdit()
        self.skip_end_edit.setDisplayFormat("HH:mm")
        skip_row.addWidget(self.skip_start_edit)
        skip_row.addWidget(QLabel("ถึง"))
        skip_row.addWidget(self.skip_end_edit)
        skip_row.addStretch(1)
        grid.addLayout(skip_row, 5, 1, 1, 3)

        grid.addWidget(QLabel("จำนวนตอนสูงสุด"), 6, 0)
        self.max_spin = QSpinBox()
        self.max_spin.setRange(0, 100000)
        self.max_spin.setSpecialValueText("ทุกตอนที่เป็นฉบับร่าง")
        grid.addWidget(self.max_spin, 6, 1)
        max_hint = QLabel("0 = ทั้งหมด (นับจากตอนเก่าสุด)")
        max_hint.setObjectName("CardHint")
        grid.addWidget(max_hint, 6, 2, 1, 2)

        self.continue_chk = QCheckBox("ต่อเวลาจากรอบก่อน หลังจาก")
        self.continue_chk.setToolTip("รันซ้ำแล้วไม่ทับเวลาที่เคยตั้งไว้ — ตอนถัดไปจะได้ช่องเวลาหลังเวลานี้เท่านั้น\nโปรแกรมจะอัปเดตค่านี้ให้อัตโนมัติหลังรันแต่ละครั้ง")
        grid.addWidget(self.continue_chk, 7, 0)
        self.last_dt_edit = QDateTimeEdit()
        self.last_dt_edit.setCalendarPopup(True)
        self.last_dt_edit.setDisplayFormat("dd/MM/yyyy HH:mm")
        self.last_dt_edit.setMinimumDateTime(QDateTime(QDate(2000, 1, 1), QTime(0, 0)))
        self.last_dt_edit.setSpecialValueText("— ยังไม่เคยตั้ง —")
        grid.addWidget(self.last_dt_edit, 7, 1)
        self.clear_last_btn = QPushButton("ล้าง")
        self.clear_last_btn.setObjectName("Ghost")
        self.clear_last_btn.setToolTip("ล้างเวลาล่าสุด — เริ่มตารางใหม่จาก 'วันที่เริ่ม'")
        self.clear_last_btn.clicked.connect(lambda: self.last_dt_edit.setDateTime(self.last_dt_edit.minimumDateTime()))
        grid.addWidget(self.clear_last_btn, 7, 2)

        grid.addWidget(QLabel("ตอนที่จะแก้"), 8, 0)
        self.target_combo = QComboBox()
        for key, label in TARGET_MODES.items():
            self.target_combo.addItem(label, key)
        self.target_combo.setToolTip("เลือก 'ฉบับร่าง + ตั้งเวลาแล้ว' เมื่อต้องการจัดเวลา/ราคาใหม่ให้ตอนที่เคยตั้งเวลาไปแล้ว")
        grid.addWidget(self.target_combo, 8, 1, 1, 3)
        grid.addWidget(QLabel("เริ่มจากลำดับตอน ≥"), 9, 0)
        self.min_order_spin = QSpinBox()
        self.min_order_spin.setRange(0, 100000)
        self.min_order_spin.setSpecialValueText("ไม่จำกัด")
        grid.addWidget(self.min_order_spin, 9, 1)
        min_hint = QLabel("ข้ามตอนที่ลำดับต่ำกว่านี้ (ใช้ตอนต้องการแก้เฉพาะช่วง)")
        min_hint.setObjectName("CardHint")
        grid.addWidget(min_hint, 9, 2, 1, 2)
        grid.setColumnStretch(3, 1)
        lay.addLayout(grid)
        self.schedule_preview = QLabel("")
        self.schedule_preview.setObjectName("Preview")
        self.schedule_preview.setTextFormat(Qt.TextFormat.RichText)
        self.schedule_preview.setWordWrap(True)
        lay.addWidget(self.schedule_preview)
        body_layout.addWidget(card)

        # --- card 4: apply to all
        card, lay = make_card("4 · ใช้การตั้งค่านี้กับทุกเรื่อง", "คัดลอกการตั้งค่าของเรื่องนี้ไปยังเรื่องอื่นทั้งหมด ไม่ต้องกรอกซ้ำทีละเรื่อง (ลิงก์และชื่อเรื่องไม่ถูกแตะต้อง)")
        row = QHBoxLayout()
        self.apply_pricing_chk = QCheckBox("ราคา")
        self.apply_pricing_chk.setChecked(True)
        self.apply_schedule_chk = QCheckBox("ตารางเวลา")
        self.apply_schedule_chk.setChecked(True)
        self.apply_checked_only_chk = QCheckBox("เฉพาะเรื่องที่ติ๊กไว้")
        row.addWidget(self.apply_pricing_chk)
        row.addWidget(self.apply_schedule_chk)
        row.addWidget(self.apply_checked_only_chk)
        row.addStretch(1)
        self.apply_all_btn = QPushButton("⧉  คัดลอกการตั้งค่านี้ไปใช้กับทุกเรื่อง (Apply to All)")
        self.apply_all_btn.setObjectName("Primary")
        self.apply_all_btn.clicked.connect(self.apply_to_all)
        row.addWidget(self.apply_all_btn)
        lay.addLayout(row)
        body_layout.addWidget(card)
        body_layout.addStretch(1)

        # connect form signals
        for w in (self.url_edit, self.title_edit, self.free_custom_edit):
            w.textChanged.connect(self.on_form_changed)
        for w in (self.price_spin, self.per_day_spin, self.interval_spin, self.max_spin):
            w.valueChanged.connect(self.on_form_changed)
        for w in (self.free_rule_combo, self.publish_combo, self.interval_unit_combo):
            w.currentIndexChanged.connect(self.on_form_changed)
        for w in (self.enabled_chk, self.per_day_chk, self.skip_chk):
            w.toggled.connect(self.on_form_changed)
        self.price_group.buttonToggled.connect(lambda *_: self.on_form_changed())
        self.start_date_edit.dateChanged.connect(self.on_form_changed)
        self.continue_chk.toggled.connect(self.on_form_changed)
        self.target_combo.currentIndexChanged.connect(self.on_form_changed)
        self.min_order_spin.valueChanged.connect(self.on_form_changed)
        self.last_dt_edit.dateTimeChanged.connect(self.on_form_changed)
        for w in (self.start_time_edit, self.skip_start_edit, self.skip_end_edit):
            w.timeChanged.connect(self.on_form_changed)
        return container

    def build_output_panel(self):
        frame = QWidget()
        frame.setObjectName("Root")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("PanelHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(14, 0, 8, 0)
        h.setSpacing(10)
        tab = QLabel("OUTPUT")
        tab.setObjectName("PanelTab")
        h.addWidget(tab)
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("CardHint")
        h.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setMaximumWidth(360)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        h.addWidget(self.progress_bar, 1)
        h.addStretch(1)
        open_logs = QToolButton()
        open_logs.setObjectName("Ghost")
        open_logs.setText("📂 logs")
        open_logs.setToolTip("เปิดโฟลเดอร์ไฟล์ log")
        open_logs.clicked.connect(self.open_logs_folder)
        h.addWidget(open_logs)
        clear_btn = QToolButton()
        clear_btn.setObjectName("Ghost")
        clear_btn.setText("⊘ ล้าง")
        clear_btn.clicked.connect(lambda: self.output.clear())
        h.addWidget(clear_btn)
        layout.addWidget(header)
        self.output = QPlainTextEdit()
        self.output.setObjectName("Output")
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(8000)
        layout.addWidget(self.output, 1)
        return frame

    def build_action_bar(self):
        bar = QFrame()
        bar.setObjectName("ActionBar")
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        lbl = QLabel("เบราว์เซอร์")
        lbl.setObjectName("BarLabel")
        row1.addWidget(lbl)
        self.browser_mode_combo = QComboBox()
        self.browser_mode_combo.addItem("Automation Profile (แนะนำ)", "automation")
        self.browser_mode_combo.addItem("Chrome Profile ในเครื่อง", "installed")
        self.browser_mode_combo.addItem("Custom profile folder", "custom")
        self.browser_mode_combo.addItem("Guest (ไม่มี session)", "guest")
        self.browser_mode_combo.setFixedWidth(230)
        row1.addWidget(self.browser_mode_combo)
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(260)
        row1.addWidget(self.profile_combo)
        self.custom_profile_edit = QLineEdit()
        self.custom_profile_edit.setPlaceholderText("โฟลเดอร์ User Data ของ Chrome")
        self.custom_profile_edit.setMinimumWidth(240)
        row1.addWidget(self.custom_profile_edit)
        self.custom_browse_btn = QPushButton("…")
        self.custom_browse_btn.setFixedWidth(34)
        self.custom_browse_btn.clicked.connect(self.browse_custom_profile)
        row1.addWidget(self.custom_browse_btn)
        lbl = QLabel("Chrome")
        lbl.setObjectName("BarLabel")
        row1.addWidget(lbl)
        self.chrome_path_edit = QLineEdit()
        self.chrome_path_edit.setPlaceholderText("ปล่อยว่าง = ค้นหาอัตโนมัติ")
        row1.addWidget(self.chrome_path_edit, 1)
        detect_btn = QPushButton("ค้นหา")
        detect_btn.clicked.connect(self.auto_detect_chrome)
        row1.addWidget(detect_btn)
        lbl = QLabel("หน้าต่าง")
        lbl.setObjectName("BarLabel")
        row1.addWidget(lbl)
        self.window_mode_combo = QComboBox()
        self.window_mode_combo.addItem("แสดงหน้าต่าง Chrome", "show")
        self.window_mode_combo.addItem("ซ่อน (ย้ายออกนอกจอ) · แนะนำ", "offscreen")
        self.window_mode_combo.addItem("Headless (เบาสุด · ทดลอง)", "headless")
        self.window_mode_combo.setToolTip(
            "ซ่อน = Chrome ทำงานเหมือนปกติทุกอย่าง แต่หน้าต่างอยู่นอกจอ (เสถียรที่สุดเวลาไม่อยากเห็นหน้าต่าง)\n"
            "Headless = ไม่มีหน้าต่างเลย ใช้ RAM น้อยกว่า แต่บางหน้าของเว็บอาจทำงานไม่เหมือนปกติ"
        )
        self.window_mode_combo.setFixedWidth(230)
        row1.addWidget(self.window_mode_combo)
        outer.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.login_btn = QPushButton("🔑  เปิดหน้า Login")
        self.login_btn.setToolTip("เปิด Chrome ไว้ล็อกอิน MyNovel ครั้งแรก — ถ้าไม่ปิดหน้าต่างนี้ โปรแกรมจะใช้ session นี้ทำงานต่อทันที")
        self.login_btn.clicked.connect(self.open_login_page)
        row2.addWidget(self.login_btn)
        self.close_login_btn = QPushButton("ปิดหน้า Login")
        self.close_login_btn.setObjectName("Ghost")
        self.close_login_btn.clicked.connect(self.close_login_browser)
        row2.addWidget(self.close_login_btn)
        row2.addSpacing(14)
        self.draft_filter_chk = QCheckBox("กรองเฉพาะ 'ฉบับร่าง' บนเว็บ (เร็วขึ้น)")
        row2.addWidget(self.draft_filter_chk)
        self.dry_run_chk = QCheckBox("Dry run (สแกน+แสดงแผน ไม่บันทึก)")
        row2.addWidget(self.dry_run_chk)
        row2.addStretch(1)
        lbl = QLabel("รัน")
        lbl.setObjectName("BarLabel")
        row2.addWidget(lbl)
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("ทุกเรื่องที่ติ๊กไว้ (คิว)", "checked")
        self.scope_combo.addItem("เฉพาะเรื่องที่เลือกอยู่", "current")
        self.scope_combo.setFixedWidth(200)
        row2.addWidget(self.scope_combo)
        lbl = QLabel("พร้อมกัน")
        lbl.setObjectName("BarLabel")
        row2.addWidget(lbl)
        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, MAX_PARALLEL_LIMIT)
        self.parallel_spin.setSuffix(" เรื่อง")
        self.parallel_spin.setFixedWidth(95)
        self.parallel_spin.setToolTip(
            f"ทำได้พร้อมกันสูงสุด {MAX_PARALLEL_LIMIT} เรื่อง — แต่ละเรื่องเปิด Chrome แยกของตัวเอง\n"
            "Chrome 1 ตัวใช้ RAM ประมาณ 300–500 MB · แนะนำเลือก 'ซ่อน (ย้ายออกนอกจอ)' เมื่อรันหลายเรื่อง\n"
            "1 = ทำทีละเรื่อง (ใช้หน้าต่าง Login เดิมได้)"
        )
        row2.addWidget(self.parallel_spin)
        self.stop_btn = QPushButton("■  หยุด")
        self.stop_btn.setObjectName("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_batch)
        row2.addWidget(self.stop_btn)
        self.start_btn = QPushButton("⚡  เริ่มปรับเวลาและติดเหรียญอัตโนมัติ (Batch Edit Drafts)")
        self.start_btn.setObjectName("Run")
        self.start_btn.clicked.connect(self.start_batch)
        row2.addWidget(self.start_btn)
        outer.addLayout(row2)

        self.browser_mode_combo.currentIndexChanged.connect(self.on_browser_settings_changed)
        self.profile_combo.currentIndexChanged.connect(self.on_browser_settings_changed)
        self.custom_profile_edit.textChanged.connect(self.on_browser_settings_changed)
        self.chrome_path_edit.textChanged.connect(self.on_browser_settings_changed)
        self.window_mode_combo.currentIndexChanged.connect(self.on_browser_settings_changed)
        for chk in (self.draft_filter_chk, self.dry_run_chk):
            chk.toggled.connect(self.on_browser_settings_changed)
        self.scope_combo.currentIndexChanged.connect(self.on_browser_settings_changed)
        self.parallel_spin.valueChanged.connect(self.on_browser_settings_changed)
        return bar

    # ================================================================== persistence
    def schedule_save(self):
        self.save_timer.start()

    def save_config(self):
        try:
            self.config["version"] = CONFIG_VERSION
            self.config["jobs"] = [job.to_dict() for job in self.jobs]
            self.config["browser"] = {
                "mode": self.browser_mode_combo.currentData(),
                "profile_label": self.profile_combo.currentText() if self.profile_map else self.config.get("browser", {}).get("profile_label", ""),
                "custom_profile_path": self.custom_profile_edit.text().strip(),
                "chrome_path": self.chrome_path_edit.text().strip(),
                "window_mode": self.window_mode_combo.currentData(),
            }
            self.config["run"] = {
                "draft_filter": self.draft_filter_chk.isChecked(),
                "dry_run": self.dry_run_chk.isChecked(),
                "scope": self.scope_combo.currentData(),
                "max_parallel": self.parallel_spin.value(),
            }
            ui = self.config.setdefault("ui", {})
            ui["selected_index"] = max(0, self.job_list.currentRow())
            write_json_atomic(CONFIG_FILE, self.config)
            self.status_saved.setText(f"บันทึกแล้ว {datetime.now():%H:%M:%S}")
        except Exception as error:
            self.status_saved.setText("บันทึกไม่สำเร็จ")
            self.append_log(f"บันทึก config.json ไม่สำเร็จ: {error}", "err")

    def restore_ui_state(self):
        ui = self.config.get("ui", {})
        try:
            if ui.get("geometry"):
                self.restoreGeometry(QByteArray.fromHex(ui["geometry"].encode()))
            if ui.get("h_splitter"):
                self.h_splitter.restoreState(QByteArray.fromHex(ui["h_splitter"].encode()))
            if ui.get("v_splitter"):
                self.v_splitter.restoreState(QByteArray.fromHex(ui["v_splitter"].encode()))
        except Exception:
            pass

    def store_ui_state(self):
        ui = self.config.setdefault("ui", {})
        ui["geometry"] = bytes(self.saveGeometry().toHex()).decode()
        ui["h_splitter"] = bytes(self.h_splitter.saveState().toHex()).decode()
        ui["v_splitter"] = bytes(self.v_splitter.saveState().toHex()).decode()

    def load_browser_settings(self):
        self._loading = True
        try:
            browser = self.config.get("browser", {})
            run = self.config.get("run", {})
            self.refresh_profile_combo(browser.get("profile_label", ""))
            idx = self.browser_mode_combo.findData(browser.get("mode", "automation"))
            self.browser_mode_combo.setCurrentIndex(max(0, idx))
            self.custom_profile_edit.setText(browser.get("custom_profile_path", ""))
            self.chrome_path_edit.setText(browser.get("chrome_path", "") or detect_chrome_path())
            mode_value = browser.get("window_mode") or ("offscreen" if browser.get("headless") else "show")
            self.window_mode_combo.setCurrentIndex(max(0, self.window_mode_combo.findData(mode_value)))
            self.draft_filter_chk.setChecked(bool(run.get("draft_filter", True)))
            self.dry_run_chk.setChecked(bool(run.get("dry_run", False)))
            idx = self.scope_combo.findData(run.get("scope", "checked"))
            self.scope_combo.setCurrentIndex(max(0, idx))
            self.parallel_spin.setValue(int(run.get("max_parallel", 3) or 1))
        finally:
            self._loading = False
        self.update_browser_widgets()

    def refresh_profile_combo(self, selected_label: str = ""):
        profiles = load_chrome_profiles()
        self.profile_map = {p.label: p for p in profiles}
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for p in profiles:
            self.profile_combo.addItem(p.label)
        if not profiles:
            self.profile_combo.addItem("(ไม่พบ Chrome profile)")
        if selected_label:
            i = self.profile_combo.findText(selected_label)
            if i >= 0:
                self.profile_combo.setCurrentIndex(i)
        self.profile_combo.blockSignals(False)

    def update_browser_widgets(self):
        mode = self.browser_mode_combo.currentData()
        self.profile_combo.setVisible(mode == "installed")
        self.custom_profile_edit.setVisible(mode == "custom")
        self.custom_browse_btn.setVisible(mode == "custom")

    def on_browser_settings_changed(self, *_):
        self.update_browser_widgets()
        if not self._loading:
            self.schedule_save()

    # ================================================================== job list
    def job_by_id(self, job_id: str) -> Optional[NovelJob]:
        return next((j for j in self.jobs if j.id == job_id), None)

    def update_item(self, item: QListWidgetItem, job: NovelJob):
        self.job_list.blockSignals(True)
        try:
            item.setText(job.display_name())
            item.setData(JobItemDelegate.STATUS_ROLE, job.status)
            item.setData(JobItemDelegate.SUB_ROLE, job.last_message)
            _, color = JOB_STATUS_META.get(job.status, JOB_STATUS_META["ready"])
            item.setIcon(dot_icon(color))
            item.setCheckState(Qt.CheckState.Checked if job.enabled else Qt.CheckState.Unchecked)
            item.setToolTip(f"{job.display_name()}\n{job.working_url}\nสถานะ: {job.status} {job.last_message}")
        finally:
            self.job_list.blockSignals(False)

    def refresh_job_list(self, select_id: Optional[str] = None):
        current_id = select_id or (self.current_job.id if self.current_job else None)
        self.job_list.blockSignals(True)
        self.job_list.clear()
        for job in self.jobs:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, job.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
            self.job_list.addItem(item)
            self.update_item(item, job)
        self.job_list.blockSignals(False)
        if current_id:
            for row in range(self.job_list.count()):
                if self.job_list.item(row).data(Qt.ItemDataRole.UserRole) == current_id:
                    self.job_list.setCurrentRow(row)
                    break
        self.apply_list_filter()
        self.update_counts()

    def refresh_job_item(self, job: NovelJob):
        for row in range(self.job_list.count()):
            item = self.job_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == job.id:
                self.update_item(item, job)
                break
        self.update_counts()

    def apply_list_filter(self):
        text = self.filter_edit.text().strip().lower()
        for row in range(self.job_list.count()):
            item = self.job_list.item(row)
            job = self.job_by_id(item.data(Qt.ItemDataRole.UserRole))
            hay = f"{job.display_name()} {job.working_url}".lower() if job else ""
            item.setHidden(bool(text) and text not in hay)

    def update_counts(self):
        total = len(self.jobs)
        enabled = sum(1 for j in self.jobs if j.enabled)
        done = sum(1 for j in self.jobs if j.status == "done")
        failed = sum(1 for j in self.jobs if j.status == "failed")
        self.sidebar_footer.setText(f"{total} เรื่อง · ติ๊ก {enabled} · Done {done} · Failed {failed}")
        self.status_counts.setText(f"{enabled}/{total} เรื่องที่จะรัน")

    def on_rows_moved(self, *_):
        order = [self.job_list.item(r).data(Qt.ItemDataRole.UserRole) for r in range(self.job_list.count())]
        lookup = {j.id: j for j in self.jobs}
        self.jobs = [lookup[i] for i in order if i in lookup]
        self.schedule_save()

    def on_job_item_changed(self, item: QListWidgetItem):
        job = self.job_by_id(item.data(Qt.ItemDataRole.UserRole))
        if job is None:
            return
        enabled = item.checkState() == Qt.CheckState.Checked
        if job.enabled != enabled:
            job.enabled = enabled
            if self.current_job is job:
                self._loading = True
                self.enabled_chk.setChecked(enabled)
                self._loading = False
            self.update_counts()
            self.schedule_save()

    def on_job_selected(self, row: int):
        if row < 0 or row >= self.job_list.count():
            self.show_job(None)
            return
        job = self.job_by_id(self.job_list.item(row).data(Qt.ItemDataRole.UserRole))
        self.show_job(job)
        self.schedule_save()

    def toggle_all_enabled(self):
        target = not all(j.enabled for j in self.jobs)
        for job in self.jobs:
            job.enabled = target
        self.refresh_job_list()
        if self.current_job:
            self.show_job(self.current_job)
        self.schedule_save()

    def new_job_from_template(self, url: str, title: str = "") -> NovelJob:
        template = self.current_job
        job = NovelJob(working_url=normalize_episode_url(url), title=title.strip())
        if template:
            for name in NovelJob.SETTINGS_PRICING + NovelJob.SETTINGS_SCHEDULE:
                setattr(job, name, getattr(template, name))
        if not job.start_date:
            job.start_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        return job

    def existing_urls(self) -> set:
        return {normalize_episode_url(j.working_url) for j in self.jobs}

    def add_link(self):
        clip = QApplication.clipboard().text().strip() if QApplication.clipboard() else ""
        dialog = AddLinkDialog(self, clip if is_valid_working_url(clip) else "")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        url = normalize_episode_url(dialog.url_edit.text())
        if url in self.existing_urls():
            QMessageBox.information(self, "มีอยู่แล้ว", "ลิงก์นี้อยู่ในรายการแล้ว")
            return
        job = self.new_job_from_template(url, dialog.title_edit.text())
        self.jobs.append(job)
        self.refresh_job_list(select_id=job.id)
        self.append_log(f"เพิ่มเรื่อง: {job.display_name()}", "ok")
        self.schedule_save()

    def import_links(self):
        dialog = ImportLinksDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        existing = self.existing_urls()
        added, skipped = 0, 0
        last_id = None
        for url, title in dialog.parsed():
            if url in existing:
                skipped += 1
                continue
            job = self.new_job_from_template(url, title)
            self.jobs.append(job)
            existing.add(url)
            last_id = job.id
            added += 1
        self.refresh_job_list(select_id=last_id)
        self.append_log(f"นำเข้า {added} เรื่อง" + (f" (ข้ามลิงก์ซ้ำ {skipped})" if skipped else ""), "ok")
        self.schedule_save()

    def remove_selected_job(self):
        if self.current_job is None:
            return
        if self.is_running() and self.current_job.id in self.run_job_ids:
            QMessageBox.warning(self, "กำลังทำงาน", "ลบเรื่องที่อยู่ในคิวที่กำลังรันไม่ได้")
            return
        job = self.current_job
        if QMessageBox.question(self, "ลบเรื่อง", f"ลบ '{job.display_name()}' ออกจากรายการ?") != QMessageBox.StandardButton.Yes:
            return
        row = self.jobs.index(job)
        self.jobs.remove(job)
        self.current_job = None
        self.refresh_job_list()
        if self.jobs:
            self.job_list.setCurrentRow(min(row, len(self.jobs) - 1))
        else:
            self.show_job(None)
        self.schedule_save()

    def show_job_context_menu(self, pos):
        item = self.job_list.itemAt(pos)
        if item is None:
            return
        job = self.job_by_id(item.data(Qt.ItemDataRole.UserRole))
        if job is None:
            return
        menu = QMenu(self)
        act_run = menu.addAction("⚡ รันเฉพาะเรื่องนี้")
        act_open = menu.addAction("↗ เปิดลิงก์ในเบราว์เซอร์")
        act_copy = menu.addAction("คัดลอกลิงก์")
        menu.addSeparator()
        act_dup = menu.addAction("ทำสำเนา (ใช้ค่าเดียวกัน)")
        act_reset = menu.addAction("รีเซ็ตสถานะเป็น Ready")
        menu.addSeparator()
        act_del = menu.addAction("ลบ")
        chosen = menu.exec(self.job_list.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_run:
            self.start_batch(only_job=job)
        elif chosen == act_open:
            QDesktopServices.openUrl(QUrl(job.working_url))
        elif chosen == act_copy:
            QApplication.clipboard().setText(job.working_url)
        elif chosen == act_dup:
            clone = NovelJob.from_dict({**job.to_dict(), "id": uuid.uuid4().hex[:12], "status": "ready", "last_message": ""})
            self.jobs.insert(self.jobs.index(job) + 1, clone)
            self.refresh_job_list(select_id=clone.id)
            self.schedule_save()
        elif chosen == act_reset:
            job.status, job.last_message = "ready", ""
            self.refresh_job_item(job)
            self.schedule_save()
        elif chosen == act_del:
            self.job_list.setCurrentItem(item)
            self.remove_selected_job()

    # ================================================================== editor <-> job
    def show_job(self, job: Optional[NovelJob]):
        self.current_job = job
        if job is None:
            self.editor_stack.setCurrentIndex(0)
            self.editor_tab_label.setText("⚙  settings")
            return
        self.editor_stack.setCurrentIndex(1)
        self._loading = True
        try:
            self.url_edit.setText(job.working_url)
            self.title_edit.setText(job.title)
            self.enabled_chk.setChecked(job.enabled)
            self.price_radios.get(job.price_mode, self.price_radios["auto_free"]).setChecked(True)
            self.price_spin.setValue(int(job.price_value or DEFAULT_PRICE))
            idx = self.free_rule_combo.findText(job.free_rule)
            self.free_rule_combo.setCurrentIndex(max(0, idx))
            self.free_custom_edit.setText(job.free_custom)
            self.publish_combo.setCurrentIndex(max(0, self.publish_combo.findData(job.publish_mode)))
            date = QDate.fromString(job.start_date or "", "yyyy-MM-dd")
            self.start_date_edit.setDate(date if date.isValid() else QDate.currentDate().addDays(1))
            self.start_time_edit.setTime(QTime.fromString(job.start_time or "12:00", "HH:mm"))
            self.per_day_chk.setChecked(job.per_day_enabled)
            self.per_day_spin.setValue(int(job.chapters_per_day or 1))
            self.interval_spin.setValue(int(job.interval_value or 1))
            self.interval_unit_combo.setCurrentIndex(max(0, self.interval_unit_combo.findData(job.interval_unit)))
            self.skip_chk.setChecked(job.skip_enabled)
            self.skip_start_edit.setTime(QTime.fromString(job.skip_start or "00:00", "HH:mm"))
            self.skip_end_edit.setTime(QTime.fromString(job.skip_end or "06:00", "HH:mm"))
            self.max_spin.setValue(int(job.max_episodes or 0))
            self.continue_chk.setChecked(bool(job.continue_after_last))
            self.target_combo.setCurrentIndex(max(0, self.target_combo.findData(job.target_mode)))
            self.min_order_spin.setValue(int(job.min_order or 0))
            last = parse_last_scheduled(job.last_scheduled_at)
            self.last_dt_edit.setDateTime(
                QDateTime(QDate(last.year, last.month, last.day), QTime(last.hour, last.minute)) if last
                else self.last_dt_edit.minimumDateTime()
            )
        finally:
            self._loading = False
        if not job.start_date:
            job.start_date = self.start_date_edit.date().toString("yyyy-MM-dd")
        self.update_form_state()
        self.update_editor_header()

    def read_form_into_job(self, job: NovelJob):
        job.working_url = self.url_edit.text().strip()
        job.title = self.title_edit.text().strip()
        job.enabled = self.enabled_chk.isChecked()
        for key, radio in self.price_radios.items():
            if radio.isChecked():
                job.price_mode = key
        job.price_value = self.price_spin.value()
        job.free_rule = self.free_rule_combo.currentText()
        job.free_custom = self.free_custom_edit.text().strip()
        job.publish_mode = self.publish_combo.currentData()
        job.start_date = self.start_date_edit.date().toString("yyyy-MM-dd")
        job.start_time = self.start_time_edit.time().toString("HH:mm")
        job.per_day_enabled = self.per_day_chk.isChecked()
        job.chapters_per_day = self.per_day_spin.value()
        job.interval_value = self.interval_spin.value()
        job.interval_unit = self.interval_unit_combo.currentData()
        job.skip_enabled = self.skip_chk.isChecked()
        job.skip_start = self.skip_start_edit.time().toString("HH:mm")
        job.skip_end = self.skip_end_edit.time().toString("HH:mm")
        job.max_episodes = self.max_spin.value()
        job.continue_after_last = self.continue_chk.isChecked()
        job.target_mode = self.target_combo.currentData()
        job.min_order = self.min_order_spin.value()
        if self.last_dt_edit.dateTime() <= self.last_dt_edit.minimumDateTime():
            job.last_scheduled_at = ""
        else:
            job.last_scheduled_at = self.last_dt_edit.dateTime().toString("yyyy-MM-dd HH:mm")

    def on_form_changed(self, *_):
        if self._loading or self.current_job is None:
            return
        self.read_form_into_job(self.current_job)
        self.update_form_state()
        self.update_editor_header()
        self.refresh_job_item(self.current_job)
        self.schedule_save()

    def update_editor_header(self):
        job = self.current_job
        if job is None:
            return
        self.editor_title.setText(job.display_name())
        self.editor_sub.setText(normalize_episode_url(job.working_url) if job.working_url else "ยังไม่ได้ใส่ลิงก์")
        self.editor_tab_label.setText(f"⚙  {job.display_name()[:60]}")
        if job.working_url and not is_valid_working_url(job.working_url):
            self.url_error.setText("ลิงก์ไม่ถูกต้อง — ต้องเป็น mynovel.co/dashboard/workings/<id>")
        else:
            self.url_error.setText("")

    def update_form_state(self):
        job = self.current_job
        if job is None:
            return
        mode = job.price_mode
        self.price_spin.setEnabled(mode in ("paid_all", "auto_free"))
        auto = mode == "auto_free"
        self.free_rule_combo.setEnabled(auto)
        self.free_rule_label.setEnabled(auto)
        custom = auto and "กำหนดเอง" in job.free_rule
        self.free_custom_edit.setEnabled(custom)
        self.free_custom_label.setEnabled(custom)

        scheduled = job.publish_mode == "scheduled"
        for w in (self.start_date_edit, self.start_time_edit, self.per_day_chk, self.interval_spin,
                  self.interval_unit_combo, self.skip_chk):
            w.setEnabled(scheduled)
        self.per_day_spin.setEnabled(scheduled and job.per_day_enabled)
        self.skip_start_edit.setEnabled(scheduled and job.skip_enabled)
        self.skip_end_edit.setEnabled(scheduled and job.skip_enabled)
        self.continue_chk.setEnabled(scheduled)
        self.last_dt_edit.setEnabled(scheduled and job.continue_after_last)
        self.clear_last_btn.setEnabled(scheduled and job.continue_after_last)

        # pricing preview
        if mode == "auto_free":
            samples = [n for n in range(1, 61) if is_episode_free_by_rule(n, job.free_rule, job.free_custom)][:12]
            sample_text = ", ".join(map(str, samples)) if samples else "ไม่มี"
            self.price_preview.setText(f"ตอนฟรี (ตัวอย่างจากเลขตอน 1–60): {sample_text}  ·  ตอนอื่นติด {job.price_value} เหรียญ")
        elif mode == "paid_all":
            self.price_preview.setText(f"ทุกตอนที่เป็นฉบับร่างจะติด {job.price_value} เหรียญ")
        elif mode == "free_all":
            self.price_preview.setText("ทุกตอนที่เป็นฉบับร่างจะตั้งเป็นฟรี")
        else:
            self.price_preview.setText("ไม่แตะราคาเดิมของแต่ละตอน")

        # schedule preview
        if not scheduled:
            self.schedule_preview.setText(
                "ตอนจะถูก <b>เผยแพร่ทันที</b> หลังบันทึก" if job.publish_mode == "published"
                else "จะไม่แก้สถานะ — แก้เฉพาะราคา (ตอนยังเป็นฉบับร่าง)"
            )
            return
        try:
            cfg = job.schedule_config()
            dts = job_schedule_slots(job, 14)
            lines = []
            now = datetime.now()
            for i, dt in enumerate(dts[:14], start=1):
                color = C["err"] if dt < now else "#b5cea8"
                lines.append(f"<span style='color:#808080'>ร่างลำดับที่ {i:>2}</span> → <span style='color:{color}'>{format_thai_dt(dt)}</span>")
            per_day = f"{cfg.chapters_per_day} ตอน/วัน" if cfg.limit_per_day_enabled else "ไม่จำกัดต่อวัน"
            unit = "ชม." if job.interval_unit == "hours" else "นาที"
            header = f"<span style='color:#4fc1ff'>ตัวอย่างตาราง</span> · {per_day} · ห่าง {job.interval_value} {unit}"
            if cfg.skip_enabled:
                header += f" · ข้าม {cfg.skip_start}–{cfg.skip_end}"
            last = parse_last_scheduled(job.last_scheduled_at) if job.continue_after_last else None
            if last:
                header += f" · <span style='color:#cca700'>ต่อหลัง {format_thai_dt(last)}</span>"
            warn = ""
            if dts and dts[0] < now:
                warn = f"<br><span style='color:{C['err']}'>⚠ เวลาเริ่มอยู่ในอดีต — เว็บอาจไม่รับ ควรเลือกเวลาในอนาคต</span>"
            self.schedule_preview.setText(header + "<br>" + "<br>".join(lines) + "<br>…" + warn)
        except Exception as error:
            self.schedule_preview.setText(f"คำนวณตารางไม่ได้: {html_escape(str(error))}")

    def apply_to_all(self):
        if self.current_job is None:
            return
        names: List[str] = []
        if self.apply_pricing_chk.isChecked():
            names += list(NovelJob.SETTINGS_PRICING)
        if self.apply_schedule_chk.isChecked():
            names += list(NovelJob.SETTINGS_SCHEDULE)
        if not names:
            QMessageBox.information(self, "Apply to All", "เลือกอย่างน้อย 1 หมวด (ราคา / ตารางเวลา)")
            return
        targets = [j for j in self.jobs if j is not self.current_job and (j.enabled or not self.apply_checked_only_chk.isChecked())]
        if not targets:
            QMessageBox.information(self, "Apply to All", "ไม่มีเรื่องอื่นให้คัดลอกไป")
            return
        if QMessageBox.question(
            self, "Apply to All",
            f"คัดลอกการตั้งค่า ({'ราคา' if self.apply_pricing_chk.isChecked() else ''}"
            f"{' + ' if self.apply_pricing_chk.isChecked() and self.apply_schedule_chk.isChecked() else ''}"
            f"{'ตารางเวลา' if self.apply_schedule_chk.isChecked() else ''}) ไปยัง {len(targets)} เรื่อง?",
        ) != QMessageBox.StandardButton.Yes:
            return
        for job in targets:
            for name in names:
                setattr(job, name, getattr(self.current_job, name))
        self.append_log(f"คัดลอกการตั้งค่าไปยัง {len(targets)} เรื่องแล้ว", "ok")
        self.schedule_save()

    def open_current_url(self):
        if self.current_job and is_valid_working_url(self.current_job.working_url):
            QDesktopServices.openUrl(QUrl(normalize_episode_url(self.current_job.working_url)))

    # ================================================================== browser helpers
    def auto_detect_chrome(self):
        path = detect_chrome_path()
        if path:
            self.chrome_path_edit.setText(path)
        else:
            QMessageBox.warning(self, "Chrome", "ไม่พบ Chrome ในตำแหน่งมาตรฐาน — กรุณาระบุเอง (หรือปล่อยว่างให้ Selenium หาเอง)")

    def browse_custom_profile(self):
        folder = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์ Chrome User Data")
        if folder:
            self.custom_profile_edit.setText(folder)

    def resolve_profile(self) -> BrowserProfile:
        mode = self.browser_mode_combo.currentData()
        if mode == "automation":
            return build_automation_profile()
        if mode == "guest":
            return build_guest_profile()
        if mode == "custom":
            path = self.custom_profile_edit.text().strip()
            if not path:
                raise RuntimeError("กรุณาเลือกโฟลเดอร์ Custom profile")
            return build_profile_from_custom_path(path)
        label = self.profile_combo.currentText().strip()
        if label not in self.profile_map:
            raise RuntimeError("กรุณาเลือก Chrome profile")
        return self.profile_map[label]

    def login_driver_alive(self) -> bool:
        if self.login_driver is None:
            return False
        try:
            _ = self.login_driver.current_url
            return True
        except Exception:
            return False

    def open_login_page(self):
        try:
            if self.login_driver_alive():
                self.login_driver.get(MYNOVEL_LOGIN_URL)
                self.append_log("หน้าต่าง Login เปิดอยู่แล้ว — ใช้หน้าต่างเดิม", "dim")
                return
            profile = self.resolve_profile()
            mode = self.browser_mode_combo.currentData()
            self.login_bot = MyNovelBot(log_func=lambda m, l="info": self.append_log(m, l))
            self.login_driver = self.login_bot.open_login_browser(
                self.chrome_path_edit.text().strip(), profile, persistent_profile=(mode == "automation"),
            )
            self.login_driver_mode = mode
            self.append_log("เปิดหน้า Login แล้ว — ล็อกอินให้เสร็จ แล้วกด ⚡ เริ่ม (ไม่ต้องปิดหน้าต่าง Chrome)", "ok")
        except Exception as error:
            QMessageBox.critical(self, "เปิดหน้า Login ไม่สำเร็จ", str(error))

    def close_login_browser(self):
        if self.is_running():
            QMessageBox.warning(self, "กำลังทำงาน", "ปิดหน้า Login ระหว่างรันไม่ได้")
            return
        if self.login_driver is not None:
            if self.login_bot is not None:
                self.login_bot.cleanup_driver(self.login_driver)
            else:
                try:
                    self.login_driver.quit()
                except Exception:
                    pass
        self.login_driver = None
        self.login_bot = None
        self.append_log("ปิดหน้า Login แล้ว", "dim")

    # ================================================================== run
    def is_running(self) -> bool:
        return bool(self.runs) or bool(self.run_queue)

    def set_busy(self, busy: bool):
        self.start_btn.setEnabled(not busy)
        self.stop_btn.setEnabled(busy)
        self.login_btn.setEnabled(not busy)
        self.close_login_btn.setEnabled(not busy)
        self.browser_mode_combo.setEnabled(not busy)
        self.profile_combo.setEnabled(not busy)
        self.custom_profile_edit.setEnabled(not busy)
        self.chrome_path_edit.setEnabled(not busy)
        self.window_mode_combo.setEnabled(not busy)
        self.dry_run_chk.setEnabled(not busy)
        self.parallel_spin.setEnabled(not busy)
        self.draft_filter_chk.setEnabled(not busy)
        self.remove_btn.setEnabled(not busy)
        if busy:
            self.status_state.setText("⟳ Running")
            self.statusBar().setStyleSheet("QStatusBar { background: #cc6633; }")
        else:
            self.status_state.setText("● Ready")
            self.statusBar().setStyleSheet("")

    def start_batch(self, only_job: Optional[NovelJob] = None):
        if self.is_running():
            return
        if self.current_job is not None:
            self.read_form_into_job(self.current_job)
        if isinstance(only_job, NovelJob):
            jobs = [only_job]
        elif self.scope_combo.currentData() == "current":
            jobs = [self.current_job] if self.current_job else []
        else:
            jobs = [j for j in self.jobs if j.enabled]
        if not jobs:
            QMessageBox.information(self, "ยังไม่มีงาน", "ไม่มีเรื่องที่จะรัน — ติ๊กเรื่องทางซ้าย หรือเพิ่มลิงก์ก่อน")
            return
        invalid = [j for j in jobs if not is_valid_working_url(j.working_url)]
        if invalid:
            QMessageBox.warning(self, "ลิงก์ไม่ถูกต้อง", "เรื่องต่อไปนี้ลิงก์ไม่ถูกต้อง:\n\n" + "\n".join(f"• {j.display_name()}" for j in invalid))
            return
        dry_run = self.dry_run_chk.isChecked()
        now = datetime.now()
        past = []
        for j in jobs:
            if j.publish_mode == "scheduled":
                first = job_schedule_slots(j, 1)
                if first and first[0] < now + timedelta(minutes=5):
                    past.append(f"• {j.display_name()} → {format_thai_dt(first[0])}")
        lines = [
            f"จำนวนเรื่อง: {len(jobs)}",
            f"โหมด: {'Dry run (สแกนอย่างเดียว ไม่บันทึก)' if dry_run else 'แก้ไขจริงบนเว็บ'}",
            "",
            *[f"• {j.display_name()}" for j in jobs[:15]],
        ]
        if len(jobs) > 15:
            lines.append(f"… และอีก {len(jobs) - 15} เรื่อง")
        if past:
            lines += ["", "⚠ เวลาเริ่มอยู่ในอดีต/ใกล้เกินไป (เว็บอาจไม่รับ):", *past[:10]]
        if QMessageBox.question(self, "ยืนยันการเริ่มทำงาน", "\n".join(lines)) != QMessageBox.StandardButton.Yes:
            return
        try:
            profile = self.resolve_profile()
        except Exception as error:
            QMessageBox.warning(self, "เบราว์เซอร์", str(error))
            return

        mode = self.browser_mode_combo.currentData()
        max_parallel = max(1, min(MAX_PARALLEL_LIMIT, self.parallel_spin.value()))
        parallel = max_parallel > 1 and len(jobs) > 1

        existing = None
        if parallel:
            # แต่ละเรื่องใช้ Chrome ของตัวเอง (สำเนาโปรไฟล์) — ต้องปิดหน้าต่าง Login ก่อนเพื่อปลดล็อกโปรไฟล์และบันทึกคุกกี้
            if self.login_driver is not None:
                self.append_log("ปิดหน้าต่าง Login ก่อน เพื่อให้แต่ละเรื่องคัดลอกโปรไฟล์ที่ล็อกอินไว้ไปใช้ได้", "dim")
                self.close_login_browser()
        elif self.login_driver_alive():
            existing = self.login_driver
            self.append_log("ใช้หน้าต่าง Chrome ที่ล็อกอินไว้ทำงานต่อ", "dim")
        elif self.login_driver is not None:
            self.login_driver = None
            self.login_bot = None

        snapshots = [NovelJob.from_dict(j.to_dict()) for j in jobs]
        self.run_job_ids = [j.id for j in jobs]
        for j in jobs:
            j.status, j.last_message = "ready", "อยู่ในคิว"
            self.refresh_job_item(j)
        self.open_log_file()
        self.append_log("═" * 70, "dim")
        self.append_log(
            f"เริ่ม Batch Edit Drafts — {len(jobs)} เรื่อง"
            + (f" · พร้อมกันสูงสุด {max_parallel} เรื่อง" if parallel else " · ทีละเรื่อง")
            + ("" if self.window_mode_combo.currentData() == "show" else f" · {self.window_mode_combo.currentText()}")
            + (" (DRY RUN)" if dry_run else ""),
            "head",
        )
        self.run_ctx = {
            "profile": profile,
            "chrome_path": self.chrome_path_edit.text().strip(),
            "headless": self.window_mode_combo.currentData(),
            "dry_run": dry_run,
            "draft_filter": self.draft_filter_chk.isChecked(),
            "parallel": parallel,
            "max_parallel": max_parallel,
            "persistent": (mode == "automation") and not parallel,
            "total_jobs": len(jobs),
            "finished_jobs": 0,
            "ok_jobs": 0,
            "failed_jobs": 0,
            "stopping": False,
            "abort_message": "",
        }
        self.job_progress: Dict[str, tuple] = {}
        self.run_queue = list(snapshots) if parallel else []
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_label.setText("")
        self.set_busy(True)
        self.save_config()
        if parallel:
            self.launch_from_queue()
        else:
            self.launch_worker(snapshots, existing_driver=existing, tag="")

    def launch_worker(self, jobs: List[NovelJob], existing_driver=None, tag: str = ""):
        ctx = self.run_ctx
        worker = BatchWorker(
            jobs,
            profile=ctx["profile"],
            chrome_path=ctx["chrome_path"],
            headless=ctx["headless"],
            persistent_profile=ctx["persistent"],
            dry_run=ctx["dry_run"],
            draft_filter=ctx["draft_filter"],
            existing_driver=existing_driver,
            tag=tag,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.log.connect(self.append_log)
        worker.job_state.connect(self.on_job_state)
        worker.job_title.connect(self.on_job_title)
        worker.progress.connect(self.on_progress)
        worker.job_last_dt.connect(self.on_job_last_dt)
        worker.overall.connect(self.on_overall)
        worker.job_result.connect(self.on_job_result)
        worker.finished.connect(thread.quit)
        key = uuid.uuid4().hex
        self.runs[key] = (worker, thread)
        thread.finished.connect(lambda k=key: self.on_worker_thread_finished(k))
        thread.start()
        self.update_running_status()

    def launch_from_queue(self):
        """เปิด worker เพิ่มจนครบจำนวนพร้อมกันสูงสุด (เว้นจังหวะ 2 วินาทีกัน Chrome เปิดชนกัน)"""
        ctx = getattr(self, "run_ctx", None)
        if not ctx or ctx["stopping"]:
            return
        if self.run_queue and len(self.runs) < ctx["max_parallel"]:
            job = self.run_queue.pop(0)
            name = job.display_name()
            tag = name if len(name) <= 18 else name[:17] + "…"
            self.launch_worker([job], existing_driver=None, tag=tag)
            if self.run_queue and len(self.runs) < ctx["max_parallel"]:
                QTimer.singleShot(2000, self.launch_from_queue)

    def update_running_status(self):
        ctx = getattr(self, "run_ctx", None)
        if not ctx:
            return
        if ctx["parallel"]:
            self.status_state.setText(
                f"⟳ Running · กำลังทำ {len(self.runs)} เรื่อง · เสร็จ {ctx['finished_jobs']}/{ctx['total_jobs']}"
                + (f" · รอคิว {len(self.run_queue)}" if self.run_queue else "")
            )

    def stop_batch(self):
        ctx = getattr(self, "run_ctx", None)
        if ctx is not None:
            ctx["stopping"] = True
        for job in getattr(self, "run_queue", []):
            self.on_job_state(job.id, "stopped", "ยังไม่ได้เริ่ม")
        self.run_queue = []
        for worker, _thread in list(self.runs.values()):
            worker.stop()
        self.stop_btn.setEnabled(False)
        self.status_state.setText("■ Stopping...")
        self.append_log("กำลังหยุด... (จะหยุดหลังขั้นตอนปัจจุบันของทุกเรื่อง)", "warn")

    def on_job_state(self, job_id: str, status: str, message: str):
        job = self.job_by_id(job_id)
        if job is None:
            return
        job.status = status
        job.last_message = message
        if status in ("done", "failed"):
            job.last_run_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.refresh_job_item(job)
        self.schedule_save()

    def on_job_last_dt(self, job_id: str, value: str):
        job = self.job_by_id(job_id)
        if job is None:
            return
        old = parse_last_scheduled(job.last_scheduled_at)
        new = parse_last_scheduled(value)
        if new and (old is None or new > old):
            job.last_scheduled_at = value
            if self.current_job is job:
                self.show_job(job)
            self.append_log(f"บันทึกเวลาล่าสุดของเรื่องนี้: {format_thai_dt(new)} (รอบหน้าจะต่อจากเวลานี้)", "dim")
            self.schedule_save()

    def on_job_title(self, job_id: str, title: str):
        job = self.job_by_id(job_id)
        if job is None or job.title:
            return
        job.title = title
        self.refresh_job_item(job)
        if self.current_job is job:
            self._loading = True
            self.title_edit.setText(title)
            self._loading = False
            self.update_editor_header()
        self.schedule_save()

    def on_progress(self, job_id: str, done: int, total: int):
        job = self.job_by_id(job_id)
        if job is not None:
            job.last_done, job.last_total = done, total
            job.last_message = f"{done}/{total} ตอน"
            self.refresh_job_item(job)
        self.job_progress[job_id] = (done, total)
        sum_done = sum(d for d, _ in self.job_progress.values())
        sum_total = sum(t for _, t in self.job_progress.values())
        self.progress_bar.setRange(0, max(1, sum_total))
        self.progress_bar.setValue(sum_done)
        ctx = getattr(self, "run_ctx", None)
        if ctx and ctx["parallel"]:
            self.progress_label.setText(f"{sum_done}/{sum_total} ตอน · {len(self.job_progress)} เรื่อง")
        else:
            self.progress_label.setText(f"{done}/{total} ตอน")

    def on_overall(self, current: int, total: int):
        ctx = getattr(self, "run_ctx", None)
        if ctx and not ctx["parallel"]:
            self.status_state.setText(f"⟳ Running · เรื่อง {current}/{total}")

    def on_job_result(self, job_id: str, ok: bool, abort_message: str):
        ctx = getattr(self, "run_ctx", None)
        if not ctx:
            return
        ctx["finished_jobs"] += 1
        if ok:
            ctx["ok_jobs"] += 1
        else:
            ctx["failed_jobs"] += 1
        if abort_message and not ctx["abort_message"]:
            ctx["abort_message"] = abort_message
            if "ล็อกอิน" in abort_message and ctx["parallel"]:
                self.append_log("ยังไม่ได้ล็อกอิน — หยุดคิวที่เหลือ", "err")
                self.stop_batch()
        self.update_running_status()

    def on_worker_thread_finished(self, key: str):
        worker, thread = self.runs.pop(key, (None, None))
        if worker is not None:
            worker.deleteLater()
        if thread is not None:
            thread.deleteLater()
        ctx = getattr(self, "run_ctx", None)
        if ctx and ctx["parallel"] and not ctx["stopping"] and self.run_queue:
            self.launch_from_queue()
            return
        self.update_running_status()
        if not self.runs and not self.run_queue:
            self.on_all_finished()

    def on_all_finished(self):
        ctx = self.run_ctx or {}
        if ctx.get("stopping"):
            message, success = "หยุดการทำงานแล้ว", False
        elif ctx.get("abort_message") and not ctx.get("parallel"):
            message, success = ctx["abort_message"], False
        else:
            message = f"เสร็จสิ้น: สำเร็จ {ctx.get('ok_jobs', 0)} เรื่อง · ล้มเหลว {ctx.get('failed_jobs', 0)} เรื่อง"
            success = ctx.get("failed_jobs", 0) == 0
        self.append_log(message, "ok" if success else "warn")
        self.set_busy(False)
        self.run_job_ids = []
        self.run_ctx = None
        self.save_config()
        self.close_log_file()
        if not self.isMinimized():
            if success:
                QMessageBox.information(self, "เสร็จสิ้น", message)
            else:
                QMessageBox.warning(self, "จบการทำงาน", message)

    # ================================================================== log
    def open_log_file(self):
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            self.log_file_path = LOG_DIR / f"batch_{datetime.now():%Y%m%d}.log"
        except Exception:
            self.log_file_path = None

    def close_log_file(self):
        self.log_file_path = None

    def open_logs_folder(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_DIR)))

    def append_log(self, message: str, level: str = "info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = LOG_COLORS.get(level, LOG_COLORS["info"])
        weight = "font-weight:600;" if level == "head" else ""
        for line in str(message).splitlines() or [""]:
            safe = html_escape(line).replace("  ", "&nbsp;&nbsp;")
            self.output.appendHtml(
                f"<span style='color:#6a6a6a'>[{timestamp}]</span> <span style='color:{color};{weight}'>{safe}</span>"
            )
        self.output.moveCursor(QTextCursor.MoveOperation.End)
        if self.log_file_path is not None:
            try:
                with open(self.log_file_path, "a", encoding="utf-8") as f:
                    f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{level}] {message}\n")
            except Exception:
                pass
        if level in ("err", "warn", "ok", "head"):
            self.statusBar().showMessage(str(message).splitlines()[0][:140] if message else "", 6000)

    # ================================================================== update
    def build_update_bar(self):
        bar = QFrame()
        bar.setObjectName("UpdateBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 6, 10, 6)
        layout.setSpacing(8)
        self.update_label = QLabel("")
        layout.addWidget(self.update_label, 1)
        self.update_notes_btn = QPushButton("ดูว่ามีอะไรใหม่")
        self.update_notes_btn.clicked.connect(self.show_update_notes)
        layout.addWidget(self.update_notes_btn)
        self.update_now_btn = QPushButton("⬇  อัปเดตเลย")
        self.update_now_btn.setObjectName("Primary")
        self.update_now_btn.clicked.connect(lambda: self.start_update())
        layout.addWidget(self.update_now_btn)
        later_btn = QPushButton("ภายหลัง")
        later_btn.clicked.connect(lambda: bar.setVisible(False))
        layout.addWidget(later_btn)
        skip_btn = QPushButton("ข้ามเวอร์ชันนี้")
        skip_btn.clicked.connect(self.skip_update_version)
        layout.addWidget(skip_btn)
        bar.setVisible(False)
        self.update_bar = bar
        return bar

    def check_for_updates(self, silent: bool = True):
        if self.update_checker is not None:
            return
        self.version_btn.setText(f"v{APP_VERSION} · กำลังตรวจ…")
        self.update_checker = UpdateChecker()
        self.update_checker.done.connect(lambda info, err, s=silent: self.on_update_checked(info, err, s))
        self.update_checker.start()

    def on_update_checked(self, info, error: str, silent: bool):
        self.update_checker = None
        self.version_btn.setText(f"v{APP_VERSION}")
        if info is None:
            if not silent:
                QMessageBox.information(self, "ตรวจหาอัปเดต", error or "ตรวจหาอัปเดตไม่สำเร็จ")
            return
        if not is_newer_version(info["version"]):
            if not silent:
                QMessageBox.information(self, "ตรวจหาอัปเดต", f"ใช้เวอร์ชันล่าสุดแล้ว (v{APP_VERSION})")
            return
        if silent and not info.get("mandatory") and self.config.get("ui", {}).get("skip_version") == info["version"]:
            return
        self.update_info = info
        self.update_label.setText(
            f"🔔  มีเวอร์ชันใหม่  v{info['version']}  (ตอนนี้ใช้ v{APP_VERSION})"
            + ("" if IS_FROZEN else "  — โหมด source: ใช้ git pull หรือดาวน์โหลดใหม่")
        )
        self.update_now_btn.setText("⬇  อัปเดตเลย" if IS_FROZEN and info.get("asset_url") else "เปิดหน้าดาวน์โหลด")
        self.update_bar.setVisible(True)
        self.version_btn.setText(f"v{APP_VERSION} → v{info['version']} ●")
        self.append_log(f"มีเวอร์ชันใหม่ v{info['version']} บน GitHub", "head")
        if info.get("mandatory") and IS_FROZEN and info.get("asset_url"):
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("ต้องอัปเดตโปรแกรม")
            box.setText(f"เวอร์ชันนี้ (v{APP_VERSION}) ใช้ต่อไม่ได้แล้ว\nกรุณาอัปเดตเป็น v{info['version']}")
            box.setDetailedText(info.get("notes") or "")
            update_btn = box.addButton("อัปเดตเลย", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("ปิดโปรแกรม", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is update_btn:
                self.start_update(skip_confirm=True)
            else:
                self.close()

    def show_update_notes(self):
        info = self.update_info
        if not info:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"มีอะไรใหม่ใน v{info['version']}")
        dialog.resize(640, 480)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setMarkdown(f"# {info.get('name') or info['tag']}\n\n" + (info.get("notes") or "_ไม่มีรายละเอียด_"))
        layout.addWidget(browser, 1)
        buttons = QDialogButtonBox()
        update_btn = buttons.addButton(self.update_now_btn.text(), QDialogButtonBox.ButtonRole.AcceptRole)
        update_btn.setObjectName("Primary")
        buttons.addButton("ปิด", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.start_update()

    def skip_update_version(self):
        if self.update_info:
            self.config.setdefault("ui", {})["skip_version"] = self.update_info["version"]
            self.schedule_save()
        self.update_bar.setVisible(False)

    def start_update(self, skip_confirm: bool = False):
        info = self.update_info
        if not info:
            return
        if not IS_FROZEN or not info.get("asset_url"):
            QDesktopServices.openUrl(QUrl(info.get("url") or f"{GITHUB_URL}/releases"))
            return
        if self.is_running():
            QMessageBox.warning(self, "กำลังทำงาน", "รอให้งานที่รันอยู่เสร็จ (หรือกดหยุด) ก่อนอัปเดตโปรแกรม")
            return
        if not skip_confirm and QMessageBox.question(
            self, "อัปเดตโปรแกรม",
            f"ดาวน์โหลดและติดตั้ง v{info['version']}?\n\n"
            "โปรแกรมจะปิดแล้วเปิดใหม่อัตโนมัติ\n"
            "รายชื่อเรื่อง การตั้งค่า และการล็อกอินจะยังอยู่ครบ",
        ) != QMessageBox.StandardButton.Yes:
            return
        if self.current_job is not None:
            self.read_form_into_job(self.current_job)
        self.store_ui_state()
        self.save_config()
        self.update_progress = QProgressDialog("กำลังดาวน์โหลดเวอร์ชันใหม่…", "ยกเลิก", 0, 100, self)
        self.update_progress.setWindowTitle("อัปเดตโปรแกรม")
        self.update_progress.setMinimumWidth(420)
        self.update_progress.setAutoClose(False)
        self.update_progress.setAutoReset(False)
        self.update_progress.setValue(0)
        self.update_downloader = UpdateDownloader(info["asset_url"], info.get("sha256", ""))
        self.update_progress.canceled.connect(self.update_downloader.cancel)
        self.update_downloader.progress.connect(self.on_update_progress)
        self.update_downloader.done.connect(self.on_update_downloaded)
        self.update_progress.show()
        self.update_downloader.start()

    def on_update_progress(self, received: int, total: int):
        if total > 0:
            self.update_progress.setMaximum(100)
            self.update_progress.setValue(int(received * 100 / total))
            self.update_progress.setLabelText(f"กำลังดาวน์โหลด… {received / 1048576:.1f} / {total / 1048576:.1f} MB")
        else:
            self.update_progress.setMaximum(0)
            self.update_progress.setLabelText(f"กำลังดาวน์โหลด… {received / 1048576:.1f} MB")

    def on_update_downloaded(self, ok: bool, result: str, temp_root: str):
        self.update_progress.close()
        self.update_downloader = None
        if not ok:
            if "ยกเลิก" not in result:
                QMessageBox.warning(self, "อัปเดตไม่สำเร็จ", f"{result}\n\nดาวน์โหลดเองได้ที่ {GITHUB_URL}/releases")
            return
        try:
            launch_updater_and_quit(result, temp_root)
        except Exception as error:
            QMessageBox.warning(self, "อัปเดตไม่สำเร็จ", f"เปิดตัวติดตั้งไม่ได้: {error}")
            return
        self.append_log("กำลังติดตั้งเวอร์ชันใหม่ — โปรแกรมจะเปิดขึ้นมาใหม่เอง", "ok")
        self._updating = True
        self.close()

    # ================================================================== close
    def closeEvent(self, event):
        if self.is_running():
            if QMessageBox.question(self, "กำลังทำงาน", "ยังทำงานอยู่ ต้องการหยุดและปิดโปรแกรม?") != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.stop_batch()
            for worker, thread in list(self.runs.values()):
                worker.stop()
                thread.quit()
                thread.wait(8000)
        if self.current_job is not None:
            self.read_form_into_job(self.current_job)
        self.store_ui_state()
        self.save_config()
        if self.login_driver is not None:
            try:
                if self.login_bot is not None:
                    self.login_bot.cleanup_driver(self.login_driver)
                else:
                    self.login_driver.quit()
            except Exception:
                pass
        event.accept()


def install_crash_handler():
    """ไม่มีหน้าต่าง CMD แล้ว — ถ้าโปรแกรมพัง ให้บันทึกลง logs/crash.log และเด้งแจ้งเตือนแทน"""
    def handler(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(LOG_DIR / "crash.log", "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] v{APP_VERSION}\n{text}")
        except Exception:
            pass
        try:
            if QApplication.instance() is not None:
                QMessageBox.critical(None, "เกิดข้อผิดพลาด",
                                     f"{exc_type.__name__}: {exc}\n\nรายละเอียดอยู่ใน logs/crash.log")
        except Exception:
            pass
    sys.excepthook = handler


def main():
    if handle_special_args(sys.argv):
        return
    install_crash_handler()
    if os.name == "nt":
        try:  # ให้ taskbar แสดงไอคอนโปรแกรมแทนไอคอน Python
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except Exception:
            pass
    if hasattr(Qt.HighDpiScaleFactorRoundingPolicy, "PassThrough"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    icon_path = RESOURCE_DIR / "assets" / "icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
