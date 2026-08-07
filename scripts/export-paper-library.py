#!/usr/bin/env python3
"""Export an unlocked paper_reader vault into static/papers/ for this site.

Produces an exact static snapshot of the paper_reader library UI (same CSS/JS)
plus self-contained reader pages. No backend — API calls are stubbed client-side.

Highlights/notes live in the browser (localStorage keys
``paper_reader_highlights::<encodeURIComponent(title)>``); notes are the
``note`` field on each highlight object. Pass a dump via
PAPER_READER_LOCALSTORAGE_JSON so they are seeded into the static pages.

Requires:
  PAPER_READER_SECRET_KEY   Account secret (pr_…) that unlocks the vault
  Optional PAPER_READER_LIBRARY_DIR  Override library root (default ~/.paper_reader_library)
  Optional PAPER_READER_PACKAGE_DIR  Path to reader-research-paper repo
  Optional PAPER_READER_LOCALSTORAGE_JSON  Path to localStorage dump JSON
      Shape: {"data": {"paper_reader_highlights::…": "[…]", …}}
      or a flat {key: value} map. Also checked at
      ~/.paper_reader_library/localstorage-export.json

Usage:
  PAPER_READER_SECRET_KEY=pr_… python3 scripts/export-paper-library.py

Dump localStorage from an open Chrome tab on http://127.0.0.1:8765 (example)::

  osascript -e 'tell application "Google Chrome" to execute
    (first tab of first window whose URL starts with "http://127.0.0.1:8765")
    javascript "JSON.stringify({data:Object.fromEntries(
      [...Array(localStorage.length)].map((_,i)=>{const k=localStorage.key(i);
      return [k, localStorage.getItem(k)]}).filter(([k])=>k&&k.startsWith(\"paper_reader_\")))})"'

Never commits secret keys. Does not write keys into the site tree.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "static" / "papers"
CONTENT_PAPERS = ROOT / "content" / "papers"
LAYOUTS_PAPERS = ROOT / "layouts" / "papers"
PBKDF2 = 200_000
HIGHLIGHT_PREFIX = "paper_reader_highlights::"
SCROLL_PREFIX = "paper_reader_scroll::"
PCT_PREFIX = "paper_reader_pct::"

BACK_SNIPPET = """
<style>
  .pr-site-back{position:fixed;top:12px;left:12px;z-index:9999;font:600 13px/1.2 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
    background:rgba(250,249,245,.92);color:#1a1a1a;border:1px solid #e3e0d8;border-radius:8px;padding:8px 12px;text-decoration:none;
    backdrop-filter:blur(8px);box-shadow:0 1px 2px rgba(0,0,0,.04)}
  .pr-site-back:hover{background:#fff;border-color:#cfc9bc}
  @media (prefers-color-scheme: dark){
    .pr-site-back{background:rgba(32,32,32,.9);color:#f5f5f5;border-color:#444}
  }
</style>
<a class="pr-site-back" href="/papers/">← Papers</a>
"""

STATIC_NOTE_HTML = """
        <div class="prefs-popover-label" style="margin-top: 0.6em;">Snapshot</div>
        <div class="prefs-popover-row" style="flex-direction: column; align-items: stretch; gap: 0.45em; padding-bottom: 0.2em;">
          <div style="font-size: 0.78em; color: var(--muted); line-height: 1.45;">
            Read-only static export for andluo.com. Upload, sync, and account changes are disabled.
          </div>
        </div>
"""


def _library_dir() -> Path:
    env = os.environ.get("PAPER_READER_LIBRARY_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".paper_reader_library"


def _package_dir() -> Path:
    pkg = os.environ.get("PAPER_READER_PACKAGE_DIR", "").strip()
    candidates = []
    if pkg:
        candidates.append(Path(pkg).expanduser())
    candidates.append(Path.home() / "Projects" / "reader-research-paper")
    for c in candidates:
        if (c / "paper_reader" / "vault.py").is_file():
            return c
    raise SystemExit(
        "Could not find paper_reader package — set PAPER_READER_PACKAGE_DIR to the "
        "reader-research-paper checkout."
    )


def _import_vault(pkg: Path):
    sys.path.insert(0, str(pkg))
    from paper_reader.vault import decrypt_raw_tree, raw_paper_dir  # noqa: WPS433

    return decrypt_raw_tree, raw_paper_dir


def _hash_secret(secret_key: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", secret_key.encode("utf-8"), salt, PBKDF2).hex()


def _derive_fernet(secret_key: str, enc_salt: bytes):
    from cryptography.fernet import Fernet

    raw = hashlib.pbkdf2_hmac(
        "sha256", secret_key.encode("utf-8"), enc_salt, PBKDF2, dklen=32
    )
    return Fernet(base64.urlsafe_b64encode(raw))


def _find_account(accounts: list[dict], secret_key: str) -> dict:
    for acct in accounts:
        salt = bytes.fromhex(acct["key_salt"])
        if _hash_secret(secret_key, salt) == acct["key_hash"]:
            return acct
    raise SystemExit("Secret key does not match any account in accounts.json")


def _clean_text(s: str, limit: int) -> str:
    s = " ".join((s or "").replace("\n", " ").split())
    if len(s) > limit:
        s = s[: limit - 1] + "…"
    return s


def _rewrite_abs_raw(html: str, pid: str) -> str:
    return re.sub(
        rf'(src|href)=(["\'])/Users/[^"\']+?/\.paper_reader_library/raw/{re.escape(pid)}/([^"\']+)\2',
        lambda m: f"{m.group(1)}={m.group(2)}raw/{m.group(3)}{m.group(2)}",
        html,
        flags=re.I,
    )


def _prune_unreferenced_raw(paper_dir: Path, html: str) -> None:
    refs = {paper_dir / r for r in re.findall(r'src="(raw/[^"]+)"', html)}
    raw = paper_dir / "raw"
    if not raw.is_dir():
        return
    for p in sorted(raw.rglob("*"), reverse=True):
        if p.is_file() and p not in refs:
            p.unlink(missing_ok=True)
    for p in sorted(raw.rglob("*"), reverse=True):
        if p.is_dir() and not any(p.iterdir()):
            p.rmdir()


def _public_index_entry(it: dict) -> dict:
    """Fields the library UI expects, plus a site-relative url."""
    authors = it.get("authors") or []
    if isinstance(authors, str):
        authors = [authors]
    pid = str(it["id"])
    return {
        "id": pid,
        "title": it.get("title") or pid,
        "authors": authors,
        "venue": it.get("venue") or "",
        "summary": it.get("summary") or "",
        "status": it.get("status") or "inbox",
        "tags": it.get("tags") or [],
        "pinned": bool(it.get("pinned")),
        "completed": bool(it.get("completed")),
        "addedAt": it.get("addedAt"),
        "lastOpenedAt": it.get("lastOpenedAt"),
        "deletedAt": it.get("deletedAt"),
        "sourceFilename": it.get("sourceFilename") or "",
        "url": f"/papers/{pid}/",
    }


def _static_bootstrap(papers: list[dict]) -> str:
    payload = json.dumps(papers, separators=(",", ":"))
    # Prevent </script> breakouts in titles/summaries.
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e")
    return f"""<script>
window.__STATIC_PAPERS__ = {payload};
window.__PAPER_READER_STATIC__ = true;
(function () {{
  var papers = window.__STATIC_PAPERS__;
  function paperHref(id) {{
    return "/papers/" + encodeURIComponent(id) + "/";
  }}
  function jsonResp(data, status) {{
    return Promise.resolve(new Response(JSON.stringify(data), {{
      status: status || 200,
      headers: {{ "Content-Type": "application/json" }}
    }}));
  }}
  function findPaper(id) {{
    for (var i = 0; i < papers.length; i++) if (papers[i].id === id) return papers[i];
    return null;
  }}
  var origFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {{
    var url = typeof input === "string" ? input : (input && input.url) || "";
    var method = ((init && init.method) || "GET").toUpperCase();
    var path = url.replace(/^https?:\\/\\/[^/]+/, "").split("?")[0];
    var body = {{}};
    if (init && typeof init.body === "string") {{
      try {{ body = JSON.parse(init.body); }} catch (e) {{ body = {{}}; }}
    }}

    if (path === "/api/papers" && method === "GET") return jsonResp(papers);
    if (path === "/api/pipeline-status") return jsonResp([]);
    if (path === "/api/account" && method === "GET") {{
      return jsonResp({{ displayName: "Andrew", hasAvatar: false }});
    }}
    if (path === "/api/account" && method === "POST") {{
      return jsonResp({{
        ok: true,
        displayName: body.displayName || "Andrew",
        hasAvatar: false
      }});
    }}
    if (path.indexOf("/api/papers/") === 0) {{
      var rest = path.slice("/api/papers/".length);
      var parts = rest.split("/");
      var id = decodeURIComponent(parts[0] || "");
      var p = findPaper(id);
      if (!p) return jsonResp({{ error: "not found" }}, 404);
      if (method === "DELETE") {{
        papers = papers.filter(function (x) {{ return x.id !== id; }});
        window.__STATIC_PAPERS__ = papers;
        return jsonResp({{ ok: true }});
      }}
      if (method === "PATCH") {{
        Object.keys(body).forEach(function (k) {{ p[k] = body[k]; }});
        return jsonResp(p);
      }}
      if (parts[1] === "tags" && method === "PUT") {{
        p.tags = Array.isArray(body.tags) ? body.tags : [];
        return jsonResp(p);
      }}
      if (parts[1] === "status" && method === "PUT") {{
        p.status = body.status;
        if (body.status === "trash") p.deletedAt = Date.now() / 1000;
        else if (p.status !== "trash") p.deletedAt = null;
        return jsonResp(p);
      }}
    }}
    if (path.indexOf("/api/") === 0) {{
      return jsonResp({{ ok: true, error: "unavailable in static snapshot" }});
    }}
    return origFetch(input, init);
  }};

  // Rewrite library reader URLs to static site paths.
  document.addEventListener("click", function (e) {{
    var a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
    if (!a) return;
    var href = a.getAttribute("href") || "";
    var m = href.match(/^\\/library\\/([^\\/]+?)\\.html$/);
    if (m) a.setAttribute("href", paperHref(decodeURIComponent(m[1])));
  }}, true);
}})();
</script>
"""


def _build_library_index(pkg: Path, papers: list[dict]) -> str:
    sys.path.insert(0, str(pkg))
    from paper_reader.palette import get_palette_html  # noqa: WPS433
    from paper_reader.server import HOME_PAGE_HTML  # noqa: WPS433

    html_out = HOME_PAGE_HTML
    html_out = html_out.replace("<!--AUTH_LOGOUT_SLOT-->", STATIC_NOTE_HTML)
    # Point paper links at static reader pages under /papers/<id>/
    html_out = html_out.replace(
        '"/library/" + encodeURIComponent(p.id) + ".html"',
        '"/papers/" + encodeURIComponent(p.id) + "/"',
    )
    html_out = html_out.replace(
        "'/library/' + encodeURIComponent(p.id) + '.html'",
        "'/papers/' + encodeURIComponent(p.id) + '/'",
    )
    html_out = html_out.replace(
        "'/library/' + esc(j.paperId) + '.html'",
        "'/papers/' + esc(j.paperId) + '/'",
    )
    html_out = html_out.replace(
        '"/library/" + encodeURIComponent(res.data.id) + ".html"',
        '"/papers/" + encodeURIComponent(res.data.id) + "/"',
    )
    # Footer extras that need the live server → GitHub
    html_out = html_out.replace('href="/pipeline"', 'href="https://github.com/andrewluoooo/paper-reader"')
    html_out = html_out.replace('href="/about"', 'href="https://github.com/andrewluoooo/paper-reader"')
    html_out = html_out.replace('href="/guide"', 'href="https://github.com/andrewluoooo/paper-reader#readme"')
    # Soft-hide upload FAB (still in DOM for fidelity; click is stubbed via /api/upload)
    html_out = html_out.replace(
        ".add-paper-fab {",
        ".add-paper-fab { display: none !important;",
        1,
    )

    bootstrap = _static_bootstrap(papers)
    # Inject bootstrap early so fetch stub exists before library JS runs.
    if "<head>" in html_out:
        html_out = html_out.replace("<head>", "<head>\n" + bootstrap, 1)
    else:
        html_out = bootstrap + html_out

    html_out = html_out.replace("</body>", get_palette_html("home") + "\n</body>")

    # Site escape hatch back to the Hugo homepage (library is full-bleed).
    site_back = (
        '<a href="/" style="position:fixed;top:12px;right:12px;z-index:9999;'
        "font:600 13px/1.2 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        "background:rgba(250,249,245,.92);color:#1a1a1a;border:1px solid #e3e0d8;"
        "border-radius:8px;padding:8px 12px;text-decoration:none;"
        'backdrop-filter:blur(8px)">← andluo.com</a>\n'
    )
    html_out = re.sub(
        r"(<body[^>]*>)",
        r"\1\n" + site_back,
        html_out,
        count=1,
        flags=re.I,
    )
    return html_out


def _clear_hugo_papers_override() -> None:
    """Remove Hugo content/layout that would replace static/papers/index.html."""
    if CONTENT_PAPERS.exists():
        shutil.rmtree(CONTENT_PAPERS)
        print(f"removed {CONTENT_PAPERS} (so static/papers/index.html is served)")
    if LAYOUTS_PAPERS.exists():
        shutil.rmtree(LAYOUTS_PAPERS)
        print(f"removed {LAYOUTS_PAPERS}")


def _localstorage_candidates() -> list[Path]:
    env = os.environ.get("PAPER_READER_LOCALSTORAGE_JSON", "").strip()
    paths: list[Path] = []
    if env:
        paths.append(Path(env).expanduser())
    paths.append(_library_dir() / "localstorage-export.json")
    paths.append(Path("/tmp/paper_reader_localstorage.json"))
    return paths


def _load_localstorage_dump() -> dict[str, str]:
    """Return flat {localStorageKey: stringValue} for paper_reader_* keys."""
    for path in _localstorage_candidates():
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"warn: could not read {path}: {e}", file=sys.stderr)
            continue
        if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
            data = raw["data"]
        elif isinstance(raw, dict):
            data = raw
        else:
            continue
        out: dict[str, str] = {}
        for k, v in data.items():
            if not isinstance(k, str) or not k.startswith("paper_reader_"):
                continue
            if isinstance(v, (dict, list)):
                out[k] = json.dumps(v, separators=(",", ":"))
            elif isinstance(v, str):
                out[k] = v
            else:
                out[k] = json.dumps(v)
        print(f"loaded {len(out)} localStorage keys from {path}")
        return out
    print(
        "note: no localStorage dump found — highlights/notes will not be seeded.\n"
        "      Set PAPER_READER_LOCALSTORAGE_JSON or write "
        f"{_library_dir() / 'localstorage-export.json'}",
        file=sys.stderr,
    )
    return {}


def _html_title(html: str) -> str:
    m = re.search(r"<title>(.*?)</title>", html, flags=re.I | re.S)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()


def _seed_keys_for_title(ls: dict[str, str], title: str) -> dict[str, str]:
    """Pick highlight/scroll/pct keys that belong to this document title."""
    if not title:
        return {}
    enc = urllib.parse.quote(title, safe="")
    wanted = (
        HIGHLIGHT_PREFIX + enc,
        SCROLL_PREFIX + enc,
        PCT_PREFIX + enc,
    )
    return {k: ls[k] for k in wanted if k in ls}


def _storage_seed_script(seed: dict[str, str]) -> str:
    """Inject early so reader JS loadHighlights() sees seeded data."""
    if not seed:
        return ""
    payload = json.dumps(seed, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e")
    return f"""
<script>
/* Seeded paper_reader localStorage (highlights + notes) for static snapshot */
(function () {{
  var seed = {payload};
  try {{
    Object.keys(seed).forEach(function (k) {{
      localStorage.setItem(k, seed[k]);
    }});
  }} catch (e) {{}}
}})();
</script>
"""


def _inject_head_script(html: str, script: str) -> str:
    if not script:
        return html
    m = re.search(r"<head[^>]*>", html, flags=re.I)
    if m:
        i = m.end()
        return html[:i] + "\n" + script + html[i:]
    return script + html


def _highlight_stats(ls: dict[str, str]) -> tuple[int, int, int]:
    """Return (papers_with_highlights, total_highlights, highlights_with_notes)."""
    papers = 0
    total = 0
    noted = 0
    for k, v in ls.items():
        if not k.startswith(HIGHLIGHT_PREFIX):
            continue
        try:
            arr = json.loads(v)
        except json.JSONDecodeError:
            continue
        if not isinstance(arr, list) or not arr:
            continue
        papers += 1
        total += len(arr)
        noted += sum(1 for h in arr if isinstance(h, dict) and str(h.get("note") or "").strip())
    return papers, total, noted


def main() -> None:
    secret = os.environ.get("PAPER_READER_SECRET_KEY", "").strip()
    if not secret:
        # Allow a local one-shot file (never committed) for agent/export runs.
        tmp = Path("/tmp/paper_reader_export_env")
        if tmp.is_file():
            secret = tmp.read_text(encoding="utf-8").strip()
        if not secret:
            raise SystemExit("Set PAPER_READER_SECRET_KEY to your account secret (pr_…).")

    pkg = _package_dir()
    decrypt_raw_tree, raw_paper_dir = _import_vault(pkg)
    lib = _library_dir()
    accounts = json.loads((lib / "accounts.json").read_text(encoding="utf-8"))["accounts"]
    acct = _find_account(accounts, secret)
    fernet = _derive_fernet(secret, bytes.fromhex(acct["enc_salt"]))
    vdir = lib / "vaults" / acct["id"]
    items = json.loads(fernet.decrypt((vdir / "index.json.enc").read_bytes()))
    # Keep trash in the embedded index so the Trash tab works offline.
    active_for_pages = [
        i
        for i in items
        if isinstance(i, dict)
        and not i.get("deletedAt")
        and i.get("status") != "trash"
        and i.get("id")
    ]
    library_papers = [
        _public_index_entry(i)
        for i in items
        if isinstance(i, dict) and i.get("id")
    ]

    ls_dump = _load_localstorage_dump()
    # Persist a copy next to the vault for future regenerations (not a secret).
    if ls_dump:
        cache = lib / "localstorage-export.json"
        try:
            cache.write_text(
                json.dumps({"data": ls_dump}, indent=2),
                encoding="utf-8",
            )
            print(f"cached localStorage dump → {cache}")
        except OSError as e:
            print(f"warn: could not cache localStorage dump: {e}", file=sys.stderr)

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    written = 0
    seeded_papers = 0
    for it in sorted(active_for_pages, key=lambda x: (x.get("title") or "").lower()):
        pid = str(it["id"])
        enc = vdir / f"{pid}.html.enc"
        if not enc.is_file():
            print(f"skip missing html {pid}", file=sys.stderr)
            continue
        html = fernet.decrypt(enc.read_bytes()).decode("utf-8", errors="replace")
        paper_dir = OUT / pid
        paper_dir.mkdir(parents=True)

        if "/.paper_reader_library/raw/" in html:
            decrypt_raw_tree(fernet, raw_paper_dir(vdir, pid), paper_dir / "raw")
            html = _rewrite_abs_raw(html, pid)
            _prune_unreferenced_raw(paper_dir, html)

        if re.search(r"<body[^>]*>", html, re.I):
            html = re.sub(r"(<body[^>]*>)", r"\1" + BACK_SNIPPET, html, count=1, flags=re.I)
        else:
            html = BACK_SNIPPET + html

        title = _html_title(html) or (it.get("title") or "")
        seed = _seed_keys_for_title(ls_dump, title)
        # Also try vault title if HTML title differs (rare truncation edge cases).
        if not seed and it.get("title"):
            seed = _seed_keys_for_title(ls_dump, str(it["title"]))
        html = _inject_head_script(html, _storage_seed_script(seed))
        hl_vals = [
            v for k, v in seed.items() if k.startswith(HIGHLIGHT_PREFIX)
        ]
        if hl_vals:
            try:
                n = len(json.loads(hl_vals[0]))
            except json.JSONDecodeError:
                n = 0
            if n:
                seeded_papers += 1
                print(f"seeded {n} highlights → {pid}")

        (paper_dir / "index.html").write_text(html, encoding="utf-8")
        written += 1
        print(f"wrote {pid} | {_clean_text(it.get('title') or pid, 70)}")

    manifest = [_public_index_entry(i) for i in active_for_pages]
    manifest.sort(key=lambda x: (x.get("title") or "").lower())
    (OUT / "index.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Library home needs all highlight keys so the info panel can list them.
    hl_seed = {k: v for k, v in ls_dump.items() if k.startswith(HIGHLIGHT_PREFIX)}
    library_html = _build_library_index(pkg, library_papers)
    library_html = _inject_head_script(library_html, _storage_seed_script(hl_seed))
    (OUT / "index.html").write_text(library_html, encoding="utf-8")
    print(f"wrote library UI → {OUT / 'index.html'}")

    # Public-safe summary (no raw localStorage secrets — highlights are reading notes).
    papers_n, total_n, noted_n = _highlight_stats(ls_dump)
    summary = {
        "papersWithHighlights": papers_n,
        "totalHighlights": total_n,
        "highlightsWithNotes": noted_n,
        "seededReaderPages": seeded_papers,
        "titles": [],
    }
    titles = []
    for k, v in ls_dump.items():
        if not k.startswith(HIGHLIGHT_PREFIX):
            continue
        try:
            arr = json.loads(v)
        except json.JSONDecodeError:
            continue
        if isinstance(arr, list) and arr:
            titles.append(urllib.parse.unquote(k[len(HIGHLIGHT_PREFIX) :]))
    summary["titles"] = sorted(titles)
    (OUT / "highlights.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        f"highlights: {papers_n} papers, {total_n} highlights, "
        f"{noted_n} with notes (seeded into {seeded_papers} reader pages)"
    )

    _clear_hugo_papers_override()
    print(f"exported {written} papers → {OUT}")


if __name__ == "__main__":
    main()
