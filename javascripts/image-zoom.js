/* 公開サイトの図を押すと、拡大・移動できる窓を開く。
 * 印刷と PDF には影響しない。窓は開くまで DOM に作らず、印刷では隠す。
 * PDF の生成はページ内のすべての img を検証するため、閉じたあとも窓を残さない。
 * 大きな SVG は、img のビットマップを拡大せず、インラインの SVG を拡大して文字がぼけないようにする。
 */

(() => {
  const SELECTOR = ".md-typeset img";
  const PAD = 24;
  const STEP = 1.12;
  const MOVE_PX = 5;
  const PAN = 48;

  let dialog = null;
  let viewport = null;
  let stage = null;
  let closeBtn = null;
  let plusBtn = null;
  let minusBtn = null;
  let natW = 1;
  let natH = 1;
  let scale = 1;
  let tx = 0;
  let ty = 0;
  let fit = 1;
  let pointers = new Map();
  let pinch = null;
  let drag = null;
  let moved = false;
  let openSeq = 0;

  const zoomable = (img) =>
    img instanceof HTMLImageElement &&
    img.matches(SELECTOR) &&
    !img.closest("a, button, .doc-zoom");

  const enhance = (root) => {
    (root || document).querySelectorAll(SELECTOR).forEach((img) => {
      if (!zoomable(img) || img.dataset.docZoom === "1") return;
      img.dataset.docZoom = "1";
      img.tabIndex = 0;
      img.setAttribute("role", "button");
      const alt = (img.getAttribute("alt") || "図").trim();
      img.setAttribute("aria-label", `${alt}を拡大する`);
    });
  };

  const updateZoomButtons = () => {
    if (!minusBtn || !plusBtn) return;
    minusBtn.disabled = scale <= fit + 1e-6;
    plusBtn.disabled = scale >= maxScale() - 1e-6;
  };

  const apply = () => {
    if (stage) stage.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
    updateZoomButtons();
  };

  const viewRect = () => viewport.getBoundingClientRect();

  const fitScale = () => {
    const r = viewRect();
    const w = Math.max(1, r.width - PAD * 2);
    const h = Math.max(1, r.height - PAD * 2);
    return Math.min(w / natW, h / natH, 1);
  };

  const maxScale = () => Math.max(2, 4 * fit);

  const resetView = () => {
    fit = fitScale();
    scale = fit;
    const r = viewRect();
    tx = (r.width - natW * scale) / 2;
    ty = (r.height - natH * scale) / 2;
    apply();
  };

  const zoomAt = (clientX, clientY, factor) => {
    const r = viewRect();
    const x = clientX - r.left;
    const y = clientY - r.top;
    const worldX = (x - tx) / scale;
    const worldY = (y - ty) / scale;
    const next = Math.min(maxScale(), Math.max(fit, scale * factor));
    tx = x - worldX * next;
    ty = y - worldY * next;
    scale = next;
    apply();
  };

  const onImage = (clientX, clientY) => {
    const r = viewRect();
    const x = (clientX - r.left - tx) / scale;
    const y = (clientY - r.top - ty) / scale;
    return x >= 0 && y >= 0 && x <= natW && y <= natH;
  };

  const unlock = () => {
    document.documentElement.style.removeProperty("overflow");
  };

  const destroy = () => {
    unlock();
    if (dialog) dialog.remove();
    dialog = viewport = stage = closeBtn = plusBtn = minusBtn = null;
    pointers = new Map();
    pinch = drag = null;
    openSeq += 1;
  };

  const isSvgUrl = (src) => /\.svg(?=([?#]|$))/i.test(src || "");

  const isSameOrigin = (src) => {
    try {
      return new URL(src, location.href).origin === location.origin;
    } catch (_) {
      return false;
    }
  };

  const sizeFromSvg = (svg) => {
    const vb = svg.viewBox && svg.viewBox.baseVal;
    if (vb && vb.width && vb.height) return { w: vb.width, h: vb.height };
    const w = parseFloat(svg.getAttribute("width"));
    const h = parseFloat(svg.getAttribute("height"));
    if (w && h) return { w, h };
    return null;
  };

  const mountMedia = (el) => {
    el.classList.add("doc-zoom__media");
    el.style.width = `${natW}px`;
    el.style.height = `${natH}px`;
    el.setAttribute("draggable", "false");
    stage.replaceChildren(el);
  };

  const fillStage = async (img) => {
    const src = img.currentSrc || img.src;
    const alt = (img.getAttribute("alt") || "").trim();
    natW = img.naturalWidth || 1;
    natH = img.naturalHeight || 1;

    if (isSvgUrl(src) && isSameOrigin(src)) {
      try {
        const res = await fetch(src, { cache: "force-cache" });
        if (res.ok) {
          const text = await res.text();
          const parsed = new DOMParser().parseFromString(text, "image/svg+xml");
          const svg = parsed.documentElement;
          if (svg instanceof SVGSVGElement && !parsed.querySelector("parsererror")) {
            const size = sizeFromSvg(svg);
            if (size) {
              natW = size.w;
              natH = size.h;
            }
            svg.removeAttribute("width");
            svg.removeAttribute("height");
            svg.setAttribute("role", "img");
            if (alt) svg.setAttribute("aria-label", alt);
            mountMedia(svg);
            return;
          }
        }
      } catch (_) {
        /* img に戻す */
      }
    }

    const copy = new Image();
    copy.alt = alt;
    copy.src = src;
    if (copy.decode) await copy.decode().catch(() => {});
    if (copy.naturalWidth) {
      natW = copy.naturalWidth;
      natH = copy.naturalHeight;
    }
    mountMedia(copy);
  };

  const onWheel = (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? STEP : 1 / STEP;
    zoomAt(e.clientX, e.clientY, factor);
  };

  const midOf = (pts) => ({
    x: (pts[0].x + pts[1].x) / 2,
    y: (pts[0].y + pts[1].y) / 2,
    dist: Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) || 1,
  });

  const onPointerDown = (e) => {
    if (isControls(e.target)) return;
    if (e.pointerType === "mouse" && e.button !== 0) return;
    try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size >= 2) {
      drag = null;
      const mid = midOf([...pointers.values()]);
      const r = viewRect();
      pinch = {
        dist: mid.dist,
        scale,
        worldX: (mid.x - r.left - tx) / scale,
        worldY: (mid.y - r.top - ty) / scale,
      };
    } else {
      moved = false;
      drag = { x: e.clientX, y: e.clientY, tx, ty };
    }
  };

  const onPointerMove = (e) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size >= 2 && pinch) {
      const mid = midOf([...pointers.values()].slice(0, 2));
      const next = Math.min(maxScale(), Math.max(fit, pinch.scale * (mid.dist / pinch.dist)));
      const r = viewRect();
      scale = next;
      tx = mid.x - r.left - pinch.worldX * next;
      ty = mid.y - r.top - pinch.worldY * next;
      moved = true;
      apply();
      return;
    }
    if (drag && pointers.size === 1) {
      const dx = e.clientX - drag.x;
      const dy = e.clientY - drag.y;
      if (Math.hypot(dx, dy) > MOVE_PX) moved = true;
      tx = drag.tx + dx;
      ty = drag.ty + dy;
      viewport.classList.add("is-dragging");
      apply();
    }
  };

  const onPointerUp = (e) => {
    pointers.delete(e.pointerId);
    if (viewport.hasPointerCapture(e.pointerId)) viewport.releasePointerCapture(e.pointerId);
    if (pointers.size < 2) pinch = null;
    if (pointers.size === 1) {
      const left = [...pointers.entries()][0];
      drag = { x: left[1].x, y: left[1].y, tx, ty };
    }
    if (pointers.size === 0) {
      drag = null;
      viewport.classList.remove("is-dragging");
    }
  };

  const blockTouch = (e) => {
    e.preventDefault();
  };

  const center = () => {
    const r = viewRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  };

  const onKey = (e) => {
    if (e.key === "Escape") return;
    const c = center();
    if (e.key === "+" || e.key === "=") {
      e.preventDefault();
      zoomAt(c.x, c.y, STEP);
    } else if (e.key === "-" || e.key === "_") {
      e.preventDefault();
      zoomAt(c.x, c.y, 1 / STEP);
    } else if (e.key === "0") {
      e.preventDefault();
      resetView();
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      tx += PAN;
      apply();
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      tx -= PAN;
      apply();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      ty += PAN;
      apply();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      ty -= PAN;
      apply();
    }
  };

  const isControls = (el) => {
    if (!el) return false;
    return !!(el.closest && el.closest('.doc-zoom__close, .doc-zoom__controls, .doc-zoom__btn'));
  };

  const onBackdropClick = (e) => {
    if (isControls(e.target)) return;
    if (moved) return;
    // pointer-events: none のため、図の上でも e.target は viewport になる。
    // 座標で図の上かどうかを見て、図の外の余白のときだけ閉じる。
    if (!onImage(e.clientX, e.clientY)) {
      dialog.close();
    }
  };

  const ensureDialog = () => {
    if (dialog) return;
    dialog = document.createElement("dialog");
    dialog.className = "doc-zoom";
    dialog.setAttribute("aria-modal", "true");
    closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "doc-zoom__btn doc-zoom__close";
    closeBtn.textContent = "閉じる";
    const controls = document.createElement("div");
    controls.className = "doc-zoom__controls";
    minusBtn = document.createElement("button");
    minusBtn.type = "button";
    minusBtn.className = "doc-zoom__btn";
    minusBtn.textContent = "−";
    minusBtn.setAttribute("aria-label", "縮小");
    plusBtn = document.createElement("button");
    plusBtn.type = "button";
    plusBtn.className = "doc-zoom__btn";
    plusBtn.textContent = "＋";
    plusBtn.setAttribute("aria-label", "拡大");
    controls.append(minusBtn, plusBtn);
    viewport = document.createElement("div");
    viewport.className = "doc-zoom__viewport";
    stage = document.createElement("div");
    stage.className = "doc-zoom__stage";
    viewport.appendChild(stage);
    dialog.append(closeBtn, controls, viewport);
    document.body.appendChild(dialog);

    closeBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      dialog.close();
    });
    const zoomBy = (factor) => (e) => {
      e.stopPropagation();
      const c = center();
      zoomAt(c.x, c.y, factor);
    };
    minusBtn.addEventListener("click", zoomBy(1 / STEP));
    plusBtn.addEventListener("click", zoomBy(STEP));
    dialog.addEventListener("close", destroy);
    dialog.addEventListener("click", onBackdropClick);
    dialog.addEventListener("keydown", onKey);
    viewport.addEventListener("wheel", onWheel, { passive: false });
    viewport.addEventListener("pointerdown", onPointerDown);
    viewport.addEventListener("pointermove", onPointerMove);
    viewport.addEventListener("pointerup", onPointerUp);
    viewport.addEventListener("pointercancel", onPointerUp);
    viewport.addEventListener("touchmove", blockTouch, { passive: false });
  };

  const open = async (img) => {
    ensureDialog();
    const seq = ++openSeq;
    document.documentElement.style.overflow = "hidden";
    const alt = (img.getAttribute("alt") || "図").trim();
    dialog.setAttribute("aria-label", `${alt}（拡大）`);
    try {
      await fillStage(img);
    } catch (_) {
      if (seq !== openSeq) return;
      destroy();
      return;
    }
    if (seq !== openSeq || !dialog) return;
    if (!dialog.open) dialog.showModal();
    resetView();
    closeBtn.focus();
  };

  document.addEventListener("click", (e) => {
    const img = e.target && e.target.closest && e.target.closest(SELECTOR);
    if (!zoomable(img)) return;
    e.preventDefault();
    open(img);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    if (!zoomable(e.target)) return;
    e.preventDefault();
    open(e.target);
  });

  const boot = () => enhance(document);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(boot);
  }
})();
