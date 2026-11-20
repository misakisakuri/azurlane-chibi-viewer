"""Local viewer for Azur Lane chibi (SD) Spine bundles.

Serves a small web UI that plays char/* directly out of the game's
AssetBundles folder.  Bundles are unpacked on demand with UnityPy and cached
on disk, so the 480 MB char/ folder does not have to be exported first.

Run standalone:  python server.py --root "D:\\AzurLane\\AssetBundles" --port 8765
Or embed:        httpd = create_server(root, port=0)  -> (httpd, port)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import struct
import sys
import threading
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageChops

import UnityPy

UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.51f1"

# Bump when the cached meta.json layout changes, so old caches are rebuilt.
CACHE_VERSION = 3

# char/ 里混着极少数占位文件：3rd 只有 2.7 KB，没有 .skel/.atlas，不是角色。
IGNORED_BUNDLES = {"3rd"}
MIN_BUNDLE_BYTES = 4096

HERE = os.path.dirname(os.path.abspath(__file__))


def resource_dir() -> str:
    """Folder that holds index.html / app.js / vendor (PyInstaller aware)."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", HERE)
    return HERE


def cache_dir() -> str:
    """Writable cache folder: AL_CHIBI_CACHE > %LOCALAPPDATA% > %TEMP%."""
    import tempfile

    override = os.environ.get("AL_CHIBI_CACHE")
    if override:
        os.makedirs(override, exist_ok=True)
        return override

    candidates = []
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    candidates.append(os.path.join(base, "ALChibiViewer", "cache"))
    candidates.append(os.path.join(tempfile.gettempdir(), "ALChibiViewer-cache"))

    for cand in candidates:
        try:
            os.makedirs(cand, exist_ok=True)
            probe = os.path.join(cand, ".write-test")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("x")
            os.remove(probe)
            return cand
        except Exception:
            continue
    return tempfile.mkdtemp(prefix="alchibi-cache-")


def to_bytes(value):
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    return value.encode("utf-8", "surrogateescape")


def skel_version(data: bytes) -> str:
    i = data.find(b"3.")
    if i < 0 or i > 40:
        return ""
    j = i
    while j < len(data) and (data[j:j + 1].isdigit() or data[j:j + 1] == b"."):
        j += 1
    return data[i:j].decode("ascii", "replace")


def premultiply(img):
    """RGBA -> premultiplied RGBA (rgb *= a).

    The renderer writes premultiplied pixels into a premultiplied canvas, so the
    textures have to be premultiplied too.  Feeding straight-alpha textures into
    that pipeline makes every semi-transparent pixel too bright, which is what
    gives sprites the washed-out / white-halo look.
    """
    rgba = img.convert("RGBA")
    r, g, b, a = rgba.split()
    return Image.merge("RGBA", (
        ImageChops.multiply(r, a),
        ImageChops.multiply(g, a),
        ImageChops.multiply(b, a),
        a,
    ))


def detect_pma(img) -> bool:
    """Rough premultiplied-alpha probe, only used for the meta info field."""
    try:
        rgba = img.convert("RGBA")
        w, h = rgba.size
        px = rgba.load()
        step = max(1, int(((w * h) / 60000) ** 0.5))
        best = -999
        seen = 0
        for y in range(0, h, step):
            for x in range(0, w, step):
                r, g, b, a = px[x, y]
                if 16 < a < 250:
                    seen += 1
                    d = max(r, g, b) - a
                    if d > best:
                        best = d
        if seen < 200:
            return False
        return best <= 60
    except Exception:
        return False


# ---------------------------------------------------------------- grouping
# char/ 命名约定：<角色>[_<皮肤号>][_<变体>][_l|_r]
#   皮肤号：2、3…（第 N 套皮肤）
#   变体：g=改造、h=婚纱、hx=和谐、alter=异格、doa=联动……
#   l/r：双人单位的左/右半身
VARIANT_TOKENS = ("dark_shadow", "buildhx", "shophx", "hx", "doa", "alter",
                  "g", "h", "ex", "asmr", "wjz", "n")
VARIANT_LABELS = {
    "g": "改造", "h": "婚纱", "hx": "和谐", "alter": "异格", "doa": "联动DOA",
    "ex": "EX", "asmr": "ASMR", "wjz": "特别", "n": "无装备",
    "buildhx": "建造预览", "shophx": "商店预览", "dark_shadow": "暗影",
}
VARIANT_ORDER = {name: i for i, name in enumerate(VARIANT_TOKENS)}
SIDE_LABELS = {"l": "左", "r": "右"}


def _split_side(name: str, names: set):
    if name.endswith("_l") or name.endswith("_r"):
        stem = name[:-2]
        if stem in names:
            return stem, name[-1]
        head, sep, tail = stem.rpartition("_")
        if sep and tail.isdigit() and head in names:
            return stem, name[-1]
    return name, ""


