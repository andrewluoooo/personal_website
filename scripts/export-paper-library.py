#!/usr/bin/env python3
"""Export an unlocked paper_reader vault into static/papers/ for this site.

Decrypts Fernet-encrypted library HTML (and any referenced raw assets) into a
public static snapshot. Does not write secret keys into the site tree.

Requires:
  PAPER_READER_SECRET_KEY   Account secret (pr_…) that unlocks the vault
  Optional PAPER_READER_LIBRARY_DIR  Override library root (default ~/.paper_reader_library)
  Optional PAPER_READER_PACKAGE_DIR  Path to reader-research-paper repo (for vault helpers)

Usage:
  PAPER_READER_SECRET_KEY=pr_… python3 scripts/export-paper-library.py
"""

from __future__ import annotations

import base64
import hashlib
import html as htmlmod
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "static" / "papers"
CONTENT_INDEX = ROOT / "content" / "papers" / "_index.md"
PBKDF2 = 200_000

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


def _library_dir() -> Path:
    env = os.environ.get("PAPER_READER_LIBRARY_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".paper_reader_library"


def _import_vault():
    pkg = os.environ.get("PAPER_READER_PACKAGE_DIR", "").strip()
    candidates = []
    if pkg:
        candidates.append(Path(pkg).expanduser())
    candidates.append(Path.home() / "Projects" / "reader-research-paper")
    for c in candidates:
        if (c / "paper_reader" / "vault.py").is_file():
            sys.path.insert(0, str(c))
            from paper_reader.vault import decrypt_raw_tree, raw_paper_dir  # noqa: WPS433

            return decrypt_raw_tree, raw_paper_dir
    raise SystemExit(
        "Could not import paper_reader.vault — set PAPER_READER_PACKAGE_DIR to the "
        "reader-research-paper checkout."
    )


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


def _clean_authors(authors) -> str:
    if not authors:
        return ""
    if isinstance(authors, str):
        authors = [authors]
    text = ", ".join(a.replace("\n", " ").strip() for a in authors if a and str(a).strip())
    text = " ".join(text.split())
    if len(text) > 160:
        text = text[:157] + "…"
    return text


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


def _write_content_index(manifest: list[dict]) -> None:
    cards = []
    for p in manifest:
        title = htmlmod.escape(_clean_text(p.get("title") or p["id"], 200))
        authors = htmlmod.escape(_clean_authors(p.get("authors")))
        venue = htmlmod.escape(_clean_text(p.get("venue") or "", 120))
        summary = htmlmod.escape(_clean_text(p.get("summary") or "", 240))
        url = htmlmod.escape(p["url"])
        authors_html = f'<p class="pub-authors">{authors}</p>' if authors else ""
        venue_html = f'<p class="pub-venue">{venue}</p>' if venue else ""
        summary_html = f'<p class="pub-abstract">{summary}</p>' if summary else ""
        cards.append(
            f'''    <article class="pub-card">
      <div class="pub-thumb" aria-hidden="true">
        <svg class="pub-thumb-svg" viewBox="0 0 160 100" xmlns="http://www.w3.org/2000/svg" role="img">
          <rect width="160" height="100" fill="#f4f4f5" stroke="#d4d4d8" stroke-width="1" />
          <rect x="28" y="22" width="70" height="8" rx="2" fill="#d4d4d8" />
          <rect x="28" y="38" width="104" height="5" rx="1.5" fill="#e4e4e7" />
          <rect x="28" y="50" width="96" height="5" rx="1.5" fill="#e4e4e7" />
          <rect x="28" y="62" width="84" height="5" rx="1.5" fill="#e4e4e7" />
        </svg>
      </div>
      <div class="pub-content">
        <h3 class="pub-title"><a href="{url}">{title}</a></h3>
        {authors_html}
        {venue_html}
        {summary_html}
        <div class="pub-actions">
          <a class="pub-action" href="{url}">Read paper →</a>
        </div>
      </div>
    </article>'''
        )

    body = f"""---
title: "Papers"
description: "A static snapshot of papers from my research reading library."
---

<div class="pub-page">
  <p class="pub-scholar">
    A browsable snapshot of papers from my local research reader — HTML restyled for reading.
    This archive is regenerated from the library when updated.
  </p>

  <p class="pub-updated">{len(manifest)} papers</p>

  <div class="pub-year-block">
    <h2 class="pub-year">Library</h2>
    <hr class="pub-year-rule" />
{chr(10).join(cards)}
  </div>
</div>
"""
    CONTENT_INDEX.parent.mkdir(parents=True, exist_ok=True)
    CONTENT_INDEX.write_text(body, encoding="utf-8")


def main() -> None:
    secret = os.environ.get("PAPER_READER_SECRET_KEY", "").strip()
    if not secret:
        raise SystemExit("Set PAPER_READER_SECRET_KEY to your account secret (pr_…).")

    decrypt_raw_tree, raw_paper_dir = _import_vault()
    lib = _library_dir()
    accounts = json.loads((lib / "accounts.json").read_text(encoding="utf-8"))["accounts"]
    acct = _find_account(accounts, secret)
    fernet = _derive_fernet(secret, bytes.fromhex(acct["enc_salt"]))
    vdir = lib / "vaults" / acct["id"]
    items = json.loads(fernet.decrypt((vdir / "index.json.enc").read_bytes()))
    active = [
        i
        for i in items
        if isinstance(i, dict)
        and not i.get("deletedAt")
        and i.get("status") != "trash"
        and i.get("id")
    ]

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    manifest: list[dict] = []
    for it in sorted(active, key=lambda x: (x.get("title") or "").lower()):
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

        (paper_dir / "index.html").write_text(html, encoding="utf-8")
        authors = it.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        entry = {
            "id": pid,
            "title": it.get("title") or pid,
            "authors": authors,
            "venue": it.get("venue") or "",
            "summary": it.get("summary") or "",
            "url": f"/papers/{pid}/",
            "addedAt": it.get("addedAt"),
            "tags": it.get("tags") or [],
        }
        manifest.append(entry)
        print(f"wrote {pid} | {_clean_text(entry['title'], 70)}")

    (OUT / "index.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _write_content_index(manifest)
    print(f"exported {len(manifest)} papers → {OUT}")


if __name__ == "__main__":
    main()
