"""Desktop launcher for the Azur Lane chibi viewer.

Double-click behaviour:
  * remembers the AssetBundles folder in %APPDATA%\\ALChibiViewer\\config.json
  * starts the local viewer server and opens the default browser
  * keeps a small window with the URL, so the server can be stopped again

Frozen with PyInstaller (see build.ps1).  `--selftest` starts the server on a
random port, requests a few endpoints, writes a JSON report and exits, which is
how the packaged build is verified without a browser.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser

APP_NAME = "碧蓝航线小人预览器"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "ALChibiViewer")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
ERROR_LOG = os.path.join(CONFIG_DIR, "error.log")


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_config(data: dict) -> None:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def load_root() -> str:
    return load_config().get("root", "")


def save_root(root: str) -> None:
    data = load_config()
    data["root"] = root
    save_config(data)


def load_browser_pref() -> str:
    return load_config().get("browser", "")


def save_browser_pref(path: str) -> None:
    data = load_config()
    data["browser"] = path
    save_config(data)


def log_error(text: str) -> None:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(text + "\n\n")
    except Exception:
        pass


def valid_root(path: str) -> bool:
    return bool(path) and os.path.isdir(os.path.join(path, "char"))


def open_url(url: str) -> bool:
    """Try every Windows way of handing a URL to a browser, and log which one worked."""
    attempts = []

    def attempt(name, fn):
        try:
            ok = bool(fn())
        except Exception as exc:  # noqa: BLE001 - logged for the user
            attempts.append(f"{name}=ERR({type(exc).__name__}: {exc})")
            return False
        attempts.append(f"{name}={'ok' if ok else 'no'}")
        return ok

    if attempt("webbrowser", lambda: webbrowser.open(url, new=2)):
        launch_log("open_url: " + ", ".join(attempts))
        return True
    if attempt("startfile", lambda: os.startfile(url) or True):
        launch_log("open_url: " + ", ".join(attempts))
        return True
    if attempt("cmd-start", lambda: subprocess.Popen(
            ["cmd", "/c", "start", "", url], creationflags=0x08000000) and True):
        launch_log("open_url: " + ", ".join(attempts))
        return True
    if attempt("rundll32", lambda: subprocess.Popen(
            ["rundll32.exe", "url.dll,FileProtocolHandler", url],
            creationflags=0x08000000) and True):
        launch_log("open_url: " + ", ".join(attempts))
        return True
    if attempt("explorer", lambda: subprocess.Popen(["explorer.exe", url]) and True):
        launch_log("open_url: " + ", ".join(attempts))
        return True

    launch_log("open_url: all methods failed -> " + ", ".join(attempts))
    return False


BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
]


def registry_browser() -> str:
    """Edge installed outside Program Files (or a Store build) is only found here."""
    try:
        import winreg
    except Exception:
        return ""
    subkeys = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
    )
    for sub in subkeys:
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, sub) as key:
                    path = winreg.QueryValue(key, None)
                path = (path or "").strip('"').strip()
                if path and os.path.isfile(path):
                    return path
            except OSError:
                pass
    return ""


def find_browser(preferred: str = "") -> str:
    for path in ([preferred] if preferred else []) + BROWSER_CANDIDATES:
        if path and os.path.isfile(path):
            return path
    return registry_browser()


def launch_log(msg: str) -> None:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(os.path.join(CONFIG_DIR, "launch.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def is_elevated() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def integrity_level() -> int:
    """Own process integrity level (8192 medium, 4096 low)."""
    try:
        import ctypes
        import ctypes.wintypes as wt

        adv = ctypes.WinDLL("advapi32")
        k32 = ctypes.WinDLL("kernel32")
        tok = wt.HANDLE()
        if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(tok)):
            return 0
        buf = ctypes.create_string_buffer(128)
        size = wt.DWORD(0)
        if not adv.GetTokenInformation(tok, 25, buf, 128, ctypes.byref(size)):
            return 0
        sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
        count = ctypes.cast(ctypes.c_void_p(sid + 1), ctypes.POINTER(ctypes.c_ubyte))[0]
        subs = ctypes.cast(ctypes.c_void_p(sid + 8), ctypes.POINTER(ctypes.c_uint))
        return int(subs[count - 1])
    except Exception:
        return 0


def relaunch_unelevated() -> bool:
    """explorer.exe runs at medium integrity, so starting through it drops the admin token.

    Chromium refuses to hand a URL to an elevated instance ("existing instance is
    running with elevated privileges"), so running this app as admin breaks the
    browser launch.  Restarting ourselves through Explorer fixes that.
    """
    if not getattr(sys, "frozen", False) or os.environ.get("AL_NO_RELAUNCH") == "1":
        return False
    try:
        env = dict(os.environ, AL_NO_RELAUNCH="1")
        subprocess.Popen(["explorer.exe", sys.executable], env=env)
        launch_log("elevated: relaunched through explorer.exe")
        return True
    except Exception as exc:
        launch_log(f"elevated: relaunch failed {type(exc).__name__}: {exc}")
        return False


def launch_app_window(url: str):
    """Open the viewer in a chromeless Edge/Chrome window (no tabs, no address bar)."""
    exe = find_browser(load_browser_pref())
    if not exe:
        launch_log("app window: no Edge/Chrome found")
        return None
    # A fresh profile per run: a previous run may have left an elevated browser
    # holding the old profile, which makes Chromium refuse the hand-off.
    profile = os.path.join(CONFIG_DIR, f"browser-{os.getpid()}")
    try:
        os.makedirs(profile, exist_ok=True)
        args = [
            exe,
            f"--app={url}",
            "--window-size=1520,960",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate",
            f"--user-data-dir={profile}",
        ]
        proc = subprocess.Popen(args, cwd=os.path.dirname(exe))
        launch_log(f"app window: started pid={proc.pid} exe={exe}")
        return proc
    except Exception as exc:
        launch_log(f"app window: Popen failed {type(exc).__name__}: {exc}")
    try:  # second try: let it join the normal browser profile
        proc = subprocess.Popen([exe, f"--app={url}"], cwd=os.path.dirname(exe))
        launch_log(f"app window: started without profile pid={proc.pid}")
        return proc
    except Exception as exc:
        launch_log(f"app window: profile-less launch failed {type(exc).__name__}: {exc}")
        return None


def guess_root() -> str:
    """Look in the places an AssetBundles folder usually ends up on Windows."""
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, "Documents", "MuMuSharedFolder", "Download", "AssetBundles"),
        r"D:\AzurLane\AssetBundles",
        r"C:\AzurLane\AssetBundles",
        r"D:\Games\AzurLane\AssetBundles",
    ]
    for cand in candidates:
        if valid_root(cand):
            return os.path.normpath(cand)
    return ""


# --------------------------------------------------------------------- server
class ServerThread(threading.Thread):
    def __init__(self, httpd):
        super().__init__(daemon=True)
        self.httpd = httpd

    def run(self):
        self.httpd.serve_forever(poll_interval=0.2)


def start_server(root: str):
    import server  # imported lazily so --help stays fast

    try:
        httpd, port = server.create_server(root, port=8765, config_path=CONFIG_PATH)
    except OSError:
        httpd, port = server.create_server(root, port=0, config_path=CONFIG_PATH)
    thread = ServerThread(httpd)
    thread.start()
    return httpd, thread, port


# ------------------------------------------------------------------- selftest
def selftest(root: str, log_path: str) -> int:
    report = {"root": root, "ok": False}
    httpd = None

    def get(path, timeout=60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}" + path, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"HTTP {exc.code} on {path}: {body}") from None

    def post(path, payload):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}" + path, data=data,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"HTTP {exc.code} on {path}: {body}") from None

    try:
        httpd, _thread, port = start_server(root)
        names = json.loads(get("/api/chars"))
        meta = json.loads(get("/api/meta/2b"))
        atlas_len = len(get("/api/asset/2b/" + meta["atlas"]))
        skel_len = len(get("/api/asset/2b/" + meta["skel"]))
        index_len = len(get("/"))
        state = json.loads(get("/api/state"))
        switched = post("/api/root", {"root": state["root"]})

        report.update({
            "ok": True, "port": port, "chars": len(names), "meta": meta,
            "atlasBytes": atlas_len, "skelBytes": skel_len, "indexBytes": index_len,
            "state": state, "switch": switched,
        })
        code = 0
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
        code = 1
    finally:
        if httpd is not None:
            httpd.shutdown()

    try:
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    except Exception:
        code = 2
    return code


VIEWER_TITLE = "小人动画预览"


def viewer_window_exists() -> bool:
    """True if a top-level window with the viewer page title is on screen."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def callback(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    if VIEWER_TITLE in buf.value:
                        found.append(hwnd)
            return True

        user32.EnumWindows(callback, 0)
        return bool(found)
    except Exception:
        return False


# ------------------------------------------------------------------------ GUI
def run_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class App:
        def __init__(self, win: tk.Tk):
            self.win = win
            self.httpd = None
            self.thread = None
            self.url = ""
            self.auto_started = False
            self.edge_proc = None
            self.viewer_seen = False
            self.viewer_misses = 0
            self.fallback_done = False

            win.title(APP_NAME)
            win.geometry("640x360")
            win.minsize(600, 330)

            try:
                win.iconbitmap(default=os.path.join(getattr(sys, "_MEIPASS", ""), "app.ico"))
            except Exception:
                pass

            frm = ttk.Frame(win, padding=16)
            frm.pack(fill="both", expand=True)

            ttk.Label(frm, text="素材目录（AssetBundles，内含 char/）").grid(row=0, column=0, sticky="w")
            self.path_var = tk.StringVar(value=load_root() or guess_root())
            entry = ttk.Entry(frm, textvariable=self.path_var)
            entry.grid(row=1, column=0, sticky="ew", pady=(4, 0))
            ttk.Button(frm, text="浏览…", command=self.pick).grid(row=1, column=1, padx=(8, 0), pady=(4, 0))

            self.url_var = tk.StringVar(value="（尚未启动）")
            url_row = ttk.Frame(frm)
            url_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
            self.url_entry = ttk.Entry(url_row, textvariable=self.url_var, state="readonly")
            self.url_entry.pack(side="left", fill="x", expand=True)
            ttk.Button(url_row, text="复制地址", command=self.copy_url).pack(side="left", padx=(8, 0))

            self.status = tk.StringVar(value="未启动")
            ttk.Label(frm, textvariable=self.status, foreground="#3a6ea5").grid(
                row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))

            self.hint = tk.StringVar(
                value="双击后会自动启动并尝试打开浏览器；没弹出的话点“复制地址”粘到浏览器里。")
            ttk.Label(frm, textvariable=self.hint, foreground="#777").grid(
                row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))

            level = integrity_level()
            if 0 < level < 0x2000:
                launch_log(f"running at low integrity ({level}); browser launch will fail")
                self.hint.set("检测到低权限沙箱：这个文件夹带“低完整性”标签。"
                              "浏览器无法启动，请把整个文件夹复制到 D 盘等普通目录后再运行。")

            btns = ttk.Frame(frm)
            btns.grid(row=5, column=0, columnspan=2, sticky="w", pady=(16, 0))
            self.btn_open = ttk.Button(btns, text="打开预览", command=self.open_browser, state="disabled")
            self.btn_open.pack(side="left")
            self.btn_start = ttk.Button(btns, text="启动", command=self.start)
            self.btn_start.pack(side="left", padx=(8, 0))
            self.btn_stop = ttk.Button(btns, text="停止", command=self.stop, state="disabled")
            self.btn_stop.pack(side="left", padx=(8, 0))
            ttk.Button(btns, text="退出", command=self.quit).pack(side="left", padx=(8, 0))

            extra = ttk.Frame(frm)
            extra.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
            ttk.Button(extra, text="选择浏览器…", command=self.pick_browser).pack(side="left")
            ttk.Button(extra, text="诊断报告", command=self.diagnose).pack(side="left", padx=(8, 0))

            self.browser_lbl = tk.StringVar(value=load_browser_pref() and f"浏览器：{load_browser_pref()}")
            ttk.Label(frm, textvariable=self.browser_lbl, foreground="#777").grid(
                row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))

            frm.columnconfigure(0, weight=1)
            win.protocol("WM_DELETE_WINDOW", self.quit)

            win.after(150, self.autostart)

        # ------------------------------------------------------------- actions
        def autostart(self):
            if self.auto_started:
                return
            self.auto_started = True
            if valid_root(self.path_var.get()):
                self.start()
            else:
                self.status.set("请选择 AssetBundles 目录后点“启动”")

        def pick(self):
            initial = self.path_var.get() or os.path.expanduser("~")
            path = filedialog.askdirectory(title="选择 AssetBundles 目录（里面应能看到 char）", initialdir=initial)
            if path:
                self.path_var.set(os.path.normpath(path))

        def start(self):
            root = self.path_var.get().strip()
            if not valid_root(root):
                messagebox.showerror(APP_NAME, "这个目录下没有找到 char/ 文件夹。\n请选择游戏的 AssetBundles 目录。")
                return
            if self.httpd is not None:
                return
            try:
                self.httpd, self.thread, port = start_server(root)
            except Exception as exc:
                log_error(traceback.format_exc())
                messagebox.showerror(APP_NAME, f"启动失败：{exc}")
                return
            save_root(root)
            self.url = f"http://127.0.0.1:{port}/"
            self.url_var.set(self.url)
            self.btn_open.configure(state="normal")
            self.btn_stop.configure(state="normal")
            self.btn_start.configure(state="disabled")

            self.edge_proc = launch_app_window(self.url)
            if self.edge_proc is not None:
                self.status.set("已在应用窗口打开（本窗口已最小化）")
                self.hint.set("关闭应用窗口即退出；要换素材目录就把本窗口还原。")
                self.viewer_seen = False
                self.viewer_misses = 0
                self.fallback_done = False
                self.win.after(800, self.poll_edge)
                self.win.after(500, self.win.iconify)
            else:
                ok = self.open_browser()
                self.status.set("运行中" if ok else "运行中（浏览器未自动打开，请复制地址）")
                if is_elevated():
                    self.hint.set("检测到管理员权限：浏览器会拒绝连接。请直接双击 exe，不要用“以管理员身份运行”。")
                else:
                    self.hint.set("关掉本窗口即停止服务。")

        def stop(self):
            if self.httpd is None:
                return
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
            self.httpd = None
            self.thread = None
            self.url = ""
            self.url_var.set("（已停止）")
            self.status.set("已停止")
            self.hint.set("可以重新点“启动”。")
            self.btn_open.configure(state="disabled")
            self.btn_stop.configure(state="disabled")
            self.btn_start.configure(state="normal")

        def poll_edge(self):
            """Keep the app alive while a viewer window exists.

            msedge.exe often is just a launcher: the process exits as soon as the
            real browser process has the window, so a dead child does not mean the
            window failed.  Watch the window title instead.
            """
            if self.httpd is None:
                return
            if viewer_window_exists():
                self.viewer_seen = True
                self.viewer_misses = 0
            else:
                self.viewer_misses += 1
                if self.viewer_seen:
                    self.quit()
                    return
                if self.viewer_misses >= 8 and not self.fallback_done:
                    self.fallback_done = True
                    launch_log("no viewer window after 6s, falling back to default browser")
                    self.status.set("没等到应用窗口，改用默认浏览器…")
                    if not self.open_browser():
                        self.status.set("浏览器也没能打开，地址已复制到剪贴板。")
            self.win.after(800, self.poll_edge)

        def pick_browser(self):
            path = filedialog.askopenfilename(
                title="选择 msedge.exe 或 chrome.exe",
                filetypes=[("浏览器程序", "*.exe"), ("所有文件", "*.*")])
            if not path:
                return
            path = os.path.normpath(path)
            if not os.path.isfile(path):
                return
            save_browser_pref(path)
            self.browser_lbl.set(f"浏览器：{path}")
            self.status.set("已记住这个浏览器，点“打开预览”试试。")
            launch_log(f"browser preference set to {path}")

        def diagnose(self):
            found = find_browser(load_browser_pref())
            lines = [
                f"程序路径: {sys.executable}",
                f"管理员权限: {is_elevated()}",
                f"配置的浏览器: {load_browser_pref() or '(未设置)'}",
                f"实际使用浏览器: {found or '(没找到)'}",
                f"服务地址: {self.url or '(未启动)'}",
            ]
            if self.url:
                try:
                    with urllib.request.urlopen(self.url + "api/state", timeout=5) as r:
                        lines.append(f"服务状态: HTTP {r.status} {r.read(200).decode('utf-8', 'replace')}")
                except Exception as exc:
                    lines.append(f"服务状态: 访问失败 {type(exc).__name__}: {exc}")
            lines.append(f"日志文件: {os.path.join(CONFIG_DIR, 'launch.log')}")
            text = "\n".join(lines)
            launch_log("diagnose:\n" + text)
            messagebox.showinfo(APP_NAME, text + "\n\n已写入 launch.log")

        def copy_url(self):
            if not self.url:
                return
            self.win.clipboard_clear()
            self.win.clipboard_append(self.url)
            self.win.update()
            self.status.set("地址已复制，粘贴到浏览器地址栏即可。")

        def open_browser(self):
            if not self.url:
                return False
            ok = open_url(self.url)
            if not ok:
                self.copy_url()
                self.status.set("没能自动打开浏览器，地址已复制到剪贴板。")
            return ok

        def quit(self):
            if self.edge_proc is not None:
                try:
                    self.edge_proc.terminate()
                except Exception:
                    pass
                self.edge_proc = None
            self.stop()
            self.win.destroy()

    win = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    App(win)
    win.mainloop()