def _split_variants(name: str):
    tails = []
    changed = True
    while changed:
        changed = False
        for tok in VARIANT_TOKENS:
            if name.endswith("_" + tok) and len(name) > len(tok) + 1:
                tails.insert(0, tok)
                name = name[: -(len(tok) + 1)]
                changed = True
                break
    return name, tails


def _variant_label(num: str, tails: list, side: str) -> str:
    parts = []
    if num:
        parts.append(f"皮肤 {num}")
    for tok in tails:
        parts.append(VARIANT_LABELS.get(tok, tok))
    if side:
        parts.append(SIDE_LABELS.get(side, side))
    return " · ".join(parts) if parts else "原版"


def build_groups(names: list) -> list:
    """Fold 3281 bundles into ~1500 characters, each with its variant list."""
    name_set = set(names)
    buckets = {}
    for name in names:
        stem, side = _split_side(name, name_set)
        base, tails = _split_variants(stem)
        head, sep, num = base.rpartition("_")
        if sep and num.isdigit() and head in name_set:
            base = head
        else:
            num = ""
        if base not in name_set:  # no clean base: keep it standalone
            base, side, tails, num = name, "", [], ""
        buckets.setdefault(base, []).append({
            "name": name,
            "label": _variant_label(num, tails, side),
            "_sort": (int(num) if num else 0,
                      [VARIANT_ORDER.get(t, 99) for t in tails],
                      0 if not side else (1 if side == "l" else 2),
                      name),
        })

    groups = []
    for key in sorted(buckets):
        variants = sorted(buckets[key], key=lambda v: v["_sort"])
        for v in variants:
            v.pop("_sort", None)
        groups.append({"key": key, "variants": variants})
    return groups


def build_gif(raw: bytes) -> bytes:
    """Assemble the browser-rendered PNG frames into one looping GIF.

    Payload: <u32 width><u32 height><u32 delay_ms><u32 count><u32 flags>
             then count * (<u32 len><png bytes>)
    flags bit0 = keep transparency (GIF index 255).
    """
    if len(raw) < 20:
        raise ValueError("payload too small")
    width, height, delay, count, flags = struct.unpack_from("<IIIII", raw, 0)
    if not (2 <= width <= 2048 and 2 <= height <= 2048 and 2 <= count <= 400):
        raise ValueError("bad header")
    pos = 20
    blobs = []
    for _ in range(count):
        if pos + 4 > len(raw):
            raise ValueError("truncated frame header")
        size, = struct.unpack_from("<I", raw, pos)
        pos += 4
        if size <= 0 or pos + size > len(raw):
            raise ValueError("truncated frame")
        blobs.append(raw[pos:pos + size])
        pos += size
    if not blobs:
        raise ValueError("no frames")

    transparent = bool(flags & 1)
    # One palette for all frames keeps colours stable between frames.
    first = Image.open(io.BytesIO(blobs[0])).convert("RGBA")
    palette = first.convert("RGB").quantize(colors=255, method=Image.Quantize.MEDIANCUT)

    converted = []
    for blob in blobs:
        im = Image.open(io.BytesIO(blob)).convert("RGBA")
        p = im.convert("RGB").quantize(palette=palette, dither=Image.Dither.NONE)
        if transparent:
            # index 255 is reserved for "transparent"
            pal = (p.getpalette() or [])[:768]
            if len(pal) < 768:
                pal += [0] * (768 - len(pal))
            p.putpalette(pal)
            mask = im.getchannel("A").point(lambda a: 255 if a < 128 else 0)
            p.paste(255, mask=mask)
        converted.append(p)

    out = io.BytesIO()
    # GIF 的帧间隔只能精确到 10ms，30fps=33.3ms 没法整除；按累计时间分配 30/40ms，
    # 这样整段时长仍然准确，平均帧率就是 30fps。
    total_ms = max(20, int(delay))
    targets = [round(i * total_ms / count / 10.0) * 10 for i in range(count + 1)]
    delays = [max(20, targets[i + 1] - targets[i]) for i in range(count)]

    save_kwargs = dict(
        format="GIF", save_all=True, append_images=converted[1:],
        duration=delays, loop=0, optimize=False, disposal=2,
    )
    if transparent:
        save_kwargs["transparency"] = 255
    converted[0].save(out, **save_kwargs)
    return out.getvalue()


