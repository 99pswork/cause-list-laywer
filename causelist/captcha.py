"""Captcha fetching, solving (audio + image fallback), and verification."""

import base64
import io
import logging
import random
import time

import requests

logger = logging.getLogger(__name__)

from causelist.config import (
    CAPTCHA_RETRY_DELAY,
    CAPTCHA_URL,
    CAPTCHA_VERIFY_URL,
    HEADERS_FORM_POST,
    MAX_CAPTCHA_RETRIES,
    REQUEST_TIMEOUT,
)


def fetch_captcha(session: requests.Session) -> dict:
    """Fetch a fresh captcha from the server. Returns dict with 'image' and 'audio' base64 strings."""
    resp = session.get(
        f"{CAPTCHA_URL}?{random.random()}",
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return {"image": data.get("image", ""), "audio": data.get("audio", "")}


def _words_to_digits(text: str) -> str:
    """Convert spoken digit words to actual digits.

    The captcha audio spells out digits individually, but Google Speech API
    sometimes transcribes them as words (e.g., "six" -> "sex", "four" -> "for").
    """
    word_map = {
        "zero": "0", "oh": "0",
        "one": "1", "won": "1",
        "two": "2", "to": "2", "too": "2",
        "three": "3", "tree": "3",
        "four": "4", "for": "4",
        "five": "5",
        "six": "6", "sex": "6",
        "seven": "7",
        "eight": "8", "ate": "8",
        "nine": "9",
    }
    # Split on spaces and convert word by word
    parts = text.lower().strip().split()
    result = []
    for part in parts:
        if part in word_map:
            result.append(word_map[part])
        elif part.isdigit():
            result.append(part)
        else:
            # Try to extract digits from mixed strings like "sex3823" -> "63823"
            converted = ""
            i = 0
            while i < len(part):
                matched = False
                # Try longest word match first
                for word, digit in sorted(word_map.items(), key=lambda x: -len(x[0])):
                    if part[i:].startswith(word):
                        converted += digit
                        i += len(word)
                        matched = True
                        break
                if not matched:
                    if part[i].isdigit():
                        converted += part[i]
                    i += 1
            result.append(converted)
    return "".join(result)


def _extract_digits_from_result(result: dict) -> list[str]:
    """Extract all digit-string candidates from a Google Speech API result.

    Checks every alternative for raw digits and word-to-digit conversion.
    Returns list of candidate strings (may include duplicates).
    """
    candidates = []
    if not result or "alternative" not in result:
        return candidates

    for alt in result["alternative"]:
        transcript = alt.get("transcript", "")
        if not transcript:
            continue
        # Raw digits (strip spaces)
        cleaned = transcript.strip().replace(" ", "")
        if cleaned.isdigit():
            candidates.append(cleaned)
        # Word-to-digit conversion
        converted = _words_to_digits(transcript)
        if converted and converted.isdigit():
            candidates.append(converted)

    return candidates


def _audio_to_wav(audio_segment) -> io.BytesIO:
    """Export an AudioSegment to a WAV BytesIO buffer."""
    wav_buffer = io.BytesIO()
    audio_segment.export(wav_buffer, format="wav")
    wav_buffer.seek(0)
    return wav_buffer


def solve_audio_captcha(audio_base64: str) -> str | None:
    """Decode base64 MP3 audio, convert to WAV, transcribe with Google Speech API.

    Tries multiple audio processing variants (original, slowed, padded) and
    multiple languages. Prefers 6-digit results over other lengths.
    """
    try:
        import speech_recognition as sr
        from pydub import AudioSegment
    except ImportError:
        return None

    try:
        mp3_bytes = base64.b64decode(audio_base64)
        mp3_buffer = io.BytesIO(mp3_bytes)
        audio_segment = AudioSegment.from_mp3(mp3_buffer)

        # Normalize volume to -20 dBFS for consistent recognition
        change_in_dbfs = -20 - audio_segment.dBFS
        audio_segment = audio_segment.apply_gain(change_in_dbfs)

        # Build audio variants to try:
        # 1. Original + 1s silence padding (prevents last digit cutoff)
        silence = AudioSegment.silent(duration=1000)
        padded = audio_segment + silence
        # 2. Slowed to 85% speed (gives API more time to catch each digit)
        slowed = padded._spawn(padded.raw_data, overrides={
            "frame_rate": int(padded.frame_rate * 0.85)
        }).set_frame_rate(padded.frame_rate)

        variants = [
            ("padded", padded),
            ("slowed", slowed),
        ]

        all_candidates = []
        recognizer = sr.Recognizer()

        for variant_name, audio_seg in variants:
            wav_buffer = _audio_to_wav(audio_seg)
            with sr.AudioFile(wav_buffer) as source:
                audio_data = recognizer.record(source)

            for lang in ("en-IN", "en-US"):
                try:
                    result = recognizer.recognize_google(
                        audio_data, language=lang, show_all=True,
                    )
                    candidates = _extract_digits_from_result(result)
                    for c in candidates:
                        logger.debug(f"    Audio [{variant_name}/{lang}]: '{c}'")
                        all_candidates.append(c)
                except sr.UnknownValueError:
                    continue
                except sr.RequestError:
                    continue

        # Prefer 6-digit results
        six_digit = [c for c in all_candidates if len(c) == 6]
        if six_digit:
            # If multiple 6-digit results agree, high confidence
            from collections import Counter
            counts = Counter(six_digit)
            best = counts.most_common(1)[0][0]
            logger.debug(f"    Audio best (6-digit): '{best}' (seen {counts[best]}x)")
            return best

        # Fallback: best non-6-digit candidate (closest to 6)
        if all_candidates:
            best = min(all_candidates, key=lambda c: abs(len(c) - 6))
            return best

        return None
    except Exception as e:
        logger.error(f"Audio captcha error: {e}")
        return None


def solve_image_captcha(image_base64: str) -> str | None:
    """Decode base64 PNG image, try multiple preprocessing pipelines + OCR configs.

    Since captcha is always 6 digits, restricts whitelist to 0-9 and
    prefers 6-digit results across multiple preprocessing attempts.
    """
    try:
        import pytesseract
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    except ImportError:
        return None

    try:
        img_bytes = base64.b64decode(image_base64)
        img = Image.open(io.BytesIO(img_bytes)).convert("L")  # Grayscale

        # Multiple preprocessing pipelines to try
        preprocessed = []

        # Pipeline 1: High contrast + threshold 128 + median filter
        p1 = ImageEnhance.Contrast(img).enhance(2.0)
        p1 = p1.point(lambda x: 0 if x < 128 else 255)
        p1 = p1.filter(ImageFilter.MedianFilter(size=3))
        preprocessed.append(("t128", p1))

        # Pipeline 2: Higher threshold (better for light backgrounds)
        p2 = ImageEnhance.Contrast(img).enhance(2.5)
        p2 = p2.point(lambda x: 0 if x < 160 else 255)
        p2 = p2.filter(ImageFilter.MedianFilter(size=3))
        preprocessed.append(("t160", p2))

        # Pipeline 3: Lower threshold + invert (for dark captchas)
        p3 = ImageEnhance.Contrast(img).enhance(2.0)
        p3 = p3.point(lambda x: 0 if x < 100 else 255)
        p3 = ImageOps.invert(p3)
        p3 = p3.filter(ImageFilter.MedianFilter(size=3))
        preprocessed.append(("t100inv", p3))

        # Pipeline 4: Sharpen then threshold
        p4 = img.filter(ImageFilter.SHARPEN)
        p4 = ImageEnhance.Contrast(p4).enhance(3.0)
        p4 = p4.point(lambda x: 0 if x < 128 else 255)
        preprocessed.append(("sharp", p4))

        # Digits-only whitelist — captcha is always 6 numbers
        configs = [
            "--psm 7 -c tessedit_char_whitelist=0123456789",  # Single line
            "--psm 8 -c tessedit_char_whitelist=0123456789",  # Single word
            "--psm 13 -c tessedit_char_whitelist=0123456789", # Raw line
        ]

        all_candidates = []
        for pipe_name, processed_img in preprocessed:
            for config in configs:
                text = pytesseract.image_to_string(processed_img, config=config)
                cleaned = text.strip().replace(" ", "").replace("\n", "")
                if cleaned and cleaned.isdigit():
                    logger.debug(f"    Image [{pipe_name}]: '{cleaned}'")
                    all_candidates.append(cleaned)

        # Prefer 6-digit results
        six_digit = [c for c in all_candidates if len(c) == 6]
        if six_digit:
            from collections import Counter
            counts = Counter(six_digit)
            best = counts.most_common(1)[0][0]
            logger.debug(f"    Image best (6-digit): '{best}' (seen {counts[best]}x)")
            return best

        # Fallback: closest to 6 digits
        if all_candidates:
            best = min(all_candidates, key=lambda c: abs(len(c) - 6))
            return best

        return None
    except Exception as e:
        logger.error(f"Image captcha error: {e}")
        return None


def verify_captcha(session: requests.Session, captcha_code: str) -> bool:
    """Submit captcha solution to the server and check if accepted."""
    resp = session.post(
        CAPTCHA_VERIFY_URL,
        data=f"captcha={captcha_code}",
        headers=HEADERS_FORM_POST,
        timeout=REQUEST_TIMEOUT,
    )
    return "SecCodeError" not in resp.text and "Invalid" not in resp.text


def solve_and_verify(session: requests.Session) -> bool:
    """Fetch, solve, and verify captcha with retries. Returns True on success.

    Tries both audio and image solving on each attempt. If both produce
    a 6-digit result that agrees, that's highest confidence. Otherwise
    tries each 6-digit candidate individually.
    """
    for attempt in range(1, MAX_CAPTCHA_RETRIES + 1):
        captcha_data = fetch_captcha(session)

        # Try both audio and image
        audio_result = solve_audio_captcha(captcha_data["audio"])
        image_result = solve_image_captcha(captcha_data["image"])

        # Collect 6-digit candidates in priority order
        candidates = []

        # Highest priority: if both agree on the same 6 digits
        if (audio_result and image_result
                and len(audio_result) == 6 and len(image_result) == 6
                and audio_result == image_result):
            candidates.append(("audio+image", audio_result))
        else:
            # Audio 6-digit result (most reliable)
            if audio_result and len(audio_result) == 6:
                candidates.append(("audio", audio_result))
            # Image 6-digit result
            if image_result and len(image_result) == 6:
                candidates.append(("image", image_result))

        if not candidates:
            # Log what we got (for debugging)
            parts = []
            if audio_result:
                parts.append(f"audio={audio_result}({len(audio_result)}d)")
            if image_result:
                parts.append(f"image={image_result}({len(image_result)}d)")
            detail = ", ".join(parts) if parts else "nothing decoded"
            logger.warning(
                f"  Attempt {attempt}/{MAX_CAPTCHA_RETRIES}: No 6-digit candidate ({detail}), retrying..."
            )
            continue

        # Try each candidate (best first)
        for solver, solution in candidates:
            logger.info(f"  Attempt {attempt}/{MAX_CAPTCHA_RETRIES}: Trying {solver} -> '{solution}'")

            if verify_captcha(session, solution):
                logger.info("  Captcha verified successfully!")
                return True

            logger.warning(f"  {solver} solution rejected by server.")

        time.sleep(CAPTCHA_RETRY_DELAY)

    return False
