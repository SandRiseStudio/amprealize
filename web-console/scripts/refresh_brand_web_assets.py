#!/usr/bin/env python3
"""
Regenerate web-console and extension brand bitmaps from sources in
../../files/images (repo root, sibling to the amprealize package).

- Removes light backgrounds (R,G,B >= threshold) -> transparent.
- Writes favicon + extension icons as square, centered, fixed output sizes.
- If ../../amprealize-enterprise/web-console exists, mirrors public/* branding there too.

After changing `public/branding/*` or `favicon.png`, bump `BRAND_ASSET_BUST` in
`web-console/src/components/branding/BrandLogo.tsx` and the `?v=` query on
`favicon.png` in `index.html` and `dashboard/index.html` (both OSS and
enterprise) so CDNs and browsers load the new files.

Run from any cwd:
  amprealize/.venv/bin/python amprealize/web-console/scripts/refresh_brand_web_assets.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageFile

# Large PNG; allow decompression of big images
ImageFile.LOAD_TRUNCATED_IMAGES = True

THRESH = 235  # aggressive: strips off-white common in "white" JPEG/PNG export


def _repo_main(script: Path) -> Path:
  """/.../Main when script is .../amprealize/web-console/scripts/thisfile.py"""
  return script.resolve().parents[3]


def remove_bright_bg(im: Image.Image, threshold: int = THRESH) -> Image.Image:
  im = im.convert("RGBA")
  px = im.load()
  w, h = im.size
  for y in range(h):
    for x in range(w):
      r, g, b, a = px[x, y]
      if r >= threshold and g >= threshold and b >= threshold:
        px[x, y] = (0, 0, 0, 0)
  return im


def save_cropped_rgba(im: Image.Image, path: Path) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  im = remove_bright_bg(im, THRESH)
  im.save(path, "PNG", optimize=True)
  print(f"ok {path}")


def to_square_favicon(source: Image.Image, out: Path, out_size: int) -> None:
  im = remove_bright_bg(source.convert("RGBA"), THRESH)
  bb = im.getbbox()
  if bb:
    im = im.crop(bb)
  w, h = im.size
  side = int(max(w, h) * 1.12) or 1
  canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
  ox, oy = (side - w) // 2, (side - h) // 2
  canvas.paste(im, (ox, oy), im)
  out.parent.mkdir(parents=True, exist_ok=True)
  canvas.resize((out_size, out_size), Image.Resampling.LANCZOS).save(out, "PNG", optimize=True)
  print(f"ok {out} ({out_size}×{out_size})")


def main() -> int:
  here = Path(__file__).resolve()
  main = _repo_main(here)
  src = main / "files" / "images"
  if not (src / "amprealize_logo.png").is_file():
    print(f"Missing {src / 'amprealize_logo.png'}; adjust paths or add sources.", file=sys.stderr)
    return 1

  logo = Image.open(src / "amprealize_logo.png")
  text = Image.open(src / "amprealize_text.png")
  lock = Image.open(src / "amprealize_logo_and_text.png")

  # .../amprealize/web-console/public
  web_console = here.parent.parent
  oss_web = web_console / "public"
  ent_root = main / "amprealize-enterprise" / "web-console" / "public"
  ext_oss = main / "amprealize" / "extension" / "resources"
  ext_ent = main / "amprealize-enterprise" / "extension" / "resources"
  mkt = main / "amprealize-enterprise" / "marketing-site" / "public"

  # Full-res mark + word (same aspect; alpha clean)
  save_cropped_rgba(logo.copy(), oss_web / "branding" / "logo-icon.png")
  save_cropped_rgba(text.copy(), oss_web / "branding" / "logo-wordmark.png")
  save_cropped_rgba(lock.copy(), oss_web / "branding" / "logo-lockup.png")

  for public_root in [ent_root]:
    if not public_root.is_dir():
      continue
    for rel in [
      "branding/logo-icon.png",
      "branding/logo-wordmark.png",
      "branding/logo-lockup.png",
    ]:
      a = oss_web / rel
      b = public_root / rel
      b.parent.mkdir(parents=True, exist_ok=True)
      b.write_bytes(a.read_bytes())
    print(f"synced {public_root} branding from OSS")

  to_square_favicon(logo.copy(), oss_web / "favicon.png", 64)
  for extra in (ent_root, mkt):
    if extra.is_dir():
      to_square_favicon(Image.open(src / "amprealize_logo.png"), extra / "favicon.png", 64)

  # og-default = lockup (transparency)
  if mkt.is_dir():
    save_cropped_rgba(lock.copy(), mkt / "og-default.png")
    t_m = mkt / "brand" / "logo-wordmark-v2.png"
    t_m.parent.mkdir(parents=True, exist_ok=True)
    t_m.write_bytes((oss_web / "branding" / "logo-wordmark.png").read_bytes())

  # Extension marketplace + activity bar
  to_square_favicon(logo.copy(), ext_oss / "icon.png", 128)
  to_square_favicon(logo.copy(), ext_oss / "amprealize-icon.png", 128)
  if ext_ent.is_dir():
    to_square_favicon(logo.copy(), ext_ent / "icon.png", 128)
    to_square_favicon(logo.copy(), ext_ent / "amprealize-icon.png", 128)

  # Update files/images for designers
  save_cropped_rgba(logo.copy(), src / "amprealize_logo.png")
  save_cropped_rgba(text.copy(), src / "amprealize_text.png")
  save_cropped_rgba(lock.copy(), src / "amprealize_logo_and_text.png")
  return 0


if __name__ == "__main__":
  sys.exit(main())
