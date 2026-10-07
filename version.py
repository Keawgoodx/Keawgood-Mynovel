"""
version.py — จุดเดียวที่กำหนดตัวตนของแอป (ชื่อ, เวอร์ชัน) และช่องทางอัปเดต

ทุกครั้งที่ออกเวอร์ชันใหม่ให้เพื่อน:
  1. แก้โค้ด + ทดสอบโปรแกรมให้เรียบร้อย (รันผ่าน run.bat)
  2. เพิ่มเลข __version__ ด้านล่าง (ต้องมากกว่าเดิมเสมอ)
     - หลักขวาสุด (Patch: 2.0.0 → 2.0.1): แก้บั๊กเล็กน้อย, คำผิด, ปรับแก้ UI ย่อย
     - หลักกลาง (Minor: 2.0.1 → 2.1.0): เพิ่มฟีเจอร์ใหม่ (รีเซ็ตขวาสุดเป็น 0)
     - หลักซ้ายสุด (Major: 2.1.0 → 3.0.0): ปรับโครงสร้างใหญ่ทั้งโปรแกรม
  3. เขียนสิ่งที่เปลี่ยนไว้บนสุดของ release_notes.md (หัวข้อ "### ✨ มีอะไรใหม่ใน vX.Y.Z")
  4. ดับเบิลคลิก build_and_release.bat  (หรือรัน: python release.py --publish)
     ถ้าต้องการบังคับให้ทุกเครื่องอัปเดต: python release.py --publish --mandatory

  build_and_release.bat จะ build .exe → zip → commit + push โค้ดขึ้น GitHub
  → สร้าง Release พร้อมแนบ zip + version.json ให้เอง เครื่องเพื่อนจะขึ้นแจ้งเตือนอัปเดต
"""

APP_NAME = "Keawgood_Mynovel"          # ชื่อไฟล์ .exe / โฟลเดอร์ (ห้ามมีช่องว่าง)
APP_DISPLAY_NAME = "Keawgood MyNovel"  # ชื่อที่แสดงบนหน้าต่าง
APP_ORG = "Keawgood"

# Windows AppUserModelID — ทำให้ taskbar แสดงไอคอนโปรแกรมแทนไอคอน Python
APP_USER_MODEL_ID = "Keawgood.Mynovel.Desktop"

__version__ = "2.0.2"

# ── ช่องทางอัปเดต ──────────────────────────────────────────────────────────────
# ⚠️ repo ต้องเป็น Public (เพื่อนดาวน์โหลดได้โดยไม่ต้องล็อกอิน)
GITHUB_REPO = "Keawgoodx/Keawgood-Mynovel"

# ไฟล์ zip ที่แนบใน Release (ข้างในคือโฟลเดอร์ Keawgood_Mynovel/ ที่มี Keawgood_Mynovel.exe)
RELEASE_ASSET_NAME = f"{APP_NAME}-windows.zip"

# โปรแกรมของเพื่อนอ่านไฟล์นี้ทุกครั้งที่เปิด
# "releases/latest/download/..." = GitHub พาไปยังไฟล์ใน Release ล่าสุดให้อัตโนมัติ
UPDATE_MANIFEST_URL = f"https://github.com/{GITHUB_REPO}/releases/latest/download/version.json"