class Extractor:
    """Unpack one char bundle into {skel, atlas, pages} with a disk cache."""

    def __init__(self, root: str, cache: str):
        self.root = root
        self.cache = cache
        self._lock = threading.Lock()

    def bundle_path(self, name: str) -> str:
        return os.path.join(self.root, "char", name)

    def _dir(self, name: str) -> str:
        safe = re.sub(r'[\\/:*?"<>|]+', "_", name)
        return os.path.join(self.cache, safe)

    def manifest(self, name: str) -> dict:
        meta_path = os.path.join(self._dir(name), "meta.json")
        meta = self._load_cached(meta_path)
        if meta is not None:
            return meta
        with self._lock:
            meta = self._load_cached(meta_path)
            if meta is not None:
                return meta
            return self._build(name)

    @staticmethod
    def _load_cached(meta_path: str):
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("cacheVersion") == CACHE_VERSION:
                return meta
        except Exception:
            pass
        return None

    def _build(self, name: str) -> dict:
        d = self._dir(name)
        env = UnityPy.load(self.bundle_path(name))
        skel_name = atlas_name = None
        skel_bytes = b""
        atlas_text = ""
        pages = []
        page_errors = []
        first_image = None

        for obj in env.objects:
            kind = obj.type.name
            if kind == "TextAsset":
                ta = obj.read()
                low = ta.m_Name.lower()
                if low.endswith(".skel"):
                    skel_name = ta.m_Name
                    skel_bytes = to_bytes(ta.m_Script)
                elif low.endswith(".atlas") or low.endswith(".atlas.txt"):
                    atlas_name = ta.m_Name
                    atlas_text = to_bytes(ta.m_Script).decode("utf-8", "replace")
            elif kind == "Texture2D":
                tex = obj.read()
                try:
                    img = tex.image
                except Exception as exc:  # noqa: BLE001 - reported to the UI
                    img = None
                    page_errors.append(f"{tex.m_Name}: {type(exc).__name__}: {exc}")
                if img is not None:
                    if not pages:
                        first_image = img
                    buf = io.BytesIO()
                    premultiply(img).save(buf, "PNG")
                    pages.append((tex.m_Name + ".png", buf.getvalue(), img.size))

        if not skel_name or not atlas_name:
            raise RuntimeError("这个资源不是小人骨架（缺少 .skel/.atlas）")

        os.makedirs(d, exist_ok=True)
        for fname, data, _ in pages:
            with open(os.path.join(d, fname), "wb") as f:
                f.write(data)
        with open(os.path.join(d, skel_name), "wb") as f:
            f.write(skel_bytes)
        with open(os.path.join(d, atlas_name), "w", encoding="utf-8", newline="") as f:
            f.write(atlas_text)

        meta = {
            "name": name,
            "skel": skel_name,
            "atlas": atlas_name,
            "pages": [{"file": p[0], "width": p[2][0], "height": p[2][1]} for p in pages],
            "version": skel_version(skel_bytes),
            "skelBytes": len(skel_bytes),
            "pageErrors": page_errors,
            "pma": True,
            "sourcePma": detect_pma(first_image) if first_image is not None else False,
            "cacheVersion": CACHE_VERSION,
        }
        with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        return meta

    def read(self, name: str, filename: str):
        meta = self.manifest(name)
        allowed = {meta["skel"], meta["atlas"]} | {p["file"] for p in meta["pages"]}
        if filename not in allowed:
            return None
        path = os.path.join(self._dir(name), filename)
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            return f.read()


