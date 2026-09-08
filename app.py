# -*- coding: utf-8 -*-
"""
TASHIL DOCUMENT HUB — WEB EDITION
Copyright ILINE TECH 2026 BY FERAK ALADDIN

A single Python backend that serves a normal responsive web page —
identical on Windows and on Android (Termux). No custom window chrome,
no manual widget positioning: the browser handles all layout.

v2.3.0 — Multi-tenant architecture: this device can now hold several
institution profiles side by side, each with its own isolated database
and archive folders, unlocked by a per-profile PIN. See the "Session /
multi-tenant" section below.

⚠️ Security honesty note: the PIN is a lock-screen deterrent against
casual/physical snooping on a shared device (hashed with werkzeug's
salted hash, never stored in plaintext) — it is NOT full-disk or
per-file encryption. Anyone with direct filesystem access to
~/TASHIL_DATA/profiles/<key>/ can still read the archived documents and
the SQLite database directly, PIN or not. Treat it as a screen lock, not
as data-at-rest encryption.

⚠️ Concurrency note: "active profile" is tracked as a single in-memory
value on the server process. This app is built for one person on one
device switching between institution hats — not for multiple people
using the same running server concurrently under different profiles.

Run directly:
    python app.py
Then open http://127.0.0.1:5000 in any browser (desktop or phone on the
same network, using the LAN IP shown at startup).
"""

import os
import re
import json
import socket
import sqlite3
import shutil
import hashlib
import hmac
import base64
import uuid
from io import BytesIO
from datetime import datetime

from flask import (Flask, request, jsonify, send_from_directory,
                    send_file, render_template, abort)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

try:
    import qrcode
    _QRCODE_AVAILABLE = True
except ImportError:
    _QRCODE_AVAILABLE = False

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes as _crypto_hashes
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False

try:
    import certifi
    _CERTIFI_AVAILABLE = True
except ImportError:
    _CERTIFI_AVAILABLE = False

try:
    from pyzbar.pyzbar import decode as _zbar_decode
    _QR_DECODE_AVAILABLE = True
    _QR_DECODE_IMPORT_ERROR = None
except ImportError as _qr_import_exc:
    _QR_DECODE_AVAILABLE = False
    # Captured deliberately (unlike a bare False flag) — a previous choice
    # here (opencv-python-headless) failed to import in a real built exe
    # with no visible reason beyond "not available on this build". This
    # ensures that if the replacement ever fails too, the actual cause is
    # visible instead of another silent dead end.
    _QR_DECODE_IMPORT_ERROR = str(_qr_import_exc)

# --------------------------------------------------------------------------- #
# Paths — cross-platform, no admin rights required (works on Windows AND
# Termux/Android identically, unlike the old C:\TASHIL\... hardcoded paths).
# --------------------------------------------------------------------------- #
BASE_DIR = os.path.join(os.path.expanduser("~"), "TASHIL_DATA")
PROFILES_DIR = os.path.join(BASE_DIR, "profiles")
REGISTRY_DB_PATH = os.path.join(BASE_DIR, "registry.db")

# Legacy v2.x single-tenant paths (pre-v2.3.0) — used only for one-time
# migration into the new per-profile structure, never written to again.
_LEGACY_DB_PATH = os.path.join(BASE_DIR, "tashil.db")
_LEGACY_ARCHIVE_SORTANT = os.path.join(BASE_DIR, "archives", "Courrier_Sortant")
_LEGACY_ARCHIVE_ENTRANT = os.path.join(BASE_DIR, "archives", "Courrier_Entrant")

os.makedirs(PROFILES_DIR, exist_ok=True)

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
APP_VERSION = "2.8.0"
GITHUB_REPO = "Aladdinweb/TASHIL-ES"  # used by the in-app OTA update checker

app = Flask(__name__,
            template_folder=os.path.join(APP_ROOT, "templates"),
            static_folder=os.path.join(APP_ROOT, "static"))
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64MB upload cap


