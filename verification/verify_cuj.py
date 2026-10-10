from playwright.sync_api import sync_playwright
import time
import subprocess

# Start the server
server_process = subprocess.Popen(['python3', '-m', 'http.server', '8000', '-d', './intelligence/company/www'])
time.sleep(2) # let it start

def run_cuj(page):
    page.goto("http://localhost:8000/trust-ops.html")
    page.wait_for_timeout(500)

    # Unhide bulk action bar (simulating operator unlocking queue/making it visible)
    page.evaluate("document.querySelector('[data-trust-ops-bulk-bar]').removeAttribute('hidden');")
    page.wait_for_timeout(500)

    # Hover over the disabled approve button to trigger tooltip
    approve_btn = page.locator('button[data-bulk-decision="approve"]')
    approve_btn.hover()
    page.wait_for_timeout(1000)

    # Take screenshot of the disabled state
    page.screenshot(path="/app/verification/screenshots/verification.png")

    # Enable the buttons by selecting all
    page.click('[data-trust-ops-select-all]')
    page.wait_for_timeout(500)

    # Hover again over the enabled button
    approve_btn.hover()
    page.wait_for_timeout(1000)

if __name__ == "__main__":
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                record_video_dir="/app/verification/videos"
            )
            page = context.new_page()
            try:
                run_cuj(page)
            finally:
                context.close()
                browser.close()
    finally:
        server_process.kill()
