"""
release.py — Build Keawgood_Mynovel.exe แล้วอัปโหลดขึ้น GitHub ให้อัตโนมัติ

ใช้งาน (ปกติแค่ดับเบิลคลิก build_and_release.bat):
    python release.py                 build อย่างเดียว (dist/ + zip + version.json) ไม่อัปโหลด
    python release.py --publish       build → commit + push โค้ด → สร้าง GitHub Release + แนบไฟล์
    python release.py --publish --mandatory          บังคับทุกเครื่องต้องอัปเดต
    python release.py --publish --min-version 2.0.0  เครื่องที่เก่ากว่านี้ต้องอัปเดต
    python release.py --publish --skip-build         ใช้ไฟล์ใน dist/ ที่ build ไว้แล้ว
    python release.py --publish --no-git             ไม่ commit/push โค้ด (สร้าง Release อย่างเดียว)

ต้องมีสิทธิ์เขียน GitHub อย่างใดอย่างหนึ่ง:
    - ติดตั้ง GitHub CLI แล้ว `gh auth login`  หรือ
    - ตั้งตัวแปร GITHUB_TOKEN / GH_TOKEN  หรือ
    - สร้างไฟล์ github_token.txt (มีแต่ token บรรทัดเดียว — ไฟล์นี้ไม่ถูกอัปขึ้น GitHub)
"""
import argparse
import hashlib
import io
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")  # กัน git ค้างรอพิมพ์รหัสผ่านในหน้าจอดำ

V = runpy.run_path(str(ROOT / "version.py"))
APP_NAME = V["APP_NAME"]
APP_DISPLAY_NAME = V["APP_DISPLAY_NAME"]
VERSION = V["__version__"]
REPO = V["GITHUB_REPO"]
ASSET_NAME = V["RELEASE_ASSET_NAME"]
TAG = f"v{VERSION}"
MAIN_SCRIPT = ROOT / f"{APP_NAME}.py"
DIST = ROOT / "dist"
ICON = ROOT / "assets" / "icon.ico"
TOKEN_FILE = ROOT / "github_token.txt"

# ไฟล์ส่วนตัวที่ห้ามขึ้น GitHub เด็ดขาด
FORBIDDEN = [
    re.compile(r"(^|/)automation_profile/"),
    re.compile(r"(^|/)config(_v1_backup)?\.json$"),
    re.compile(r"(^|/)github_token\.txt$"),
    re.compile(r"(^|/)logs/"),
    re.compile(r"(^|/)\.venv/"),
]


# ─────────────────────────────────────────────────────────────── helpers
def step(text):
    print(f"\n━━ {text}", flush=True)


def info(text):
    print(f"   {text}", flush=True)


def fail(text):
    print(f"\n✗ {text}", flush=True)
    sys.exit(1)


def run(cmd, check=True, capture=False, redact=None):
    shown = " ".join(cmd)
    if cmd and cmd[0] == "git":
        # ไดรฟ์ภายนอก/ไดรฟ์ที่เจ้าของไฟล์ต่างกัน ทำให้ git ปฏิเสธ ("dubious ownership") → อนุญาตโฟลเดอร์นี้
        cmd = ["git", "-c", f"safe.directory={ROOT.as_posix()}", "-c", "safe.directory=*"] + list(cmd[1:])
    if redact:
        shown = shown.replace(redact, "***")
    info(f"$ {shown}")
    result = subprocess.run(cmd, cwd=ROOT, text=True, encoding="utf-8", errors="replace",
                            capture_output=capture)
    if check and result.returncode != 0:
        output = ((result.stdout or "") + (result.stderr or "")) if capture else ""
        if redact:
            output = output.replace(redact, "***")
        fail(f"คำสั่งล้มเหลว ({result.returncode}): {shown}\n{output}")
    return result


def has_git():
    return shutil.which("git") is not None


def release_notes_for(version):
    path = ROOT / "release_notes.md"
    if not path.exists():
        return "", ""
    text = io.open(path, encoding="utf-8").read()
    pattern = r"(?ms)^#{2,3} [^\n]*?v?" + re.escape(version) + r"\b[^\n]*\n(.*?)(?=^#{2,3} [^\n]*v?\d+\.\d+|\Z)"
    match = re.search(pattern, text)
    return (match.group(1).strip() if match else ""), text


# ─────────────────────────────────────────────────────────────── GitHub API
def get_token():
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(key):
            return os.environ[key].strip()
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token
    if shutil.which("gh"):
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return ""