# --------------------------------------------------------------------------- #
# Global JSON error handling. Without this, any unhandled exception or
# oversized upload on an /api/ route falls through to Flask/Werkzeug's
# default HTML error page — which is exactly what broke sending from the
# desktop PC: the frontend calls res.json() on that HTML page and gets
# "Unexpected token '<', <!doctype ..." instead of a real error message.
# Every /api/ route now always returns JSON, no matter what fails inside
# it; non-API routes (the page itself, static files) are unaffected.
# --------------------------------------------------------------------------- #
@app.errorhandler(413)
def handle_payload_too_large(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Fichier trop volumineux (limite : 64 Mo)."}), 413
    return e


@app.errorhandler(404)
def handle_not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Route introuvable."}), 404
    return e


@app.errorhandler(Exception)
def handle_unexpected_error(e):
    if request.path.startswith("/api/"):
        # Log the real exception server-side for diagnosis, but never leak
        # a raw traceback to the frontend — just a clear, safe JSON error.
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Erreur interne du serveur : {e}"}), 500
    raise e

INSTITUTION_TYPES = ["EPSP", "EPH", "CHU", "EHU", "Polyclinique"]
_TYPE_CODES = {"EPSP": "EP", "EPH": "EH", "CHU": "CU", "EHU": "HU", "Polyclinique": "PC"}
WILAYAS = [
    (1, "Adrar"), (2, "Chlef"), (3, "Laghouat"), (4, "Oum El Bouaghi"),
    (5, "Batna"), (6, "Béjaïa"), (7, "Biskra"), (8, "Béchar"),
    (9, "Blida"), (10, "Bouira"), (11, "Tamanrasset"), (12, "Tébessa"),
    (13, "Tlemcen"), (14, "Tiaret"), (15, "Tizi Ouzou"), (16, "Alger"),
    (17, "Djelfa"), (18, "Jijel"), (19, "Sétif"), (20, "Saïda"),
    (21, "Skikda"), (22, "Sidi Bel Abbès"), (23, "Annaba"), (24, "Guelma"),
    (25, "Constantine"), (26, "Médéa"), (27, "Mostaganem"), (28, "M'Sila"),
    (29, "Mascara"), (30, "Ouargla"), (31, "Oran"), (32, "El Bayadh"),
    (33, "Illizi"), (34, "Bordj Bou Arreridj"), (35, "Boumerdès"),
    (36, "El Tarf"), (37, "Tindouf"), (38, "Tissemsilt"), (39, "El Oued"),
    (40, "Khenchela"), (41, "Souk Ahras"), (42, "Tipaza"), (43, "Mila"),
    (44, "Aïn Defla"), (45, "Naâma"), (46, "Aïn Témouchent"), (47, "Ghardaïa"),
    (48, "Relizane"), (49, "Timimoun"), (50, "Bordj Badji Mokhtar"),
    (51, "Ouled Djellal"), (52, "Béni Abbès"), (53, "In Salah"),
    (54, "In Guezzam"), (55, "Touggourt"), (56, "Djanet"),
    (57, "El M'Ghair"), (58, "El Meniaa"),
]

# --------------------------------------------------------------------------- #
# Institution directory (autocomplete source for "Institution destinataire"
# when sending a message — unaffected by the multi-tenant change below).
#
# ⚠️ STARTER LIST, NOT AN OFFICIAL REGISTRY — see onboarding directory notes
# further down for the same caveat, which applies here too.
# --------------------------------------------------------------------------- #
_REAL_ESSENIA_POLYCLINICS = [
    "POLYCLINIQUE ES SENIA",
    "POLYCLINIQUE AADL AIN BEIDA MABROUK LOUCIF",
    "POLYCLINIQUE AIN BEIDA 1",
    "POLYCLINIQUE AIN BEIDA 2",
    "POLYCLINIQUE SIDI MAAROUF",
    "POLYCLINIQUE SIDI CHAHMI",
    "POLYCLINIQUE EL KERMA",
]
_CHU_WILAYAS = {"Alger", "Oran", "Constantine", "Annaba", "Tlemcen", "Sétif",
                "Batna", "Blida", "Béjaïa", "Sidi Bel Abbès", "Tizi Ouzou"}

def _build_institutions_directory():
    entries = list(_REAL_ESSENIA_POLYCLINICS)
    for _, wilaya_name in WILAYAS:
        entries.append(f"EPSP {wilaya_name}")
        entries.append(f"EPH {wilaya_name}")
        entries.append(f"Polyclinique {wilaya_name}")
        if wilaya_name in _CHU_WILAYAS:
            entries.append(f"CHU {wilaya_name}")
    return sorted(set(entries))

INSTITUTIONS_DIRECTORY = _build_institutions_directory()

# --------------------------------------------------------------------------- #
# Onboarding institution dropdown (feature 1) — deliberately smaller and
# more curated than the messaging autocomplete above: this is what fills
# the "Nom de l'établissement" <select> during onboarding.
#
# ⚠️ Only Oran (wilaya 31) has real, user-confirmed entries below. Every
# other wilaya falls back to a single generic "<Type> <Wilaya>" option.
# The onboarding form always keeps an "Autre (saisir manuellement)" choice
# too, so no one is ever blocked by an incomplete list.
# --------------------------------------------------------------------------- #
_ONBOARDING_KNOWN = {
    (31, "EPSP"): list(_REAL_ESSENIA_POLYCLINICS),
    (31, "Polyclinique"): list(_REAL_ESSENIA_POLYCLINICS),
    (31, "EPH"): ["EPH AIN TURCK"],
    (31, "CHU"): ["CHU ORAN"],
    (31, "EHU"): ["EHU ORAN"],
}

def get_onboarding_institutions(wilaya_code: int, institution_type: str):
    known = _ONBOARDING_KNOWN.get((wilaya_code, institution_type))
    if known:
        return list(known)
    wilaya_name = dict(WILAYAS).get(wilaya_code)
    if wilaya_name is None:
        return []
    return [f"{institution_type} {wilaya_name}"]


# --------------------------------------------------------------------------- #
# Registry DB — the master list of institution profiles on this device.
# Lives OUTSIDE any profile folder, at ~/TASHIL_DATA/registry.db.
# --------------------------------------------------------------------------- #
def get_registry_db():
    conn = sqlite3.connect(REGISTRY_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_registry_db():
    conn = get_registry_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            institution_key TEXT PRIMARY KEY,
            wilaya_code INTEGER NOT NULL,
            wilaya_name TEXT NOT NULL,
            institution_type TEXT NOT NULL,
            institution_name TEXT NOT NULL,
            serial_key TEXT NOT NULL,
            pin_hash TEXT,
            theme TEXT DEFAULT 'dark',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bridge_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            github_owner TEXT,
            github_repo TEXT,
            github_token TEXT,
            enabled INTEGER DEFAULT 0,
            updated_at TEXT
        )
    """)
    # Schema migration for pre-v2.7.0 databases: CREATE TABLE IF NOT EXISTS
    # above won't add a new column to an already-existing table, so this
    # runs an explicit, idempotent, backward-compatible ALTER. Existing
    # profiles get encryption_salt = NULL, which the app treats as "legacy,
    # unencrypted" — they keep working exactly as before, in plaintext.
    # Only profiles created from this version onward opt into encryption.
    existing_cols = [r[1] for r in conn.execute("PRAGMA table_info(profiles)").fetchall()]
    if "encryption_salt" not in existing_cols:
        conn.execute("ALTER TABLE profiles ADD COLUMN encryption_salt TEXT")
    conn.commit()
    conn.close()


init_registry_db()


def sanitize(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return name.strip() or "document"


def make_institution_key(wilaya_code: int, institution_type: str, institution_name: str) -> str:
    type_code = _TYPE_CODES.get(institution_type, "XX")
    slug = re.sub(r'[^A-Za-z0-9]+', '_', institution_name.strip().upper()).strip('_')
    base_key = f"{wilaya_code:02d}_{type_code}_{slug}"[:80]

    conn = get_registry_db()
    key = base_key
    suffix = 2
    while conn.execute("SELECT 1 FROM profiles WHERE institution_key = ?", (key,)).fetchone():
        key = f"{base_key}_{suffix}"
        suffix += 1
    conn.close()
    return key


def generate_serial_key(wilaya_code, institution_type, institution_name) -> str:
    secret = b"ILINE-TECH-2026-FERAK-ALADDIN-TASHIL-DOCUMENT-HUB"
    type_code = _TYPE_CODES.get(institution_type, "XX")
    salt = datetime.now().strftime("%Y%m%d")
    payload = f"{wilaya_code:02d}|{type_code}|{institution_name.upper()}|{salt}"
    digest = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).digest()
    body_hex = digest.hex()[:4].upper()
    checksum = base64.b32encode(digest[:3]).decode("utf-8")[:4]
    return f"TSH-{wilaya_code:02d}-{type_code}-{body_hex}-{checksum}"


def list_profiles():
    conn = get_registry_db()
    rows = conn.execute("SELECT * FROM profiles ORDER BY institution_name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_profile_row(institution_key: str):
    conn = get_registry_db()
    row = conn.execute("SELECT * FROM profiles WHERE institution_key = ?", (institution_key,)).fetchone()
    conn.close()
    return dict(row) if row else None


def profile_public_dict(row: dict) -> dict:
    """Strip pin_hash before ever sending a profile row to the frontend."""
    return {k: v for k, v in row.items() if k != "pin_hash"}


def profile_paths(institution_key: str):
    folder = os.path.join(PROFILES_DIR, institution_key)
    return {
        "folder": folder,
        "db": os.path.join(folder, "tashil.db"),
        "sortant": os.path.join(folder, "archives", "Courrier_Sortant"),
        "entrant": os.path.join(folder, "archives", "Courrier_Entrant"),
    }


def get_profile_db(institution_key: str):
    paths = profile_paths(institution_key)
    os.makedirs(paths["sortant"], exist_ok=True)
    os.makedirs(paths["entrant"], exist_ok=True)
    conn = sqlite3.connect(paths["db"])
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction TEXT NOT NULL,
            tracking_number TEXT UNIQUE NOT NULL,
            sender_institution TEXT,
            recipient_institution TEXT,
            subject TEXT,
            body TEXT,
            file_path TEXT,
            file_original_name TEXT,
            status TEXT DEFAULT 'envoye',
            created_at TEXT NOT NULL
        )
    """)
    # Idempotent migration: tracks HOW a message reached this database
    # ('local', 'bridge', or NULL for anything predating this column) —
    # needed so accusé-de-réception can route a receipt back to the right
    # place (see api_update_message_status).
    existing_cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
    if "delivery_method" not in existing_cols:
        conn.execute("ALTER TABLE messages ADD COLUMN delivery_method TEXT")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bridge_pending_cleanup (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_path TEXT NOT NULL,
            sha TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def next_tracking_number(conn, direction: str, institution_key: str) -> str:
    """
    Tracking numbers now embed a short institution code (derived from the
    wilaya+type prefix of institution_key) so that a number generated by
    one institution's database doesn't collide with an unrelated message
    already present in another institution's database when a message is
    delivered locally (see find_local_profile_by_name / api_send_message).
    """
    prefix = "S" if direction == "sortant" else "E"
    year = datetime.now().year
    count = conn.execute(
        "SELECT COUNT(*) as c FROM messages WHERE direction = ?", (direction,)
    ).fetchone()["c"]
    short = "".join(institution_key.split("_")[:2]) or "XX"
    return f"TASHIL-{short}-{prefix}-{year}-{count + 1:06d}"


def find_local_profile_by_recipient(recipient_text: str, exclude_key: str = None):
    """
    Looks for another profile registered on THIS device matching the given
    recipient string — either an exact institution ID/key (e.g.
    '31_EP_EPSP_ES_SENIA', shown to each institution as its "ID de routage"
    in Paramètres) or a plain institution name (case/whitespace-insensitive).
    Matching by ID first lets two institutions communicate unambiguously
    even if names collide; name matching remains the friendly default.
    Returns None if no match — this does NOT reach across a network to a
    different computer; see the honesty note in api_send_message().
    """
    conn = get_registry_db()
    rows = conn.execute("SELECT * FROM profiles").fetchall()
    conn.close()
    target_key = recipient_text.strip()
    target_name = recipient_text.strip().casefold()
    for row in rows:
        if row["institution_key"] == exclude_key:
            continue
        if row["institution_key"] == target_key:
            return dict(row)
        if row["institution_name"].strip().casefold() == target_name:
            return dict(row)
    return None


# --------------------------------------------------------------------------- #
# Cloud Bridge — GitHub-backed transport for institutions NOT on this same
# device. Uses only the Python standard library (urllib) rather than a
# GitHub SDK, matching this project's "fewer packaging-risk dependencies"
# lesson from the pywebview/PyInstaller issues earlier.
#
# ⚠️ Security model, stated plainly: the configured repo's PRIVACY setting
# and who has access to it ARE the entire protection here — documents are
# committed as plain content, not end-to-end encrypted. The app refuses to
# save a bridge configuration pointing at a public repository (checked
# live against the GitHub API before saving), but it cannot stop someone
# from making a private repo public later, or from over-sharing repo
# access. Treat the bridge token as a real credential.
# --------------------------------------------------------------------------- #
GITHUB_API_BASE = "https://api.github.com"


def _github_request(method: str, url_or_path: str, token: str, json_body: dict = None):
    """
    Minimal GitHub REST API client using urllib only. Accepts either a
    path (starting with '/') or a full URL (as returned in listing
    responses' 'url' field) — both are used by the polling logic below.
    Returns (status_code, parsed_json_or_empty_dict).

    Explicitly uses certifi's CA bundle for SSL verification rather than
    relying on urllib's default context. This is a real, known issue with
    PyInstaller-frozen Windows executables: the frozen exe often can't
    locate the OS certificate store the way a normal Python installation
    does, producing "SSL: CERTIFICATE_VERIFY_FAILED — unable to get local
    issuer certificate" even when the network connection itself is fine.
    Bundling and pointing at certifi's own cacert.pem sidesteps that
    entirely — confirmed as the cause via a real error report.
    """
    import urllib.request
    import urllib.error
    import ssl

    url = url_or_path if url_or_path.startswith("http") else f"{GITHUB_API_BASE}{url_or_path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "TASHIL-DOCUMENT-HUB",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = json.dumps(json_body).encode("utf-8") if json_body is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    ssl_context = ssl.create_default_context(cafile=certifi.where()) if _CERTIFI_AVAILABLE else None

    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl_context) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw.decode("utf-8")) if raw else {})
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8"))
        except Exception:
            payload = {}
        return e.code, payload
    except Exception as exc:
        return 0, {"message": str(exc)}