def uitest(log_path: str) -> int:
    """Check that Tk actually starts inside the frozen bundle (no window shown)."""
    report = {"ok": False}
    try:
        import tkinter as tk
        from tkinter import ttk  # noqa: F401
        win = tk.Tk()
        win.withdraw()
        ttk.Style().theme_use("vista")
        win.update_idletasks()
        win.destroy()
        report["ok"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    except Exception:
        return 2
    return 0 if report["ok"] else 1


def main() -> int:
    args = sys.argv[1:]
    if "--selftest" in args:
        root = load_root() or guess_root()
        if "--root" in args:
            root = args[args.index("--root") + 1]
        log_path = os.path.join(os.environ.get("TEMP", "."), "alchibi-selftest.json")
        if "--log" in args:
            log_path = args[args.index("--log") + 1]
        return selftest(root, log_path)

    if "--uitest" in args:
        log_path = os.path.join(os.environ.get("TEMP", "."), "alchibi-uitest.json")
        if "--log" in args:
            log_path = args[args.index("--log") + 1]
        return uitest(log_path)

    if "--tk" in args:          # force the tkinter + browser fallback
        run_gui()
        return 0

    if is_elevated() and relaunch_unelevated():
        return 0

    run_gui()
    return 0

    try:
        run_gui()
    except Exception:
        log_error(traceback.format_exc())
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
