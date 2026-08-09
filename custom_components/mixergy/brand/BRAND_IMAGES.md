# Brand Images

Image files in this directory give the integration its icon in the Home
Assistant UI and the HACS store.

## Files in this directory

| File | Size | Format | Usage |
| ---- | ---- | ------ | ----- |
| `icon.png` | 256 × 256 px | PNG with transparency | Integration icon shown in HACS and HA integrations page |
| `icon@2x.png` | 512 × 512 px | PNG with transparency | High-DPI version of the icon |

A separate landscape `logo.png` (min 300 px wide) is **optional** and not
currently provided — when the logo is absent, Home Assistant falls back to the
icon on the device card, so nothing is missing in the UI.

## Vector sources

The icon and the repository banner are drawn as SVG and rendered to PNG, so
every asset can be regenerated at any size without quality loss:

| Source | Renders to |
| ------ | ---------- |
| [`assets/icon.svg`](../../../assets/icon.svg) | `icon.png`, `icon@2x.png`, repo-root `icon.png` |
| [`assets/banner.svg`](../../../assets/banner.svg) | `assets/banner.png` (1280 × 640, README hero + GitHub social preview) |

Re-render with any SVG rasteriser, for example:

```bash
pip install cairosvg
python -c "import cairosvg; cairosvg.svg2png(url='assets/icon.svg', write_to='custom_components/mixergy/brand/icon@2x.png', output_width=512, output_height=512)"
```

## Design

- Capsule tank silhouette on a transparent background
- Dark teal body (`#0a303c` → `#15505f`), hot-water fill in orange
  (`#ffa040` → `#f4562a`) with a wave meniscus at ~62% charge
- White heating bolt centred in the hot zone; three steam strokes above
- Reads clearly from 512 px down to 32 px — no text inside the icon

## GitHub social preview

`assets/banner.png` is sized for GitHub's social preview card (1280 × 640,
2:1). GitHub has no API for this — upload it manually via
**Repo → Settings → General → Social preview → Edit**.

## After changing images

No code changes are needed — Home Assistant automatically picks up images from
this directory when the integration is loaded (HA 2024.6+).

If you want the icon to also appear on the HACS default store listing, submit
it to the [home-assistant/brands](https://github.com/home-assistant/brands)
repository following their contribution guide. That repository uses the same
file names and size requirements.
