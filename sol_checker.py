"""Sol Fast Track Checker — проверка токена Solana по Ctrl+C с уведомлением Windows.

Скопировал контракт (или ссылку pump.fun / dexscreener / gmgn / axiom) — через пару секунд
уведомление с оценкой безопасности, вердиктом и главными красными флагами. Проверку делает
бот Solana Fast Track VIP (глубокий режим: бандл, снайперы, история создателя, honeypot-
расширения Token-2022, свежие кошельки в топе). Код подключения выдаёт бот: /desktopkey.

Запуск: SolFastTrackChecker.exe (или python sol_checker.py). Самопроверка: --selftest [файл].
"""

import base64
import ctypes
import html
import http.client
import json
import os
import queue
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

APP_NAME = "Sol Fast Track Checker"
APP_ID = "SolFastTrack.Checker"            # AUMID: под этим именем Windows показывает уведомления
# Запасной AUMID, который в Windows зарегистрирован всегда (уведомления будут «от Windows PowerShell»).
FALLBACK_APP_ID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"
VERSION = "1.3.3"
IS_WINDOWS = sys.platform == "win32"

# Контракт Solana (base58, 32–44 символа) — внутри текста или ссылки.
MINT_RE = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![1-9A-HJ-NP-Za-km-z])")
# Не токены: системные программы и адреса, которые часто копируют.
NOT_TOKENS = {
    "11111111111111111111111111111111",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
}
CLIPBOARD_POLL_SEC = 0.03                 # буфер обмена — 30 раз в секунду (вызов ничего не стоит)
WARM_EVERY_SEC = 15                       # соединения с сервером держим «тёплыми»
REUSE_MAX_IDLE_SEC = 20                   # дольше простаивало — не доверяем (могли молча оборвать)
QUICK_TIMEOUT = 12                        # быстрая проверка целиком (сервер ограничен 12 с)
QUICK_HEDGE_SEC = 1.2                     # тёплое соединение молчит дольше — параллельно запрос по новому
REPEAT_SEC = 30                            # тот же токен повторно не проверяем 30 секунд
MAX_CLIPBOARD_CHARS = 600                  # длинные тексты не разбираем — это не контракт
REQUEST_TIMEOUT = 45                       # полная проверка (сервер ограничен 35 с)
REPORTS_KEEP = 60

TEXTS = {
    "ru": {
        "started": "Работаю. Скопируй контракт (Ctrl+C) — пришлю проверку.",
        "need_code": "Нужен код подключения: напиши боту /desktop и вставь код в настройках (трей → Код подключения).",
        "bad_key": "Код подключения не подходит. Сделай новый в боте: /desktop.",
        "offline": "Сервер бота недоступен. Проверю, когда скопируешь контракт снова.",
        "rate": "Слишком много проверок за минуту — подожди немного.",
        "failed": "Не получилось проверить токен. Попробуй ещё раз.",
        "checking": "Проверяю",
        "report": "📄 Отчёт",
        "pause": "Пауза",
        "paused": "⏸ На паузе",
        "running": "✅ Работает",
        "recent": "Последние проверки",
        "empty": "пока пусто",
        "check_now": "Проверить из буфера",
        "test": "Тестовое окно",
        "test_text": "Уведомления работают 👍",
        "window_mode": "Окно с полной проверкой",
        "copy_ca": "📋 CA",
        "no_vip": "Код не работает: VIP закончился. Продли VIP в боте — код снова заработает.",
        "dialog_checking": "Проверяю связь с ботом…",
        "deep_pending": "⏳ Идёт глубокая проверка: бандл, снайперы, свежие кошельки…",
        "deep_failed": "⚠️ Глубокая проверка не успела — показана быстрая.",
        "sound": "Звук",
        "lang": "Язык: Русский",
        "autostart": "Запускать с Windows",
        "settings": "Код подключения…",
        "quit": "Выход",
        "dialog_title": "Подключение к боту",
        "dialog_text": "Напиши боту команду /desktop и вставь сюда код, который он пришлёт (начинается с sftd1:).",
        "dialog_save": "Сохранить и проверить",
        "dialog_bad": "Это не похоже на код подключения. Он начинается с sftd1:",
        "dialog_ok": "Готово, программа подключена к боту.",
        "dialog_fail": "Код сохранён, но сервер не ответил: ",
        "already": "Программа уже запущена — её значок в трее, у часов.",
    },
    "en": {
        "started": "Running. Copy a contract (Ctrl+C) and I'll check it.",
        "need_code": "A connection code is needed: send /desktop to the bot and paste the code in settings (tray → Connection code).",
        "bad_key": "The connection code doesn't work. Make a new one in the bot: /desktop.",
        "offline": "The bot's server is unreachable. I'll retry when you copy a contract again.",
        "rate": "Too many checks per minute — wait a little.",
        "failed": "Couldn't check the token. Try again.",
        "checking": "Checking",
        "report": "📄 Report",
        "pause": "Pause",
        "paused": "⏸ Paused",
        "running": "✅ Running",
        "recent": "Recent checks",
        "empty": "nothing yet",
        "check_now": "Check clipboard now",
        "test": "Test window",
        "test_text": "Notifications work 👍",
        "window_mode": "Window with the full check",
        "copy_ca": "📋 CA",
        "no_vip": "The code doesn't work: VIP has ended. Renew VIP in the bot and the code works again.",
        "dialog_checking": "Checking the connection to the bot…",
        "deep_pending": "⏳ Deep check running: bundle, snipers, fresh wallets…",
        "deep_failed": "⚠️ The deep check didn't finish — showing the quick one.",
        "sound": "Sound",
        "lang": "Language: English",
        "autostart": "Start with Windows",
        "settings": "Connection code…",
        "quit": "Quit",
        "dialog_title": "Connect to the bot",
        "dialog_text": "Send /desktop to the bot and paste the code it sends here (it starts with sftd1:).",
        "dialog_save": "Save and test",
        "dialog_bad": "That doesn't look like a connection code. It starts with sftd1:",
        "dialog_ok": "Done, the program is connected to the bot.",
        "dialog_fail": "Code saved, but the server didn't answer: ",
        "already": "The program is already running — its icon is in the tray, next to the clock.",
    },
}


# ------------------------------------------------------------------ хранение и журнал

def app_dir():
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    path = Path(base) / "SolFastTrackChecker"
    path.mkdir(parents=True, exist_ok=True)
    return path


CONFIG_DEFAULT = {"server": "", "key": "", "lang": "ru", "sound": True, "paused": False}
_config_lock = threading.Lock()


def load_config():
    try:
        data = json.loads((app_dir() / "config.json").read_text(encoding="utf-8"))
        return {**CONFIG_DEFAULT, **data}
    except Exception:
        return dict(CONFIG_DEFAULT)


