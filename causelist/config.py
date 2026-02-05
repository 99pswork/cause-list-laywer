"""Configuration constants for the Rajasthan HC Cause List tool."""

BASE_URL = "https://hcraj.nic.in"
CAUSELIST_PAGE = f"{BASE_URL}/cishcraj-jp/causelists/"
CAPTCHA_URL = f"{BASE_URL}/cishcraj-jp/causelists/setgetcaptcha"
CAPTCHA_VERIFY_URL = f"{BASE_URL}/cishcraj-jp/causelists/check-captcha"
CAUSELIST_URL = f"{BASE_URL}/cishcraj-jp/get-causelist-in-pdf.php"
AJAX_DATA_URL = f"{BASE_URL}/cishcraj-jp/causelists/getajaxdata"

HEADERS_FORM_POST = {
    "X-CSRF-Token": "false",
    "Content-Type": "application/x-www-form-urlencoded",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

MAX_CAPTCHA_RETRIES = 10
CAPTCHA_RETRY_DELAY = 0.5  # seconds
REQUEST_TIMEOUT = 30  # seconds

CAUSELIST_TYPES = {
    "daily": "D",
    "supplementary": "S",
    "weekly": "W",
    "regular": "L",
}

# Display names for CLI output
CAUSELIST_TYPE_NAMES = {
    "D": "Daily",
    "S": "Supplementary",
    "W": "Weekly",
    "L": "Regular",
}