def get_bridge_config():
    conn = get_registry_db()
    row = conn.execute("SELECT * FROM bridge_config WHERE id = 1").fetchone()
    conn.close()
    return dict(row) if row else None


def bridge_slug(institution_name: str) -> str:
    """
    Normalizes an institution name into a stable Cloud Bridge address.
    ⚠️ Name-only, no wilaya/type disambiguation — two different real
    institutions that happen to share an identical name would collide on
    the same bridge folder. Same limitation as local delivery matching
    (find_local_profile_by_name) for consistency; worth revisiting if the
    recipient picker ever becomes a structured Wilaya+Type+Name selection
    instead of free text.
    """
    return re.sub(r'[^A-Za-z0-9]+', '_', institution_name.strip().upper()).strip('_')[:80]


def push_to_bridge(cfg: dict, recipient_name: str, sender_name: str, subject: str,
                    body: str, tracking: str, file_bytes: bytes, original_filename: str) -> bool:
    owner, repo, token = cfg["github_owner"], cfg["github_repo"], cfg["github_token"]
    key = bridge_slug(recipient_name)

    file_ext = os.path.splitext(original_filename)[1]
    attachment_repo_path = f"bridge/{key}/{tracking}{file_ext}"
    meta_repo_path = f"bridge/{key}/{tracking}.json"

    meta = {
        "tracking_number": tracking,
        "sender_institution": sender_name,
        "recipient_institution": recipient_name,
        "subject": subject,
        "body": body,
        "file_original_name": original_filename,
        "attachment_path_in_repo": attachment_repo_path,
        "created_at": datetime.now().isoformat(),
    }

    # file_bytes are the ORIGINAL plaintext (see api_send_message) — never
    # the sender's own encrypted archive copy, which only the sender's key
    # could ever open. The Cloud Bridge itself provides no encryption of
    # its own (see the module-level security note above); the recipient
    # applies its own encryption independently when it later imports this.
    file_b64 = base64.b64encode(file_bytes).decode("utf-8")

    meta_b64 = base64.b64encode(
        json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("utf-8")

    status_meta, _ = _github_request(
        "PUT", f"/repos/{owner}/{repo}/contents/{meta_repo_path}", token,
        {"message": f"TASHIL bridge: {tracking} (metadata)", "content": meta_b64}
    )
    status_file, _ = _github_request(
        "PUT", f"/repos/{owner}/{repo}/contents/{attachment_repo_path}", token,
        {"message": f"TASHIL bridge: {tracking} (attachment)", "content": file_b64}
    )
    return status_meta in (200, 201) and status_file in (200, 201)


def get_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# --------------------------------------------------------------------------- #
# One-time legacy migration (pre-v2.3.0 single-tenant data).
#
# If an old flat ~/TASHIL_DATA/tashil.db exists from before the multi-tenant
# change AND no profiles have been registered yet, move it (with its
# archives) into a new profile folder rather than silently orphaning it.
# The migrated profile has no PIN yet — the frontend detects this (pin_set:
# false) and prompts the user to CREATE a PIN on first unlock instead of
# asking them to enter one that was never set.
# --------------------------------------------------------------------------- #
def migrate_legacy_single_tenant_if_needed():
    if not os.path.exists(_LEGACY_DB_PATH):
        return
    if list_profiles():
        return  # already have at least one profile — never auto-migrate again

    try:
        legacy_conn = sqlite3.connect(_LEGACY_DB_PATH)
        legacy_conn.row_factory = sqlite3.Row
        legacy_profile = legacy_conn.execute(
            "SELECT * FROM profile WHERE id = 1"
        ).fetchone()
    except sqlite3.Error:
        legacy_conn.close()
        return

    if legacy_profile is None:
        legacy_conn.close()
        return

    wilaya_code = legacy_profile["wilaya_code"]
    wilaya_name = legacy_profile["wilaya_name"]
    institution_type = legacy_profile["institution_type"]
    institution_name = legacy_profile["institution_name"]
    serial_key = legacy_profile["serial_key"]
    theme = legacy_profile["theme"] if "theme" in legacy_profile.keys() else "dark"

    key = make_institution_key(wilaya_code, institution_type, institution_name)
    paths = profile_paths(key)
    os.makedirs(paths["folder"], exist_ok=True)
    os.makedirs(os.path.join(paths["folder"], "archives"), exist_ok=True)

    # Move (not copy) the legacy db and archive folders into the new location
    shutil.move(_LEGACY_DB_PATH, paths["db"])
    if os.path.isdir(_LEGACY_ARCHIVE_SORTANT):
        shutil.move(_LEGACY_ARCHIVE_SORTANT, paths["sortant"])
    if os.path.isdir(_LEGACY_ARCHIVE_ENTRANT):
        shutil.move(_LEGACY_ARCHIVE_ENTRANT, paths["entrant"])

    registry_conn = get_registry_db()
    registry_conn.execute("""
        INSERT INTO profiles (institution_key, wilaya_code, wilaya_name,
                               institution_type, institution_name, serial_key,
                               pin_hash, theme, created_at)
        VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
    """, (key, wilaya_code, wilaya_name, institution_type, institution_name,
          serial_key, theme, datetime.now().isoformat()))
    registry_conn.commit()
    registry_conn.close()
    legacy_conn.close()

    print(f"[migration] Legacy profile '{institution_name}' migrated to profiles/{key}/ "
          f"— a PIN must be set on first unlock.")


migrate_legacy_single_tenant_if_needed()


# --------------------------------------------------------------------------- #
# Active session — single in-memory value (see concurrency note at top).
# --------------------------------------------------------------------------- #
_active_key = None
_active_fernet = None  # Fernet instance derived from the active profile's PIN, or None


def require_active_profile():
    """Returns the active profile's registry row, or None if locked."""
    if _active_key is None:
        return None
    return get_profile_row(_active_key)


def locked_response():
    return jsonify({"error": "Session verrouillée. Veuillez entrer votre code PIN.",
                     "locked": True}), 423


# --------------------------------------------------------------------------- #
# Encryption at rest (v2.7.0) — keyed to the profile's own PIN.
#
# ⚠️ Honesty note, stated plainly (also shown to the user in Paramètres):
# a 4-6 digit PIN has only 10,000–1,000,000 possible values. Even with a
# deliberately slow key-derivation function, this is brute-forceable
# offline by anyone who obtains the encrypted files directly, given
# enough time. This protects against the realistic everyday threat —
# a stolen or borrowed device being casually browsed without the PIN —
# not against a determined, resourced attacker with the encrypted blob
# and time to spend on it.
#
# ⚠️ Scope limitation, also stated plainly: encryption only applies to
# content THIS profile's own unlocked session writes — its own sent
# messages, and anything it receives via the Cloud Bridge while unlocked.
# Same-device LOCAL delivery (v2.4.0) writes directly into a recipient
# profile's storage while that profile is locked — we don't have their
# PIN at that moment, so that content is written in plaintext. This is a
# real, currently-unavoidable gap given the local-delivery design, not an
# oversight; see api_send_message for where this is handled.
#
# Only profiles created from v2.7.0 onward (encryption_salt is not NULL)
# participate at all — existing profiles keep working exactly as before.
# --------------------------------------------------------------------------- #
def generate_encryption_salt() -> str:
    return base64.b64encode(os.urandom(16)).decode("ascii")


def derive_fernet(pin: str, salt_b64: str):
    if not _CRYPTO_AVAILABLE:
        return None
    salt = base64.b64decode(salt_b64)
    kdf = PBKDF2HMAC(algorithm=_crypto_hashes.SHA256(), length=32, salt=salt, iterations=480000)
    derived = kdf.derive(pin.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(derived))


def set_active_session(institution_key: str, pin: str, profile_row: dict = None):
    """Activates a profile's session AND derives/caches its encryption key
    (if it has one) in the same place, so the two can never drift apart."""
    global _active_key, _active_fernet
    _active_key = institution_key
    row = profile_row or get_profile_row(institution_key)
    if row and row.get("encryption_salt"):
        _active_fernet = derive_fernet(pin, row["encryption_salt"])
    else:
        _active_fernet = None


def clear_active_session():
    global _active_key, _active_fernet
    _active_key = None
    _active_fernet = None


def encrypt_text(value: str) -> str:
    if _active_fernet is None or not value:
        return value
    return _active_fernet.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_text(value: str) -> str:
    if _active_fernet is None or not value:
        return value
    try:
        return _active_fernet.decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, Exception):
        return value  # legacy plaintext row, or content this key can't open — degrade, don't crash


