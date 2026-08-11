# Brand Images

Image files in this directory give the integration its icon in the Home
Assistant UI. HACS repository listings use the separate Home Assistant brands
CDN, so their icon must also be updated in `home-assistant/brands`.

## Files in this directory

| File | Size | Format | Usage |
| ---- | ---- | ------ | ----- |
| `icon.png` | 256 × 256 px | PNG with transparency | Integration icon shown in Home Assistant |
| `icon@2x.png` | 512 × 512 px | PNG with transparency | High-DPI version of the icon |
| `logo.png` | 1000 × 256 px | PNG with transparency | Light-theme landscape logo |
| `logo@2x.png` | 2000 × 512 px | PNG with transparency | High-DPI light-theme logo |
| `dark_logo.png` | 1000 × 256 px | PNG with transparency | Dark-theme landscape logo |
| `dark_logo@2x.png` | 2000 × 512 px | PNG with transparency | High-DPI dark-theme logo |

The square icon works on both light and dark themes, so separate dark icon
files are deliberately omitted. Home Assistant falls back to `icon.png` and
`icon@2x.png` for the dark icon endpoints.

## Vector sources

The icon and the repository banner are drawn as SVG and rendered to PNG, so
every asset can be regenerated at any size without quality loss:

| Source | Renders to |
| ------ | ---------- |
| [`assets/icon.svg`](../../../assets/icon.svg) | `icon.png`, `icon@2x.png` |
| [`assets/logo.svg`](../../../assets/logo.svg) | `logo.png`, `logo@2x.png` |
| [`assets/dark_logo.svg`](../../../assets/dark_logo.svg) | `dark_logo.png`, `dark_logo@2x.png` |
| [`assets/banner.svg`](../../../assets/banner.svg) | `assets/banner.png` (1280 × 640, README hero + GitHub social preview) |

Re-render with any SVG rasteriser, for example:

```bash
pip install cairosvg
python -c "import cairosvg; cairosvg.svg2png(url='assets/icon.svg', write_to='custom_components/mixergy_tank/brand/icon@2x.png', output_width=512, output_height=512)"
```

After re-rendering, update `assets/brand-manifest.json`. Repository tests verify
the reviewed SHA-256 of every vector source and raster output, so a stale PNG or
an unreviewed source edit cannot pass silently.

## Design

- Capsule tank silhouette on a transparent background
- Dark teal body (`#0a303c` → `#15505f`), hot-water fill in orange
  (`#ffa040` → `#f4562a`) with a wave meniscus at ~62% charge
- White heating bolt centred in the hot zone; three steam strokes above
- Reads clearly from 512 px down to 32 px — no text inside the icon
- Landscape logo pairs the same tank with the **Mixergy Home Assistant**
  wordmark; the light and dark versions differ only where contrast requires it

## GitHub social preview

`assets/banner.png` is sized for GitHub's social preview card (1280 × 640,
2:1). GitHub has no API for this — upload it manually via
**Repo → Settings → General → Social preview → Edit**.

## After changing images

No code changes are needed. Home Assistant 2026.3+ automatically prefers images
from this directory when the integration is loaded. Supported older releases
(HA 2025.8–2026.2) continue using the matching brands-CDN assets instead; this
does not change the integration's Home Assistant 2025.8 minimum.

For the icon to appear in HACS repository listings, submit it to the
[home-assistant/brands](https://github.com/home-assistant/brands) repository
following its contribution guide. That repository uses the same file names and
size requirements.
