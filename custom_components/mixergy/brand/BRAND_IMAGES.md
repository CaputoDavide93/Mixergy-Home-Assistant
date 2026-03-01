# Brand Images

Place the following image files in this directory to give the integration a proper icon in the Home Assistant UI and HACS store.

## Required files

| File | Size | Format | Usage |
| ---- | ---- | ------ | ----- |
| `icon.png` | 256 × 256 px | PNG with transparency | Integration icon shown in HACS and HA integrations page |
| `icon@2x.png` | 512 × 512 px | PNG with transparency | High-DPI version of the icon (optional but recommended) |
| `logo.png` | Landscape, min 300 px wide | PNG with transparency | Logo shown on the device card in HA |

## Design guidelines

- Use the Mixergy brand colours (dark teal / orange accent)
- Keep the icon simple and recognisable at small sizes
- Transparent background is required — do not use a white or coloured background
- PNG format only (no SVG, no JPEG)

## After adding images

No code changes are needed — Home Assistant automatically picks up images from this directory
when the integration is loaded (HA 2024.6+).

If you want the icon to also appear on the HACS default store listing, submit it to the
[home-assistant/brands](https://github.com/home-assistant/brands) repository following their
contribution guide. That repository uses the same file names and size requirements.