def encrypt_file_bytes(data: bytes) -> bytes:
    if _active_fernet is None:
        return data
    return _active_fernet.encrypt(data)


def decrypt_file_bytes(data: bytes) -> bytes:
    if _active_fernet is None:
        return data
    try:
        return _active_fernet.decrypt(data)
    except (InvalidToken, ValueError):
        return data


def decrypt_message_row(row: dict) -> dict:
    """Applied to every message dict before it's ever sent to the frontend."""
    row = dict(row)
    row["subject"] = decrypt_text(row.get("subject") or "")
    row["body"] = decrypt_text(row.get("body") or "")
    return row


# --------------------------------------------------------------------------- #
# Page routes
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/manifest.json")
def manifest():
    return send_from_directory(app.static_folder, "manifest.json",
                                mimetype="application/manifest+json")


@app.route("/api/network-qr.png")
def api_network_qr():
    """
    Generates a QR code encoding this device's LAN URL, so a phone can
    open TASHIL by scanning instead of typing an IP address by hand.
    """
    if not _QRCODE_AVAILABLE:
        abort(501)  # Not Implemented — dependency missing on this build
    url = f"http://{get_lan_ip()}:5000/"
    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


# --------------------------------------------------------------------------- #
# API — Meta / directories
# --------------------------------------------------------------------------- #
@app.route("/api/meta", methods=["GET"])
def api_meta():
    return jsonify({
        "wilayas": WILAYAS,
        "institution_types": INSTITUTION_TYPES,
        "lan_url": f"http://{get_lan_ip()}:5000/",
        "app_version": APP_VERSION,
        "github_repo": GITHUB_REPO,
    })


@app.route("/api/institutions", methods=["GET"])
def api_institutions():
    return jsonify({"institutions": INSTITUTIONS_DIRECTORY})


@app.route("/api/institutions/onboarding", methods=["GET"])
def api_institutions_onboarding():
    wilaya_code = request.args.get("wilaya_code", type=int)
    institution_type = request.args.get("institution_type", "")
    if wilaya_code is None or institution_type not in INSTITUTION_TYPES:
        return jsonify({"error": "Paramètres invalides."}), 400
    return jsonify({"institutions": get_onboarding_institutions(wilaya_code, institution_type)})


# --------------------------------------------------------------------------- #
# API — Session / multi-tenant profile management
# --------------------------------------------------------------------------- #
@app.route("/api/session", methods=["GET"])
def api_session():
    profiles = list_profiles()
    active = require_active_profile()
    return jsonify({
        "first_launch": len(profiles) == 0,
        "profiles": [
            {
                "institution_key": p["institution_key"],
                "institution_name": p["institution_name"],
                "wilaya_name": p["wilaya_name"],
                "institution_type": p["institution_type"],
                "pin_set": p["pin_hash"] is not None,
            }
            for p in profiles
        ],
        "active": profile_public_dict(active) if active else None,
    })


@app.route("/api/session/set-pin", methods=["POST"])
def api_session_set_pin():
    """Used once, for a profile that has no PIN yet (new onboarding, or a
    migrated legacy profile). Refuses to overwrite an existing PIN — use
    the (future) change-PIN flow for that, this endpoint is creation-only."""
    data = request.get_json(force=True)
    key = data.get("institution_key", "")
    pin = data.get("pin", "")

    if not re.fullmatch(r"\d{4,6}", pin):
        return jsonify({"error": "Le code PIN doit contenir 4 à 6 chiffres."}), 400

    row = get_profile_row(key)
    if row is None:
        return jsonify({"error": "Établissement introuvable."}), 404
    if row["pin_hash"] is not None:
        return jsonify({"error": "Un code PIN existe déjà pour ce profil."}), 400

    # A profile getting its first-ever PIN (migrated legacy profile) also
    # opts into encryption at rest from this point forward — old plaintext
    # rows/files stay readable (decrypt_text/decrypt_file_bytes fall back
    # gracefully when content isn't actually encrypted), new ones get
    # encrypted going forward.
    salt = generate_encryption_salt()
    conn = get_registry_db()
    conn.execute("UPDATE profiles SET pin_hash = ?, encryption_salt = ? WHERE institution_key = ?",
                 (generate_password_hash(pin), salt, key))
    conn.commit()
    conn.close()

    updated_row = get_profile_row(key)
    set_active_session(key, pin, updated_row)
    return jsonify({"ok": True, "profile": profile_public_dict(updated_row)})


@app.route("/api/session/unlock", methods=["POST"])
def api_session_unlock():
    data = request.get_json(force=True)
    key = data.get("institution_key", "")
    pin = data.get("pin", "")

    row = get_profile_row(key)
    if row is None:
        return jsonify({"error": "Établissement introuvable."}), 404
    if row["pin_hash"] is None:
        return jsonify({"error": "Aucun code PIN défini pour ce profil.", "pin_not_set": True}), 400
    if not check_password_hash(row["pin_hash"], pin):
        return jsonify({"error": "Code PIN incorrect."}), 401

    set_active_session(key, pin, row)
    return jsonify({"ok": True, "profile": profile_public_dict(row)})


@app.route("/api/session/lock", methods=["POST"])
def api_session_lock():
    """Locks the workspace (the 'logout' action) WITHOUT deleting any data —
    switching institutions must never show a previous institution's
    archives, but it also must never destroy them."""
    clear_active_session()
    return jsonify({"ok": True})


@app.route("/api/profile/delete", methods=["POST"])
def api_delete_profile():
    """
    Permanently deletes the CURRENTLY ACTIVE profile: its isolated database,
    its entire archive folder (Courrier_Sortant + Courrier_Entrant), and its
    entry in the device's registry. Irreversible — requires the profile's
    own PIN to be re-entered as the actual authorization (a dismissible
    confirm() dialog alone is not enough protection for a destructive
    action against real archived documents).
    """
    global _active_key
    if _active_key is None:
        return locked_response()

    data = request.get_json(force=True)
    pin = data.get("pin", "")

    profile = get_profile_row(_active_key)
    if profile is None:
        clear_active_session()
        return jsonify({"error": "Profil introuvable."}), 404
    if profile["pin_hash"] is None or not check_password_hash(profile["pin_hash"], pin):
        return jsonify({"error": "Code PIN incorrect."}), 401

    key_to_delete = _active_key
    paths = profile_paths(key_to_delete)

    # Lock immediately — no further access to this profile from this point
    # on, regardless of whether file cleanup below fully succeeds.
    clear_active_session()

    conn = get_registry_db()
    conn.execute("DELETE FROM profiles WHERE institution_key = ?", (key_to_delete,))
    conn.commit()
    conn.close()

    try:
        if os.path.isdir(paths["folder"]):
            shutil.rmtree(paths["folder"])
    except OSError as exc:
        # The profile is already gone from the picker either way (registry
        # entry removed above) — but tell the user plainly if some files
        # couldn't be removed (e.g. one was open in another program),
        # rather than silently leaving orphaned data on disk unmentioned.
        return jsonify({
            "ok": True,
            "warning": f"Le profil a été retiré, mais certains fichiers n'ont pas pu être "
                       f"supprimés automatiquement ({exc}). Vous pouvez les supprimer "
                       f"manuellement dans le dossier de l'application si besoin."
        })

    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
# API — Profile creation (onboarding)
# --------------------------------------------------------------------------- #
@app.route("/api/profile", methods=["POST"])
def api_save_profile():
    data = request.get_json(force=True)
    wilaya_code = int(data.get("wilaya_code"))
    institution_type = data.get("institution_type", "").strip()
    institution_name = data.get("institution_name", "").strip()
    pin = data.get("pin", "")

    if not institution_name or institution_type not in INSTITUTION_TYPES:
        return jsonify({"error": "Champs invalides."}), 400
    if not re.fullmatch(r"\d{4,6}", pin):
        return jsonify({"error": "Le code PIN doit contenir 4 à 6 chiffres."}), 400

    wilaya_name = dict(WILAYAS).get(wilaya_code)
    if wilaya_name is None:
        return jsonify({"error": "Wilaya invalide."}), 400

    key = make_institution_key(wilaya_code, institution_type, institution_name)
    serial_key = generate_serial_key(wilaya_code, institution_type, institution_name)
    salt = generate_encryption_salt()

    conn = get_registry_db()
    conn.execute("""
        INSERT INTO profiles (institution_key, wilaya_code, wilaya_name,
                               institution_type, institution_name, serial_key,
                               pin_hash, theme, encryption_salt, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'dark', ?, ?)
    """, (key, wilaya_code, wilaya_name, institution_type, institution_name,
          serial_key, generate_password_hash(pin), salt, datetime.now().isoformat()))
    conn.commit()
    conn.close()

    # Ensure the isolated storage folder exists immediately
    get_profile_db(key).close()

    updated_row = get_profile_row(key)
    set_active_session(key, pin, updated_row)
    return jsonify({"ok": True, "profile": profile_public_dict(updated_row)})


