(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  window.addEventListener("error", (e) => {
    const el = document.getElementById("status");
    if (el) el.textContent = "运行错误: " + (e.message || e.error);
  });
  window.addEventListener("unhandledrejection", (e) => {
    const el = document.getElementById("status");
    if (el) el.textContent = "运行错误: " + (e.reason && e.reason.message ? e.reason.message : e.reason);
  });

  const canvas = $("canvas");
  const gl = canvas.getContext("webgl", {
    alpha: true,
    antialias: true,
    premultipliedAlpha: true,
    preserveDrawingBuffer: true,
  });
  if (!gl) {
    $("status").textContent = "这个浏览器/显卡没有可用的 WebGL。";
    return;
  }

  const renderer = new spine.webgl.SceneRenderer(canvas, gl);
  const camera = renderer.camera;

  const view = {
    zoom: 1,          // 1 = 适应窗口；>1 放大
    panX: 0,
    panY: 0,
    bounds: { x: 0, y: 0, w: 1, h: 1 },
  };

  const app = {
    groups: [],
    names: 0,
    list: [],
    currentKey: "",
    current: "",
    variants: [],
    skeleton: null,
    data: null,
    atlas: null,
    animState: null,
    playing: true,
    loop: true,
    pma: false,
    sharp: false,
    speed: 1,
    seq: 0,
    dragging: false,
    dragFrom: null,
    last: performance.now(),
  };

  // ------------------------------------------------------------ small utils
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  async function getJSON(url) {
    const r = await fetch(url, { cache: "no-store" });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
    return j;
  }

  function setStatus(msg) {
    $("status").textContent = msg || "";
  }

  function loadImage(url) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error("图片加载失败: " + url));
      img.src = url;
    });
  }

  function atlasPages(text) {
    const pages = [];
    for (const raw of text.split(/\r?\n/)) {
      if (!raw) continue;
      if (raw[0] === " " || raw[0] === "\t") continue;
      if (/\.(png|jpe?g|webp)$/i.test(raw.trim())) pages.push(raw.trim());
    }
    return pages;
  }

  function disposeScene() {
    if (app.atlas) {
      for (const page of app.atlas.pages) {
        try { page.texture.dispose(); } catch (e) { /* ignore */ }
      }
    }
    app.atlas = null;
    app.skeleton = null;
    app.data = null;
    app.animState = null;
  }

  // 预乘 alpha 由服务端按贴图统计推断：预乘贴图里 rgb 永远不超过 a，
  // 直线 alpha 的贴图会有大量 rgb > a 的像素。判断错了边缘就会发脏。
  function applyPma(on) {
    app.pma = !!on;
    const box = $("pma");
    if (box) box.checked = app.pma;
  }

  function applyFilters() {
    if (!app.atlas) return;
    const f = app.sharp ? spine.TextureFilter.Nearest : spine.TextureFilter.Linear;
    for (const page of app.atlas.pages) {
      try { page.texture.setFilters(f, f); } catch (e) { /* ignore */ }
    }
  }

  // -------------------------------------------------------------- view maths
  function resize() {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(1, Math.round(rect.width * dpr));
    const h = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    gl.viewport(0, 0, w, h);
    fitView();
  }

  function fitView() {
    const b = view.bounds;
    const aspect = canvas.width / Math.max(1, canvas.height);
    const margin = 1.6;
    let vw = Math.max(b.w * margin, b.h * margin * aspect);
    if (!isFinite(vw) || vw <= 0) vw = 100;
    camera.zoom = 1 / Math.max(0.01, view.zoom);
    camera.viewportWidth = vw;
    camera.viewportHeight = vw / aspect;
    camera.position.x = b.x + b.w / 2 + view.panX;
    camera.position.y = b.y + b.h / 2 + view.panY;
    camera.update();
  }

  function measureBounds() {
    const s = app.skeleton;
    if (!s) return;
    s.setToSetupPose();
    s.updateWorldTransform();
    const offset = new spine.Vector2();
    const size = new spine.Vector2();
    s.getBounds(offset, size, []);
    if (size.x > 0 && size.y > 0) {
      view.bounds = { x: offset.x, y: offset.y, w: size.x, h: size.y };
    } else {
      view.bounds = { x: -50, y: -50, w: 100, h: 100 };
    }
    view.panX = 0;
    view.panY = 0;
    view.zoom = 1;
    fitView();
  }

  // ------------------------------------------------------------------ loader
  function findGroupByVariant(name) {
    return app.groups.find((g) => g.variants.some((v) => v.name === name));
  }

  function fillVariantSelect(group, activeName) {
    const sel = $("skin");
    sel.innerHTML = "";
    for (const v of group.variants) {
      const opt = document.createElement("option");
      opt.value = v.name;
      opt.textContent = v.label;
      opt.title = v.name;
      sel.appendChild(opt);
    }
    sel.value = activeName;
    sel.disabled = group.variants.length <= 1;
    sel.onchange = () => loadVariant(sel.value, true);
  }

  async function selectGroup(key, wantedName) {
    const group = app.groups.find((g) => g.key === key) || findGroupByVariant(key);
    if (!group) return;
    const wanted = wantedName && group.variants.some((v) => v.name === wantedName)
      ? wantedName : group.variants[0].name;
    app.currentKey = group.key;
    app.variants = group.variants;
    highlight(group.key);
    fillVariantSelect(group, wanted);
    await loadVariant(wanted, true);
  }

  async function loadVariant(name, force) {
    if (!name || (name === app.current && !force)) return;
    const seq = ++app.seq;
    app.current = name;
    highlight(app.currentKey);
    $("skin").value = name;
    setStatus("");
    $("charname").textContent = app.currentKey || name;
    $("meta").textContent = "解包中…";
    try {
      const meta = await getJSON(`/api/meta/${encodeURIComponent(name)}`);
      if (seq !== app.seq) return;
      const base = `/api/asset/${encodeURIComponent(name)}/`;

      const atlasText = await (await fetch(base + encodeURIComponent(meta.atlas), { cache: "no-store" })).text();
      const pages = atlasPages(atlasText);
      const images = {};
      await Promise.all(pages.map(async (p) => {
        images[p] = await loadImage(base + encodeURIComponent(p));
      }));
      if (seq !== app.seq) return;

      const atlas = new spine.TextureAtlas(atlasText, (p) => {
        if (!images[p]) throw new Error("图集缺页: " + p);
        return new spine.webgl.GLTexture(gl, images[p]);
      });

      // 少数资源里的 region path 带了尾随空格（如 "meimao_11 "），
      // 严格的查找会返回 null，这里退一步按 trim 后的名字再找一次。
      const rawFindRegion = atlas.findRegion.bind(atlas);
      atlas.findRegion = (name) => {
        if (name == null) return null;
        return rawFindRegion(name) || rawFindRegion(String(name).trim());
      };

      const buf = await (await fetch(base + encodeURIComponent(meta.skel), { cache: "no-store" })).arrayBuffer();
      if (seq !== app.seq) return;

      const loader = new spine.AtlasAttachmentLoader(atlas);
      const data = new spine.SkeletonBinary(loader).readSkeletonData(new Uint8Array(buf));
      disposeScene();
      app.atlas = atlas;
      app.data = data;
      app.skeleton = new spine.Skeleton(data);
      app.animState = new spine.AnimationState(new spine.AnimationStateData(data));

      const variant = app.variants.find((v) => v.name === name);
      $("meta").textContent =
        (variant && variant.label !== "原版" ? `${variant.label} · ` : "") +
        `Spine ${data.version || meta.version} · ${data.bones.length} 骨 · ` +
        `${data.slots.length} 槽 · ${data.animations.length} 动作 · ` +
        `${pages.length} 页图集`;

      fillAnims(data);
      applyPma(meta.pma === true);
      applyFilters();
      measureBounds();
      playDefault();
      history.replaceState(null, "", `?char=${encodeURIComponent(name)}`);
      $("play").textContent = app.playing ? "❚❚" : "▶";
    } catch (err) {
      if (seq !== app.seq) return;
      disposeScene();
      setStatus(String(err.message || err));
      $("meta").textContent = "加载失败";
    }
  }

  function fillAnims(data) {
    const sel = $("anim");
    sel.innerHTML = "";
    for (const a of data.animations) {
      const opt = document.createElement("option");
      opt.value = a.name;
      opt.textContent = `${a.name}  (${a.duration.toFixed(2)}s)`;
      sel.appendChild(opt);
    }
    sel.onchange = () => playAnim(sel.value);
  }

  function playDefault() {
    const names = app.data.animations.map((a) => a.name);
    const pick = ["normal", "idle", "home", "move"].find((n) => names.includes(n)) || names[0];
    if (!pick) return;
    $("anim").value = pick;
    playAnim(pick);
  }

  function playAnim(name) {
    if (!app.animState) return;
    app.animState.setAnimation(0, name, app.loop);
    app.animState.apply(app.skeleton);
    app.skeleton.updateWorldTransform();
    const track = app.animState.getCurrent(0);
    if (track) {
      $("seek").max = String(Math.round((track.animationEnd - track.animationStart) * 1000));
      $("seek").value = "0";
    }
    updateFrameLabel(track);
  }

  // 动作列表里前后跳一格（循环）
  function stepAnim(dir) {
    const sel = $("anim");
    if (!sel.options.length) return;
    let i = sel.selectedIndex + dir;
    if (i < 0) i = sel.options.length - 1;
    if (i >= sel.options.length) i = 0;
    sel.selectedIndex = i;
    playAnim(sel.value);
  }

  // ------------------------------------------------------------------ frames
  // Spine 3.8 的 track.trackTime 在循环播放时会一直累加，不取模的话
  // 时钟会显示 4.20 / 1.00、帧号会卡在最后一帧。这里统一换算成循环内时间。
  function animLocal(track) {
    const dur = track.animationEnd - track.animationStart;
    let t;
    if (typeof track.getAnimationTime === "function") {
      t = track.getAnimationTime() - track.animationStart;
    } else {
      t = track.trackTime - track.animationStart;
    }
    if (dur > 0) {
      t %= dur;
      if (t < 0) t += dur;
    }
    return Math.max(0, t);
  }

  function frameInfo(track) {
    const fps = parseInt($("fps").value, 10) || 30;
    const dur = Math.max(0.0001, track.animationEnd - track.animationStart);
    const total = Math.max(1, Math.round(dur * fps));
    const local = animLocal(track);
    const idx = Math.min(total - 1, Math.max(0, Math.round(local * fps)));
    return { fps, dur, total, idx, local };
  }

  function updateFrameLabel(track) {
    if (!track) {
      $("frameno").textContent = "0 / 0";
      return;
    }
    const info = frameInfo(track);
    $("frameno").textContent = `${info.idx + 1} / ${info.total}`;
  }

  function stepFrame(dir) {
    const track = app.animState && app.animState.getCurrent(0);
    if (!track || !app.skeleton) return;
    if (app.playing) {
      app.playing = false;
      $("play").textContent = "▶";
    }
    const info = frameInfo(track);
    let next = info.idx + dir;
    if (next < 0) next = app.loop ? info.total - 1 : 0;
    if (next >= info.total) next = app.loop ? 0 : info.total - 1;
    track.trackTime = track.animationStart + next / info.fps;
    app.animState.apply(app.skeleton);
    app.skeleton.updateWorldTransform();
    updateFrameLabel(track);
  }

  // ------------------------------------------------------------------ render
  function drawScene() {
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    if (!app.skeleton) return;
    renderer.begin();
    renderer.drawSkeleton(app.skeleton, app.pma);
    renderer.end();
  }

  function frame(now) {
    requestAnimationFrame(frame);
    const dt = Math.min(0.1, (now - app.last) / 1000) * app.speed;
    app.last = now;

    if (!app.skeleton) {
      drawScene();
      return;
    }

    if (app.playing) app.animState.update(dt);
    app.animState.apply(app.skeleton);
    app.skeleton.updateWorldTransform();

    drawScene();

    const track = app.animState.getCurrent(0);
    if (track) {
      const info = frameInfo(track);
      $("clock").textContent = `${info.local.toFixed(2)} / ${info.dur.toFixed(2)}`;
      if (!app.draggingSeek) $("seek").value = String(Math.round(info.local * 1000));
      updateFrameLabel(track);
    }
  }

  // ------------------------------------------------------------------- list
  function highlight(key) {
    for (const li of $("list").children) {
      li.classList.toggle("active", li.dataset.key === key);
    }
  }

  function renderList() {
    const q = $("search").value.trim().toLowerCase();
    const hits = q
      ? app.groups.filter((g) => g.key.toLowerCase().includes(q)
          || g.variants.some((v) => v.name.toLowerCase().includes(q)))
      : app.groups;
    app.list = hits;
    const shown = hits.slice(0, 400);
    const frag = document.createDocumentFragment();
    for (const g of shown) {
      const li = document.createElement("li");
      li.dataset.key = g.key;
      const name = document.createElement("span");
      name.textContent = g.key;
      const cnt = document.createElement("span");
      cnt.className = "cnt";
      cnt.textContent = g.variants.length > 1 ? String(g.variants.length) : "";
      li.append(name, cnt);
      li.onclick = () => selectGroup(g.key);
      frag.appendChild(li);
    }
    $("list").replaceChildren(frag);
    $("count").textContent = q
      ? `${hits.length} 个匹配${hits.length > shown.length ? `（显示前 ${shown.length}）` : ""}`
      : `${app.groups.length} 个角色 · ${app.names} 个版本`;
    highlight(app.currentKey);
  }

  // ----------------------------------------------------------------- events
  $("search").addEventListener("input", renderList);
  $("prevanim").onclick = () => stepAnim(-1);
  $("nextanim").onclick = () => stepAnim(1);
  $("play").onclick = () => {
    app.playing = !app.playing;
    $("play").textContent = app.playing ? "❚❚" : "▶";
  };
  $("loop").onchange = (e) => {
    app.loop = e.target.checked;
    const cur = $("anim").value;
    if (cur) playAnim(cur);
  };
  $("pma").onchange = (e) => { app.pma = e.target.checked; };
  $("sharp").onchange = (e) => { app.sharp = e.target.checked; applyFilters(); };
  function setSpeed(value, fromButton) {
    app.speed = value;
    $("speed").value = String(value);
    document.querySelectorAll(".speeds button").forEach((b) => {
      b.classList.toggle("on", fromButton ? parseFloat(b.dataset.speed) === value : false);
    });
  }

  $("speed").oninput = (e) => setSpeed(parseFloat(e.target.value), false);
  document.querySelectorAll(".speeds button").forEach((btn) => {
    btn.onclick = () => setSpeed(parseFloat(btn.dataset.speed), true);
  });

  $("loadroot").onclick = async () => {
    const root = $("rootpath").value.trim();
    if (!root) return;
    setStatus("正在切换素材目录…");
    try {
      const r = await fetch("/api/root", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root }),
      });
      const j = await r.json();
      if (!j.ok) throw new Error(j.error || "失败");
      setStatus("");
      app.current = "";
      app.currentKey = "";
      app.variants = [];
      $("charname").textContent = "—";
      $("meta").textContent = "";
      disposeScene();
      await loadChars();
    } catch (err) {
      setStatus("切换失败：" + (err.message || err));
    }
  };

  $("openbrowser").onclick = async () => {
    try {
      await fetch("/api/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: location.href }),
      });
    } catch (err) {
      setStatus("打开浏览器失败：" + (err.message || err));
    }
  };
  $("fit").onclick = () => { view.zoom = 1; view.panX = 0; view.panY = 0; fitView(); };

  let draggingSeek = false;
  $("seek").addEventListener("pointerdown", () => { draggingSeek = true; app.draggingSeek = true; });
  $("seek").addEventListener("pointerup", () => { draggingSeek = false; app.draggingSeek = false; });
  $("seek").addEventListener("input", (e) => {
    const track = app.animState && app.animState.getCurrent(0);
    if (!track) return;
    track.trackTime = track.animationStart + parseInt(e.target.value, 10) / 1000;
    app.animState.apply(app.skeleton);
    app.skeleton.updateWorldTransform();
    updateFrameLabel(track);
  });

  $("prev").onclick = () => stepFrame(-1);
  $("next").onclick = () => stepFrame(1);
  $("fps").onchange = () => {
    const track = app.animState && app.animState.getCurrent(0);
    if (track) updateFrameLabel(track);
  };

  $("shot").onclick = () => {
    const a = document.createElement("a");
    a.download = `${app.current || "chibi"}-${$("anim").value || "anim"}.png`;
    a.href = canvas.toDataURL("image/png");
    a.click();
  };

  // 把当前动作完整渲染一遍，交给服务端合成 GIF（Pillow 负责 LZW 编码）
  // 输出：透明背景、30fps（不再抽稀）、按角色实际外框裁剪
  async function exportGif() {
    const track = app.animState && app.animState.getCurrent(0);
    if (!track || !app.skeleton) return;
    const dur = track.animationEnd - track.animationStart;
    if (!(dur > 0.05)) {
      setStatus("这个动作太短，无法导出 GIF。");
      return;
    }
    const btn = $("gif");
    if (btn.disabled) return;
    btn.disabled = true;
    const wasPlaying = app.playing;
    app.playing = false;
    $("play").textContent = "▶";

    const FPS = 30;
    const MAX_SIDE = 720;
    const total = Math.max(2, Math.min(400, Math.round(dur * FPS)));

    try {
      // 1) 采样整个动作的外框，避免把画布四周的空白也录进去
      const savedTime = track.trackTime;
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      const samples = 24;
      for (let i = 0; i < samples; i++) {
        track.trackTime = track.animationStart + (i / samples) * dur;
        app.animState.apply(app.skeleton);
        app.skeleton.updateWorldTransform();
        const off = new spine.Vector2();
        const size = new spine.Vector2();
        app.skeleton.getBounds(off, size, []);
        if (size.x > 0 && size.y > 0) {
          minX = Math.min(minX, off.x);
          minY = Math.min(minY, off.y);
          maxX = Math.max(maxX, off.x + size.x);
          maxY = Math.max(maxY, off.y + size.y);
        }
      }
      track.trackTime = savedTime;

      // 2) 世界坐标 -> 画布像素
      const vw = camera.viewportWidth;
      const vh = camera.viewportHeight;
      const camX = camera.position.x;
      const camY = camera.position.y;
      const sx = canvas.width / vw;
      const sy = canvas.height / vh;
      let rect = {
        x: (minX - (camX - vw / 2)) * sx,
        y: (camY + vh / 2 - maxY) * sy,
        w: (maxX - minX) * sx,
        h: (maxY - minY) * sy,
      };
      if (!isFinite(rect.w) || rect.w <= 2 || rect.h <= 2) {
        rect = { x: 0, y: 0, w: canvas.width, h: canvas.height };
      }
      const padX = rect.w * 0.03;
      const padY = rect.h * 0.03;
      let cx = Math.max(0, Math.floor(rect.x - padX));
      let cy = Math.max(0, Math.floor(rect.y - padY));
      let cw = Math.min(canvas.width - cx, Math.ceil(rect.w + padX * 2));
      let ch = Math.min(canvas.height - cy, Math.ceil(rect.h + padY * 2));
      if (cw < 4 || ch < 4) { cx = 0; cy = 0; cw = canvas.width; ch = canvas.height; }

      // 3) 输出尺寸：外框等比缩到最长边 720，不放大
      const outScale = Math.min(1, MAX_SIDE / Math.max(cw, ch));
      const w = Math.max(2, Math.round(cw * outScale));
      const h = Math.max(2, Math.round(ch * outScale));
      const off = document.createElement("canvas");
      off.width = w;
      off.height = h;
      const ctx = off.getContext("2d");

      const frames = [];
      for (let i = 0; i < total; i++) {
        const t = (i / total) * dur;
        track.trackTime = track.animationStart + t;
        app.animState.apply(app.skeleton);
        app.skeleton.updateWorldTransform();
        drawScene();
        ctx.clearRect(0, 0, w, h);  // 透明背景
        ctx.drawImage(canvas, cx, cy, cw, ch, 0, 0, w, h);
        const blob = await new Promise((res) => off.toBlob(res, "image/png"));
        frames.push(new Uint8Array(await blob.arrayBuffer()));
        if (i % 10 === 0) setStatus(`正在渲染 GIF：${i + 1} / ${total}`);
      }

      setStatus(`正在编码 GIF（${total} 帧，可能要十几秒）…`);
      let size = 20;
      for (const f of frames) size += 4 + f.length;
      const buf = new Uint8Array(size);
      const dv = new DataView(buf.buffer);
      dv.setUint32(0, w, true);
      dv.setUint32(4, h, true);
      dv.setUint32(8, Math.max(20, Math.round(dur * 1000)), true);  // 总时长 ms
      dv.setUint32(12, total, true);
      dv.setUint32(16, 1, true);  // flags: 1 = 透明背景
      let pos = 20;
      for (const f of frames) {
        dv.setUint32(pos, f.length, true);
        pos += 4;
        buf.set(f, pos);
        pos += f.length;
      }

      const resp = await fetch("/api/gif", {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: buf,
      });
      if (!resp.ok) {
        let msg = `HTTP ${resp.status}`;
        try { msg = (await resp.json()).error || msg; } catch (e) { /* ignore */ }
        throw new Error(msg);
      }
      const gif = await resp.blob();
      const a = document.createElement("a");
      a.download = `${app.current || "chibi"}-${$("anim").value || "anim"}.gif`;
      a.href = URL.createObjectURL(gif);
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 20000);
      setStatus(`已导出 GIF（${Math.round(gif.size / 1024)} KB，${total} 帧）`);
      setTimeout(() => setStatus(""), 4000);
    } catch (err) {
      setStatus("GIF 导出失败：" + (err.message || err));
    } finally {
      track.trackTime = track.animationStart;
      app.playing = wasPlaying;
      $("play").textContent = app.playing ? "❚❚" : "▶";
      btn.disabled = false;
    }
  }

  $("gif").onclick = exportGif;

  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const factor = Math.exp(-e.deltaY * 0.0012);
    const next = clamp(view.zoom * factor, 0.15, 8);
    if (next === view.zoom) return;
    // 以鼠标位置为中心缩放
    const rect = canvas.getBoundingClientRect();
    const mx = (e.clientX - rect.left) / rect.width - 0.5;
    const my = 0.5 - (e.clientY - rect.top) / rect.height;
    const w = camera.viewportWidth, h = camera.viewportHeight;
    const worldDX = mx * w * (1 / Math.max(0.01, view.zoom) - 1 / next);
    const worldDY = my * h * (1 / Math.max(0.01, view.zoom) - 1 / next);
    view.panX += worldDX;
    view.panY += worldDY;
    view.zoom = next;
    fitView();
  }, { passive: false });

  canvas.addEventListener("pointerdown", (e) => {
    app.dragging = true;
    app.dragFrom = { x: e.clientX, y: e.clientY };
    canvas.classList.add("dragging");
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!app.dragging || !app.dragFrom) return;
    const dx = e.clientX - app.dragFrom.x;
    const dy = e.clientY - app.dragFrom.y;
    app.dragFrom = { x: e.clientX, y: e.clientY };
    const rect = canvas.getBoundingClientRect();
    view.panX -= dx * camera.viewportWidth / rect.width;
    view.panY += dy * camera.viewportHeight / rect.height;
    fitView();
  });
  canvas.addEventListener("pointerup", () => {
    app.dragging = false;
    app.dragFrom = null;
    canvas.classList.remove("dragging");
  });

  window.addEventListener("resize", resize);

  window.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    if (e.code === "Space") {
      e.preventDefault();
      $("play").click();
    } else if (e.code === "KeyR") {
      $("fit").click();
    } else if (e.code === "Comma" || e.code === "Period") {
      e.preventDefault();
      stepAnim(e.code === "Period" ? 1 : -1);
    } else if (e.code === "ArrowLeft" || e.code === "ArrowRight") {
      e.preventDefault();
      stepFrame(e.code === "ArrowRight" ? 1 : -1);
    } else if (e.code === "ArrowDown" || e.code === "ArrowUp") {
      e.preventDefault();
      const idx = app.list.findIndex((g) => g.key === app.currentKey);
      if (idx < 0) return;
      const next = app.list[idx + (e.code === "ArrowDown" ? 1 : -1)];
      if (next) selectGroup(next.key);
    }
  });

  // ------------------------------------------------------------------- boot
  async function loadChars(preferred) {
    app.groups = await getJSON("/api/groups");
    app.names = app.groups.reduce((n, g) => n + g.variants.length, 0);
    renderList();
    if (!app.groups.length) {
      setStatus("这个目录里没有 char/ 子目录，或者它是空的。");
      return;
    }
    const wanted = preferred || new URLSearchParams(location.search).get("char");
    if (wanted) {
      const g = findGroupByVariant(wanted) || app.groups.find((x) => x.key === wanted);
      if (g) {
        await selectGroup(g.key, wanted);
        return;
      }
    }
    const start = app.groups.find((g) => g.key === "2b") || app.groups[0];
    await selectGroup(start.key);
  }

  (async () => {
    resize();
    requestAnimationFrame(frame);
    try {
      const st = await getJSON("/api/state");
      $("rootpath").value = st.root || "";
      if (!st.root) {
        setStatus("请先填写 AssetBundles 目录，然后点“加载”。");
        return;
      }
      await loadChars();
    } catch (err) {
      setStatus("无法读取角色列表: " + err.message);
    }
  })();
})();