class State:
    """Mutable server state: the current AssetBundles root and its bundle list."""

    def __init__(self, root: str, config_path: str | None = None):
        self.lock = threading.Lock()
        self.config_path = config_path
        self.root = ""
        self.names: list = []
        self.groups: list = []
        self.extractor = None
        self.set_root(root)

    def set_root(self, root: str) -> int:
        root = os.path.normpath(os.path.abspath(root))
        names = list_chars(root)  # raises RuntimeError when char/ is missing
        extractor = Extractor(root, cache_dir())
        groups = build_groups(names)
        with self.lock:
            self.root = root
            self.names = names
            self.groups = groups
            self.extractor = extractor
        self._save()
        return len(names)

    def _save(self):
        if not self.config_path:
            return
        try:
            folder = os.path.dirname(self.config_path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump({"root": self.root}, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def snapshot(self):
        with self.lock:
            return self.root, self.names, self.extractor

    def group_snapshot(self):
        with self.lock:
            return self.groups


def open_url(url: str) -> bool:
    """Open the default browser, with fallbacks; webbrowser fails silently."""
    import subprocess
    import webbrowser

    try:
        if webbrowser.open(url, new=2):
            return True
    except Exception:
        pass
    try:
        os.startfile(url)  # type: ignore[attr-defined]  # Windows shell
        return True
    except Exception:
        pass
    try:
        subprocess.Popen(["cmd", "/c", "start", "", url], creationflags=0x08000000)
        return True
    except Exception:
        return False


def make_handler(state: State):
    resources = resource_dir()

    class Handler(SimpleHTTPRequestHandler):
        server_version = "ALChibiViewer/1.1"

        def log_message(self, fmt, *args):
            pass

        def _json(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _bytes(self, data: bytes, ctype: str):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _static(self, rel: str):
            base = os.path.abspath(resources)
            path = os.path.abspath(os.path.join(base, rel))
            if not path.startswith(base + os.sep) or not os.path.isfile(path):
                self.send_error(404)
                return
            ctype = {
                ".html": "text/html; charset=utf-8",
                ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".png": "image/png",
                ".ico": "image/x-icon",
                ".map": "application/json",
            }.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
            with open(path, "rb") as f:
                self._bytes(f.read(), ctype)

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            parts = [p for p in parsed.path.split("/") if p]

            if not parts:
                return self._static("index.html")

            if parts[0] == "api":
                try:
                    root, names, extractor = state.snapshot()
                    if parts[1:2] == ["state"]:
                        return self._json({"root": root, "count": len(names)})
                    if parts[1:2] == ["chars"]:
                        return self._json(names)
                    if parts[1:2] == ["groups"]:
                        return self._json(state.group_snapshot())
                    if parts[1:2] == ["meta"] and len(parts) >= 3:
                        name = urllib.parse.unquote(parts[2])
                        if name not in names:
                            return self._json({"error": "unknown bundle"}, 404)
                        return self._json(extractor.manifest(name))
                    if parts[1:2] == ["asset"] and len(parts) >= 4:
                        name = urllib.parse.unquote(parts[2])
                        filename = urllib.parse.unquote("/".join(parts[3:]))
                        if name not in names:
                            return self._json({"error": "unknown bundle"}, 404)
                        data = extractor.read(name, filename)
                        if data is None:
                            return self._json({"error": "no such asset"}, 404)
                        ctype = "image/png" if filename.lower().endswith(".png") else "application/octet-stream"
                        return self._bytes(data, ctype)
                    return self._json({"error": "bad api path"}, 404)
                except Exception as exc:  # noqa: BLE001 - surface the reason to the UI
                    return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

            return self._static(urllib.parse.unquote(parsed.path.lstrip("/")))

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            parts = [p for p in parsed.path.split("/") if p]

            if parts[1:2] == ["gif"]:
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    if length <= 0 or length > 256 * 1024 * 1024:
                        return self._json({"error": "帧数据为空或过大"}, 400)
                    gif = build_gif(self.rfile.read(length))
                except Exception as exc:  # noqa: BLE001 - reported to the UI
                    return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
                return self._bytes(gif, "image/gif")

            try:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                payload = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                payload = {}

            if parts[1:2] == ["root"]:
                root = str(payload.get("root") or "").strip()
                if not root:
                    return self._json({"ok": False, "error": "路径为空"}, 400)
                try:
                    count = state.set_root(root)
                except Exception as exc:  # noqa: BLE001 - reported to the UI
                    return self._json({"ok": False, "error": f"无法使用这个目录：{exc}"}, 400)
                return self._json({"ok": True, "root": state.root, "count": count})

            if parts[1:2] == ["open"]:
                url = str(payload.get("url") or "")
                ok = open_url(url) if url else False
                return self._json({"ok": ok})

            return self._json({"ok": False, "error": "bad api path"}, 404)

    return Handler


def list_chars(root: str) -> list:
    char_dir = os.path.join(root, "char")
    if not os.path.isdir(char_dir):
        raise RuntimeError(f"char/ not found under {root}")
    out = []
    for f in os.listdir(char_dir):
        path = os.path.join(char_dir, f)
        if not os.path.isfile(path):
            continue
        if f in IGNORED_BUNDLES or os.path.getsize(path) < MIN_BUNDLE_BYTES:
            continue  # placeholders like "3rd" (2.7 KB, no skeleton)
        out.append(f)
    return sorted(out)


class _Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second process steal a busy port; refuse
    # instead, so the launcher can fall back to an ephemeral port.
    allow_reuse_address = False
    daemon_threads = True


def create_server(root: str, host: str = "127.0.0.1", port: int = 8765,
                  config_path: str | None = None):
    """Start a viewer server; returns (httpd, actual_port). Caller serves it."""
    state = State(root, config_path)
    handler = make_handler(state)
    httpd = _Server((host, port), handler)
    return httpd, httpd.server_address[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("AL_ASSET_ROOT", ""))
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    if not args.root:
        sys.exit("--root is required (the folder that contains char/)")

    httpd, port = create_server(args.root, args.host, args.port)
    print(f"chibi viewer: http://{args.host}:{port}/  ({len(list_chars(args.root))} bundles)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
