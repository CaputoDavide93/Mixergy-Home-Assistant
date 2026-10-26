#!/usr/bin/env python3
"""Take the README and setup screenshots from a real, throwaway Home Assistant.

    make screenshots                 # builds .venv-screenshots on first use
    .venv-screenshots/bin/python tools/screenshots/take_screenshots.py [--keep]

1. Starts Home Assistant (the version pinned in requirements.txt beside this
   file) in a new temporary config directory on a free localhost port, with
   the integration and the `screenshot_env` stand-ins copied into
   custom_components/. Onboarding is completed through its own API.
2. Opens the integration's setup in the real frontend (Chromium, through
   Playwright) and photographs each screen in the light and the dark theme.
   The Mixergy cloud is replaced by a demo tank (serial A12345), so no
   account is needed and nothing leaves the machine.
3. After setup, it writes a day of charge history for the tank, then
   photographs the device page, the charge history and the water heater.

Every image is docs/assets/screenshots/<screen>-{light,dark}.png, re-saved
without any metadata and quantised to 256 colours. The data is demo data
only. Nothing outside the temporary directory is touched; --keep leaves it
behind for a look.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import aiohttp  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from playwright.async_api import Locator, Page, async_playwright  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = ROOT / "docs" / "assets" / "screenshots"
VIEWPORT = {"width": 1280, "height": 900}
SCALE = 2
THEMES = ("light", "dark")
USER = {"name": "Demo", "username": "demo", "password": "demo-password-0000"}
SERIAL = "A12345"

CONFIGURATION = """\
homeassistant:
  name: Home
  unit_system: metric
  time_zone: UTC
  currency: EUR
  country: NL
  latitude: 52.37
  longitude: 4.89
  elevation: 0
http:
  server_host: 127.0.0.1
  server_port: {port}
frontend:
config:
history:
energy:
logger:
  default: warning
screenshot_env:
"""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def prepare(config: Path, port: int) -> None:
    (config / "configuration.yaml").write_text(CONFIGURATION.format(port=port))
    # Every onboarding step but the owner is marked done before the start:
    # the core-config step would otherwise set up example integrations this
    # instance has no use for. The owner is created through the API below.
    storage = config / ".storage"
    storage.mkdir()
    (storage / "onboarding").write_text(
        json.dumps(
            {
                "version": 4,
                "minor_version": 1,
                "key": "onboarding",
                "data": {"done": ["core_config", "analytics", "integration"]},
            }
        )
    )
    components = config / "custom_components"
    components.mkdir()
    shutil.copytree(
        ROOT / "custom_components" / "mixergy_tank",
        components / "mixergy_tank",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copytree(
        HERE / "screenshot_env",
        components / "screenshot_env",
        ignore=shutil.ignore_patterns("__pycache__"),
    )


async def wait_for_http(session: aiohttp.ClientSession, base: str, proc) -> None:
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit("Home Assistant exited during start-up; see its log")
        try:
            async with session.get(f"{base}/api/onboarding") as resp:
                if resp.status == 200:
                    return
        except aiohttp.ClientError:
            pass
        await asyncio.sleep(1)
    raise SystemExit("Home Assistant did not start within five minutes")


async def onboard(session: aiohttp.ClientSession, base: str) -> dict:
    """The owner, through the onboarding API; returns the browser's tokens."""
    client_id = f"{base}/"
    async with session.post(
        f"{base}/api/onboarding/users",
        json={**USER, "client_id": client_id, "language": "en"},
    ) as resp:
        resp.raise_for_status()
        code = (await resp.json())["auth_code"]
    async with session.post(
        f"{base}/auth/token",
        data={"grant_type": "authorization_code", "code": code, "client_id": client_id},
    ) as resp:
        resp.raise_for_status()
        tokens = await resp.json()
    return {
        **tokens,
        "hassUrl": base,
        "clientId": client_id,
        "expires": int(time.time() * 1000) + tokens["expires_in"] * 1000,
    }


async def settle(session: aiohttp.ClientSession, base: str, token: str) -> None:
    """Keep the HTTP settings from configuration.yaml for good (otherwise they
    are a five-minute trial that asks to be confirmed on every page), and
    dismiss the repairs that only say YAML is deprecated, so no badge or
    dialog that has nothing to do with the integration reaches a picture."""
    async with session.ws_connect(f"{base}/api/websocket") as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": token})
        if (await ws.receive_json())["type"] != "auth_ok":
            raise SystemExit("websocket authentication failed")
        ids = iter(range(1, 1_000_000))

        async def call(message: dict):
            await ws.send_json({"id": next(ids), **message})
            reply = await ws.receive_json()
            if not reply.get("success"):
                raise SystemExit(f"{message['type']} failed: {reply}")
            return reply["result"]

        # The HTTP server answers before start-up has finished; the stand-ins
        # must be in place before anything is photographed.
        for _ in range(600):
            config = await call({"type": "get_config"})
            if (
                config["state"] == "RUNNING"
                and "screenshot_env" in config["components"]
            ):
                break
            await asyncio.sleep(1)
        else:
            raise SystemExit("Home Assistant did not finish starting")
        await call({"type": "http/config/promote"})
        for issue in (await call({"type": "repairs/list_issues"}))["issues"]:
            await call(
                {
                    "type": "repairs/ignore_issue",
                    "domain": issue["domain"],
                    "issue_id": issue["issue_id"],
                    "ignore": True,
                }
            )


