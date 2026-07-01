import sys
import time

from camoufox.sync_api import Camoufox


def open_visible(storage_state_path: str, url: str) -> None:
    with Camoufox(
        headless=False,
        humanize=1.5,
        i_know_what_im_doing=True,
    ) as browser:
        context = browser.new_context(
            no_viewport=True,
            storage_state=storage_state_path,
        )
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=45000)

        while True:
            time.sleep(1)
            try:
                if page.is_closed():
                    break
            except Exception:
                break


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Uso: python open_visible_camoufox.py <storage_state.json> <url>")

    open_visible(sys.argv[1], sys.argv[2])