def api(method, url, token, data=None, content_type="application/json", raw=None):
    if not url.startswith("http"):
        url = f"https://api.github.com{url}"
    body = raw if raw is not None else (json.dumps(data).encode("utf-8") if data is not None else None)
    request = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"{APP_NAME}-release",
        **({"Content-Type": content_type} if body is not None else {}),
    })
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            text = response.read().decode("utf-8")
            return response.status, (json.loads(text) if text else {})
    except urllib.error.HTTPError as error:
        text = error.read().decode("utf-8", errors="replace")
        try:
            return error.code, json.loads(text)
        except Exception:
            return error.code, {"message": text}


# ─────────────────────────────────────────────────────────────── build
def build():
    step(f"Build {APP_NAME}.exe v{VERSION}")
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        run([sys.executable, "-m", "pip", "install", "pyinstaller"])
    for folder in ("build", "dist"):
        shutil.rmtree(ROOT / folder, ignore_errors=True)
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", APP_NAME,
        "--add-data", f"assets{os.pathsep}assets",
        "--collect-all", "selenium",
        str(MAIN_SCRIPT),
    ]
    if ICON.exists():
        cmd[cmd.index("--name"):cmd.index("--name")] = ["--icon", str(ICON)]
    run(cmd)
    exe = DIST / APP_NAME / (f"{APP_NAME}.exe" if os.name == "nt" else APP_NAME)
    if not exe.exists():
        fail(f"build เสร็จแต่ไม่พบ {exe}")
    info(f"✓ {exe}")