@app.route("/api/profile/theme", methods=["POST"])
def api_set_theme():
    if _active_key is None:
        return locked_response()
    data = request.get_json(force=True)
    theme = data.get("theme", "dark")
    if theme not in ("dark", "light"):
        return jsonify({"error": "Thème invalide."}), 400
    conn = get_registry_db()
    conn.execute("UPDATE profiles SET theme = ? WHERE institution_key = ?", (theme, _active_key))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
# API — Dashboard (scoped to the active profile)
# --------------------------------------------------------------------------- #
@app.route("/api/dashboard", methods=["GET"])
def api_dashboard():
    if _active_key is None:
        return locked_response()
    conn = get_profile_db(_active_key)
    sent = conn.execute("SELECT COUNT(*) c FROM messages WHERE direction='sortant'").fetchone()["c"]
    received = conn.execute("SELECT COUNT(*) c FROM messages WHERE direction='entrant'").fetchone()["c"]
    # "En attente" = sent but not yet acknowledged by the recipient. Note:
    # previously this counted status='en_attente', a value nothing ever
    # actually inserted (every outgoing message is written with status
    # 'envoye') — so this counter silently showed 0 always. Redefined here
    # to mean what the dashboard label actually implies: outgoing messages
    # still awaiting an accusé de réception. total_sent stays an honest
    # all-time count regardless of acknowledgement state.
    pending = conn.execute(
        "SELECT COUNT(*) c FROM messages WHERE direction='sortant' AND status != 'accuse'"
    ).fetchone()["c"]
    recent = conn.execute("SELECT * FROM messages ORDER BY created_at DESC LIMIT 15").fetchall()
    conn.close()
    return jsonify({
        "total_sent": sent,
        "total_received": received,
        "pending": pending,
        "recent": [decrypt_message_row(r) for r in recent],
    })


# --------------------------------------------------------------------------- #
# API — Messaging (scoped to the active profile)
# --------------------------------------------------------------------------- #
@app.route("/api/messages", methods=["GET"])
def api_list_messages():
    if _active_key is None:
        return locked_response()
    direction = request.args.get("direction", "sortant")
    conn = get_profile_db(_active_key)
    rows = conn.execute(
        "SELECT * FROM messages WHERE direction = ? ORDER BY created_at DESC",
        (direction,)
    ).fetchall()
    conn.close()
    return jsonify({"messages": [decrypt_message_row(r) for r in rows]})


@app.route("/api/messages/send", methods=["POST"])
def api_send_message():
    if _active_key is None:
        return locked_response()

    recipient = request.form.get("recipient", "").strip()
    subject = request.form.get("subject", "").strip()
    body = request.form.get("body", "").strip()
    file = request.files.get("file")

    if not recipient:
        return jsonify({"error": "Institution destinataire requise."}), 400
    if not file or file.filename == "":
        return jsonify({"error": "Un fichier est requis."}), 400

    profile = get_profile_row(_active_key)
    sender = profile["institution_name"] if profile else "TASHIL"
    paths = profile_paths(_active_key)

    # Read the original plaintext bytes ONCE. Only the SENDER's own
    # archived copy gets encrypted below, with the sender's own key — any
    # copy handed to a different security domain (local delivery, Cloud
    # Bridge) must use these original bytes, never the sender's encrypted
    # file, which a recipient has no way to decrypt (different key/PIN).
    original_bytes = file.read()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = sanitize(sender).replace(" ", "")[:30]
    safe_name = sanitize(secure_filename(file.filename) or "document")
    archived_name = f"{ts}_{tag}_{safe_name}"
    archived_path = os.path.join(paths["sortant"], archived_name)
    with open(archived_path, "wb") as f:
        f.write(encrypt_file_bytes(original_bytes))

    conn = get_profile_db(_active_key)
    tracking = next_tracking_number(conn, "sortant", _active_key)
    conn.execute("""
        INSERT INTO messages (direction, tracking_number, sender_institution,
                               recipient_institution, subject, body, file_path,
                               file_original_name, status, delivery_method, created_at)
        VALUES ('sortant', ?, ?, ?, ?, ?, ?, ?, 'envoye', NULL, ?)
    """, (tracking, sender, recipient, encrypt_text(subject), encrypt_text(body),
          archived_path, file.filename, datetime.now().isoformat()))
    conn.commit()
    conn.close()

    # --------------------------------------------------------------- #
    # Local delivery: if the recipient happens to be another profile
    # registered on THIS SAME DEVICE, actually deliver the message into
    # its inbox (own isolated database + archive). This does NOT reach
    # a different computer on the network — that is a separate feature
    # (LAN push / Cloud Bridge) not yet built. See STATE.md.
    # --------------------------------------------------------------- #
    delivered_locally = False
    recipient_profile = find_local_profile_by_recipient(recipient, exclude_key=_active_key)
    if recipient_profile is not None:
        try:
            recipient_key = recipient_profile["institution_key"]
            recipient_paths = profile_paths(recipient_key)
            recipient_archived_path = os.path.join(recipient_paths["entrant"], archived_name)
            # Plaintext, deliberately — see the encryption scope limitation
            # documented above set_active_session(): we don't have the
            # recipient's PIN/key at this point (they're locked), so we
            # cannot encrypt on their behalf. This writes the ORIGINAL
            # bytes, never the sender's encrypted copy (which only the
            # sender's own key could ever open).
            with open(recipient_archived_path, "wb") as f:
                f.write(original_bytes)

            recipient_conn = get_profile_db(recipient_key)
            recipient_tracking = tracking
            try:
                recipient_conn.execute("""
                    INSERT INTO messages (direction, tracking_number, sender_institution,
                                           recipient_institution, subject, body, file_path,
                                           file_original_name, status, delivery_method, created_at)
                    VALUES ('entrant', ?, ?, ?, ?, ?, ?, ?, 'envoye', 'local', ?)
                """, (recipient_tracking, sender, recipient, subject, body,
                      recipient_archived_path, file.filename, datetime.now().isoformat()))
            except sqlite3.IntegrityError:
                # Extremely rare tracking-number collision across two
                # independent institution databases — disambiguate and retry.
                recipient_tracking = f"{tracking}-{uuid.uuid4().hex[:4].upper()}"
                recipient_conn.execute("""
                    INSERT INTO messages (direction, tracking_number, sender_institution,
                                           recipient_institution, subject, body, file_path,
                                           file_original_name, status, delivery_method, created_at)
                    VALUES ('entrant', ?, ?, ?, ?, ?, ?, ?, 'envoye', 'local', ?)
                """, (recipient_tracking, sender, recipient, subject, body,
                      recipient_archived_path, file.filename, datetime.now().isoformat()))
            recipient_conn.commit()
            recipient_conn.close()
            delivered_locally = True
        except Exception:
            # Never fail the whole send just because local delivery hit an
            # issue — the sender's own record above is already saved.
            delivered_locally = False

    # --------------------------------------------------------------- #
    # Cloud Bridge fallback: only attempted when no local profile matched
    # (a local match always takes precedence — see find_local_profile_by_name
    # docstring). Never fails the overall send; the sender's own record is
    # already safely saved regardless of bridge outcome.
    # --------------------------------------------------------------- #
    delivered_via_bridge = False
    bridge_attempted = False
    if not delivered_locally:
        bridge_cfg = get_bridge_config()
        if bridge_cfg and bridge_cfg["enabled"]:
            bridge_attempted = True
            try:
                delivered_via_bridge = push_to_bridge(
                    bridge_cfg, recipient, sender, subject, body,
                    tracking, original_bytes, file.filename
                )
            except Exception:
                delivered_via_bridge = False

    delivery_method = "local" if delivered_locally else ("bridge" if delivered_via_bridge else None)
    if delivery_method:
        method_conn = get_profile_db(_active_key)
        method_conn.execute("UPDATE messages SET delivery_method = ? WHERE tracking_number = ?",
                             (delivery_method, tracking))
        method_conn.commit()
        method_conn.close()

    return jsonify({
        "ok": True,
        "tracking_number": tracking,
        "delivered_locally": delivered_locally,
        "recipient_has_local_profile": recipient_profile is not None,
        "bridge_attempted": bridge_attempted,
        "delivered_via_bridge": delivered_via_bridge,
    })


