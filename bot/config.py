"""Bot-specific configuration. Loads secrets from environment / .env file."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
DATABASE_URL: str = os.environ["DATABASE_URL"]

# Timezone
TIMEZONE_NAME = "Asia/Kolkata"

# Schedule times (hour, minute) in IST
SCHEDULE_MORNING = (7, 0)
SCHEDULE_EVENING = (22, 0)

# Cause list types to fetch on schedule
SCHEDULED_CL_TYPES = ["D", "S"]  # Daily and Supplementary

# Telegram message limits
TELEGRAM_MAX_MESSAGE_LENGTH = 4096
