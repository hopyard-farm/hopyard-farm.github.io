#!/usr/bin/env python3
"""
Hopyard Farm Static Site Builder (build.py)
===========================================
Reads `content/farm.toml` and `content/farmer.txt` and builds `public/`.
"""

import argparse
import html
import http.server
import json
import os
import shutil
import socketserver
import ssl
import tomllib
import urllib.request
from pathlib import Path


def esc(val) -> str:
    if val is None:
        return ""
    return html.escape(str(val), quote=True)


def _norm_url(u: str) -> str:
    return (u or "").strip().rstrip("/")


def fetch_behold_photos(feed_url: str, fallback_photos: list, default_ig_url: str) -> list:
    """Fetch up to 9 recent Instagram posts from Behold JSON feed, padding to 9 with fallbacks."""
    items = []
    if feed_url:
        raw_bytes = None
        req = urllib.request.Request(feed_url, headers={"User-Agent": "HopyardFarmBuilder/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                raw_bytes = resp.read()
        except Exception:
            try:
                ctx = ssl._create_unverified_context()
                with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
                    raw_bytes = resp.read()
            except Exception as exc:
                print(f"Note: Could not fetch Behold feed at build time ({exc}); using fallback photos.")

        if raw_bytes:
            try:
                payload = json.loads(raw_bytes.decode("utf-8"))
                posts = payload if isinstance(payload, list) else payload.get("posts", [])
                for post in posts:
                    if len(items) >= 9:
                        break
                    sizes = post.get("sizes") or {}
                    children = post.get("children") or []
                    child_sizes = (children[0].get("sizes") or {}) if children else {}
                    img_url = (
                        (sizes.get("large") or {}).get("mediaUrl")
                        or (sizes.get("medium") or {}).get("mediaUrl")
                        or (child_sizes.get("large") or {}).get("mediaUrl")
                        or (child_sizes.get("medium") or {}).get("mediaUrl")
                        or post.get("thumbnailUrl")
                        or post.get("mediaUrl")
                        or ""
                    )
                    if not img_url:
                        continue
                    caption_raw = (post.get("prunedCaption") or post.get("caption") or "").strip()
                    first_line = next((ln.strip() for ln in caption_raw.splitlines() if ln.strip()), "")
                    alt_txt = (first_line[:110] + "…") if len(first_line) > 110 else (first_line or "Hopyard Farm on Instagram")
                    permalink = post.get("permalink") or default_ig_url
                    items.append({"image": img_url, "alt": alt_txt, "ig_url": permalink})
            except Exception as exc:
                print(f"Note: Failed parsing Behold JSON ({exc}); using fallback photos.")

    seen_urls = {_norm_url(x.get("ig_url", "")) for x in items if x.get("ig_url")}
    seen_imgs = {x.get("image", "") for x in items}

    for fb in fallback_photos:
        if len(items) >= 9:
            break
        fb_url = _norm_url(fb.get("ig_url", ""))
        fb_img = fb.get("image", "")
        if fb_url and fb_url in seen_urls:
            continue
        if fb_img in seen_imgs:
            continue
        items.append(fb)
        if fb_url:
            seen_urls.add(fb_url)
        seen_imgs.add(fb_img)

    for fb in fallback_photos:
        if len(items) >= 9:
            break
        if fb.get("image", "") not in seen_imgs:
            items.append(fb)
            seen_imgs.add(fb.get("image", ""))

    return items[:9]


def render_site(data: dict, farmer_text: str = "") -> str:
    site = data.get("site", {})
    barnstand = data.get("barnstand", {})
    farmer = data.get("farmer", {})
    fallback_photos = data.get("photos", [])[:9]
    default_ig_url = site.get("instagram_url", "https://www.instagram.com/hopyard_farm/")
    behold_feed_url = site.get("behold_feed_url", "").strip()
    photos = fetch_behold_photos(behold_feed_url, fallback_photos, default_ig_url)
    fallback_photos_json = json.dumps(fallback_photos).replace("</", "<\\/")
    store = data.get("store", {})

    if farmer_text.strip():
        paragraphs = [p.strip() for p in farmer_text.strip().split("\n\n") if p.strip()]
    else:
        paragraphs = farmer.get("paragraphs", [])

    farmer_paragraphs_html = "\n".join(
        f"<p>{esc(p)}</p>" for p in paragraphs
    )

    photos_grid_html = ""
    for p in photos:
        img_src = esc(p.get("image", ""))
        alt_txt = esc(p.get("alt", "Hopyard Farm photo"))
        ig_url = esc(p.get("ig_url", default_ig_url))
        photos_grid_html += f"""
          <a href="{ig_url}" target="_blank" rel="noopener" class="photo-tile" aria-label="{alt_txt} — View on Instagram">
            <img src="{img_src}" alt="{alt_txt}" loading="lazy">
            <div class="photo-overlay">
              <span class="photo-overlay-pill">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"></rect><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"></path><line x1="17.5" y1="6.5" x2="17.51" y2="6.5"></line></svg>
                View on Instagram &nearr;
              </span>
            </div>
          </a>"""

    store_enabled = bool(store.get("enabled", False))
    store_html = ""
    if store_enabled:
        cards = ""
        for prod in store.get("products", []):
            cards += f"""
            <article class="store-card">
              <img src="{esc(prod.get("image"))}" alt="{esc(prod.get("name"))}" loading="lazy">
              <div class="store-card-body">
                <div class="store-card-top">
                  <h3>{esc(prod.get("name"))}</h3>
                  <span class="store-price">{esc(prod.get("price"))}</span>
                </div>
                <p>{esc(prod.get("description"))}</p>
                <a href="{esc(prod.get("checkout_url"))}" class="btn btn-primary">{esc(prod.get("cta_text", "Reserve"))}</a>
              </div>
            </article>"""
        store_html = f"""
    <section id="store" class="section-panel">
      <div class="container">
        <div class="panel-box">
          <h2 class="section-title">{esc(store.get("heading", "Farmstand Pre-Orders"))}</h2>
          <p class="section-lead">{esc(store.get("subtitle", ""))}</p>
          <div class="store-grid">{cards}</div>
        </div>
      </div>
    </section>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Hopyard Farm, LLC · Graton, California</title>
  <meta name="description" content="{esc(site.get("description", ""))}">
  <link rel="canonical" href="{esc(site.get("url", "https://hopyardfarm.org"))}/">

  <meta property="og:type" content="website">
  <meta property="og:url" content="{esc(site.get("url", "https://hopyardfarm.org"))}/">
  <meta property="og:title" content="Hopyard Farm, LLC · Graton, CA">
  <meta property="og:description" content="{esc(site.get("description", ""))}">
  <meta property="og:image" content="{esc(site.get("url", "https://hopyardfarm.org"))}/images/amie%20tractor.jpg">

  <link rel="icon" href="/favicon.ico" sizes="any">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;600&family=Spectral:ital,wght@0,400;0,500;0,600;1,400;1,600&display=swap" rel="stylesheet">

  <style>
    :root {{
      --bg-header: #F5F0E6;
      --bg-body: #322833;
      --bg-panel: #F5F0E6;
      --bg-footer: #231B24;

      --text-primary: #221D24;
      --text-secondary: #433C45;

      --accent-sage: #33543D;
      --accent-sage-hover: #27422F;
      --accent-plum: #7A3650;
      --badge-bg: #EFE1E7;
      --badge-fg: #6B2B44;

      --border-subtle: rgba(34, 29, 36, 0.16);
      --font-serif: 'Spectral', Georgia, serif;
      --font-sans: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      --radius-md: 14px;
    }}

    *, *::before, *::after {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    html {{
      font-size: 103%;
      scroll-behavior: smooth;
      background-color: var(--bg-header);
      color: var(--text-primary);
      font-family: var(--font-serif);
      line-height: 1.65;
      -webkit-font-smoothing: antialiased;
    }}

    body {{
      background-color: var(--bg-header);
    }}

    img {{
      max-width: 100%;
      height: auto;
      display: block;
    }}

    a {{
      color: inherit;
      text-decoration: none;
    }}

    .container {{
      width: 100%;
      max-width: 900px;
      margin: 0 auto;
      padding: 0 1.25rem;
    }}

    /* Buttons */
    .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0.4rem;
      font-family: var(--font-sans);
      font-weight: 600;
      font-size: 0.9rem;
      padding: 0.56rem 1.15rem;
      border-radius: 999px;
      border: 1px solid transparent;
      cursor: pointer;
      transition: background-color 0.2s ease, border-color 0.2s ease;
    }}

    .btn-primary {{
      background: var(--accent-sage);
      color: #ffffff;
    }}

    .btn-primary:hover {{
      background: var(--accent-sage-hover);
    }}

    .btn-outline {{
      background: #FFFFFF;
      color: var(--text-primary);
      border-color: var(--border-subtle);
    }}

    .btn-outline:hover {{
      background: #FAF8F4;
    }}

    /* 1. Header Banner + Garden-Sage Gingham Ribbon */
    .top-banner {{
      background-color: var(--bg-header);
      padding: 1.15rem 0;
    }}

    .banner-inner {{
      display: flex;
      align-items: center;
      gap: 1.35rem;
    }}

    .brand-logo {{
      width: 118px;
      height: 118px;
      object-fit: contain;
      flex-shrink: 0;
    }}

    .brand-title {{
      font-family: var(--font-serif);
      font-size: clamp(1.95rem, 3.2vw, 2.45rem);
      font-weight: 600;
      line-height: 1.08;
      color: var(--text-primary);
      margin-bottom: 0.25rem;
    }}

    .brand-intro {{
      font-size: 1.14rem;
      font-style: italic;
      color: var(--text-secondary);
      line-height: 1.45;
    }}

    .gingham-sage {{
      height: 11px;
      width: 100%;
      background-color: #ffffff;
      background-image:
        linear-gradient(90deg, rgba(51, 84, 61, 0.52) 50%, transparent 50%),
        linear-gradient(rgba(51, 84, 61, 0.52) 50%, transparent 50%);
      background-size: 14px 14px;
      border-top: 1px solid rgba(51, 84, 61, 0.25);
      border-bottom: 1px solid rgba(51, 84, 61, 0.25);
    }}

    /* 2. Deep Fig Body + Seed-Packet Hairline Panels */
    .main-zone {{
      background-color: var(--bg-body);
      padding: 2.4rem 0 3.1rem;
    }}

    .section-panel {{
      margin-bottom: 2rem;
    }}

    .section-panel:last-child {{
      margin-bottom: 0;
    }}

    .panel-box {{
      background: var(--bg-panel);
      border: 1px solid var(--border-subtle);
      border-radius: 0;
      padding: 1.95rem 2.15rem;
      outline: 1px solid rgba(122, 54, 80, 0.2);
      outline-offset: -7px;
    }}

    /* Horizontal Split Barnstand Card */
    .barnstand-split {{
      display: grid;
      grid-template-columns: 1.35fr 0.65fr;
      gap: 1.75rem;
      align-items: center;
    }}

    .barnstand-cta-col {{
      display: flex;
      flex-direction: column;
      gap: 0.65rem;
      border-left: 1px solid var(--border-subtle);
      padding-left: 1.75rem;
    }}

    .hours-badge {{
      display: inline-block;
      background: var(--badge-bg);
      color: var(--badge-fg);
      font-family: var(--font-sans);
      font-size: 0.72rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      padding: 0.2rem 0.68rem;
      border-radius: 999px;
    }}

    .barnstand-heading {{
      font-family: var(--font-serif);
      font-size: clamp(1.8rem, 2.8vw, 2.2rem);
      font-weight: 600;
      color: var(--text-primary);
      line-height: 1.12;
      margin: 0.4rem 0 0.25rem;
    }}

    .hours-time {{
      font-family: var(--font-serif);
      font-size: 1.35rem;
      font-weight: 600;
      color: var(--accent-sage);
      line-height: 1.25;
      margin-bottom: 0.15rem;
    }}

    .hours-address {{
      font-weight: 600;
      color: var(--accent-plum);
      font-size: 1.08rem;
      margin-bottom: 0.45rem;
    }}

    .hours-note {{
      font-size: 1.04rem;
      color: var(--text-secondary);
    }}

    /* Farmer Section */
    .section-title {{
      font-family: var(--font-serif);
      font-size: clamp(1.8rem, 2.8vw, 2.2rem);
      font-weight: 600;
      line-height: 1.15;
      margin-bottom: 0.55rem;
    }}

    .section-lead {{
      color: var(--text-secondary);
      font-size: 1.04rem;
      margin-bottom: 1.5rem;
    }}

    .farmer-grid {{
      display: grid;
      grid-template-columns: 0.85fr 1.15fr;
      gap: 1.9rem;
      align-items: center;
    }}

    .farmer-name {{
      font-family: var(--font-serif);
      font-size: 1.28rem;
      font-style: italic;
      color: var(--accent-plum);
      font-weight: 600;
      margin-bottom: 0.6rem;
    }}

    .farmer-copy p {{
      color: var(--text-secondary);
      font-size: 1.06rem;
      margin-bottom: 0.9rem;
    }}

    .farmer-copy p:last-child {{
      margin-bottom: 0;
    }}

    .farmer-photo-frame {{
      border-radius: var(--radius-md);
      overflow: hidden;
      border: 1px solid var(--border-subtle);
    }}

    .farmer-photo-frame img {{
      width: 100%;
      object-fit: cover;
    }}

    /* 3x3 Instagram Photo Grid */
    .photo-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 0.85rem;
      margin-top: 1.15rem;
    }}

    .photo-tile {{
      position: relative;
      display: block;
      aspect-ratio: 1 / 1;
      border-radius: var(--radius-md);
      overflow: hidden;
      background: var(--bg-panel);
    }}

    .photo-tile img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      transition: transform 0.35s ease;
    }}

    .photo-overlay {{
      position: absolute;
      inset: 0;
      background: rgba(35, 27, 36, 0.45);
      display: flex;
      align-items: center;
      justify-content: center;
      opacity: 0;
      transition: opacity 0.22s ease;
    }}

    .photo-overlay-pill {{
      background: rgba(255, 255, 255, 0.95);
      color: var(--text-primary);
      font-family: var(--font-sans);
      font-size: 0.8rem;
      font-weight: 600;
      padding: 0.45rem 0.9rem;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      gap: 0.38rem;
    }}

    .photo-tile:hover img,
    .photo-tile:focus-visible img {{
      transform: scale(1.04);
    }}

    .photo-tile:hover .photo-overlay,
    .photo-tile:focus-visible .photo-overlay {{
      opacity: 1;
    }}

    .photos-footer {{
      margin-top: 1.45rem;
      text-align: center;
    }}

    /* Optional Store */
    .store-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
      gap: 1.25rem;
    }}

    .store-card {{
      background: #ffffff;
      border: 1px solid var(--border-subtle);
      border-radius: 0;
      overflow: hidden;
    }}

    .store-card img {{
      aspect-ratio: 4 / 3;
      width: 100%;
      object-fit: cover;
    }}

    .store-card-body {{
      padding: 1.1rem;
    }}

    .store-card-top {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 0.4rem;
    }}

    /* Compact Footer */
    .site-footer {{
      background: var(--bg-footer);
      color: #F5F2EB;
      padding: 1.15rem 0 0.95rem;
      font-family: var(--font-sans);
    }}

    .footer-inner {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 0.85rem;
      padding-bottom: 0.65rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.12);
    }}

    .footer-brand h2 {{
      font-family: var(--font-serif);
      font-size: 1.15rem;
      font-weight: 600;
    }}

    .footer-brand p {{
      color: rgba(245, 242, 235, 0.78);
      font-size: 0.84rem;
    }}

    .footer-links {{
      display: flex;
      flex-wrap: wrap;
      gap: 1.15rem;
      font-size: 0.88rem;
    }}

    .footer-links a {{
      color: #F5F2EB;
      text-decoration: underline;
      text-underline-offset: 4px;
    }}

    .footer-links a:hover {{
      color: #ffffff;
    }}

    .footer-bottom {{
      padding-top: 0.55rem;
      font-size: 0.68rem;
      font-style: italic;
      color: rgba(245, 242, 235, 0.65);
      display: flex;
      justify-content: flex-end;
    }}

    @media (max-width: 820px) {{
      .barnstand-split,
      .farmer-grid {{
        grid-template-columns: 1fr;
        gap: 1.35rem;
      }}

      .barnstand-cta-col {{
        border-left: none;
        padding-left: 0;
        border-top: 1px solid var(--border-subtle);
        padding-top: 1.1rem;
        flex-direction: row;
        flex-wrap: wrap;
      }}
    }}

    @media (max-width: 560px) {{
      .banner-inner {{
        flex-direction: column;
        align-items: center;
        text-align: center;
        gap: 0.6rem;
      }}

      .brand-logo {{
        width: 96px;
        height: 96px;
      }}

      .panel-box {{
        padding: 1.35rem;
      }}

      .barnstand-cta-col {{
        flex-direction: column;
      }}

      .photo-grid {{
        grid-template-columns: repeat(3, 1fr);
        gap: 0.45rem;
      }}

      .photo-tile {{
        border-radius: 8px;
      }}

      .photo-overlay {{
        display: none;
      }}
    }}
  </style>
</head>
<body>

  <!-- 1. HEADER BANNER + SAGE GINGHAM RIBBON -->
  <header class="top-banner">
    <div class="container banner-inner">
      <img
        src="{esc(site.get("logo_icon", "/images/transparent rabbit.png"))}"
        alt="Hopyard Farm Rabbit Logo"
        class="brand-logo"
      >
      <div>
        <h1 class="brand-title">Hopyard Farm, LLC</h1>
        <p class="brand-intro">
          A Regenerative Market-Garden Farm in Graton, Sonoma County, California.
        </p>
      </div>
    </div>
  </header>
  <div class="gingham-sage" aria-hidden="true"></div>

  <!-- 2. DEEP FIG BODY + CONTENT PANELS -->
  <main class="main-zone">
    <!-- WEEKLY BARNSTAND SPLIT CARD -->
    <section id="barnstand" class="section-panel">
      <div class="container">
        <div class="panel-box barnstand-split">
          <div>
            <span class="hours-badge">{esc(barnstand.get("status", "Open Weekly"))}</span>
            <h2 class="barnstand-heading">{esc(barnstand.get("heading", "Barnstand Thursdays!"))}</h2>
            <p class="hours-time">{esc(barnstand.get("hours", "Thursdays · 2:00 PM – Sunset"))}</p>
            <p class="hours-address">{esc(barnstand.get("address", "2590 Edison Street, Graton, CA"))}</p>
            <p class="hours-note">{esc(barnstand.get("note", ""))}</p>
          </div>
          <div class="barnstand-cta-col">
            <a href="https://www.google.com/maps/search/?api=1&amp;query=2590+Edison+Street+Graton+CA+95444" target="_blank" rel="noopener" class="btn btn-primary">
              Google Maps &rarr;
            </a>
            <a href="https://maps.apple.com/?q=2590+Edison+Street,+Graton,+CA+95444" target="_blank" rel="noopener" class="btn btn-outline">
              Apple Maps
            </a>
          </div>
        </div>
      </div>
    </section>

    <!-- GET TO KNOW YOUR FARMER -->
    <section id="farmer" class="section-panel">
      <div class="container">
        <div class="panel-box farmer-grid">
          <div class="farmer-copy">
            <h2 class="section-title">{esc(farmer.get("heading", "Get to Know Your Farmer"))}</h2>
            <div class="farmer-name">{esc(farmer.get("name", "Amie Neff"))}</div>
            <div id="farmerBio">
              {farmer_paragraphs_html}
            </div>
          </div>
          <div class="farmer-photo-frame">
            <img src="{esc(farmer.get("image", "/images/amie tractor.jpg"))}" alt="{esc(farmer.get("name", "Amie Neff"))} on the tractor at Hopyard Farm">
          </div>
        </div>
      </div>
    </section>

    <!-- 3x3 INSTAGRAM PHOTO GRID -->
    <section id="photos" class="section-panel">
      <div class="container">
        <div class="panel-box">
          <h2 class="section-title" style="margin-bottom: 0;">From the Farm</h2>
          <div id="photoGrid" class="photo-grid" data-behold-url="{esc(behold_feed_url)}" data-default-ig="{esc(default_ig_url)}">
            {photos_grid_html}
          </div>
          <div class="photos-footer">
            <a href="{esc(site.get("instagram_url", "https://www.instagram.com/hopyard_farm/"))}" target="_blank" rel="noopener" class="btn btn-primary">
              Follow {esc(site.get("instagram_handle", "@hopyard_farm"))} on Instagram &rarr;
            </a>
          </div>
        </div>
      </div>
    </section>

    {store_html}
  </main>

  <!-- 3. COMPACT FOOTER -->
  <footer id="contact" class="site-footer">
    <div class="container">
      <div class="footer-inner">
        <div class="footer-brand">
          <h2>Hopyard Farm, LLC</h2>
          <p>{esc(site.get("address", "2590 Edison Street, Graton, CA 95444"))}</p>
        </div>

        <div class="footer-links">
          <a href="mailto:{esc(site.get("email_primary", "amie@hopyardfarm.org"))}">{esc(site.get("email_primary", "amie@hopyardfarm.org"))}</a>
          <a href="{esc(site.get("instagram_url", "https://www.instagram.com/hopyard_farm/"))}" target="_blank" rel="noopener">Instagram ({esc(site.get("instagram_handle", "@hopyard_farm"))})</a>
        </div>
      </div>

      <div class="footer-bottom">
        <span>&copy; {esc(site.get("copyright_year", "2026"))} Hopyard Farm, LLC · Graton, CA</span>
      </div>
    </div>
  </footer>

  <script>
    fetch('/farmer.txt', {{ cache: 'no-store' }})
      .then(res => res.ok ? res.text() : '')
      .then(text => {{
        const bio = document.getElementById('farmerBio');
        if (!bio || !text.trim()) return;
        const paras = text.trim().split(/\\n\\s*\\n/).map(p => p.trim()).filter(Boolean);
        if (!paras.length) return;
        bio.innerHTML = '';
        paras.forEach(p => {{
          const el = document.createElement('p');
          el.textContent = p;
          bio.appendChild(el);
        }});
      }})
      .catch(() => {{}});

    (function () {{
      const grid = document.getElementById('photoGrid');
      const beholdUrl = grid && grid.dataset.beholdUrl;
      if (!grid || !beholdUrl) return;

      const defaultIg = grid.dataset.defaultIg || 'https://www.instagram.com/hopyard_farm/';
      const fallbackPhotos = {fallback_photos_json};
      const normUrl = u => (u || '').trim().replace(/\\/+$/, '');

      fetch(beholdUrl)
        .then(res => res.ok ? res.json() : null)
        .then(payload => {{
          if (!payload) return;
          const posts = Array.isArray(payload) ? payload : (payload.posts || []);
          const items = [];

          for (const post of posts) {{
            if (items.length >= 9) break;
            const sizes = post.sizes || {{}};
            const child0 = (post.children && post.children[0]) || {{}};
            const childSizes = child0.sizes || {{}};
            const imgUrl = (sizes.large && sizes.large.mediaUrl)
              || (sizes.medium && sizes.medium.mediaUrl)
              || (childSizes.large && childSizes.large.mediaUrl)
              || (childSizes.medium && childSizes.medium.mediaUrl)
              || post.thumbnailUrl
              || post.mediaUrl
              || '';
            if (!imgUrl) continue;

            const rawCap = (post.prunedCaption || post.caption || '').trim();
            const firstLine = (rawCap.split(/\\r?\\n/).map(s => s.trim()).find(Boolean)) || '';
            const altTxt = firstLine.length > 110
              ? firstLine.slice(0, 110) + '…'
              : (firstLine || 'Hopyard Farm on Instagram');
            items.push({{
              image: imgUrl,
              alt: altTxt,
              ig_url: post.permalink || defaultIg
            }});
          }}

          if (!items.length) return;

          const seenUrls = new Set(items.map(x => normUrl(x.ig_url)).filter(Boolean));
          const seenImgs = new Set(items.map(x => x.image));

          for (const fb of fallbackPhotos) {{
            if (items.length >= 9) break;
            const u = normUrl(fb.ig_url);
            if ((u && seenUrls.has(u)) || seenImgs.has(fb.image)) continue;
            items.push(fb);
            if (u) seenUrls.add(u);
            seenImgs.add(fb.image);
          }}

          for (const fb of fallbackPhotos) {{
            if (items.length >= 9) break;
            if (!seenImgs.has(fb.image)) {{
              items.push(fb);
              seenImgs.add(fb.image);
            }}
          }}

          grid.innerHTML = '';
          items.slice(0, 9).forEach(item => {{
            const a = document.createElement('a');
            a.href = item.ig_url || defaultIg;
            a.target = '_blank';
            a.rel = 'noopener';
            a.className = 'photo-tile';
            a.setAttribute('aria-label', (item.alt || 'Hopyard Farm photo') + ' — View on Instagram');

            const img = document.createElement('img');
            img.src = item.image;
            img.alt = item.alt || 'Hopyard Farm photo';
            img.loading = 'lazy';

            const overlay = document.createElement('div');
            overlay.className = 'photo-overlay';
            overlay.innerHTML = '<span class="photo-overlay-pill">'
              + '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">'
              + '<rect x="2" y="2" width="20" height="20" rx="5" ry="5"></rect>'
              + '<path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"></path>'
              + '<line x1="17.5" y1="6.5" x2="17.51" y2="6.5"></line></svg>'
              + 'View on Instagram &nearr;</span>';

            a.appendChild(img);
            a.appendChild(overlay);
            grid.appendChild(a);
          }});
        }})
        .catch(() => {{}});
    }})();
  </script>
</body>
</html>
"""


def build(repo_root: Path):
    toml_path = repo_root / "content" / "farm.toml"
    if not toml_path.exists():
        raise FileNotFoundError(f"Missing content file: {toml_path}")

    with open(toml_path, "rb") as f:
        data = tomllib.load(f)

    farmer_txt_path = repo_root / "content" / "farmer.txt"
    farmer_text = farmer_txt_path.read_text(encoding="utf-8") if farmer_txt_path.exists() else ""

    public_dir = repo_root / "public"
    public_dir.mkdir(parents=True, exist_ok=True)

    static_dir = repo_root / "static"
    if static_dir.exists():
        for item in static_dir.iterdir():
            dest = public_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)

    if farmer_txt_path.exists():
        shutil.copy2(farmer_txt_path, public_dir / "farmer.txt")

    html_out = render_site(data, farmer_text=farmer_text)
    index_path = public_dir / "index.html"
    index_path.write_text(html_out, encoding="utf-8")

    print(f"Built Hopyard Farm website -> {index_path} ({len(html_out):,} bytes)")


def serve(repo_root: Path, port: int = 8080):
    build(repo_root)
    public_dir = repo_root / "public"
    os.chdir(public_dir)

    handler = http.server.SimpleHTTPRequestHandler
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"Serving Hopyard Farm at http://localhost:{port} (Press Ctrl+C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped local server.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Hopyard Farm website from content/farm.toml")
    parser.add_argument("--serve", action="store_true", help="Start a local preview server after building")
    parser.add_argument("--port", type=int, default=8080, help="Port for --serve (default: 8080)")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    if args.serve:
        serve(root, args.port)
    else:
        build(root)