@app.route("/api/messages/<int:message_id>/download", methods=["GET"])
def api_download_message(message_id):
    if _active_key is None:
        return locked_response()
    conn = get_profile_db(_active_key)
    row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    conn.close()
    if row is None or not row["file_path"] or not os.path.exists(row["file_path"]):
        abort(404)

    # decrypt_file_bytes is safe to call unconditionally: files written by
    # local delivery (a different security domain — see api_send_message)
    # are genuinely plaintext, and Fernet.decrypt() on non-Fernet bytes
    # raises InvalidToken, which decrypt_file_bytes catches and returns
    # the original bytes unchanged. The ciphertext format itself is the
    # only "is this encrypted" flag needed — no separate per-file marker.
    with open(row["file_path"], "rb") as f:
        raw = f.read()
    plaintext = decrypt_file_bytes(raw)

    return send_file(BytesIO(plaintext), as_attachment=True,
                      download_name=row["file_original_name"] or "document")


@app.route("/api/messages/<int:message_id>/status", methods=["POST"])
def api_update_message_status(message_id):
    if _active_key is None:
        return locked_response()
    data = request.get_json(force=True)
    status = data.get("status", "").strip()
    if status not in ("envoye", "recu", "accuse", "en_attente"):
        return jsonify({"error": "Statut invalide."}), 400

    conn = get_profile_db(_active_key)
    row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    if row is None:
        conn.close()
        return jsonify({"error": "Message introuvable."}), 404

    conn.execute("UPDATE messages SET status = ? WHERE id = ?", (status, message_id))
    conn.commit()
    updated = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    conn.close()

    # Read-receipt routing: only for entrant messages being acknowledged.
    if status == "accuse" and row["direction"] == "entrant":
        route_read_receipt(row)

    return jsonify({"ok": True, "message": decrypt_message_row(updated)})


def route_read_receipt(message_row):
    """
    Notifies the ORIGINAL SENDER that their document was acknowledged —
    instantly if they're a profile on this same device (delivery_method
    == 'local'), or via a small receipt object pushed through the Cloud
    Bridge otherwise. Never raises: a receipt that can't be delivered
    isn't worth failing the accusé action itself over — the requester's
    own local status update already succeeded regardless.
    """
    tracking = message_row["tracking_number"]
    sender_name = message_row["sender_institution"] or ""
    delivery_method = message_row["delivery_method"] if "delivery_method" in message_row.keys() else None

    try:
        if delivery_method == "local":
            sender_profile = find_local_profile_by_recipient(sender_name, exclude_key=_active_key)
            if sender_profile is not None:
                sender_conn = get_profile_db(sender_profile["institution_key"])
                sender_conn.execute(
                    "UPDATE messages SET status = 'accuse' WHERE tracking_number = ? AND direction = 'sortant'",
                    (tracking,)
                )
                sender_conn.commit()
                sender_conn.close()
        elif delivery_method == "bridge":
            cfg = get_bridge_config()
            if cfg and cfg["enabled"]:
                acknowledger = get_profile_row(_active_key)
                acknowledger_name = acknowledger["institution_name"] if acknowledger else "?"
                push_receipt_to_bridge(cfg, sender_name, tracking, acknowledger_name)
    except Exception:
        pass  # see docstring — a failed receipt never blocks the accusé itself


def push_receipt_to_bridge(cfg: dict, sender_name: str, tracking: str, acknowledger_name: str) -> bool:
    owner, repo, token = cfg["github_owner"], cfg["github_repo"], cfg["github_token"]
    key = bridge_slug(sender_name)
    receipt_path = f"bridge/{key}/receipts/{tracking}.json"
    payload = {
        "type": "receipt",
        "tracking_number": tracking,
        "acknowledged_by": acknowledger_name,
        "acknowledged_at": datetime.now().isoformat(),
    }
    payload_b64 = base64.b64encode(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ).decode("utf-8")
    status, _ = _github_request(
        "PUT", f"/repos/{owner}/{repo}/contents/{receipt_path}", token,
        {"message": f"TASHIL bridge: receipt for {tracking}", "content": payload_b64}
    )
    return status in (200, 201)


@app.route("/api/messages/<int:message_id>", methods=["DELETE"])
def api_delete_message(message_id):
    if _active_key is None:
        return locked_response()
    conn = get_profile_db(_active_key)
    row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    if row is None:
        conn.close()
        return jsonify({"error": "Message introuvable."}), 404

    file_path = row["file_path"]
    conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
    conn.commit()
    conn.close()

    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError:
            pass  # DB record is already gone; a leftover file is not fatal

    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
# API — Registry (Administration), scoped to the active profile
# --------------------------------------------------------------------------- #
@app.route("/api/registre", methods=["GET"])
def api_registre():
    if _active_key is None:
        return locked_response()
    direction = request.args.get("direction", "tous")
    conn = get_profile_db(_active_key)
    if direction == "tous":
        rows = conn.execute("SELECT * FROM messages ORDER BY created_at DESC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM messages WHERE direction = ? ORDER BY created_at DESC",
            (direction,)
        ).fetchall()
    conn.close()
    return jsonify({"entries": [decrypt_message_row(r) for r in rows]})


# --------------------------------------------------------------------------- #
# API — Cloud Bridge configuration & manual poll
# --------------------------------------------------------------------------- #
@app.route("/api/bridge/network-test", methods=["GET"])
def api_bridge_network_test():
    """
    Diagnostic-only, no token/repo needed: checks whether THIS machine can
    reach api.github.com over HTTPS at all — separates "GitHub itself is
    unreachable / blocked by a firewall or proxy" from "the repo/token
    configuration is wrong", which otherwise look identical from the
    config form's point of view. Deliberately sends NO Authorization
    header (unlike _github_request) — this checks pure network/SSL
    reachability, not credentials.
    """
    import time
    import urllib.request
    import urllib.error
    import ssl

    ssl_context = ssl.create_default_context(cafile=certifi.where()) if _CERTIFI_AVAILABLE else None
    req = urllib.request.Request(
        "https://api.github.com/zen",
        headers={"User-Agent": "TASHIL-DOCUMENT-HUB", "Accept": "application/vnd.github+json"},
    )

    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=10, context=ssl_context) as resp:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return jsonify({"ok": True, "elapsed_ms": elapsed_ms,
                             "message": "Connexion à api.github.com réussie."})
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        error_message = str(exc)
        hint = ""
        if "CERTIFICATE_VERIFY_FAILED" in error_message:
            hint = ("Problème de certificat SSL — souvent causé par un antivirus/pare-feu "
                    "qui inspecte le trafic HTTPS, ou un proxy d'entreprise.")
        elif "timed out" in error_message.lower():
            hint = "Délai dépassé — le pare-feu bloque probablement la connexion sortante."
        elif "Name or service not known" in error_message or "getaddrinfo failed" in error_message:
            hint = "Résolution DNS échouée — vérifiez la connexion Internet de cette machine."
        elif "Connection refused" in error_message:
            hint = "Connexion refusée — un pare-feu local ou réseau bloque probablement le port 443."

        return jsonify({"ok": False, "elapsed_ms": elapsed_ms, "message": error_message, "hint": hint})


@app.route("/api/bridge/config", methods=["GET"])
def api_bridge_get_config():
    cfg = get_bridge_config()
    if cfg is None:
        return jsonify({"configured": False, "enabled": False})
    return jsonify({
        "configured": bool(cfg["github_owner"] and cfg["github_repo"] and cfg["github_token"]),
        "enabled": bool(cfg["enabled"]),
        "github_owner": cfg["github_owner"],
        "github_repo": cfg["github_repo"],
        # github_token deliberately never sent back to the frontend
    })


def _validate_and_save_bridge_config(owner: str, repo: str, token: str):
    """
    Shared by both the manual entry form AND the QR/pasted-code import path
    — guarantees the private-repo safety check applies identically no
    matter how the credentials arrived. Returns (status_code, body_dict).
    """
    if not owner or not repo or not token:
        return 400, {"error": "Propriétaire, dépôt et jeton GitHub sont tous requis."}

    status, repo_info = _github_request("GET", f"/repos/{owner}/{repo}", token)
    if status == 0:
        return 502, {"error": f"Impossible de contacter GitHub : {repo_info.get('message', 'réseau indisponible')}"}
    if status == 401:
        return 401, {"error": "Jeton GitHub invalide ou expiré."}
    if status == 404:
        return 404, {"error": "Dépôt introuvable (ou le jeton n'y a pas accès)."}
    if status != 200:
        return 502, {"error": f"Erreur GitHub inattendue ({status})."}

    if repo_info.get("private") is not True:
        return 400, {
            "error": "Ce dépôt est PUBLIC. TASHIL refuse d'y transmettre des documents. "
                     "Utilisez un dépôt privé dédié."
        }

    conn = get_registry_db()
    conn.execute("""
        INSERT INTO bridge_config (id, github_owner, github_repo, github_token, enabled, updated_at)
        VALUES (1, ?, ?, ?, 1, ?)
        ON CONFLICT(id) DO UPDATE SET
            github_owner=excluded.github_owner, github_repo=excluded.github_repo,
            github_token=excluded.github_token, enabled=1, updated_at=excluded.updated_at
    """, (owner, repo, token, datetime.now().isoformat()))
    conn.commit()
    conn.close()

    return 200, {"ok": True, "private_verified": True}