def package(notes, notes_all, mandatory, min_version):
    step("สร้างไฟล์ zip + version.json")
    app_dir = DIST / APP_NAME
    if not app_dir.exists():
        fail(f"ไม่พบ {app_dir} — รันโดยไม่ใส่ --skip-build ก่อน")
    zip_path = DIST / ASSET_NAME
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", root_dir=DIST, base_dir=APP_NAME)
    digest = hashlib.sha256()
    with open(zip_path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    manifest = {
        "app": APP_NAME,
        "version": VERSION,
        "tag": TAG,
        "name": f"{APP_DISPLAY_NAME} {TAG}",
        "notes": notes,
        "notes_all": notes_all,
        "asset_name": ASSET_NAME,
        "asset_url": f"https://github.com/{REPO}/releases/download/{TAG}/{ASSET_NAME}",
        "release_url": f"https://github.com/{REPO}/releases/tag/{TAG}",
        "sha256": digest.hexdigest(),
        "size": zip_path.stat().st_size,
        "mandatory": bool(mandatory),
        "min_version": min_version or "",
        "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    manifest_path = DIST / "version.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    info(f"✓ {zip_path.name}  ({manifest['size'] / 1048576:.1f} MB)")
    info(f"✓ {manifest_path.name}  (sha256 {manifest['sha256'][:12]}…)")
    return zip_path, manifest_path


# ─────────────────────────────────────────────────────────────── git
def git_commit_and_push(token):
    step("Commit + push โค้ดขึ้น GitHub")
    if not has_git():
        info("⚠ ไม่พบ git ในเครื่อง — ข้ามขั้นตอนนี้ (ติดตั้งได้ที่ https://git-scm.com)")
        return False
    remote_url = f"https://github.com/{REPO}.git"
    # จำโฟลเดอร์นี้ไว้เป็น safe.directory ถาวร (ให้ใช้ git เองได้ด้วยโดยไม่ติด dubious ownership)
    existing_safe = subprocess.run(["git", "config", "--global", "--get-all", "safe.directory"],
                                   capture_output=True, text=True).stdout.split()
    if ROOT.as_posix() not in existing_safe and "*" not in existing_safe:
        subprocess.run(["git", "config", "--global", "--add", "safe.directory", ROOT.as_posix()])
    if not (ROOT / ".git").exists():
        run(["git", "init", "-b", "main"])
    remotes = run(["git", "remote"], capture=True).stdout.split()
    if "origin" not in remotes:
        run(["git", "remote", "add", "origin", remote_url])

    # repo บน GitHub มี commit อยู่แล้ว (เช่น README ที่สร้างตอนเปิด repo) → ต่อประวัติจากของบน GitHub
    run(["git", "fetch", "origin"], check=False, capture=True)
    remote_has_main = run(["git", "rev-parse", "--verify", "-q", "origin/main"], check=False, capture=True).returncode == 0
    local_has_commit = run(["git", "rev-parse", "--verify", "-q", "HEAD"], check=False, capture=True).returncode == 0
    if remote_has_main and not local_has_commit:
        info("ต่อจากประวัติบน GitHub (origin/main) — ไฟล์ในเครื่องจะทับของเดิมบน GitHub")
        run(["git", "reset", "-q", "origin/main"])
    if not run(["git", "config", "user.name"], check=False, capture=True).stdout.strip():
        run(["git", "config", "user.name", REPO.split("/")[0]])
    if not run(["git", "config", "user.email"], check=False, capture=True).stdout.strip():
        run(["git", "config", "user.email", f"{REPO.split('/')[0]}@users.noreply.github.com"])

    run(["git", "add", "-A"])
    staged = run(["git", "diff", "--cached", "--name-only"], capture=True).stdout.splitlines()
    bad = [p for p in staged if any(rx.search(p.replace("\\", "/")) for rx in FORBIDDEN)]
    if bad:
        run(["git", "reset", "-q"], check=False)
        fail("พบไฟล์ส่วนตัวกำลังจะขึ้น GitHub (ยกเลิกให้แล้ว):\n   " + "\n   ".join(bad)
             + "\n   ตรวจ .gitignore ก่อนรันใหม่")
    if staged:
        run(["git", "commit", "-q", "-m", f"Release {TAG}"])
    else:
        info("ไม่มีไฟล์เปลี่ยน — ไม่ต้อง commit")
    if not run(["git", "tag", "-l", TAG], capture=True).stdout.strip():
        run(["git", "tag", "-a", TAG, "-m", f"{APP_DISPLAY_NAME} {TAG}"])

    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture=True).stdout.strip() or "main"
    last_output = ""
    for attempt in ("normal", "token", "rebase-normal", "rebase-token"):
        if attempt == "rebase-normal":
            info("push ไม่ผ่าน — ลองดึงของบน GitHub มารวมก่อน (pull --rebase)")
            run(["git", "pull", "--rebase", "origin", "main"], check=False, capture=True)
            attempt = "normal"
        elif attempt == "rebase-token":
            attempt = "token"
        if attempt == "normal":
            targets = [["git", "push", "-u", "origin", f"{branch}:main"], ["git", "push", "origin", TAG]]
        else:
            url = f"https://x-access-token:{token}@github.com/{REPO}.git"
            targets = [["git", "push", url, f"{branch}:main"], ["git", "push", url, "--force", TAG]]
        pushed = True
        for cmd in targets:
            result = run(cmd, check=False, capture=True, redact=token)
            if result.returncode != 0:
                last_output = ((result.stdout or "") + (result.stderr or "")).replace(token, "***").strip()
                pushed = False
                break
        if pushed:
            info("✓ push โค้ด + tag แล้ว")
            return True
    fail("push ขึ้น GitHub ไม่สำเร็จ:\n   " + (last_output[-1200:] or "(ไม่มีข้อความจาก git)")
         + "\n   ส่งข้อความนี้ให้ Claude ตรวจได้เลย")


# ─────────────────────────────────────────────────────────────── publish
def publish(zip_path, manifest_path, notes, use_git):
    token = get_token()
    if not token:
        fail(
            "ยังไม่มีสิทธิ์อัปโหลดขึ้น GitHub — เลือกวิธีใดวิธีหนึ่ง:\n"
            "   1) ติดตั้ง GitHub CLI (https://cli.github.com) แล้วรัน  gh auth login\n"
            "   2) สร้าง token ที่ https://github.com/settings/tokens?type=beta\n"
            f"      (Repository access: {REPO} · Permissions: Contents = Read and write)\n"
            f"      แล้ววาง token ลงไฟล์ {TOKEN_FILE.name} ในโฟลเดอร์นี้ (ไฟล์นี้ไม่ถูกอัปขึ้น GitHub)"
        )

    step(f"ตรวจ repo {REPO}")
    status, data = api("GET", f"/repos/{REPO}", token)
    if status == 404:
        info("ยังไม่มี repo — กำลังสร้างแบบ Public ให้")
        status, data = api("POST", "/user/repos", token, {
            "name": REPO.split("/")[1], "private": False,
            "description": f"{APP_DISPLAY_NAME} — ตั้งราคา/ตั้งเวลาเผยแพร่ตอนนิยาย MyNovel อัตโนมัติ",
        })
        if status >= 300:
            fail(f"สร้าง repo ไม่ได้ ({status}: {data.get('message')}) — สร้างเองที่ https://github.com/new (ตั้งเป็น Public)")
    elif status >= 300:
        fail(f"เข้าถึง repo ไม่ได้ ({status}: {data.get('message')}) — ตรวจสิทธิ์ของ token")
    elif data.get("private"):
        info("⚠ repo เป็น Private — เครื่องเพื่อนจะเช็ก/ดาวน์โหลดอัปเดตไม่ได้ ควรเปลี่ยนเป็น Public")

    status, existing = api("GET", f"/repos/{REPO}/releases/tags/{TAG}", token)
    if status == 200:
        fail(f"มี Release {TAG} อยู่แล้ว — เพิ่ม __version__ ใน version.py (และเขียน release_notes.md) ก่อนรันใหม่")

    if use_git:
        git_commit_and_push(token)

    step(f"สร้าง GitHub Release {TAG}")
    body = (notes or "ดูรายละเอียดใน release_notes.md") + (
        "\n\n---\n"
        f"**ติดตั้งครั้งแรก:** ดาวน์โหลด `{ASSET_NAME}` → แตกไฟล์ → เปิด `{APP_NAME}.exe` (ต้องมี Google Chrome)\n\n"
        "**มีโปรแกรมอยู่แล้ว:** เปิดโปรแกรม แล้วกด **อัปเดตเลย** ที่แถบแจ้งเตือนด้านบน\n"
    )
    payload = {"tag_name": TAG, "name": f"{APP_DISPLAY_NAME} {TAG}", "body": body,
               "draft": False, "prerelease": False, "make_latest": "true"}
    if not use_git:
        payload["target_commitish"] = "main"
    status, release = api("POST", f"/repos/{REPO}/releases", token, payload)
    if status >= 300:
        fail(f"สร้าง Release ไม่สำเร็จ ({status}: {release.get('message')} {release.get('errors', '')})\n"
             "   ถ้า repo ยังว่าง ให้รันแบบไม่ใส่ --no-git เพื่อ push โค้ดก่อน")

    upload_base = release["upload_url"].split("{")[0]
    for path, ctype in ((zip_path, "application/zip"), (manifest_path, "application/json")):
        info(f"อัปโหลด {path.name} …")
        status, asset = api("POST", f"{upload_base}?name={path.name}", token,
                            raw=path.read_bytes(), content_type=ctype)
        if status >= 300:
            fail(f"อัปโหลด {path.name} ไม่สำเร็จ ({status}: {asset.get('message')}) — "
                 f"ลบ Release {TAG} บน GitHub แล้วรันใหม่ด้วย --skip-build")
    step("เสร็จแล้ว 🎉")
    info(f"Release: {release.get('html_url')}")
    info("เครื่องเพื่อนที่เปิดโปรแกรมจะขึ้นแจ้งเตือน 'มีเวอร์ชันใหม่' ภายในไม่กี่นาที")


def main():
    parser = argparse.ArgumentParser(description="Build & release Keawgood_Mynovel")
    parser.add_argument("--publish", action="store_true", help="อัปโหลดขึ้น GitHub")
    parser.add_argument("--mandatory", action="store_true", help="บังคับทุกเครื่องต้องอัปเดต")
    parser.add_argument("--min-version", default="", help="เวอร์ชันต่ำสุดที่ยังใช้ได้")
    parser.add_argument("--skip-build", action="store_true", help="ไม่ build ใหม่ ใช้ dist/ เดิม")
    parser.add_argument("--no-git", action="store_true", help="ไม่ commit/push โค้ด")
    args = parser.parse_args()

    print(f"{APP_DISPLAY_NAME}  {TAG}  →  github.com/{REPO}")
    notes, notes_all = release_notes_for(VERSION)
    if not notes:
        msg = f"release_notes.md ยังไม่มีหัวข้อของ v{VERSION} (เช่น '### ✨ มีอะไรใหม่ใน v{VERSION}')"
        if args.publish:
            fail(msg + " — เขียนสิ่งที่เปลี่ยนก่อน เพื่อนจะได้เห็นว่าอัปเดตอะไร")
        info("⚠ " + msg)

    if args.publish:
        token = get_token()
        if token:
            status, existing = api("GET", f"/repos/{REPO}/releases/tags/{TAG}", token)
            if status == 200:
                fail(f"มี Release {TAG} อยู่แล้ว — เพิ่ม __version__ ใน version.py ก่อน (ยังไม่ได้ build อะไร)")

    if not args.skip_build:
        build()
    zip_path, manifest_path = package(notes, notes_all, args.mandatory, args.min_version)
    if args.publish:
        publish(zip_path, manifest_path, notes, use_git=not args.no_git)
    else:
        step("Build เสร็จ (ยังไม่ได้อัปโหลด)")
        info(f"ลองเปิด dist\\{APP_NAME}\\{APP_NAME}.exe ก่อน แล้วค่อยรัน build_and_release.bat")


if __name__ == "__main__":
    main()
