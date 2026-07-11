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

## Design guidelines

- Use the Mixergy brand colours (dark teal / orange accent)
- Keep the icon simple and recognisable at small sizes
- Transparent background is required — do not use a white or coloured background
- PNG format only (no SVG, no JPEG)

## After changing images

No code changes are needed — Home Assistant automatically picks up images from this directory
when the integration is loaded (HA 2024.6+).

If you want the icon to also appear on the HACS default store listing, submit it to the
[home-assistant/brands](https://github.com/home-assistant/brands) repository following their
contribution guide. That repository uses the same file names and size requirements.