@app.route("/api/bridge/config", methods=["POST"])
def api_bridge_save_config():
    data = request.get_json(force=True)
    owner = data.get("github_owner", "").strip()
    repo = data.get("github_repo", "").strip()
    token = data.get("github_token", "").strip()
    status, body = _validate_and_save_bridge_config(owner, repo, token)
    return jsonify(body), status


# --------------------------------------------------------------------------- #
# Provisioning code / QR — lets a SECOND device pick up an ALREADY-VERIFIED
# bridge configuration without anyone retyping owner/repo/token by hand.
#
# ⚠️ This is convenience for TRANSFERRING a real credential between two
# devices you control in person — it does not change the underlying
# security model. The code/QR contains the actual token in the clear
# (base64 is encoding, not encryption); treat a screenshot or photo of it
# exactly like you'd treat the token itself. It is generated only for an
# already-unlocked session that already configured the bridge, and is
# never cached or logged server-side beyond the single response.
# --------------------------------------------------------------------------- #
def build_provisioning_code(cfg: dict) -> str:
    payload = {
        "github_owner": cfg["github_owner"],
        "github_repo": cfg["github_repo"],
        "github_token": cfg["github_token"],
    }
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def parse_provisioning_code(code: str) -> dict:
    payload = json.loads(base64.b64decode(code.strip().encode("ascii")).decode("utf-8"))
    if not isinstance(payload, dict) or "github_token" not in payload:
        raise ValueError("malformed provisioning payload")
    return payload


@app.route("/api/bridge/provisioning-code", methods=["GET"])
def api_bridge_provisioning_code():
    if _active_key is None:
        return locked_response()
    cfg = get_bridge_config()
    if not cfg or not cfg["enabled"]:
        return jsonify({"error": "Le Cloud Bridge n'est pas encore configuré sur cet appareil."}), 400
    return jsonify({"code": build_provisioning_code(cfg)})


@app.route("/api/bridge/provisioning-qr.png", methods=["GET"])
def api_bridge_provisioning_qr():
    if _active_key is None:
        return locked_response()
    if not _QRCODE_AVAILABLE:
        abort(501)
    cfg = get_bridge_config()
    if not cfg or not cfg["enabled"]:
        abort(404)
    img = qrcode.make(build_provisioning_code(cfg))
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/api/bridge/decode-qr-image", methods=["POST"])
def api_bridge_decode_qr_image():
    """
    Decodes a QR code from an uploaded image file (drag-and-drop or file
    picker) — for someone who can't use a phone camera or copy/paste text
    directly, e.g. they saved/screenshotted the QR and transferred the
    image file itself. Returns just the decoded text; the frontend feeds
    it into the same /api/bridge/import-code flow as a manually pasted
    code, so the exact same private-repo verification applies either way.

    Uses pyzbar + Pillow rather than OpenCV: an earlier version of this
    endpoint used opencv-python-headless, which imported successfully in
    every local test but failed to import at all in a real built exe
    (confirmed by the user — "Le décodage d'image QR n'est pas disponible
    sur ce build"), with no way to tell why from the generic message
    alone. Pillow is already a proven-working dependency in this exact
    build (the provisioning QR generation feature already uses it
    successfully), and pyzbar is a much smaller, simpler native
    dependency than OpenCV — lower packaging risk. If this import STILL
    fails, _QR_DECODE_IMPORT_ERROR captures the real reason instead of
    another dead-end "not available" message.
    """
    if not _QR_DECODE_AVAILABLE:
        detail = f" (détail technique : {_QR_DECODE_IMPORT_ERROR})" if _QR_DECODE_IMPORT_ERROR else ""
        return jsonify({"error": f"Le décodage d'image QR n'est pas disponible sur ce build.{detail}"}), 501

    file = request.files.get("image")
    if not file or file.filename == "":
        return jsonify({"error": "Aucune image fournie."}), 400

    try:
        from PIL import Image
        img = Image.open(BytesIO(file.read()))
        img = img.convert("RGB")

        results = _zbar_decode(img)
        if not results:
            # Real-world images (screenshots, angled phone photos) can be
            # too small or low-contrast for zbar's finder-pattern detection
            # on the first pass — a simple upscale often resolves it.
            upscaled = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
            results = _zbar_decode(upscaled)

        if not results:
            return jsonify({"error": "Aucun QR code détecté dans cette image. "
                                      "Essayez une image plus nette ou de meilleure résolution."}), 400

        decoded_text = results[0].data.decode("utf-8")
        return jsonify({"code": decoded_text})
    except Exception as exc:
        return jsonify({"error": f"Échec du décodage : {exc}"}), 500


@app.route("/api/bridge/import-code", methods=["POST"])
def api_bridge_import_code():
    data = request.get_json(force=True)
    code = data.get("code", "").strip()
    if not code:
        return jsonify({"error": "Code de provisioning vide."}), 400
    try:
        payload = parse_provisioning_code(code)
    except Exception:
        return jsonify({"error": "Code de provisioning invalide ou corrompu."}), 400

    status, body = _validate_and_save_bridge_config(
        payload.get("github_owner", ""), payload.get("github_repo", ""), payload.get("github_token", "")
    )
    return jsonify(body), status


@app.route("/api/bridge/disable", methods=["POST"])
def api_bridge_disable():
    conn = get_registry_db()
    conn.execute("UPDATE bridge_config SET enabled = 0 WHERE id = 1")
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
# Retry-on-delete-failure (v2.7.0): if a GitHub DELETE call fails right
# after a message/receipt was successfully imported (rare transient
# network issue), the entry is queued in bridge_pending_cleanup instead
# of silently left behind — because once imported, its tracking_number is
# already known locally, so future polls would otherwise skip re-checking
# it entirely, and the stray copy would linger in the repo unnoticed.
# --------------------------------------------------------------------------- #
def _queue_bridge_cleanup(conn, url_or_path: str, sha: str):
    conn.execute(
        "INSERT INTO bridge_pending_cleanup (repo_path, sha, created_at) VALUES (?, ?, ?)",
        (url_or_path, sha, datetime.now().isoformat())
    )
    conn.commit()


def _delete_bridge_entry_or_queue(conn, owner: str, repo: str, token: str, url_or_path: str, sha: str):
    status, _ = _github_request("DELETE", url_or_path, token,
                                 {"message": "TASHIL bridge: consumed", "sha": sha})
    if status not in (200, 204):
        _queue_bridge_cleanup(conn, url_or_path, sha)


def _retry_pending_bridge_cleanup(conn, owner: str, repo: str, token: str):
    pending = conn.execute("SELECT * FROM bridge_pending_cleanup").fetchall()
    for row in pending:
        status, _ = _github_request("DELETE", row["repo_path"], token,
                                     {"message": "TASHIL bridge: retried cleanup", "sha": row["sha"]})
        if status in (200, 204):
            conn.execute("DELETE FROM bridge_pending_cleanup WHERE id = ?", (row["id"],))
    conn.commit()


# --------------------------------------------------------------------------- #
# "Établissements connectés" (v2.8.0) — presence directory.
#
# ⚠️ Real design constraint, worth understanding: the bridge repo has no
# built-in registry of institutions — a folder under bridge/<address>/
# only exists once someone has actually SENT a message there. There was
# no way to answer "which institutions are configured/active on the
# network" from the existing structure alone. This adds an explicit
# heartbeat: each unlocked device periodically writes its own presence
# file to directory/<institution_key>.json, piggybacked on the existing
# bridge poll cycle (no extra timer). "Connecté" here means "has recently
# written a heartbeat" — a device that's been closed for a while will
# correctly show as offline once its last heartbeat goes stale, not
# because anything failed, simply because it stopped announcing itself.
# --------------------------------------------------------------------------- #
_HEARTBEAT_STALE_AFTER_SECONDS = 180  # ~4 missed 45s poll cycles


def _send_heartbeat(owner: str, repo: str, token: str, profile: dict):
    payload = {
        "institution_key": profile["institution_key"],
        "institution_name": profile["institution_name"],
        "institution_type": profile["institution_type"],
        "wilaya_name": profile["wilaya_name"],
        "last_seen": datetime.now().isoformat(),
    }
    payload_b64 = base64.b64encode(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ).decode("utf-8")
    path = f"directory/{profile['institution_key']}.json"

    # Need the current sha to update an existing file — GitHub's Contents
    # API rejects an overwrite without it. A fresh heartbeat file has none.
    status, existing = _github_request("GET", f"/repos/{owner}/{repo}/contents/{path}", token)
    body = {"message": f"TASHIL heartbeat: {profile['institution_name']}", "content": payload_b64}
    if status == 200 and "sha" in existing:
        body["sha"] = existing["sha"]

    _github_request("PUT", f"/repos/{owner}/{repo}/contents/{path}", token, body)