def save_config(config):
    with _config_lock:
        (app_dir() / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def log(message):
    try:
        path = app_dir() / "checker.log"

        if path.exists() and path.stat().st_size > 1_000_000:
            path.write_text("", encoding="utf-8")

        with path.open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n")
    except Exception:
        pass


# ------------------------------------------------------------------ разбор

def extract_mint(text):
    """Контракт из текста или ссылки; None — контракта нет."""
    if not text or len(text) > MAX_CLIPBOARD_CHARS:
        return None

    for match in MINT_RE.finditer(text):
        value = match.group(0)

        if value not in NOT_TOKENS:
            return value

    return None


def parse_connection_code(code):
    """sftd1:<base64 json {"u": адрес сервера, "k": ключ}> -> (адрес, ключ) или None."""
    code = (code or "").strip()

    if not code.startswith("sftd1:"):
        return None

    try:
        raw = code[len("sftd1:"):]
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8"))
        server, key = str(data["u"]).rstrip("/"), str(data["k"])
    except Exception:
        return None

    if not server.startswith(("https://", "http://")) or not key:
        return None

    return server, key


def shorten(text, limit):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def toast_lines(payload):
    """Три строки уведомления: заголовок, вердикт, цифры и главные флаги."""
    title = f"{payload.get('emoji', '')} ${shorten(payload.get('symbol') or '?', 16)} — {payload.get('score', '?')}/100".strip()
    verdict = shorten(payload.get("verdict") or "", 90)
    flags = payload.get("flags") or []
    marks = [("🔴 " if f.get("level") == "danger" else "⚠️ ") + shorten(f.get("text"), 70) for f in flags[:3]]
    details = "\n".join([payload.get("stats") or ""] + marks).strip()

    return [title, verdict, details]


ALLOWED_TAGS = re.compile(r"</?(b|code)>")


def sanitize_report(report_html):
    """Отчёт бота (Telegram-HTML: <b>, <code>, <a href>) — только эти теги, ссылки только https."""
    text = str(report_html or "")
    links = []

    def keep_link(match):
        href = html.unescape(match.group(1))

        if not href.startswith("https://"):
            return ""

        links.append(href)
        return f"\x00A{len(links) - 1}\x00"

    text = re.sub(r'<a href="([^"]*)">', keep_link, text)
    text = text.replace("</a>", "\x00/A\x00")
    tags = []

    def keep_tag(match):
        tags.append(match.group(0))
        return f"\x00T{len(tags) - 1}\x00"

    text = ALLOWED_TAGS.sub(keep_tag, text)
    text = re.sub(r"<[^>]*>", "", text)                       # остальные теги — выкидываем
    text = re.sub(r"\x00T(\d+)\x00", lambda m: tags[int(m.group(1))], text)
    text = re.sub(r"\x00A(\d+)\x00", lambda m: f'<a href="{html.escape(links[int(m.group(1))], quote=True)}">', text)
    text = text.replace("\x00/A\x00", "</a>")

    return text


def report_page(payload):
    """Полный отчёт отдельной страницей (тёмная тема), открывается в браузере."""
    title = html.escape(f"${payload.get('symbol') or '?'} — {payload.get('score', '?')}/100")
    body = sanitize_report(payload.get("report_html"))
    links = payload.get("links") or {}
    buttons = " ".join(
        f'<a class="btn" href="{html.escape(url, quote=True)}">{html.escape(name)}</a>'
        for name, url in (("DexScreener", links.get("dexscreener")), ("RugCheck", links.get("rugcheck")),
                          ("GMGN", links.get("gmgn")), ("Solscan", links.get("solscan")))
        if url and url.startswith("https://")
    )
    logo = payload.get("logo") or ""
    image = f'<img src="{html.escape(logo, quote=True)}" alt="">' if logo.startswith(("https://", "http://")) else ""

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ color-scheme: dark; }}
body {{ margin: 0; background: #16171c; color: #e9eaef; font: 15px/1.55 -apple-system, "Segoe UI", sans-serif; }}
.wrap {{ max-width: 760px; margin: 24px auto; padding: 0 16px; }}
.head {{ display: flex; align-items: center; gap: 14px; margin-bottom: 12px; }}
.head img {{ width: 56px; height: 56px; border-radius: 14px; }}
.head h1 {{ font-size: 22px; margin: 0; }}
.card {{ background: #20222a; border-radius: 16px; padding: 18px 20px; white-space: pre-wrap; word-break: break-word; }}
code {{ background: #2b2e38; padding: 1px 5px; border-radius: 6px; font-size: 13px; }}
a {{ color: #7fb2ff; }}
.btns {{ margin: 14px 0; display: flex; gap: 8px; flex-wrap: wrap; }}
.btn {{ background: #2b2e38; padding: 8px 14px; border-radius: 10px; text-decoration: none; color: #e9eaef; }}
.foot {{ color: #7b8090; font-size: 12px; margin-top: 10px; }}
</style></head>
<body><div class="wrap">
<div class="head">{image}<h1>{title}</h1></div>
<div class="btns">{buttons}</div>
<div class="card">{body}</div>
<div class="foot">{html.escape(APP_NAME)} {VERSION} · {time.strftime("%Y-%m-%d %H:%M:%S")}</div>
</div></body></html>"""


def save_report(payload):
    folder = app_dir() / "reports"
    folder.mkdir(exist_ok=True)
    path = folder / f"{payload['mint']}.html"
    path.write_text(report_page(payload), encoding="utf-8")

    files = sorted(folder.glob("*.html"), key=lambda p: p.stat().st_mtime)

    for old in files[:-REPORTS_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass

    return path


# ------------------------------------------------------------------ сервер бота

class ServerError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class Connections:
    """Постоянные HTTPS-соединения с сервером бота (keep-alive): проверка не тратит время на
    новое TCP+TLS-соединение через полмира. Системный прокси — через urllib, как раньше."""

    def __init__(self, keep=2):
        self.keep = keep
        self.lock = threading.Lock()
        self.idle = {}                    # база сервера -> [(соединение, когда вернули в пул), ...]

    @staticmethod
    def direct(base):
        try:
            proxies = urllib.request.getproxies()
        except Exception:
            proxies = {}

        scheme = urlsplit(base).scheme
        return scheme in ("http", "https") and not proxies.get(scheme)

    def open(self, base, timeout):
        parts = urlsplit(base)
        cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        return cls(parts.hostname, parts.port, timeout=timeout)

    def take(self, base):
        """Свежее соединение из пула или None. Простаивавшие дольше REUSE_MAX_IDLE_SEC закрываем:
        роутер или балансировщик мог оборвать их молча, и запрос ждал бы до таймаута."""
        stale = []

        with self.lock:
            pool = self.idle.get(base) or []
            found = None

            while pool:
                conn, since = pool.pop()

                if time.time() - since < REUSE_MAX_IDLE_SEC:
                    found = conn
                    break

                stale.append(conn)

        for conn in stale:
            conn.close()

        return found

    def give(self, base, conn):
        with self.lock:
            pool = self.idle.setdefault(base, [])

            if len(pool) < self.keep:
                pool.append((conn, time.time()))
                return

        conn.close()

    def exchange(self, base, conn, path, headers, timeout):
        conn.timeout = timeout

        if conn.sock is not None:
            conn.sock.settimeout(timeout)

        prefix = urlsplit(base).path.rstrip("/")
        conn.request("GET", prefix + path, headers=headers)
        response = conn.getresponse()
        body = response.read()

        if response.will_close:
            conn.close()
        else:
            self.give(base, conn)

        return response.status, body

    def get(self, base, path, headers, timeout, reuse=True):
        """(HTTP-статус, тело). reuse — тёплое соединение из пула (если оно подвело — сразу новое);
        иначе всегда новое соединение."""
        if not self.direct(base):
            request = urllib.request.Request(base + path, headers=headers)

            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return response.status, response.read()
            except urllib.error.HTTPError as error:
                return error.code, error.read()

        conn = self.take(base) if reuse else None

        if conn is not None:
            try:
                return self.exchange(base, conn, path, headers, timeout)
            except (http.client.HTTPException, OSError):
                conn.close()              # соединение оборвано или не ответило вовремя — пробуем новое

        conn = self.open(base, timeout)

        try:
            return self.exchange(base, conn, path, headers, timeout)
        except BaseException:
            conn.close()
            raise

    def warm(self, base, count=2):
        """Держать count соединений открытыми и свежими (для быстрых проверок)."""
        if not self.direct(base):
            return

        conns = [self.take(base) for _ in range(count)]
        headers = {"User-Agent": f"SolFastTrackChecker/{VERSION}"}

        for conn in conns:
            try:
                self.exchange(base, conn or self.open(base, 10), "/api/ping", headers, 10)
            except Exception:
                if conn is not None:
                    conn.close()


CONNECTIONS = Connections()


def hedged_get(server, path, headers):
    """Запрос по тёплому соединению; если оно молчит дольше QUICK_HEDGE_SEC (могли молча оборвать) —
    параллельно тот же запрос по новому. Берём первый ответ."""
    answers = queue.Queue()

    def attempt(reuse):
        try:
            answers.put(("ok", CONNECTIONS.get(server, path, headers, QUICK_TIMEOUT, reuse=reuse)))
        except Exception as error:
            answers.put(("error", error))

    threading.Thread(target=attempt, args=(True,), daemon=True).start()
    started, deadline = 1, time.time() + QUICK_TIMEOUT + 1
    failures = 0

    while failures < started:
        wait = QUICK_HEDGE_SEC if started == 1 else max(0.1, deadline - time.time())

        try:
            kind, value = answers.get(timeout=wait)
        except queue.Empty:
            kind, value = "slow", None

        if kind == "ok":
            return value

        if kind == "error":
            failures += 1

        if started == 1 and kind in ("slow", "error"):
            threading.Thread(target=attempt, args=(False,), daemon=True).start()
            started = 2
        elif time.time() > deadline:
            break

    raise ServerError("offline")


def fetch_check(server, key, mint, lang, stage="full"):
    """Быстрая — по тёплому соединению с таймаутом QUICK_TIMEOUT и повтором по новому;
    полная — всегда по новому соединению (она и так идёт секунды, зато без риска «мёртвого»)."""
    headers = {"X-Api-Key": key, "User-Agent": f"SolFastTrackChecker/{VERSION}"}
    path = f"/api/check/{mint}?lang={lang}&stage={stage}"

    if stage == "quick":
        status, body = hedged_get(server, path, headers)
    else:
        try:
            status, body = CONNECTIONS.get(server, path, headers, REQUEST_TIMEOUT, reuse=False)
        except (http.client.HTTPException, urllib.error.URLError, TimeoutError, OSError):
            raise ServerError("offline") from None

    if status == 200:
        try:
            return json.loads(body.decode("utf-8"))
        except Exception:
            raise ServerError("failed") from None

    try:
        code = json.loads(body.decode("utf-8")).get("error") or str(status)
    except Exception:
        code = "unauthorized" if status == 401 else str(status)

    raise ServerError(code)


def download_logo(url, mint):
    """Логотип токена для уведомления (100×100 PNG с сервера бота), кэш на диске."""
    if not url or not url.startswith(("https://", "http://")):
        return None

    folder = app_dir() / "logos"
    folder.mkdir(exist_ok=True)
    path = folder / f"{mint}.png"

    if path.exists() and time.time() - path.stat().st_mtime < 86400:
        return path

    try:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        url_path = parts.path + (f"?{parts.query}" if parts.query else "")
        status, data = CONNECTIONS.get(base, url_path, {"User-Agent": f"SolFastTrackChecker/{VERSION}"}, 10, reuse=False)

        if status != 200 or len(data) > 2_000_000:
            return None

        if data[:8] != b"\x89PNG\r\n\x1a\n":
            return None

        path.write_bytes(data)
        return path
    except Exception:
        return None


# ------------------------------------------------------------------ Windows: буфер, уведомления, автозапуск

CF_UNICODETEXT = 13


class Clipboard:
    """Чтение буфера обмена через WinAPI; изменения ловим по счётчику GetClipboardSequenceNumber."""

    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.user32.GetClipboardData.restype = ctypes.c_void_p
        self.user32.GetClipboardData.argtypes = [ctypes.c_uint]
        self.user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        self.kernel32.GlobalLock.restype = ctypes.c_void_p
        self.kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        self.kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]

    def sequence(self):
        return self.user32.GetClipboardSequenceNumber()

    def text(self):
        for _attempt in range(5):
            if self.user32.OpenClipboard(None):
                break
            time.sleep(0.03)
        else:
            return None

        try:
            if not self.user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return None

            handle = self.user32.GetClipboardData(CF_UNICODETEXT)

            if not handle:
                return None

            pointer = self.kernel32.GlobalLock(handle)

            if not pointer:
                return None

            try:
                return ctypes.wstring_at(pointer)
            finally:
                self.kernel32.GlobalUnlock(handle)
        finally:
            self.user32.CloseClipboard()


def start_menu_shortcut_path():
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_NAME}.lnk"


def ensure_start_menu_shortcut():
    """Ярлык в меню «Пуск» с AppUserModelID программы.

    Windows 10/11 показывает уведомления обычной (не из Store) программы, только если у неё есть
    ярлык в «Пуске» с этим ID. Создаём при каждом запуске — вдруг exe перенесли в другую папку.
    """
    import pythoncom
    from win32com.propsys import propsys, pscon
    from win32com.shell import shell

    pythoncom.CoInitialize()
    path = start_menu_shortcut_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    frozen = getattr(sys, "frozen", False)
    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
    link.SetPath(sys.executable)
    link.SetArguments("" if frozen else f'"{os.path.abspath(__file__)}"')
    link.SetWorkingDirectory(os.path.dirname(sys.executable))
    link.SetIconLocation(sys.executable, 0)
    link.SetDescription(APP_NAME)
    store = link.QueryInterface(propsys.IID_IPropertyStore)
    store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_ID, pythoncom.VT_LPWSTR))
    store.Commit()
    link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(path), 0)

    return path


def shortcut_app_id(path):
    """AUMID, записанный в ярлыке (для самопроверки)."""
    from win32com.propsys import propsys, pscon

    store = propsys.SHGetPropertyStoreFromParsingName(str(path))
    return store.GetValue(pscon.PKEY_AppUserModel_ID).GetValue()


def register_app_id(icon_path):
    """Имя и значок программы для уведомлений (реестр текущего пользователя, без прав админа)."""
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, rf"SOFTWARE\Classes\AppUserModelId\{APP_ID}") as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)

        if icon_path:
            winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(icon_path))


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_enabled():
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, "SolFastTrackChecker")
            return True
    except OSError:
        return False


def set_autostart(enabled):
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            target = f'"{sys.executable}"' if getattr(sys, "frozen", False) else f'"{sys.executable}" "{os.path.abspath(__file__)}"'
            winreg.SetValueEx(key, "SolFastTrackChecker", 0, winreg.REG_SZ, target)
        else:
            try:
                winreg.DeleteValue(key, "SolFastTrackChecker")
            except OSError:
                pass


def single_instance():
    """True — мы единственная копия. Именованный mutex живёт, пока жив процесс."""
    kernel32 = ctypes.windll.kernel32
    single_instance.handle = kernel32.CreateMutexW(None, False, "Local\\SolFastTrackCheckerMutex")
    return kernel32.GetLastError() != 183      # ERROR_ALREADY_EXISTS


def message_box(text, title=APP_NAME):
    if IS_WINDOWS:
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)


def load_winrt_modules():
    """Модули WinRT, которые windows-toasts подгружает неявно (при показе). Явный импорт — чтобы
    PyInstaller положил их в exe: без collections уведомление падало ещё до показа."""
    import winrt.windows.data.xml.dom  # noqa: F401
    import winrt.windows.foundation  # noqa: F401
    import winrt.windows.foundation.collections  # noqa: F401
    import winrt.windows.ui.notifications  # noqa: F401


class Notifier:
    """Уведомления Windows через WinRT (windows-toasts): текст идёт как данные XML, без PowerShell.

    Объект уведомлений WinRT можно трогать только из потока, где он создан (иначе
    RPC_E_WRONG_THREAD), а показывают уведомления разные потоки (проверки, меню трея). Поэтому
    у уведомлений свой поток: он создаёт объект и показывает всё из очереди."""

    def __init__(self, app_id=APP_ID, sink=None):
        self.app_id = app_id
        self.sink = sink                  # самопроверка: вместо показа отдать уведомление сюда
        self.jobs = queue.Queue()
        self.ready = threading.Event()
        self.error = None
        threading.Thread(target=self.loop, name="toasts", daemon=True).start()
        self.ready.wait(15)

        if self.error:
            raise self.error

    def loop(self):
        try:
            try:
                import pythoncom

                pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
            except Exception:
                log("toasts: CoInitializeEx: " + traceback.format_exc())

            load_winrt_modules()
            from windows_toasts import InteractableWindowsToaster

            toaster = InteractableWindowsToaster(APP_NAME, notifierAUMID=self.app_id)

            if self.sink is not None:
                toaster.toastNotifier = self.sink
        except Exception as error:
            self.error = error
            self.ready.set()
            return

        self.ready.set()

        while True:
            args, kwargs, done = self.jobs.get()
            result = None

            try:
                toaster.show_toast(self.build(*args, **kwargs))
            except Exception as error:
                result = error
                log("toast failed: " + traceback.format_exc())

            if done is not None:
                done.append(result)

    @staticmethod
    def build(lines, buttons=(), image=None, click=None, loud=False, sound=True):
        from windows_toasts import AudioSource, Toast, ToastAudio, ToastButton, ToastDisplayImage, ToastImagePosition

        toast = Toast([line for line in lines if line])

        if image:
            toast.AddImage(ToastDisplayImage.fromPath(str(image), position=ToastImagePosition.AppLogo, circleCrop=True))

        for label, url in buttons[:5]:
            if url:
                toast.AddAction(ToastButton(label, launch=url))

        if click:
            toast.launch_action = click

        toast.audio = ToastAudio(AudioSource.Reminder if loud else AudioSource.Default, silent=not sound)
        toast.on_failed = lambda args: log(f"toast rejected by Windows: {getattr(args, 'error_code', args)!r}")

        return toast

    def show(self, *args, **kwargs):
        """Поставить уведомление в очередь (из любого потока)."""
        self.jobs.put((args, kwargs, None))

    def show_and_wait(self, *args, timeout=15, **kwargs):
        """Показать и дождаться результата: None — показано, иначе исключение (для самопроверки)."""
        done = []
        self.jobs.put((args, kwargs, done))
        deadline = time.time() + timeout

        while not done and time.time() < deadline:
            time.sleep(0.05)

        return done[0] if done else TimeoutError("toast thread did not answer")


def tray_icon_image(size=64):
    """Значок программы: щит с галочкой (рисуется, отдельный файл не нужен)."""
    from PIL import Image, ImageDraw

    scale = 4
    big = size * scale
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    w = big
    shield = [(w * 0.5, w * 0.06), (w * 0.88, w * 0.2), (w * 0.84, w * 0.58), (w * 0.5, w * 0.94),
              (w * 0.16, w * 0.58), (w * 0.12, w * 0.2)]
    draw.polygon(shield, fill=(124, 77, 255, 255))
    draw.line([(w * 0.32, w * 0.5), (w * 0.45, w * 0.64), (w * 0.7, w * 0.36)], fill=(255, 255, 255, 255),
              width=int(w * 0.09), joint="curve")

    return image.resize((size, size))


# ------------------------------------------------------------------ окно с полной проверкой

REPORT_TAG_RE = re.compile(r'<(/?)(b|code|a)(?:\s+href="([^"]*)")?\s*>')
# Эмодзи (одиночные, с FE0F, флаги, keycap, ZWJ-цепочки) — рисуем цветными картинками.
EMOJI_RE = re.compile(
    "(?:[\U0001F1E6-\U0001F1FF]{2}"
    "|[0-9#*]\uFE0F?\u20E3"
    "|(?:[\U0001F000-\U0001FAFF\u2300-\u23FF\u2600-\u27BF\u2B00-\u2BFF\u3030\u303D\u3297\u3299]"
    "|[\u00A9\u00AE\u203C\u2049\u2122\u2139\u2194-\u21AA\u24C2\u25AA-\u25FE]\uFE0F)"
    "\uFE0F?[\U0001F3FB-\U0001F3FF]?(?:\u200D[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF]\uFE0F?)*)"
)
THEME = {
    "bg": "#16171c", "panel": "#20222a", "fg": "#e9eaef", "muted": "#8b90a0", "border": "#2e313b",
    "link": "#7fb2ff", "code": "#d2b8ff", "button": "#2b2e38", "button_hover": "#383c49",
}
POPUP_SECONDS = 15                         # окно само закрывается (пока курсор на нём — нет)
POPUP_MAX = 3                              # одновременно на экране


def score_color(score):
    if not isinstance(score, int):
        return "#8b90a0"
    if score < 20:
        return "#ff4d4f"
    if score < 40:
        return "#ff7a29"
    if score < 60:
        return "#f5b014"
    if score < 80:
        return "#d9d02b"
    return "#22c55e"


def report_segments(report_html):
    """Отчёт бота → [(текст, жирный, код, ссылка)]: то же, что видно в Telegram."""
    text = sanitize_report(report_html)
    segments = []
    bold = code = 0
    href = None
    pos = 0

    def emit(chunk):
        if chunk:
            segments.append((html.unescape(chunk), bold > 0, code > 0, href))

    for match in REPORT_TAG_RE.finditer(text):
        emit(text[pos:match.start()])
        pos = match.end()
        closing, tag, link = match.group(1) == "/", match.group(2), match.group(3)

        if tag == "b":
            bold = max(0, bold + (-1 if closing else 1))
        elif tag == "code":
            code = max(0, code + (-1 if closing else 1))
        else:
            href = None if closing else html.unescape(link or "") or None

    emit(text[pos:])
    return segments


def split_emoji(text):
    """[(кусок, это_эмодзи)] — эмодзи отдельно, чтобы вставить их цветными картинками."""
    parts = []
    pos = 0

    for match in EMOJI_RE.finditer(text):
        if match.start() > pos:
            parts.append((text[pos:match.start()], False))
        parts.append((match.group(0), True))
        pos = match.end()

    if pos < len(text):
        parts.append((text[pos:], False))

    return parts


class EmojiImages:
    """Цветные эмодзи Segoe UI Emoji через Pillow (Tk сам рисует их только чёрно-белыми)."""

    def __init__(self, size):
        self.size = size
        self.cache = {}
        self.font = None

        from PIL import ImageFont

        windows_font = Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts" / "seguiemj.ttf"

        for path in (str(windows_font), "seguiemj.ttf", "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"):
            try:
                self.font = ImageFont.truetype(path, 109)        # цветной растр у этих шрифтов — 109 px
                break
            except Exception:
                continue

        if self.font is None:
            log("emoji font not found, emoji stay as text")

    def pil(self, emoji):
        from PIL import Image, ImageDraw

        if self.font is None:
            return None

        key = emoji.replace("\uFE0F", "") or emoji
        canvas = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.text((80, 80), key, font=self.font, embedded_color=True, anchor="mm")
        box = canvas.getbbox()

        if not box:
            return None

        side = max(box[2] - box[0], box[3] - box[1])
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        square = canvas.crop((int(cx - side / 2), int(cy - side / 2), int(cx + side / 2), int(cy + side / 2)))
        return square.resize((self.size, self.size), Image.LANCZOS)

    def get(self, emoji):
        if emoji not in self.cache:
            image = None

            try:
                from PIL import ImageTk

                picture = self.pil(emoji)
                image = ImageTk.PhotoImage(picture) if picture else None
            except Exception:
                log("emoji render: " + traceback.format_exc())

            self.cache[emoji] = image

        return self.cache[emoji]


def work_area():
    """Рабочая область экрана без панели задач: (left, top, right, bottom)."""
    if IS_WINDOWS:
        rect = (ctypes.c_long * 4)()

        if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0):
            return tuple(rect)

    return None


def window_handle(window):
    """HWND окна-обёртки Tk (именно у него стиль и фокус)."""
    try:
        return int(window.wm_frame(), 16)
    except Exception:
        return ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()


def no_activate(window):
    """Окно не забирает фокус (печатаешь дальше там, где был) и не появляется на панели задач."""
    if not IS_WINDOWS:
        return None

    user32 = ctypes.windll.user32
    hwnd = window_handle(window)
    get_style = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    set_style = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
    get_style.restype = ctypes.c_ssize_t
    get_style.argtypes = [ctypes.c_void_p, ctypes.c_int]
    set_style.restype = ctypes.c_ssize_t
    set_style.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
    style = get_style(hwnd, -20)                                 # GWL_EXSTYLE
    set_style(hwnd, -20, style | 0x08000000 | 0x00000080)        # WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
    return hwnd


def ours(hwnd):
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == os.getpid()


def give_focus_back(before):
    """Если фокус оказался у нашей программы — вернуть его туда, где человек работал.
    Если человек сам переключился на другое окно — ничего не трогаем."""
    if not IS_WINDOWS or not before or ours(before):
        return

    user32 = ctypes.windll.user32
    current = user32.GetForegroundWindow()

    if current == before or (current and not ours(current)):
        return

    if not user32.SetForegroundWindow(before):
        # Запасной путь: на время подключиться к очереди ввода окна, у которого был фокус.
        kernel32 = ctypes.windll.kernel32
        target = user32.GetWindowThreadProcessId(before, None)

        thread = kernel32.GetCurrentThreadId()

        if target and target != thread and user32.AttachThreadInput(thread, target, True):
            try:
                user32.SetForegroundWindow(before)
            finally:
                user32.AttachThreadInput(thread, target, False)


class UI:
    """Все окна программы живут в одном потоке Tk; остальные потоки шлют сюда задания."""

    def __init__(self, checker):
        self.checker = checker
        self.jobs = queue.Queue()
        self.ready = threading.Event()
        self.error = None
        self.root = None
        self.popups = []
        threading.Thread(target=self.loop, name="ui", daemon=True).start()
        self.ready.wait(20)

        if self.error:
            raise self.error
        if self.root is None:
            raise RuntimeError("ui thread did not start")

    def loop(self):
        try:
            import tkinter as tk
            import tkinter.font as tkfont

            self.root = tk.Tk()
            self.root.withdraw()
            self.scale = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
            self.fonts = {
                "body": tkfont.Font(root=self.root, family="Segoe UI", size=10),
                "bold": tkfont.Font(root=self.root, family="Segoe UI", size=10, weight="bold"),
                "code": tkfont.Font(root=self.root, family="Consolas", size=10),
                "title": tkfont.Font(root=self.root, family="Segoe UI Semibold", size=12),
                "small": tkfont.Font(root=self.root, family="Segoe UI", size=9),
            }
            self.emoji = EmojiImages(max(14, int(self.fonts["body"].metrics("linespace") * 0.92)))
            self.root.update_idletasks()
            no_activate(self.root)            # скрытое главное окно Tk тоже не должно забирать фокус
        except Exception as error:
            self.error = error
            self.ready.set()
            return

        self.ready.set()
        self.root.after(40, self.poll)
        self.root.mainloop()

    def poll(self):
        while True:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                break

            try:
                job()
            except Exception:
                log("ui: " + traceback.format_exc())

        self.root.after(40, self.poll)

    def call(self, function, wait=False, timeout=600):
        """Выполнить в потоке окон. wait=True — дождаться и вернуть результат."""
        if not wait:
            self.jobs.put(function)
            return None

        done = threading.Event()
        box = {}

        def job():
            try:
                box["value"] = function()
            except Exception as error:
                box["error"] = error
            finally:
                done.set()

        self.jobs.put(job)
        done.wait(timeout)

        if "error" in box:
            raise box["error"]

        return box.get("value")

    def px(self, value):
        return int(round(value * self.scale))

    # --- карточки
    def place(self):
        area = work_area() or (0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        margin = self.px(12)
        bottom = area[3] - margin

        for popup in reversed(self.popups):             # новые — снизу
            popup.update_idletasks()
            width, height = popup.winfo_reqwidth(), popup.winfo_reqheight()
            popup.geometry(f"+{area[2] - width - margin}+{max(area[1] + margin, bottom - height)}")
            bottom -= height + self.px(8)

    def close(self, popup):
        if popup in self.popups:
            self.popups.remove(popup)

        try:
            popup.destroy()
        except Exception:
            pass

        self.place()

    def button(self, parent, text, command):
        import tkinter as tk

        parts = split_emoji(text)
        image = None

        if parts and parts[0][1]:
            image = self.emoji.get(parts[0][0])
            text = "".join(chunk for chunk, _ in parts[1:]).strip() if image is not None else text

        label = tk.Label(parent, text=(" " + text) if image is not None else text, image=image, compound="left",
                         bg=THEME["button"], fg=THEME["fg"], font=self.fonts["small"],
                         padx=self.px(10), pady=self.px(5), cursor="hand2")
        label.bind("<Button-1>", lambda _e: command())
        label.bind("<Enter>", lambda _e: label.configure(bg=THEME["button_hover"]))
        label.bind("<Leave>", lambda _e: label.configure(bg=THEME["button"]))
        return label

    def text_with_emoji(self, widget, text, tags=()):
        for chunk, is_emoji in split_emoji(text):
            image = self.emoji.get(chunk) if is_emoji else None

            if image is not None:
                widget.image_create("end", image=image, padx=1, align="center")
                for tag in tags:
                    widget.tag_add(tag, "end-2c", "end-1c")
            else:
                widget.insert("end", chunk, tags)

    def popup_frame(self, accent, seconds):
        """Пустая карточка: рамка, цветная полоса, автозакрытие с паузой под курсором."""
        import tkinter as tk

        popup = tk.Toplevel(self.root)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg=THEME["border"])
        body = tk.Frame(popup, bg=THEME["bg"])
        body.pack(fill="both", expand=True, padx=1, pady=1)
        popup.bar = tk.Frame(body, bg=accent, height=self.px(4))
        popup.bar.pack(fill="x")
        popup.seconds = seconds
        popup.state_info = {"left": seconds, "hover": False, "pinned": False}

        def enter(_event):
            popup.state_info["hover"] = True

        def leave(event):
            x, y = event.x_root, event.y_root
            inside = (popup.winfo_rootx() <= x < popup.winfo_rootx() + popup.winfo_width()
                      and popup.winfo_rooty() <= y < popup.winfo_rooty() + popup.winfo_height())
            popup.state_info["hover"] = inside

        popup.bind("<Enter>", enter)
        popup.bind("<Leave>", leave)

        def tick():
            if not popup.winfo_exists():
                return
            info = popup.state_info
            if not info["hover"] and not info["pinned"]:
                info["left"] -= 1
                if info["left"] <= 0:
                    self.close(popup)
                    return
            popup.after(1000, tick)

        popup.after(1000, tick)
        return popup, body

    def line(self, parent, parts, font, height=1):
        """Строка текста с цветными эмодзи: parts = [(текст, цвет | None)]."""
        import tkinter as tk

        widget = tk.Text(parent, height=height, bd=0, highlightthickness=0, bg=THEME["bg"], fg=THEME["fg"],
                         font=font, wrap="word", cursor="arrow", width=1, padx=0, pady=0)

        for index, (text, color) in enumerate(parts):
            tags = ()

            if color:
                widget.tag_configure(f"c{index}", foreground=color)
                tags = (f"c{index}",)

            self.text_with_emoji(widget, text, tags)

        widget.configure(state="disabled")
        return widget

    def header(self, body, popup, parts, subtitle, logo_image):
        import tkinter as tk

        row = tk.Frame(body, bg=THEME["bg"])
        row.pack(fill="x", padx=self.px(12), pady=(self.px(10), self.px(6)))

        if logo_image is not None:
            popup.logo_label = tk.Label(row, image=logo_image, bg=THEME["bg"])
            popup.logo_label.pack(side="left", padx=(0, self.px(10)))

        close = tk.Label(row, text="✕", bg=THEME["bg"], fg=THEME["muted"], font=self.fonts["title"], cursor="hand2")
        close.pack(side="right", anchor="n")
        close.bind("<Button-1>", lambda _e: self.close(popup))
        texts = tk.Frame(row, bg=THEME["bg"])
        texts.pack(side="left", fill="x", expand=True)
        self.line(texts, parts, self.fonts["title"]).pack(anchor="w", fill="x")

        if subtitle:
            sub = self.line(texts, [(subtitle, THEME["muted"])], self.fonts["small"],
                            height=1 if len(subtitle) < 52 else 2)
            sub.pack(anchor="w", fill="x")

    def logo_image(self, path, score, symbol):
        from PIL import Image, ImageDraw, ImageTk

        size = self.px(44)
        big = size * 4

        try:
            picture = Image.open(path).convert("RGBA").resize((big, big), Image.LANCZOS) if path else None
        except Exception:
            picture = None

        if picture is None:
            picture = Image.new("RGBA", (big, big), score_color(score))
            draw = ImageDraw.Draw(picture)

            try:
                from PIL import ImageFont

                font = ImageFont.truetype("segoeuib.ttf", int(big * 0.42))
            except Exception:
                font = None

            letter = (re.sub(r"[^0-9A-Za-zА-Яа-я]", "", symbol or "") or "?")[0].upper()
            draw.text((big / 2, big / 2), letter, fill="white", font=font, anchor="mm")

        mask = Image.new("L", (big, big), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
        picture.putalpha(mask)
        return ImageTk.PhotoImage(picture.resize((size, size), Image.LANCZOS))

    def show(self, popup):
        self.popups.append(popup)

        while len(self.popups) > POPUP_MAX:
            self.close(self.popups[0])

        before = ctypes.windll.user32.GetForegroundWindow() if IS_WINDOWS else None
        popup.update_idletasks()
        self.place()
        popup.deiconify()
        popup.update_idletasks()
        popup.hwnd = no_activate(popup)       # обёртка Tk появляется только при показе
        give_focus_back(before)

        for delay in (50, 250):                # Tk активирует своё приложение с задержкой
            popup.after(delay, lambda: give_focus_back(before))

    def show_report(self, payload, logo_path, report_path, seconds=POPUP_SECONDS, status=None):
        """Карточка с полной проверкой — тот же отчёт, что бот присылает в чат."""
        import tkinter as tk

        score = payload.get("score") if isinstance(payload.get("score"), int) else None
        popup, body = self.popup_frame(score_color(score), seconds)
        popup.content = tk.Frame(body, bg=THEME["bg"])
        popup.content.pack(fill="both", expand=True)
        self.fill_report(popup, payload, logo_path, report_path, status)
        self.show(popup)
        return popup

    def update_report(self, popup, payload, logo_path, report_path, status=None):
        """Подставить в уже открытое окно новые данные (полную проверку вместо быстрой)."""
        if popup not in self.popups or not popup.winfo_exists():
            return None                   # окно уже закрыли (✕ или само) — заново не открываем

        position = popup.report_text.yview()[0] if getattr(popup, "report_text", None) else 0.0

        for child in popup.content.winfo_children():
            child.destroy()

        score = payload.get("score") if isinstance(payload.get("score"), int) else None
        popup.bar.configure(bg=score_color(score))
        self.fill_report(popup, payload, logo_path, report_path, status)

        if position:
            popup.report_text.yview_moveto(position)

        if not popup.state_info["pinned"]:
            popup.state_info["left"] = popup.seconds         # новое содержимое — время заново

        self.place()
        return popup

    def set_logo(self, popup, logo_path, payload):
        if popup not in self.popups or not popup.winfo_exists() or not getattr(popup, "logo_label", None):
            return

        score = payload.get("score") if isinstance(payload.get("score"), int) else None
        image = self.logo_image(logo_path, score, payload.get("symbol"))
        popup.images.append(image)
        popup.logo_label.configure(image=image)
        popup.logo_path = logo_path

    def fill_report(self, popup, payload, logo_path, report_path, status=None):
        import tkinter as tk

        body = popup.content
        score = payload.get("score") if isinstance(payload.get("score"), int) else None
        logo_path = logo_path or getattr(popup, "logo_path", None)
        popup.logo_path = logo_path
        popup.images = [self.logo_image(logo_path, score, payload.get("symbol"))]
        parts = [(f"${payload.get('symbol') or '?'}   ", None),
                 (f"{score if score is not None else '?'}/100", score_color(score))]
        self.header(body, popup, parts, f"{payload.get('emoji', '')} {payload.get('verdict', '')}".strip(),
                    popup.images[0])

        if status:
            self.line(body, [(status, THEME["muted"])], self.fonts["small"]).pack(
                fill="x", padx=self.px(14), pady=(0, self.px(6)))

        frame = tk.Frame(body, bg=THEME["panel"])
        frame.pack(fill="both", expand=True, padx=self.px(10))
        text = tk.Text(frame, bd=0, highlightthickness=0, bg=THEME["panel"], fg=THEME["fg"], font=self.fonts["body"],
                       wrap="word", width=52, padx=self.px(10), pady=self.px(8), spacing1=1, spacing3=1,
                       cursor="arrow", insertwidth=0)
        popup.report_text = text
        text.tag_configure("b", font=self.fonts["bold"])
        text.tag_configure("code", font=self.fonts["code"], foreground=THEME["code"])

        for index, (chunk, bold, code, href) in enumerate(report_segments(payload.get("report_html"))):
            tags = (["b"] if bold else []) + (["code"] if code else [])

            if href:
                name = f"link{index}"
                text.tag_configure(name, foreground=THEME["link"], underline=True)
                text.tag_bind(name, "<Button-1>", lambda _e, url=href: webbrowser.open(url))
                text.tag_bind(name, "<Enter>", lambda _e: text.configure(cursor="hand2"))
                text.tag_bind(name, "<Leave>", lambda _e: text.configure(cursor="arrow"))
                tags.append(name)

            self.text_with_emoji(text, chunk, tuple(tags))

        text.configure(state="disabled")
        scroll = tk.Scrollbar(frame, command=text.yview, width=self.px(12))
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)

        def pin(_event=None):
            popup.state_info["pinned"] = True          # начал читать/листать — само не закроется

        text.bind("<Button-1>", pin, add="+")
        text.bind("<MouseWheel>", lambda e: (pin(), text.yview_scroll(-1 if e.delta > 0 else 1, "units"), "break")[-1])
        scroll.bind("<Button-1>", pin, add="+")

        # Высота: весь отчёт, но не выше ~70% экрана (дальше — прокрутка).
        popup.update_idletasks()
        lines = text.count("1.0", "end", "displaylines")
        lines = (lines[0] if isinstance(lines, tuple) else lines) or 20
        area = work_area() or (0, 0, 1280, 800)
        line_px = self.fonts["body"].metrics("linespace") + 2
        max_lines = max(8, int((area[3] - area[1]) * 0.7 / line_px) - 6)
        text.configure(height=min(lines, max_lines))

        if lines > max_lines:
            scroll.pack(side="right", fill="y")

        links_row = payload.get("links") or {}
        mint = payload.get("mint") or ""
        buttons = tk.Frame(body, bg=THEME["bg"])
        buttons.pack(fill="x", padx=self.px(10), pady=self.px(10))
        T = self.checker.T

        for label, url in (("📈 DexScreener", links_row.get("dexscreener")), ("🛡 RugCheck", links_row.get("rugcheck")),
                           ("GMGN", links_row.get("gmgn"))):
            if url and url.startswith("https://"):
                self.button(buttons, label, lambda url=url: webbrowser.open(url)).pack(side="left", padx=(0, self.px(6)))

        # «Отчёт» есть всегда (серый, пока полный отчёт не готов) — ширина окна не прыгает.
        report_button = self.button(buttons, T("report"),
                                    lambda: report_path and webbrowser.open(report_path.as_uri()))
        report_button.pack(side="left", padx=(0, self.px(6)))

        if not report_path:
            report_button.configure(fg=THEME["muted"], cursor="arrow")

        def copy_ca():
            self.checker.seen[mint] = time.time()      # своё копирование не проверяем повторно
            self.root.clipboard_clear()
            self.root.clipboard_append(mint)
            pin()

        if mint:
            self.button(buttons, T("copy_ca"), copy_ca).pack(side="left")

    def show_notice(self, text, seconds=8):
        """Короткая служебная карточка (подсказка, ошибка)."""
        import tkinter as tk

        popup, body = self.popup_frame(THEME["link"], seconds)
        popup.images = []
        self.header(body, popup, [(APP_NAME, None)], "", None)
        tk.Label(body, text=text, bg=THEME["bg"], fg=THEME["fg"], font=self.fonts["body"], justify="left",
                 anchor="w", wraplength=self.px(360)).pack(fill="x", padx=self.px(12), pady=(0, self.px(12)))
        self.show(popup)
        return popup


# ------------------------------------------------------------------ программа

class Checker:
    def __init__(self):
        self.config = load_config()
        self.recent = []                  # [(время, mint, подпись, путь к отчёту)]
        self.seen = {}                    # mint -> когда проверяли
        self.last_notice = {}             # ошибка -> когда сообщали (не спамим)
        self.icon = None
        self.notifier = None
        self.ui = None
        self.stop = threading.Event()

    def T(self, key):
        return TEXTS["ru" if self.config.get("lang") == "ru" else "en"][key]

    def window_mode(self):
        """Показывать своё окно с полной проверкой (по умолчанию) или уведомление Windows."""
        return self.ui is not None and self.config.get("mode", "window") == "window"

    def say(self, text, sound=False, seconds=8):
        if self.window_mode():
            self.ui.call(lambda: self.ui.show_notice(text, seconds=seconds))
        elif self.notifier:
            self.notifier.show([APP_NAME, text], sound=sound)

    def notice(self, key, every=120):
        """Служебное сообщение (ошибка, подсказка) — не чаще раза в every секунд."""
        now = time.time()

        if now - self.last_notice.get(key, 0) < every:
            return

        self.last_notice[key] = now
        self.say(self.T(key))

    # --- буфер обмена
    def keep_warm(self):
        """Раз в WARM_EVERY_SEC — лёгкий запрос к серверу: соединения открыты, проверка не ждёт TLS."""
        while not self.stop.is_set():
            server = self.config.get("server")

            if server and not self.config.get("paused"):
                try:
                    CONNECTIONS.warm(server)
                except Exception:
                    log("warm: " + traceback.format_exc())

            self.stop.wait(WARM_EVERY_SEC)

    def watch_clipboard(self):
        clipboard = Clipboard()
        last = clipboard.sequence()

        while not self.stop.is_set():
            time.sleep(CLIPBOARD_POLL_SEC)

            try:
                current = clipboard.sequence()

                if current == last:
                    continue

                last = current

                if self.config.get("paused"):
                    continue

                mint = extract_mint(clipboard.text())

                if mint:
                    self.submit(mint)
            except Exception:
                log("clipboard: " + traceback.format_exc())

    def submit(self, mint, force=False):
        now = time.time()

        if not force and now - self.seen.get(mint, 0) < REPEAT_SEC:
            return

        self.seen[mint] = now
        # Каждая проверка — в своём потоке: новая монета никогда не ждёт за медленной.
        threading.Thread(target=self.run_check, args=(mint,), daemon=True).start()

    def run_check(self, mint):
        try:
            self.check(mint)
        except Exception:
            log("check: " + traceback.format_exc())

    def test_notification(self):
        lang = "ru" if self.config.get("lang") == "ru" else "en"

        if self.window_mode():
            sample = dict(DEMO_PAYLOADS[lang])
            self.ui.call(lambda: self.ui.show_report(sample, None, None))
        elif self.notifier:
            self.notifier.show([APP_NAME, self.T("test_text")], sound=self.config.get("sound", True))

        log(f"test notification, window={self.window_mode()}, toast id={getattr(self.notifier, 'app_id', None)}")

    def check_clipboard_now(self):
        try:
            mint = extract_mint(Clipboard().text())
        except Exception:
            mint = None

        if mint:
            self.submit(mint, force=True)

    # --- проверки
    def check(self, mint):
        """Быстрая и полная проверка параллельно: окно — по первому ответу (обычно 1–2 с),
        полная подставляется в то же окно. Логотип подгружается в уже открытое окно."""
        server, key = self.config.get("server"), self.config.get("key")

        if not server or not key:
            self.notice("need_code", every=60)
            return

        lang = self.config.get("lang", "ru")
        card = {"popup": None, "full": False, "lock": threading.Lock(), "payload": None}
        started = time.time()

        if self.icon:
            self.icon.title = f"{APP_NAME} — {self.T('checking')} {mint[:4]}…{mint[-4:]}"

        def quick():
            if not self.window_mode():
                return

            try:
                payload = fetch_check(server, key, mint, lang, stage="quick")
            except ServerError as error:
                log(f"quick {mint}: {error.code}")
                return

            final = payload.get("stage") != "quick"           # сервер мог сразу отдать полную

            with card["lock"]:
                if card["full"]:
                    return

                card["payload"] = payload
                status = None if final else self.T("deep_pending")
                card["popup"] = self.ui.call(lambda: self.ui.show_report(payload, None, None, status=status), wait=True)

            if self.config.get("sound", True):
                score = payload.get("score")
                beep(isinstance(score, int) and score < 40)     # звук — когда окно появилось

            log(f"quick {mint}: {payload.get('score')} in {time.time() - started:.1f}s")
            logo = download_logo(payload.get("logo"), mint)

            if logo:
                self.ui.call(lambda: self.ui.set_logo(card["popup"], logo, card["payload"] or payload))

        threading.Thread(target=quick, daemon=True).start()

        try:
            payload = fetch_check(server, key, mint, lang)
        except ServerError as error:
            log(f"check {mint}: {error.code}")

            with card["lock"]:
                card["full"] = True
                popup, shown = card["popup"], card["payload"]

            if popup is not None and shown is not None:
                self.ui.call(lambda: self.ui.update_report(popup, shown, None, None, status=self.T("deep_failed")))
            elif error.code == "not_found":
                pass                      # скопировали не токен (кошелёк и т.п.) — молчим
            elif error.code == "unauthorized":
                self.notice("bad_key", every=60)
            elif error.code == "no_vip":
                self.notice("no_vip", every=300)
            elif error.code == "rate_limited":
                self.notice("rate", every=30)
            elif error.code == "offline":
                self.notice("offline")
            else:
                self.notice("failed", every=20)
            return
        finally:
            if self.icon:
                self.icon.title = APP_NAME

        report = save_report(payload)
        links = payload.get("links") or {}
        score = payload.get("score") if isinstance(payload.get("score"), int) else 50

        self.recent.insert(0, (time.time(), mint, f"${payload.get('symbol', '?')} — {score}/100", report))
        del self.recent[10:]

        if self.window_mode():
            with card["lock"]:
                card["full"] = True
                popup = card["popup"]

                opened = popup is None

                if opened:
                    popup = card["popup"] = self.ui.call(lambda: self.ui.show_report(payload, None, report), wait=True)
                else:
                    self.ui.call(lambda: self.ui.update_report(popup, payload, None, report))

            if opened and self.config.get("sound", True):
                beep(score < 40)                  # окна быстрой проверки не было — звук сейчас

            logo = download_logo(payload.get("logo"), mint)

            if logo and popup is not None:
                self.ui.call(lambda: self.ui.set_logo(popup, logo, payload))
        elif self.notifier:
            logo = download_logo(payload.get("logo"), mint)
            self.notifier.show(
                toast_lines(payload),
                buttons=[("📈 DexScreener", links.get("dexscreener")), ("🛡 RugCheck", links.get("rugcheck")),
                         (self.T("report"), report.as_uri())],
                image=logo,
                click=report.as_uri(),
                loud=score < 40,
                sound=self.config.get("sound", True),
            )

        if self.icon:
            self.icon.update_menu()

        log(f"check {mint}: {score} in {time.time() - started:.1f}s")

    # --- код подключения
    def settings_window(self, closed=None):
        """Окно для кода подключения (в потоке окон); после сохранения — пробная проверка wSOL."""
        import tkinter as tk
        from tkinter import messagebox

        root = self.ui.root
        window = tk.Toplevel(root)
        window.title(self.T("dialog_title"))
        window.resizable(False, False)
        window.attributes("-topmost", True)
        frame = tk.Frame(window, padx=16, pady=14)
        frame.pack()
        tk.Label(frame, text=self.T("dialog_text"), wraplength=440, justify="left").pack(anchor="w")
        entry = tk.Entry(frame, width=62)
        entry.pack(pady=10, fill="x")
        entry.insert(0, "")
        lang = tk.StringVar(value=self.config.get("lang", "ru"))
        row = tk.Frame(frame)
        row.pack(anchor="w")
        tk.Radiobutton(row, text="Русский", variable=lang, value="ru").pack(side="left")
        tk.Radiobutton(row, text="English", variable=lang, value="en").pack(side="left")
        status = tk.Label(frame, text="", fg="#666")
        status.pack(anchor="w", pady=(6, 0))
        save_button = tk.Button(frame, text=self.T("dialog_save"))
        save_button.pack(pady=(8, 0))

        def finish():
            window.destroy()

            if self.icon:
                self.icon.update_menu()
            if closed is not None:
                closed.set()

        def save():
            parsed = parse_connection_code(entry.get())

            if not parsed:
                messagebox.showerror(APP_NAME, self.T("dialog_bad"), parent=window)
                return

            self.config.update({"server": parsed[0], "key": parsed[1], "lang": lang.get()})
            save_config(self.config)
            save_button.configure(state="disabled")
            status.configure(text=self.T("dialog_checking"))

            def test():
                try:
                    fetch_check(parsed[0], parsed[1], "So11111111111111111111111111111111111111112", lang.get())
                    result = (messagebox.showinfo, self.T("dialog_ok"))
                except ServerError as error:
                    text = self.T("no_vip") if error.code == "no_vip" else self.T("dialog_fail") + error.code
                    result = (messagebox.showwarning, text)

                def done():
                    result[0](APP_NAME, result[1], parent=window)
                    finish()

                self.ui.call(done)

            threading.Thread(target=test, daemon=True).start()

        save_button.configure(command=save)
        window.bind("<Return>", lambda _e: save())
        window.protocol("WM_DELETE_WINDOW", finish)
        window.update_idletasks()
        x = (window.winfo_screenwidth() - window.winfo_reqwidth()) // 2
        y = (window.winfo_screenheight() - window.winfo_reqheight()) // 3
        window.geometry(f"+{x}+{y}")
        window.lift()
        window.focus_force()
        entry.focus_set()

    def open_settings(self):
        if self.ui:
            self.ui.call(self.settings_window)

    # --- трей
    def build_menu(self):
        import pystray

        def toggle(name, default=False):
            def action(_icon, _item):
                self.config[name] = not self.config.get(name, default)
                save_config(self.config)
                self.icon.update_menu()
            return action

        def switch_mode(_icon, _item):
            self.config["mode"] = "toast" if self.config.get("mode", "window") == "window" else "window"
            save_config(self.config)
            self.icon.update_menu()

        def switch_lang(_icon, _item):
            self.config["lang"] = "en" if self.config.get("lang") == "ru" else "ru"
            save_config(self.config)
            self.icon.update_menu()

        def switch_autostart(_icon, _item):
            set_autostart(not autostart_enabled())
            self.icon.update_menu()

        def recent_items():
            if not self.recent:
                return [pystray.MenuItem(self.T("empty"), None, enabled=False)]

            return [
                pystray.MenuItem(label, (lambda path: lambda _i, _it: webbrowser.open(path.as_uri()))(path))
                for _ts, _mint, label, path in self.recent
            ]

        def quit_app(icon, _item):
            self.stop.set()
            icon.stop()

        return pystray.Menu(
            pystray.MenuItem(lambda _i: self.T("paused") if self.config.get("paused") else self.T("running"), None, enabled=False),
            pystray.MenuItem(lambda _i: self.T("pause"), toggle("paused"), checked=lambda _i: bool(self.config.get("paused"))),
            pystray.MenuItem(lambda _i: self.T("recent"), pystray.Menu(recent_items)),
            pystray.MenuItem(lambda _i: self.T("check_now"), lambda _i, _it: self.check_clipboard_now()),
            pystray.MenuItem(lambda _i: self.T("test"), lambda _i, _it: self.test_notification()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda _i: self.T("window_mode"), switch_mode,
                             checked=lambda _i: self.config.get("mode", "window") == "window",
                             enabled=lambda _i: self.ui is not None),
            pystray.MenuItem(lambda _i: self.T("sound"), toggle("sound", True), checked=lambda _i: bool(self.config.get("sound", True))),
            pystray.MenuItem(lambda _i: self.T("lang"), switch_lang),
            pystray.MenuItem(lambda _i: self.T("autostart"), switch_autostart, checked=lambda _i: autostart_enabled()),
            pystray.MenuItem(lambda _i: self.T("settings"), lambda _i, _it: self.open_settings()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda _i: self.T("quit"), quit_app),
        )

    def run(self):
        import pystray

        if not single_instance():
            message_box(self.T("already"))
            return

        set_dpi_aware()
        icon_image = tray_icon_image(64)
        icon_path = app_dir() / "icon.png"
        icon_image.resize((256, 256)).save(icon_path)

        try:
            register_app_id(icon_path)
        except Exception:
            log("register app id: " + traceback.format_exc())

        app_id = APP_ID

        try:
            log(f"start menu shortcut: {ensure_start_menu_shortcut()}")
        except Exception:
            log("shortcut failed, using fallback app id: " + traceback.format_exc())
            app_id = FALLBACK_APP_ID

        try:
            self.notifier = Notifier(app_id)
        except Exception:
            log("notifier: " + traceback.format_exc())

        try:
            self.ui = UI(self)
        except Exception:
            log("ui: " + traceback.format_exc())

        if not self.config.get("server") or not self.config.get("key"):
            if self.ui:
                closed = threading.Event()
                self.ui.call(lambda: self.settings_window(closed))
                closed.wait()
            else:
                message_box(self.T("need_code"))

        threading.Thread(target=self.watch_clipboard, daemon=True).start()
        threading.Thread(target=self.keep_warm, daemon=True).start()
        self.say(self.T("started"), seconds=5)
        self.icon = pystray.Icon("SolFastTrackChecker", icon_image, APP_NAME, self.build_menu())
        log(f"started {VERSION}, window={self.window_mode()}")
        self.icon.run()


def set_dpi_aware():
    """Чёткие окна на экранах с масштабом 125–200%."""
    if not IS_WINDOWS:
        return

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def beep(loud=False):
    try:
        import winsound

        winsound.MessageBeep(0x30 if loud else 0x40)        # MB_ICONEXCLAMATION / MB_ICONASTERISK
    except Exception:
        pass


# ------------------------------------------------------------------ самопроверка (для сборки)

SAMPLE_PAYLOAD = {
    "ok": True, "mint": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU", "symbol": "TEST<&>\"$(calc)", "score": 33,
    "emoji": "⛔", "verdict": "Лучше не покупать", "stats": "💧 $3.3K · 📊 $35.9K · 🎂 7 мин",
    "flags": [{"level": "danger", "points": -15, "text": "Создатель запустил 19,257 токенов — фабрика токенов"},
              {"level": "warn", "points": -8, "text": "Создатель купил 18% при запуске"}],
    "report_html": '🔎 <b>Проверка</b>\n<code>7xKX</code> <script>alert(1)</script> <a href="https://dexscreener.com/x">Dex</a> '
                   '<a href="javascript:alert(1)">bad</a> <img src=x onerror=alert(1)>',
    "logo": None,
    "links": {"dexscreener": "https://dexscreener.com/solana/x", "rugcheck": "https://rugcheck.xyz/tokens/x"},
}


DEMO_MINT = "DemoTokenMint1111111111111111111111111pump"
DEMO_LINKS = {"dexscreener": f"https://dexscreener.com/solana/{DEMO_MINT}",
              "rugcheck": f"https://rugcheck.xyz/tokens/{DEMO_MINT}", "gmgn": f"https://gmgn.ai/sol/token/{DEMO_MINT}"}
# Пример (тестовое окно): отчёт сгенерирован тем же кодом бота, что и настоящие проверки.
DEMO_PAYLOADS = {
    "ru": {"mint": DEMO_MINT, "symbol": "DEMO", "score": 72, "emoji": "🟡",
           "verdict": "Можно покупать, но с небольшими опасениями", "links": DEMO_LINKS,
           "report_html": "🔎 <b>Проверка токена</b>\n\n🪙 <b>$DEMO</b> (Demo Cat)\n📄 <code>DemoTokenMint1111111111111111111111111pump</code>\n\n🟡 <b>Оценка безопасности: 72/100</b>  ███████░░░\n<b>Можно покупать, но с небольшими опасениями</b>\n\n💲 Цена: <b>$0.0000881</b>  (5м +4.2% · 1ч -12.5% · 24ч +85.0%)\n📊 Рыночная капитализация: <b>$88,100</b>\n💧 Ликвидность: <b>$23,400</b>\n👥 Держателей: <b>349</b>\n🎂 Возраст: <b>3 дн</b> (по первому пулу) · 🏦 pumpswap\n📈 Кривая pump.fun: <b>✅ выпущен на PumpSwap</b>\n\n🔒 Безопасность:\n• Mint-право: <b>✅ Отключено</b>\n• Freeze-право: <b>✅ Отключено</b>\n• Блокировка ликвидности (LP): <b>❔ н/д</b>\n• Топ-10 держателей: <b>❔ н/д</b>\n• Бандл при запуске: <b>⚠️ 4 кошелька купили 6.5%</b> в первом блоке · создатель купил 2.0%\n• Снайперы (блоки +1…+3): <b>✅ 7 · 4.1%</b>\n• Бандл и снайперы ещё держат: <b>✅ 2.0%</b>\n• Свежие кошельки в топ-10: <b>✅ 1/10 · 1.3%</b>\n• Риски (rug): <b>✅ не найдено</b>\n\n💣 Создатель: <code>Dev111</code>\n\n⚠️ Что снижает оценку:\n• Статус блокировки ликвидности неизвестен (-8)\n• Скромная ликвидность ($23,400) (-7)\n• 4 кошельков купили 6% в блоке запуска (-6)\n• Доля топ-10 холдеров неизвестна (-5)\n• Умеренное число держателей (349) (-2)\n\nℹ️ Автоматическая оценка по открытым данным, не финансовая рекомендация. Высокая оценка не гарантирует безопасность — не вкладывай больше, чем готов потерять.\n\n📈 <a href=\"https://dexscreener.com/solana/DemoTokenMint1111111111111111111111111pump\">DexScreener</a> · 🛡 <a href=\"https://rugcheck.xyz/tokens/DemoTokenMint1111111111111111111111111pump\">RugCheck</a> · 🔍 <a href=\"https://solscan.io/token/DemoTokenMint1111111111111111111111111pump\">Solscan</a>"},
    "en": {"mint": DEMO_MINT, "symbol": "DEMO", "score": 72, "emoji": "🟡",
           "verdict": "You can buy, but with some caution", "links": DEMO_LINKS,
           "report_html": "🔎 <b>Token check</b>\n\n🪙 <b>$DEMO</b> (Demo Cat)\n📄 <code>DemoTokenMint1111111111111111111111111pump</code>\n\n🟡 <b>Safety score: 72/100</b>  ███████░░░\n<b>You can buy, but with some caution</b>\n\n💲 Price: <b>$0.0000881</b>  (5m +4.2% · 1h -12.5% · 24h +85.0%)\n📊 Market cap: <b>$88,100</b>\n💧 Liquidity: <b>$23,400</b>\n👥 Holders: <b>349</b>\n🎂 Age: <b>3 d</b> (by first pool) · 🏦 pumpswap\n📈 Bonding curve: <b>✅ graduated to PumpSwap</b>\n\n🔒 Security:\n• Mint authority: <b>✅ Disabled</b>\n• Freeze authority: <b>✅ Disabled</b>\n• Liquidity lock (LP): <b>❔ N/A</b>\n• Top 10 holders: <b>❔ N/A</b>\n• Launch bundle: <b>⚠️ 4 wallets bought 6.5%</b> in the first block · creator bought 2.0%\n• Snipers (blocks +1…+3): <b>✅ 7 · 4.1%</b>\n• Bundle + snipers still hold: <b>✅ 2.0%</b>\n• Fresh wallets in top 10: <b>✅ 1/10 · 1.3%</b>\n• Rug risks: <b>✅ none flagged</b>\n\n💣 Creator: <code>Dev111</code>\n\n⚠️ What lowers the score:\n• Liquidity lock status unknown (-8)\n• Modest liquidity ($23,400) (-7)\n• 4 wallets bought 6% in the launch block (-6)\n• Top-10 holders share unknown (-5)\n• Moderate number of holders (349) (-2)\n\nℹ️ Automatic estimate from public data, not financial advice. A high score does not guarantee safety — never invest more than you can afford to lose.\n\n📈 <a href=\"https://dexscreener.com/solana/DemoTokenMint1111111111111111111111111pump\">DexScreener</a> · 🛡 <a href=\"https://rugcheck.xyz/tokens/DemoTokenMint1111111111111111111111111pump\">RugCheck</a> · 🔍 <a href=\"https://solscan.io/token/DemoTokenMint1111111111111111111111111pump\">Solscan</a>"},
}


FOCUS_DUMMY_TITLE = "SolFastTrackChecker focus test"


def focus_dummy():
    """Окно «другой программы» для самопроверки фокуса (отдельный процесс)."""
    import tkinter as tk

    root = tk.Tk()
    root.title(FOCUS_DUMMY_TITLE)
    root.geometry("300x120+40+40")
    tk.Entry(root).pack(padx=20, pady=40)
    root.after(30000, root.destroy)
    root.focus_force()
    root.mainloop()


def start_focus_dummy():
    """Запустить «другую программу» и отдать ей фокус. HWND её окна или None."""
    import subprocess

    command = [sys.executable, "--focus-dummy"] if getattr(sys, "frozen", False) else \
        [sys.executable, str(Path(__file__).resolve()), "--focus-dummy"]
    subprocess.Popen(command)
    user32 = ctypes.windll.user32
    deadline = time.time() + 15

    while time.time() < deadline:
        hwnd = user32.FindWindowW(None, FOCUS_DUMMY_TITLE)

        if hwnd:
            time.sleep(0.5)
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.5)
            return hwnd if user32.GetForegroundWindow() == hwnd else None

        time.sleep(0.2)

    return None


def selftest(out_path=None):
    results = []

    def check(condition, label):
        results.append(("PASS " if condition else "FAIL ") + label)

    mint = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
    check(extract_mint(mint) == mint, "plain contract")
    check(extract_mint(f"https://pump.fun/coin/{mint}") == mint, "pump.fun link")
    check(extract_mint(f"https://gmgn.ai/sol/token/{mint}?ref=1") == mint, "gmgn link")
    check(extract_mint("hello world") is None, "no contract in text")
    check(extract_mint("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA") is None, "system program ignored")
    check(extract_mint("x" * 700 + mint) is None, "long text ignored")
    code = "sftd1:" + base64.urlsafe_b64encode(json.dumps({"u": "https://bot.example.com/", "k": "abc"}).encode()).decode().rstrip("=")
    check(parse_connection_code(code) == ("https://bot.example.com", "abc"), "connection code")
    check(parse_connection_code("nope") is None, "bad connection code")
    lines = toast_lines(SAMPLE_PAYLOAD)
    check(len(lines) == 3 and "33/100" in lines[0] and "фабрика" in lines[2], "toast lines")
    page = report_page(SAMPLE_PAYLOAD)
    check("<script" not in page and "javascript:" not in page and "onerror" not in page and "<b>Проверка</b>" in page
          and 'href="https://dexscreener.com/x"' in page and "&lt;&amp;&gt;" in page, "report page sanitized")

    segments = report_segments(DEMO_PAYLOADS["ru"]["report_html"])
    joined = "".join(chunk for chunk, *_ in segments)
    check("<" not in joined and any(bold for _, bold, _, _ in segments) and any(code for _, _, code, _ in segments)
          and any(href and href.startswith("https://dexscreener.com/") for *_, href in segments)
          and "Оценка безопасности: 72/100" in joined, "report segments")
    check(all("<" not in chunk or "&lt;" in chunk or "<&>" in chunk for chunk, *_ in report_segments(SAMPLE_PAYLOAD["report_html"]))
          and not any(href and not href.startswith("https://") for *_, href in report_segments(SAMPLE_PAYLOAD["report_html"])),
          "report segments sanitized")
    check(split_emoji("🔎 Проверка ⚠️ риск 中文 → 1️⃣ 🇺🇸 👨‍💻") == [
        ("🔎", True), (" Проверка ", False), ("⚠️", True), (" риск 中文 → ", False), ("1️⃣", True), (" ", False),
        ("🇺🇸", True), (" ", False), ("👨‍💻", True)], "emoji split")

    if IS_WINDOWS:
        try:
            set_dpi_aware()
            checker = Checker()
            ui = checker.ui = UI(checker)
            user32 = ctypes.windll.user32
            dummy = start_focus_dummy()
            before = user32.GetForegroundWindow()
            results.append(f"INFO foreground before: {'other process window' if dummy and before == dummy else before}")
            logo = Path(app_dir()) / "selftest-logo.png"
            tray_icon_image(64).save(logo)
            popup = ui.call(lambda: ui.show_report(DEMO_PAYLOADS["ru"], logo, None), wait=True)
            notice = ui.call(lambda: ui.show_notice(TEXTS["ru"]["started"]), wait=True)
            time.sleep(1.0)
            area = work_area()
            geometry = ui.call(lambda: [(p.winfo_rootx(), p.winfo_rooty(), p.winfo_width(), p.winfo_height())
                                        for p in (popup, notice)], wait=True)
            visible = all(user32.IsWindowVisible(p.hwnd) for p in (popup, notice))
            inside = all(area[0] <= x and area[1] <= y and x + w <= area[2] + 1 and y + h <= area[3] + 1
                         for x, y, w, h in geometry)
            check(visible and inside, f"report window shown: {geometry} in {area}")
            after = user32.GetForegroundWindow()

            def describe(hwnd):
                name = ctypes.create_unicode_buffer(256)
                title = ctypes.create_unicode_buffer(256)
                pid = ctypes.c_ulong()
                user32.GetClassNameW(hwnd, name, 256)
                user32.GetWindowTextW(hwnd, title, 256)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                own = "ours" if pid.value == os.getpid() else f"pid {pid.value}"
                return f"{hwnd} {name.value!r} {title.value!r} {own}"

            if dummy:
                user32.PostMessageW(dummy, 0x0010, 0, 0)                 # WM_CLOSE

            check(after == before and (not dummy or before == dummy),
                  f"report window does not take focus (before={describe(before)}, "
                                   f"after={describe(after)}, popups={[popup.hwnd, notice.hwnd]}, "
                                   f"root={window_handle(ui.root)})")
            emoji = ui.emoji.pil("🔴")
            check(emoji is not None and any(r > 180 and g < 90 and b < 90 and a > 200 for r, g, b, a in emoji.getdata()),
                  "color emoji")
            widths = ui.call(lambda: popup.winfo_reqwidth(), wait=True)
            ui.call(lambda: ui.update_report(popup, DEMO_PAYLOADS["en"], logo, logo), wait=True)
            closed = ui.call(lambda: ui.show_report(DEMO_PAYLOADS["ru"], None, None), wait=True)
            ui.call(lambda: ui.close(closed), wait=True)
            reopened = ui.call(lambda: ui.update_report(closed, DEMO_PAYLOADS["ru"], None, logo), wait=True)
            check(reopened is None and closed not in ui.popups, "closed window is not reopened by the full check")
            ui.call(lambda: ui.set_logo(popup, logo, DEMO_PAYLOADS["en"]), wait=True)
            same = ui.call(lambda: popup in ui.popups and popup.winfo_exists() and popup.report_text.winfo_exists(), wait=True)
            check(same and abs(ui.call(lambda: popup.winfo_reqwidth(), wait=True) - widths) <= ui.px(4),
                  "report window updated in place")
            ui.call(lambda: checker.settings_window(), wait=True)
            ui.call(lambda: [w.destroy() for w in ui.root.winfo_children()], wait=True)
            check(True, "settings window")
        except Exception as error:
            check(False, f"report window: {error!r}")

        try:
            import pystray  # noqa: F401
            from windows_toasts import InteractableWindowsToaster  # noqa: F401

            import tempfile

            Notifier.build(lines, buttons=[("DexScreener", "https://dexscreener.com")], click="https://x.y")
            check(True, "winrt toast object")
        except Exception as error:
            check(False, f"winrt toast object: {error!r}")

        class Sink:
            def __init__(self):
                self.shown = []

            def show(self, notification):
                self.shown.append(notification)

        try:
            # Как в программе: объект уведомлений живёт в своём потоке, показ заказывает другой
            # поток (в 1.0.2 здесь было RPC_E_WRONG_THREAD). Весь путь — кроме вывода на экран.
            ensure_start_menu_shortcut()
            sink = Sink()
            notifier = Notifier(APP_ID, sink=sink)
            logo = Path(tempfile.gettempdir()) / "sftc-selftest-logo.png"
            tray_icon_image(64).save(logo)
            outcome = []
            caller = threading.Thread(target=lambda: outcome.append(notifier.show_and_wait(
                lines, buttons=[("📈 DexScreener", "https://dexscreener.com"), ("🛡 RugCheck", None),
                                ("📄 Report", logo.as_uri())],
                image=logo, click=logo.as_uri(), loud=True, sound=False)))
            caller.start()
            caller.join(20)
            check(outcome == [None] and len(sink.shown) == 1, f"toast pipeline from worker thread: {outcome!r}")

            if outcome != [None]:
                import faulthandler

                dump = Path(tempfile.gettempdir()) / "sftc-threads.txt"
                with open(dump, "w") as handle:
                    faulthandler.dump_traceback(handle, all_threads=True)
                results.append("INFO threads:\n" + dump.read_text(errors="replace"))
        except Exception as error:
            check(False, f"toast pipeline from worker thread: {error!r}")

        try:
            # Настоящий показ — только для сведения: на сервере сборки нет рабочего стола.
            real = Notifier(APP_ID).show_and_wait([APP_NAME, "selftest"], sound=False, timeout=8)
            results.append(f"INFO real toast on this machine: {real!r}")
        except Exception as error:
            results.append(f"INFO real toast on this machine: {error!r}")

        try:
            tray_icon_image(64)
            check(True, "tray icon")
        except Exception as error:
            check(False, f"tray icon: {error!r}")

        try:
            Clipboard().sequence()
            check(True, "clipboard api")
        except Exception as error:
            check(False, f"clipboard api: {error!r}")

        try:
            path = ensure_start_menu_shortcut()
            check(path.exists() and shortcut_app_id(path) == APP_ID, "start menu shortcut with app id")
        except Exception as error:
            check(False, f"start menu shortcut: {error!r}")

    ok = not any(r.startswith("FAIL") for r in results)
    text = "\n".join(results + ["SELFTEST " + ("OK" if ok else "FAILED")])

    if out_path:
        Path(out_path).write_text(text, encoding="utf-8")
    elif sys.stdout:
        print(text)

    return 0 if ok else 1


def main():
    if "--focus-dummy" in sys.argv:
        focus_dummy()
        return

    if "--selftest" in sys.argv:
        index = sys.argv.index("--selftest")
        out = sys.argv[index + 1] if len(sys.argv) > index + 1 else None
        sys.exit(selftest(out))

    if not IS_WINDOWS:
        print("This program is for Windows. Selftest: python sol_checker.py --selftest")
        sys.exit(1)

    try:
        Checker().run()
    except Exception:
        log("fatal: " + traceback.format_exc())
        message_box("Error, see log: " + str(app_dir() / "checker.log"))


if __name__ == "__main__":
    main()