# ── pictures ──────────────────────────────────────────────────────────────────
def strip_metadata(path: Path, radius: float = 0) -> None:
    """Re-save the PNG with pixels only: no text chunks, times or profiles,
    quantised to 256 colours (flat interface colours lose nothing visible,
    and the file shrinks to about a third).

    With a radius, the corners outside the dialog's rounded edge become
    transparent, so no stray piece of the page behind it shows."""
    with Image.open(path) as image:
        pixels = image.convert("RGBA" if radius else "RGB")
    if radius:
        mask = Image.new("L", pixels.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, pixels.width - 1, pixels.height - 1), radius=radius * SCALE, fill=255
        )
        pixels.putalpha(mask)
    pixels = pixels.quantize(
        256,
        method=Image.Quantize.FASTOCTREE if radius else Image.Quantize.MEDIANCUT,
        dither=Image.Dither.NONE,
    )
    buffer = io.BytesIO()
    pixels.save(buffer, format="PNG", optimize=True)
    path.write_bytes(buffer.getvalue())


class Camera:
    def __init__(self, page: Page, only: set[str] | None) -> None:
        self.page = page
        self.only = only
        self.taken: list[Path] = []

    async def theme(self, name: str) -> None:
        await self.page.emulate_media(color_scheme=name)
        await self.page.wait_for_timeout(600)

    async def shoot(self, name: str, target: Locator | None = None) -> None:
        """<name>-light.png and <name>-dark.png, of a dialog or the viewport."""
        if self.only and name not in self.only:
            return
        for theme in THEMES:
            await self.theme(theme)
            path = OUT / f"{name}-{theme}.png"
            radius = 0.0
            if target is None:
                await self.page.screenshot(path=path, animations="disabled")
            else:
                radius = await target.evaluate(
                    "e => parseFloat(getComputedStyle(e).borderTopLeftRadius) || 0"
                )
                box = await target.bounding_box()
                if box is None:
                    raise SystemExit(f"{name}: nothing to photograph")
                await self.page.screenshot(path=path, clip=box, animations="disabled")
            strip_metadata(path, radius)
            self.taken.append(path)
            print(f"  {path.relative_to(ROOT)}")
        await self.theme("light")


def dialog(page: Page, host: str = "dialog-data-entry-flow") -> Locator:
    """The visible surface of an open dialog."""
    return page.locator(f"{host} ha-dialog wa-dialog dialog.dialog").first


async def screen(page: Page, title: str) -> None:
    """Wait for a dialog screen by its title, and for it to settle."""
    try:
        await page.get_by_text(title, exact=True).first.wait_for(timeout=60000)
    except Exception:
        if os.environ.get("SCREENSHOT_DEBUG"):
            await page.screenshot(path=os.environ["SCREENSHOT_DEBUG"])
        raise
    await page.wait_for_timeout(1000)


async def press(page: Page, *names: str) -> None:
    for name in names:
        button = page.get_by_role("button", name=name, exact=True)
        if await button.count():
            await button.last.click()
            return
    raise SystemExit(f"no button named any of {names}")


async def call_ws(page: Page, message: dict):
    return await page.evaluate(
        "m => document.querySelector('home-assistant').hass.callWS(m)", message
    )


async def call_service(page: Page, domain: str, service: str, data: dict) -> None:
    await page.evaluate(
        "([d, s, data]) => document.querySelector('home-assistant')"
        ".hass.callService(d, s, data)",
        [domain, service, data],
    )


