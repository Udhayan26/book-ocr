/*! எழுத்து OCR embed widget — https://github.com/Udhayan26/book-ocr
 *
 * Inline (shows the tool where the script tag is):
 *   <script src="https://ocr.udhayam.in/embed.js" data-lang="tam+eng"></script>
 *
 * Button that opens the tool in a pop-up:
 *   <script src="https://ocr.udhayam.in/embed.js" data-mode="button" data-label="தமிழ் OCR"></script>
 *
 * Options (data-*): lang ("tam+eng", "tam", "eng", "san+eng", …), mode ("inline" | "button"),
 *   label (button text), target (CSS selector to place the inline tool or button into),
 *   floating ("true" puts the button at the bottom-right corner of the page).
 *
 * JavaScript:  EzhuthuOCR.open({lang})   EzhuthuOCR.close()
 *              EzhuthuOCR.onText = (text, info) => { ... }      // every result
 *              document.addEventListener("ezhuthu-ocr", e => e.detail.text)
 */
(function () {
  var script = document.currentScript;
  if (!script) return;
  var BASE = new URL(".", script.src).href;
  var ORIGIN = new URL(BASE).origin;
  var opt = script.dataset || {};
  var lang = opt.lang || "tam+eng";
  var mode = opt.mode || "inline";
  var frames = [];

  function makeFrame(l, autoHeight) {
    var f = document.createElement("iframe");
    f.src = BASE + "?embed=1&lang=" + encodeURIComponent(l || lang);
    f.title = "Tamil OCR";
    f.allow = "clipboard-write; camera";
    f.loading = "lazy";
    f.style.cssText = "display:block;width:100%;border:0;background:transparent;" + (autoHeight ? "height:760px;" : "height:100%;");
    frames.push({ el: f, auto: autoHeight });
    return f;
  }

  // results + auto height from the tool
  window.addEventListener("message", function (e) {
    if (e.origin !== ORIGIN || !e.data || typeof e.data !== "object") return;
    var fr = null;
    for (var i = 0; i < frames.length; i++) if (frames[i].el.contentWindow === e.source) fr = frames[i];
    if (!fr) return;
    if (e.data.type === "ezhuthu-height" && fr.auto) fr.el.style.height = Math.max(420, e.data.height) + "px";
    if (e.data.type === "ezhuthu-ocr") {
      var info = Object.assign({}, e.data); delete info.type; delete info.text;
      if (typeof API.onText === "function") { try { API.onText(e.data.text, info); } catch (err) { console.error(err); } }
      document.dispatchEvent(new CustomEvent("ezhuthu-ocr", { detail: { text: e.data.text, info: info } }));
    }
  });

  // pop-up
  var overlay = null;
  function open(o) {
    o = o || {};
    if (overlay) return;
    overlay = document.createElement("div");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-label", "Tamil OCR");
    overlay.style.cssText = "position:fixed;inset:0;z-index:2147483000;background:rgba(20,15,10,.55);display:flex;align-items:center;justify-content:center;padding:2vh 2vw";
    var box = document.createElement("div");
    box.style.cssText = "position:relative;width:min(1280px,100%);height:96vh;background:#f6f2ea;border-radius:14px;overflow:hidden;box-shadow:0 10px 40px rgba(0,0,0,.35)";
    var x = document.createElement("button");
    x.type = "button"; x.textContent = "✕"; x.setAttribute("aria-label", "Close");
    x.style.cssText = "position:absolute;top:8px;right:10px;z-index:2;border:0;border-radius:50%;width:34px;height:34px;font-size:16px;cursor:pointer;background:#1f1b16;color:#fff";
    x.onclick = close;
    var inner = document.createElement("div");
    inner.style.cssText = "position:absolute;inset:0;overflow:auto;padding:12px 12px 0";
    inner.appendChild(makeFrame(o.lang, true));
    box.appendChild(x); box.appendChild(inner); overlay.appendChild(box);
    overlay.addEventListener("click", function (e) { if (e.target === overlay) close(); });
    document.addEventListener("keydown", esc);
    document.body.appendChild(overlay);
    document.documentElement.style.overflow = "hidden";
  }
  function close() {
    if (!overlay) return;
    var f = overlay.querySelector("iframe");
    frames = frames.filter(function (fr) { return fr.el !== f; });
    overlay.remove(); overlay = null;
    document.removeEventListener("keydown", esc);
    document.documentElement.style.overflow = "";
  }
  function esc(e) { if (e.key === "Escape") close(); }

  var API = window.EzhuthuOCR = window.EzhuthuOCR || {};
  API.open = open; API.close = close;

  function place(el) {
    var target = opt.target && document.querySelector(opt.target);
    if (target) target.appendChild(el); else script.parentNode.insertBefore(el, script.nextSibling);
  }

  if (mode === "button") {
    var b = document.createElement("button");
    b.type = "button";
    b.textContent = opt.label || "தமிழ் OCR — image to text";
    b.style.cssText = "font:600 15px/1.2 'Noto Sans Tamil',system-ui,sans-serif;background:#b4471f;color:#fff;border:0;border-radius:10px;padding:11px 18px;cursor:pointer;box-shadow:0 4px 14px rgba(180,71,31,.3)";
    if (opt.floating === "true") b.style.cssText += ";position:fixed;right:18px;bottom:18px;z-index:2147482999";
    b.onclick = function () { open({ lang: lang }); };
    if (opt.floating === "true") document.body ? document.body.appendChild(b) : document.addEventListener("DOMContentLoaded", function () { document.body.appendChild(b); });
    else place(b);
  } else {
    var wrap = document.createElement("div");
    wrap.className = "ezhuthu-ocr";
    wrap.appendChild(makeFrame(lang, true));
    place(wrap);
  }
})();