@app.route("/api/bridge/directory", methods=["GET"])
def api_bridge_directory():
    if _active_key is None:
        return locked_response()
    cfg = get_bridge_config()
    if not cfg or not cfg["enabled"]:
        return jsonify({"bridge_enabled": False, "institutions": []})

    owner, repo, token = cfg["github_owner"], cfg["github_repo"], cfg["github_token"]
    status, listing = _github_request("GET", f"/repos/{owner}/{repo}/contents/directory", token)
    if status == 404:
        return jsonify({"bridge_enabled": True, "institutions": []})
    if status != 200:
        return jsonify({"error": f"Erreur GitHub ({status})."}), 502

    now = datetime.now()
    institutions = []
    for entry in listing:
        if not entry["name"].endswith(".json"):
            continue
        file_status, content = _github_request("GET", entry["url"], token)
        if file_status != 200 or "content" not in content:
            continue
        try:
            record = json.loads(base64.b64decode(content["content"]).decode("utf-8"))
            last_seen = datetime.fromisoformat(record["last_seen"])
        except (ValueError, KeyError):
            continue

        age_seconds = (now - last_seen).total_seconds()
        institutions.append({
            "institution_key": record.get("institution_key", ""),
            "institution_name": record.get("institution_name", "?"),
            "institution_type": record.get("institution_type", ""),
            "wilaya_name": record.get("wilaya_name", ""),
            "last_seen": record["last_seen"],
            "online": age_seconds <= _HEARTBEAT_STALE_AFTER_SECONDS,
        })

    institutions.sort(key=lambda i: (not i["online"], i["institution_name"]))
    return jsonify({"bridge_enabled": True, "institutions": institutions})


@app.route("/api/bridge/poll", methods=["POST"])
def api_bridge_poll():
    """
    Checks the Cloud Bridge repo for new messages AND read-receipts
    addressed to the CURRENTLY ACTIVE profile. Downloads/imports anything
    found into that profile's own isolated database + archive, applies
    any receipts to the matching sent items, then removes consumed
    entries from the bridge repo — retrying any cleanup that failed on a
    previous poll first. Safe to call repeatedly — already-seen tracking
    numbers are skipped.
    """
    if _active_key is None:
        return locked_response()

    cfg = get_bridge_config()
    if not cfg or not cfg["enabled"]:
        return jsonify({"ok": True, "bridge_enabled": False, "new_messages": 0, "receipts": []})

    profile = get_profile_row(_active_key)
    owner, repo, token = cfg["github_owner"], cfg["github_repo"], cfg["github_token"]
    conn = get_profile_db(_active_key)
    paths = profile_paths(_active_key)

    # Retry any deletions that failed on a previous poll BEFORE processing
    # new entries (see queue_bridge_cleanup / feature note above).
    _retry_pending_bridge_cleanup(conn, owner, repo, token)

    # Announce presence for "Établissements connectés" — piggybacked here
    # rather than a separate timer, so it costs no extra GitHub API budget
    # beyond what polling already uses.
    try:
        _send_heartbeat(owner, repo, token, profile)
    except Exception:
        pass  # a missed heartbeat just means this device looks offline a bit longer, not a real failure

    # A sender may have addressed this institution either by its plain name
    # or by its exact routing ID (institution_key) — check both folders so
    # neither addressing style silently gets lost. Deduplicated by set()
    # since the two can occasionally normalize to the same slug.
    keys_to_check = {bridge_slug(profile["institution_name"]), bridge_slug(profile["institution_key"])}

    json_entries = []
    receipt_entries = []
    for key in keys_to_check:
        status, listing = _github_request("GET", f"/repos/{owner}/{repo}/contents/bridge/{key}", token)
        if status == 200:
            json_entries.extend(f for f in listing if f["name"].endswith(".json"))
        elif status != 404:
            conn.close()
            return jsonify({"error": f"Erreur GitHub ({status})."}), 502

        r_status, r_listing = _github_request(
            "GET", f"/repos/{owner}/{repo}/contents/bridge/{key}/receipts", token
        )
        if r_status == 200:
            receipt_entries.extend(f for f in r_listing if f["name"].endswith(".json"))
        elif r_status != 404:
            conn.close()
            return jsonify({"error": f"Erreur GitHub ({r_status})."}), 502

    new_count = 0
    for entry in json_entries:
        meta_status, meta_content = _github_request("GET", entry["url"], token)
        if meta_status != 200 or "content" not in meta_content:
            continue
        try:
            meta = json.loads(base64.b64decode(meta_content["content"]).decode("utf-8"))
        except (ValueError, KeyError):
            continue

        already_have = conn.execute(
            "SELECT 1 FROM messages WHERE tracking_number = ?", (meta["tracking_number"],)
        ).fetchone()
        if already_have:
            # Already imported on a previous poll — if cleanup failed that
            # time, _retry_pending_bridge_cleanup above already handles it.
            continue

        attach_status, attach_content = _github_request(
            "GET", f"/repos/{owner}/{repo}/contents/{meta['attachment_path_in_repo']}", token
        )
        if attach_status != 200 or "content" not in attach_content:
            continue
        file_bytes = base64.b64decode(attach_content["content"])

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        tag = sanitize(meta.get("sender_institution", "DISTANT")).replace(" ", "")[:30]
        safe_name = sanitize(meta.get("file_original_name", "document"))
        local_path = os.path.join(paths["entrant"], f"{ts}_{tag}_{safe_name}")
        try:
            # Encrypts with THIS profile's own active key, if it has
            # encryption enabled — safe no-op otherwise. We're the
            # recipient and unlocked right now, so (unlike local
            # delivery) applying our own encryption here is correct.
            with open(local_path, "wb") as f:
                f.write(encrypt_file_bytes(file_bytes))
        except OSError:
            continue

        conn.execute("""
            INSERT INTO messages (direction, tracking_number, sender_institution,
                                   recipient_institution, subject, body, file_path,
                                   file_original_name, status, delivery_method, created_at)
            VALUES ('entrant', ?, ?, ?, ?, ?, ?, ?, 'envoye', 'bridge', ?)
        """, (meta["tracking_number"], meta.get("sender_institution", "?"),
              meta.get("recipient_institution", profile["institution_name"]),
              encrypt_text(meta.get("subject", "")), encrypt_text(meta.get("body", "")),
              local_path, meta.get("file_original_name", "document"),
              meta.get("created_at", datetime.now().isoformat())))
        conn.commit()
        new_count += 1

        # Clean up consumed entries so the bridge queue doesn't grow
        # forever — queue for retry instead of silently dropping if the
        # delete itself fails (see _retry_pending_bridge_cleanup).
        _delete_bridge_entry_or_queue(conn, owner, repo, token, entry["url"], entry["sha"])
        _delete_bridge_entry_or_queue(
            conn, owner, repo, token,
            f"/repos/{owner}/{repo}/contents/{meta['attachment_path_in_repo']}",
            attach_content["sha"]
        )

    receipts_applied = []
    for entry in receipt_entries:
        r_status, r_content = _github_request("GET", entry["url"], token)
        if r_status != 200 or "content" not in r_content:
            continue
        try:
            receipt = json.loads(base64.b64decode(r_content["content"]).decode("utf-8"))
        except (ValueError, KeyError):
            continue

        tracking = receipt.get("tracking_number")
        if tracking:
            sent_row = conn.execute(
                "SELECT * FROM messages WHERE tracking_number = ? AND direction = 'sortant'", (tracking,)
            ).fetchone()
            if sent_row is not None and sent_row["status"] != "accuse":
                conn.execute(
                    "UPDATE messages SET status = 'accuse' WHERE tracking_number = ? AND direction = 'sortant'",
                    (tracking,)
                )
                conn.commit()
                receipts_applied.append({
                    "tracking_number": tracking,
                    "acknowledged_by": receipt.get("acknowledged_by", "?"),
                })

        # Consume the receipt regardless, so it never sits in the queue forever.
        _delete_bridge_entry_or_queue(conn, owner, repo, token, entry["url"], entry["sha"])

    conn.close()
    return jsonify({
        "ok": True,
        "bridge_enabled": True,
        "new_messages": new_count,
        "receipts": receipts_applied,
    })


if __name__ == "__main__":
    print(f"TASHIL DOCUMENT HUB — Web Edition v{APP_VERSION}")
    print(f"Local  : http://127.0.0.1:5000/")
    print(f"Réseau : http://{get_lan_ip()}:5000/  (accessible depuis un téléphone sur le même Wi-Fi)")
    app.run(host="0.0.0.0", port=5000, debug=False)