async def run(args: argparse.Namespace) -> None:
    only = set(args.only.split(",")) if args.only else None
    OUT.mkdir(parents=True, exist_ok=True)
    config = Path(tempfile.mkdtemp(prefix="mixergy-screens-"))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    prepare(config, port)
    started = datetime.now(UTC)
    log = (config / "hass.out").open("w")
    print(f"Home Assistant in {config}, on {base}")
    proc = subprocess.Popen(
        [sys.executable, "-m", "homeassistant", "--config", str(config)],
        stdout=log,
        stderr=subprocess.STDOUT,
        # Not the repository: `python -m` puts the working directory on the
        # path, and its custom_components/ would shadow the config's own.
        cwd=config,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    try:
        async with aiohttp.ClientSession() as session:
            await wait_for_http(session, base, proc)
            tokens = await onboard(session, base)
            await settle(session, base, tokens["access_token"])
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            context = await browser.new_context(
                viewport=VIEWPORT,
                device_scale_factor=SCALE,
                locale="en-GB",
                timezone_id="UTC",
                color_scheme="light",
            )
            await context.add_init_script(
                f"localStorage.setItem('hassTokens', {json.dumps(json.dumps(tokens))});"
            )
            page = await context.new_page()
            camera = Camera(page, only)
            await shoot_setup(page, camera, base)
            await shoot_device(page, camera, base, started)
            await browser.close()
        print(f"{len(camera.taken)} screenshots in {OUT.relative_to(ROOT)}")
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(30)
        if proc.poll() is None:
            proc.kill()
        log.close()
        if args.keep:
            print(f"kept {config}")
        else:
            shutil.rmtree(config, ignore_errors=True)


async def shoot_setup(page: Page, camera: Camera, base: str) -> None:
    """The three setup screens, ending in Advanced mode."""
    await page.goto(f"{base}/config/integrations/dashboard/add?domain=mixergy_tank")
    await page.get_by_text("Do you want to set up Mixergy?").wait_for(timeout=60000)
    await page.get_by_role("button", name="OK", exact=True).click()
    await screen(page, "Sign in to Mixergy")
    flow = page.locator("dialog-data-entry-flow")
    await flow.locator("input:not([type=password])").first.fill("demo@example.com")
    await flow.locator("input[type=password]").first.fill("demo-password")
    await camera.shoot("setup-credentials", dialog(page))
    await press(page, "Submit", "Next")

    await screen(page, "Find your tank")
    await camera.shoot("setup-tank", dialog(page))
    await press(page, "Submit", "Next")

    await screen(page, "Choose your experience")
    await page.get_by_role("radio", name="Advanced").check()
    await camera.shoot("setup-mode", dialog(page))
    await press(page, "Submit", "Next")

    await page.get_by_text("Name and assign").wait_for(timeout=60000)
    await page.wait_for_timeout(1500)
    await press(page, "Skip and finish", "Finish")


async def entity(page: Page, suffix: str, domain: str = "sensor") -> str:
    """The entity id of the demo tank's entity whose id ends with `suffix`."""
    for _ in range(240):
        found = await page.evaluate(
            """([d, s]) => Object.keys(document.querySelector('home-assistant')
                 .hass.states).filter(e => e.startsWith(d + '.') && e.endsWith(s))""",
            [domain, suffix],
        )
        if found:
            return found[0]
        await page.wait_for_timeout(250)
    raise SystemExit(f"no {domain} entity ending {suffix}")


async def shoot_device(
    page: Page, camera: Camera, base: str, started: datetime
) -> None:
    """The device page, the charge history and the water heater."""
    charge = await entity(page, "_current_charge")
    heater = await entity(page, "", "water_heater")
    # A day of charge, ending a minute before Home Assistant started (the
    # recorder compiles only periods not yet run): a morning and an evening
    # draw-off, with the tank topping itself back up after each.
    shape = [
        78, 80, 80, 79, 77, 74, 71, 68, 66, 64, 72, 82, 90, 88, 85, 83,
        81, 80, 78, 75, 71, 66, 60, 54, 49, 47, 52, 60, 69, 76, 79, 80,
        79, 77, 74, 72, 70, 68, 66, 64, 63, 62,
    ]  # fmt: skip
    end = started - timedelta(minutes=1)
    step = timedelta(minutes=30)
    points = [
        [(end - step * (len(shape) - 1 - n)).isoformat(), str(value)]
        for n, value in enumerate(shape)
    ]
    await call_service(
        page, "screenshot_env", "backfill", {"entity_id": charge, "points": points}
    )

    devices = await call_ws(page, {"type": "config/device_registry/list"})
    device = next(
        d for d in devices if any(i[0] == "mixergy_tank" for i in d["identifiers"])
    )
    await page.set_viewport_size({"width": VIEWPORT["width"], "height": 1500})
    await page.goto(f"{base}/config/devices/device/{device['id']}")
    await page.get_by_text("Device info").first.wait_for(timeout=60000)
    await page.wait_for_timeout(2500)
    await camera.shoot("device")
    await page.set_viewport_size(VIEWPORT)

    for name, entity_id in (("charge-history", charge), ("water-heater", heater)):
        await page.goto(f"{base}/config/devices/device/{device['id']}")
        await page.wait_for_timeout(2000)
        await page.evaluate(
            """e => document.querySelector('home-assistant').dispatchEvent(
                 new CustomEvent('hass-more-info',
                   {detail: {entityId: e}, bubbles: true, composed: true}))""",
            entity_id,
        )
        await page.wait_for_timeout(4000)
        await camera.shoot(name, dialog(page, "ha-more-info-dialog"))
        await page.keyboard.press("Escape")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", action="store_true", help="keep the temporary config")
    parser.add_argument("--only", help="comma-separated screen names to (re)take")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
