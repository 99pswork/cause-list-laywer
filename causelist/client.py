"""HTTP client and API orchestrator for cause list lookup."""

import base64
import logging

import requests

logger = logging.getLogger(__name__)

from causelist.captcha import solve_and_verify
from causelist.config import (
    BASE_URL,
    CAUSELIST_PAGE,
    CAUSELIST_TYPE_NAMES,
    CAUSELIST_URL,
    HEADERS_FORM_POST,
    REQUEST_TIMEOUT,
    USER_AGENT,
)


def b64(value: str) -> str:
    """Base64 encode a string, matching JavaScript's btoa()."""
    return base64.b64encode(value.encode("utf-8")).decode("utf-8")


class CauseListClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def initialize_session(self):
        """Load the main page to establish server-side session and cookies."""
        resp = self.session.get(CAUSELIST_PAGE, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()

    def search_causelist(
        self,
        lawyer_name: str,
        date_str: str,
        cl_type: str = "D",
    ) -> str | None:
        """Full workflow: session -> captcha -> search -> return HTML content or None.

        Args:
            lawyer_name: Name to search (min 3 chars).
            date_str: Date in dd/mm/yyyy format.
            cl_type: Type code - "D" (Daily), "S" (Supplementary), "W" (Weekly), "L" (Regular).
        """

        # Step 1: Initialize session
        logger.info("Initializing session...")
        self.initialize_session()

        # Step 2: Solve captcha
        logger.info("Solving captcha...")
        if not solve_and_verify(self.session):
            raise RuntimeError("Failed to solve captcha after maximum retries")

        # Step 3: Build request parameters (base64 encoded; empty fields stay empty)
        params = {
            "cl": b64("C"),
            "cldt": b64(date_str),
            "cltype": b64(cl_type),
            "courtno": b64("0"),
            "judgename": b64("0"),
            "caseno": "",
            "lawyrname": b64(lawyer_name),
            "petname": "",
            "resname": "",
            "deptname": "",
            "format": b64("1"),  # 1 = HTML
            "QueryType": "Causelist",
            "view": b64("view"),
        }

        # Step 4: Submit search
        type_name = CAUSELIST_TYPE_NAMES.get(cl_type, cl_type)
        logger.info(f"Searching for '{lawyer_name}' on {date_str} ({type_name})...")
        resp = self.session.post(
            CAUSELIST_URL,
            data=params,
            headers=HEADERS_FORM_POST,
            timeout=REQUEST_TIMEOUT,
        )

        response_text = resp.text.strip()

        # Step 5: Handle response
        if not response_text or response_text in ("No Record Found", "NA"):
            return None

        # Response is a file path — fetch the actual HTML content
        if response_text.startswith("http"):
            file_url = response_text
        else:
            # Clean up path separators
            path = response_text.lstrip("/")
            file_url = f"{BASE_URL}/cishcraj-jp/{path}"

        logger.info("Fetching results from server...")
        content_resp = self.session.get(file_url, timeout=REQUEST_TIMEOUT)
        content_resp.raise_for_status()
        return content_resp.text
