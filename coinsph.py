import hmac
import hashlib
import base64
import struct
import time
import os
from datetime import datetime, timedelta

from playwright.sync_api import sync_playwright
import boto3
from botocore.exceptions import BotoCoreError, ClientError


# ─────────────────────────────────────────────────────────────
# ENV VARIABLES
# ─────────────────────────────────────────────────────────────

EMAIL = os.getenv("COINSPH_EMAIL")
PASSWORD = os.getenv("COINSPH_PASSWORD")
SECRET = os.getenv("COINSPH_TOTP_SECRET")

BASE_URL = "https://www.coins.ph/en-ph"

MAX_ATTEMPTS = 3

AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

S3_BUCKET = os.getenv("S3_BUCKET")
S3_PREFIX = os.getenv("S3_PREFIX", "coinsph_fx/raw")
AWS_REGION = os.getenv("AWS_REGION", "ap-southeast-1")


# ─────────────────────────────────────────────────────────────
# VALIDATION
# ─────────────────────────────────────────────────────────────

required_env = [
    "COINSPH_EMAIL",
    "COINSPH_PASSWORD",
    "COINSPH_TOTP_SECRET",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "S3_BUCKET",
]

missing = [x for x in required_env if not os.getenv(x)]

if missing:
    raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")


# ─────────────────────────────────────────────────────────────
# S3 Upload
# ─────────────────────────────────────────────────────────────

def upload_to_s3(local_path, s3_key):
    print(f"[*] Uploading {local_path} -> s3://{S3_BUCKET}/{s3_key}")

    client = boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        region_name=AWS_REGION,
    )

    client.upload_file(local_path, S3_BUCKET, s3_key)

    print(f"[✓] Uploaded to s3://{S3_BUCKET}/{s3_key}")


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def save_screenshot(page, tag):
    try:
        os.makedirs(".tmp", exist_ok=True)

        fname = f".tmp/{tag}_{int(time.time())}.png"

        page.screenshot(path=fname, full_page=True)

        print(f"[*] Screenshot saved: {fname}")

    except Exception:
        pass


def get_totp(secret):
    pad = len(secret) % 8

    if pad:
        secret += "=" * (8 - pad)

    key = base64.b32decode(secret.upper())

    msg = struct.pack(">Q", int(time.time() // 30))

    h = hmac.new(key, msg, hashlib.sha1).digest()

    offset = h[-1] & 0x0F

    code = (
        struct.unpack(">I", h[offset:offset + 4])[0]
        & 0x7FFFFFFF
    ) % 1000000

    return f"{code:06d}"


# ─────────────────────────────────────────────────────────────
# Login
# ─────────────────────────────────────────────────────────────

def login(page):
    print("[*] Opening login page...")

    page.goto(
        f"{BASE_URL}/login",
        wait_until="domcontentloaded",
        timeout=60000,
    )

    page.wait_for_timeout(3000)

    # Email tab
    for sel in [
        "button:has-text('Email')",
        "a:has-text('Email')",
        "[role='tab']:has-text('Email')",
    ]:
        try:
            page.locator(sel).first.click(timeout=3000)
            print("[✓] Email tab selected")
            break
        except Exception:
            continue

    # Email
    email_ok = False

    for sel in [
        "input[type='email']",
        "input[name='email']",
        "input[type='text']",
    ]:
        try:
            el = page.locator(sel).first
            el.wait_for(state="visible", timeout=8000)
            el.fill(EMAIL)
            email_ok = True
            print("[✓] Email entered")
            break
        except Exception:
            continue

    if not email_ok:
        raise RuntimeError("Email field not found")

    # Next
    for name in ["Next", "Continue", "Login", "Log in"]:
        try:
            page.get_by_role("button", name=name).click(timeout=4000)
            print(f"[✓] Clicked {name}")
            break
        except Exception:
            continue

    page.wait_for_timeout(2000)

    # Password
    pw_ok = False

    for sel in [
        "input[type='password']",
        "input[name='password']",
    ]:
        try:
            el = page.locator(sel).first
            el.wait_for(state="visible", timeout=8000)
            el.fill(PASSWORD)
            pw_ok = True
            print("[✓] Password entered")
            break
        except Exception:
            continue

    if not pw_ok:
        raise RuntimeError("Password field not found")

    # Login
    for name in ["Login", "Log in", "Sign in", "Next"]:
        try:
            page.get_by_role("button", name=name).click(timeout=4000)
            print(f"[✓] Clicked {name}")
            break
        except Exception:
            continue

    page.wait_for_timeout(3000)

    # OTP
    code = get_totp(SECRET)

    print(f"[*] TOTP: {code}")

    otp_ok = False

    try:
        inputs = page.locator("input[maxlength='1']")

        if inputs.count() >= 6:
            for i, d in enumerate(code):
                inputs.nth(i).fill(d)

            otp_ok = True

    except Exception:
        pass

    if not otp_ok:
        for sel in [
            "input[autocomplete='one-time-code']",
            "input[maxlength='6']",
            "input[inputmode='numeric']",
        ]:
            try:
                page.locator(sel).first.fill(code)
                otp_ok = True
                break
            except Exception:
                continue

    if not otp_ok:
        raise RuntimeError("OTP field not found")

    print("[✓] OTP entered")

    for name in ["Verify", "Submit", "Confirm", "Next"]:
        try:
            page.get_by_role("button", name=name).click(timeout=4000)
            break
        except Exception:
            continue

    page.wait_for_timeout(5000)

    if "dashboard" not in page.url.lower():
        save_screenshot(page, "login_failed")
        raise RuntimeError(f"Dashboard not reached: {page.url}")

    print("[✓] Logged in")


# ─────────────────────────────────────────────────────────────
# Navigate
# ─────────────────────────────────────────────────────────────

def navigate_to_trade_history(page):
    print("[*] Navigating to Trade History")

    keywords = ["Orders", "Spot", "Trade History"]

    for text in keywords:
        success = False

        for attempt in range(3):
            try:
                page.get_by_text(text, exact=True).first.click(timeout=5000)

                page.wait_for_timeout(2000)

                success = True

                print(f"[✓] Clicked {text}")

                break

            except Exception:
                continue

        if not success:
            raise RuntimeError(f"Could not click: {text}")

    page.wait_for_timeout(3000)


# ─────────────────────────────────────────────────────────────
# Export CSV
# ─────────────────────────────────────────────────────────────

def export_csv(page):
    print("[*] Starting export")

    today = datetime.now()

    start = today - timedelta(days=10)

    # Export
    export_clicked = False

    for sel in [
        "button:has-text('Export')",
        "div:has-text('Export')",
        "span:has-text('Export')",
    ]:
        try:
            page.locator(sel).first.click(timeout=5000)

            export_clicked = True

            print("[✓] Export clicked")

            break

        except Exception:
            continue

    if not export_clicked:
        raise RuntimeError("Export button not found")

    page.wait_for_timeout(2000)

    # Customize
    customize_clicked = False

    for sel in [
        "button:has-text('Customize')",
        "div:has-text('Customize')",
    ]:
        try:
            page.locator(sel).first.click(timeout=5000)

            customize_clicked = True

            print("[✓] Customize clicked")

            break

        except Exception:
            continue

    if not customize_clicked:
        raise RuntimeError("Customize button not found")

    page.wait_for_timeout(2000)

    # Final export
    with page.expect_download(timeout=120000) as dl_info:

        final_clicked = False

        for sel in [
            "button:has-text('Export')",
            "button.mui-11wlovc",
        ]:
            try:
                page.locator(sel).last.click(timeout=5000)

                final_clicked = True

                print("[✓] Final export clicked")

                break

            except Exception:
                continue

        if not final_clicked:
            raise RuntimeError("Final export button not found")

    download = dl_info.value

    os.makedirs(".tmp", exist_ok=True)

    filename = (
        f"coinsph_trade_history_"
        f"{start.strftime('%Y-%m-%d')}_"
        f"{today.strftime('%Y-%m-%d')}.csv"
    )

    local_path = os.path.join(".tmp", filename)

    download.save_as(local_path)

    print(f"[✓] Downloaded: {local_path}")

    return local_path


# ─────────────────────────────────────────────────────────────
# Main Flow
# ─────────────────────────────────────────────────────────────

def run():
    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
        )

        context = browser.new_context(viewport=None)

        page = context.new_page()

        try:
            login(page)

            navigate_to_trade_history(page)

            local_file = export_csv(page)

            s3_key = f"{S3_PREFIX}/{os.path.basename(local_file)}"

            upload_to_s3(local_file, s3_key)

            print("\n[✓] COMPLETED SUCCESSFULLY")
            print(f"[✓] S3 Path: s3://{S3_BUCKET}/{s3_key}")

        except Exception as e:
            print(f"\n[x] FLOW FAILED: {e}")

            save_screenshot(page, "fatal_error")

            raise

        finally:
            browser.close()


# ─────────────────────────────────────────────────────────────
# Retry Wrapper
# ─────────────────────────────────────────────────────────────

def run_with_retry():
    last_error = None

    for attempt in range(1, MAX_ATTEMPTS + 1):

        print("\n" + "=" * 60)
        print(f"ATTEMPT {attempt}/{MAX_ATTEMPTS}")
        print("=" * 60)

        try:
            run()

            return

        except Exception as e:
            last_error = e

            print(f"[!] Attempt failed: {e}")

            if attempt < MAX_ATTEMPTS:
                wait = attempt * 5

                print(f"[*] Retrying in {wait}s")

                time.sleep(wait)

    raise last_error


# ─────────────────────────────────────────────────────────────
# Entry
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_with_retry()
