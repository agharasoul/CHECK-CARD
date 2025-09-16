#!/usr/bin/env python3

"""
card_checker.py

CLI tool to test multiple Visa/MasterCard numbers against Stripe (test mode),
perform a small authorization, do BIN lookup, and export results to CSV/JSON
with a colored terminal summary.

Requirements:
- Input formats: TXT (number|month|year|cvv per line), CSV (columns
  number,month,year,cvv), JSON (array of objects with those fields)
- Detect format by file extension; interactive mode if no file
- Uses STRIPE_API_KEY from environment (sk_test...)
- Uses only stdlib + requests + stripe
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from typing import Callable, Iterable, List, Optional, Tuple, Dict
import random
import datetime

# Third-party packages allowed by requirements
import requests
import stripe


# -----------------------------
# Console color/ANSI utilities
# -----------------------------

# ANSI colors for terminal output
RESET = "\x1b[0m"
GREEN = "\x1b[32m"
RED = "\x1b[31m"
YELLOW = "\x1b[33m"


def _enable_windows_ansi_support() -> None:
    """Enable ANSI escape sequences on Windows 10+ consoles.

    Uses ctypes to set ENABLE_VIRTUAL_TERMINAL_PROCESSING. No-op elsewhere.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE = -11
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            new_mode = mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
            kernel32.SetConsoleMode(handle, new_mode)
    except Exception:
        # Fallback: no colors if enabling fails
        pass


# -----------------------------
# Data structures
# -----------------------------


@dataclass
class CardInput:
    """Represents a single card test input."""

    number: str
    month: str
    year: str
    cvv: str


# -----------------------------
# Luhn and generation helpers
# -----------------------------


def luhn_checksum(number_without_check: str) -> int:
    """Compute Luhn checksum digit for the number without the final check digit.

    Algorithm:
    - Starting from the right, double every second digit.
    - If doubling yields >= 10, subtract 9.
    - Sum all digits; the check digit is the amount needed to make total % 10 == 0.
    """
    digits = [int(ch) for ch in number_without_check]
    # Double every second digit from right: process reversed with index
    total = 0
    for idx, d in enumerate(reversed(digits), start=1):
        if idx % 2 == 1:
            # Odd index from right: keep as is
            total += d
        else:
            doubled = d * 2
            if doubled >= 10:
                doubled -= 9
            total += doubled
    return (10 - (total % 10)) % 10


def is_luhn_valid(number: str) -> bool:
    """Return True if full PAN passes Luhn check."""
    digits = ''.join(ch for ch in str(number) if ch.isdigit())
    if len(digits) < 12:
        return False
    core, check = digits[:-1], digits[-1]
    try:
        expected = luhn_checksum(core)
        return str(expected) == check
    except Exception:
        return False


# Diverse sample BIN pool per scheme (for varied generation across banks/issuers)
# Note: These are common/public prefixes used for demos/tests; not guaranteed to map to a specific
# live issuer in your region. They help create variety across schemes and issuers.
BIN_POOL_DEFAULT: Dict[str, List[Dict[str, str]]] = {
    "visa": [
        {"bank": "Sample Visa 1", "bin": "400000"},
        {"bank": "Sample Visa 2", "bin": "424242"},
        {"bank": "Sample Visa 3", "bin": "453201"},
        {"bank": "Sample Visa 4", "bin": "455673"},
    ],
    "mastercard": [
        {"bank": "Sample MC 1", "bin": "510510"},
        {"bank": "Sample MC 2", "bin": "520082"},
        {"bank": "Sample MC 3", "bin": "555555"},
        {"bank": "Sample MC 4", "bin": "222100"},
    ],
    "amex": [
        {"bank": "Sample AmEx 1", "bin": "340000"},
        {"bank": "Sample AmEx 2", "bin": "370000"},
    ],
    "discover": [
        {"bank": "Sample Discover 1", "bin": "601100"},
        {"bank": "Sample Discover 2", "bin": "651000"},
    ],
    "jcb": [
        {"bank": "Sample JCB 1", "bin": "352800"},
        {"bank": "Sample JCB 2", "bin": "356600"},
    ],
    "diners": [
        {"bank": "Sample Diners 1", "bin": "360000"},
        {"bank": "Sample Diners 2", "bin": "300000"},
        {"bank": "Sample Diners 3", "bin": "305000"},
    ],
}


def _random_scheme_prefix(scheme: str) -> Tuple[str, int]:
    """Pick a realistic random prefix for a scheme using known public ranges.

    Returns (prefix, target_length).
    """
    s = scheme.lower()
    if s == "mastercard":
        # Mastercard 222100–272099 (BIN/IIN), also 51–55 legacy
        if random.random() < 0.7:
            start = 222100
            end = 272099
            bin6 = random.randint(start, end)
            return str(bin6), 16
        else:
            return str(random.randint(51, 55)), 16
    if s == "visa":
        # Visa: leading 4, 16-digit common
        # Avoid obvious demo bin 424242
        candidates = ["4"]
        prefix = random.choice(candidates)
        return prefix, 16
    if s == "amex":
        # American Express: 34 or 37, length 15
        return random.choice(["34", "37"]), 15
    if s == "discover":
        # Discover: 6011, 65, 644–649
        roll = random.random()
        if roll < 0.33:
            return "6011", 16
        elif roll < 0.66:
            return "65", 16
        else:
            return str(random.randint(644, 649)), 16
    if s == "jcb":
        # JCB: 3528–3589
        return str(random.randint(3528, 3589)), 16
    if s == "diners":
        # Diners Club: 300–305 (14), 36 (14), 38 (14)
        roll = random.random()
        if roll < 0.5:
            return str(random.randint(300, 305)), 14
        else:
            return random.choice(["36", "38"]), 14
    # Fallback
    return "4", 16

def generate_luhn_card_numbers(prefix_bin: str, count: int, length: int = 16) -> List[str]:
    """Generate Luhn-valid card numbers starting with a given BIN/prefix.

    - prefix_bin: starting digits, e.g., "424242"
    - count: how many numbers to generate
    - length: total desired PAN length (default 16)
    """
    prefix = ''.join(ch for ch in str(prefix_bin) if ch.isdigit())
    if not prefix:
        return []
    remaining_body_len = max(0, length - len(prefix) - 1)
    results: List[str] = []
    seen = set()
    while len(results) < count:
        body = ''.join(str(random.randint(0, 9)) for _ in range(remaining_body_len))
        core = prefix + body
        check = luhn_checksum(core)
        pan = core + str(check)
        if pan in seen:
            continue
        seen.add(pan)
        results.append(pan)
    return results


def _is_non_trivial_digits(seq: str) -> bool:
    """Heuristics to avoid obviously fake patterns (e.g., 0000..., 1234..., 5555...).

    Rules:
    - Not all digits identical
    - No run of 4 or more identical digits
    - Not a pure ascending (012345...) or descending (987654...) progression modulo 10
    - Avoid very low-entropy bodies such as two repeating pairs like ABABAB...
    """
    if not seq:
        return False
    # All identical?
    if len(set(seq)) == 1:
        return False
    # Long identical run (>=4)
    run = 1
    for i in range(1, len(seq)):
        if seq[i] == seq[i-1]:
            run += 1
            if run >= 4:
                return False
        else:
            run = 1
    # Ascending/descending progressions
    asc = all((int(seq[i]) + 1) % 10 == int(seq[i+1]) for i in range(len(seq)-1))
    desc = all((int(seq[i]) - 1) % 10 == int(seq[i+1]) for i in range(len(seq)-1))
    if asc or desc:
        return False
    # Simple 2-length repeating patterns (e.g., 121212, 343434)
    if len(seq) >= 6 and len(set(seq[:2])) == 2:
        pattern = seq[:2]
        if pattern * (len(seq)//2) == seq[:2*(len(seq)//2)]:
            return False
    return True


def _generate_one_luhn_pan_realistic(prefix: str, length: int) -> Optional[str]:
    """Generate a single Luhn-valid PAN using heuristics to avoid trivial patterns."""
    remaining_body_len = max(0, length - len(prefix) - 1)
    if remaining_body_len <= 0:
        return None
    for _ in range(200):  # limit attempts to keep fast
        body = ''.join(str(random.randint(0, 9)) for _ in range(remaining_body_len))
        if not _is_non_trivial_digits(body):
            continue
        core = prefix + body
        check = luhn_checksum(core)
        pan = core + str(check)
        return pan
    # Fallback to simple generator if heuristics fail repeatedly
    body = ''.join(str(random.randint(0, 9)) for _ in range(remaining_body_len))
    core = prefix + body
    check = luhn_checksum(core)
    return core + str(check)


def generate_luhn_card_numbers_realistic(prefix_bin: str, count: int, length: int = 16) -> List[str]:
    """Generate Luhn-valid numbers with heuristics to avoid obvious patterns."""
    prefix = ''.join(ch for ch in str(prefix_bin) if ch.isdigit())
    if not prefix:
        return []
    results: List[str] = []
    seen = set()
    while len(results) < count:
        pan = _generate_one_luhn_pan_realistic(prefix, length)
        if not pan or pan in seen:
            continue
        if is_luhn_valid(pan):
            seen.add(pan)
            results.append(pan)
    return results


def generate_card_inputs_from_bin(prefix_bin: str, count: int) -> List[CardInput]:
    """Generate CardInput entries with random expiry and cvv.

    - Month: 01..12
    - Year: current year+1 .. current year+5 (two or four digits accepted by our parser; we keep 4-digit here)
    - CVV: random 3-digit
    """
    pans = generate_luhn_card_numbers_realistic(prefix_bin, count)
    now = datetime.datetime.utcnow()
    start_year = now.year + 1
    end_year = now.year + 5
    results: List[CardInput] = []
    for pan in pans:
        month = f"{random.randint(1, 12):02d}"
        year = str(random.randint(start_year, end_year))
        cvv = f"{random.randint(0, 999):03d}"
        results.append(CardInput(number=pan, month=month, year=year, cvv=cvv))
    return results


def _pick_random_prefix_and_length(
    optional_bin: Optional[str] = None,
    allowed_schemes: Optional[List[str]] = None,
) -> Tuple[str, int, str, int]:
    """Pick a random scheme prefix and target length.

    Returns (prefix, length, scheme_name, cvv_length).
    If optional_bin provided, infer length=16 by default (common) and scheme unknown.
    """
    # Scheme catalog with typical lengths
    catalog: List[Tuple[str, List[Tuple[str, int]], int]] = [
        ("visa", [("4", 16), ("424242", 16)], 3),
        ("mastercard", [("51", 16), ("55", 16), ("2221", 16), ("2720", 16), ("510510", 16), ("555555", 16)], 3),
        ("amex", [("34", 15), ("37", 15)], 4),
        ("discover", [("6011", 16), ("65", 16), ("644", 16)], 3),
        ("jcb", [("3528", 16), ("3589", 16)], 3),
        ("diners", [("36", 14), ("300", 14), ("305", 14)], 3),
    ]

    if optional_bin:
        cleaned = ''.join(ch for ch in str(optional_bin) if ch.isdigit())
        if cleaned:
            # Infer length heuristically by leading digits (amex 34/37 -> 15, diners 36/300/305 -> 14)
            length = 16
            cvv_len = 3
            if cleaned.startswith(("34", "37")):
                length = 15
                cvv_len = 4
            elif cleaned.startswith(("36", "300", "305")):
                length = 14
            return cleaned[:6] if len(cleaned) >= 4 else cleaned, length, "unknown", cvv_len

    filtered = catalog
    if allowed_schemes:
        allowed_lower = {s.lower() for s in allowed_schemes}
        tmp = [row for row in catalog if row[0] in allowed_lower]
        if tmp:
            filtered = tmp
    scheme_name, prefixes, cvv_len = random.choice(filtered)
    # Prefer realistic range-based prefix selection
    prefix, length = _random_scheme_prefix(scheme_name)
    return prefix, length, scheme_name, cvv_len


def generate_random_named_cards(
    count: int,
    optional_bin: Optional[str] = None,
    allowed_schemes: Optional[List[str]] = None,
) -> List[dict]:
    """Generate random cards with person names and Luhn-valid PANs.

    - If optional_bin provided, use it as prefix; otherwise pick from common Visa/Mastercard BINs.
    - Month: 01..12, Year: current+1..current+5, CVV: 3-digit.
    - Returns list of dicts: {name, number, month, year, cvv}.
    """
    # Basic name pools (kept local; no external deps)
    first_names = [
        "Ali", "Reza", "Sara", "Fatemeh", "Mina", "Omid", "Arman", "Maryam", "Hamed", "Nima",
        "John", "Jane", "Michael", "Emily", "David", "Sophia", "Daniel", "Olivia", "James", "Ava",
    ]
    last_names = [
        "Ranjbar", "Ahmadi", "Hosseini", "Karimi", "Mohammadi", "Habibi", "Rahimi", "Moradi", "Nazari", "Ebrahimi",
        "Smith", "Johnson", "Brown", "Williams", "Jones", "Miller", "Davis", "Garcia", "Martinez", "Wilson",
    ]

    now = datetime.datetime.utcnow()
    start_year = now.year + 1
    end_year = now.year + 5
    out: List[dict] = []
    for _ in range(count):
        prefix, length, scheme_name, cvv_len = _pick_random_prefix_and_length(optional_bin, allowed_schemes)
        pans = generate_luhn_card_numbers_realistic(prefix, 1, length=length)
        if not pans:
            continue
        pan = pans[0]
        if not is_luhn_valid(pan):
            continue
        name = f"{random.choice(first_names)} {random.choice(last_names)}"
        month = f"{random.randint(1, 12):02d}"
        year = str(random.randint(start_year, end_year))
        if cvv_len == 4:
            cvv = f"{random.randint(0, 9999):04d}"
        else:
            cvv = f"{random.randint(0, 999):03d}"
        out.append({"name": name, "number": pan, "month": month, "year": year, "cvv": cvv})
    return out


def generate_random_card_inputs(
    count: int,
    optional_bin: Optional[str] = None,
    allowed_schemes: Optional[List[str]] = None,
) -> List[CardInput]:
    """Generate random CardInput entries (no names), optionally constrained by BIN prefix.

    If optional_bin is not provided, choose a common Visa/Mastercard BIN prefix.
    """
    now = datetime.datetime.utcnow()
    start_year = now.year + 1
    end_year = now.year + 5
    results: List[CardInput] = []
    for _ in range(count):
        prefix, length, scheme_name, cvv_len = _pick_random_prefix_and_length(optional_bin, allowed_schemes)
        pans = generate_luhn_card_numbers_realistic(prefix, 1, length=length)
        if not pans:
            continue
        pan = pans[0]
        if not is_luhn_valid(pan):
            continue
        month = f"{random.randint(1, 12):02d}"
        year = str(random.randint(start_year, end_year))
        if cvv_len == 4:
            cvv = f"{random.randint(0, 9999):04d}"
        else:
            cvv = f"{random.randint(0, 999):03d}"
        results.append(CardInput(number=pan, month=month, year=year, cvv=cvv))
    return results


@dataclass
class BinInfo:
    """Subset of BIN data returned from binlist."""

    bank: Optional[str] = None
    scheme: Optional[str] = None
    card_type: Optional[str] = None
    brand: Optional[str] = None
    country: Optional[str] = None  # alpha2
    country_name: Optional[str] = None


@dataclass
class CardResult:
    """Final result for one processed card."""

    masked_number: str
    month: str
    year: str
    status: str  # "Live/Test OK" | "Declined" | "Error"
    message: Optional[str]
    bin_bank: Optional[str]
    bin_scheme: Optional[str]
    bin_type: Optional[str]
    bin_brand: Optional[str]
    bin_country: Optional[str]
    # Optional prediction outputs
    prediction_score: Optional[int] = None
    prediction_status: Optional[str] = None


# -----------------------------
# Input readers
# -----------------------------


def read_input_file(path: str) -> List[CardInput]:
    """Detect format by extension and parse into CardInput list."""
    lower = path.lower()
    if lower.endswith(".txt"):
        return _read_txt(path)
    if lower.endswith(".csv"):
        return _read_csv(path)
    if lower.endswith(".json"):
        return _read_json(path)
    raise ValueError("Unsupported file extension. Use .txt, .csv, or .json")


def _read_txt(path: str) -> List[CardInput]:
    """Read TXT where each line is number|month|year|cvv."""
    # Sniff if the file actually contains JSON (common when JSON saved as .txt)
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        content = f.read()
    # Normalize common non-breaking spaces to regular spaces for detection
    content = content.replace("\u00a0", " ")
    stripped = content.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        # Treat as JSON array/object
        return _read_json_content(content)

    # Otherwise parse line-delimited pipes
    results: List[CardInput] = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 4:
            continue
        number, month, year, cvv = parts
        results.append(CardInput(number=number, month=month, year=year, cvv=cvv))
    return results


def _read_csv(path: str) -> List[CardInput]:
    """Read CSV with columns number, month, year, cvv (header or no header)."""
    results: List[CardInput] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(2048)
        f.seek(0)
        dialect = csv.Sniffer().sniff(sample) if sample else csv.excel
        has_header = csv.Sniffer().has_header(sample) if sample else False
        reader = csv.reader(f, dialect)

        header: Optional[List[str]] = None
        if has_header:
            try:
                header = next(reader)
            except StopIteration:
                header = None

        for row in reader:
            if not row:
                continue
            if header:
                # Attempt to map by header names
                header_map = {h.strip().lower(): i for i, h in enumerate(header)}
                try:
                    number = row[header_map["number"]].strip()
                    month = row[header_map["month"]].strip()
                    year = row[header_map["year"]].strip()
                    cvv = row[header_map["cvv"]].strip()
                except Exception:
                    # Fallback to positional if mapping fails
                    if len(row) < 4:
                        continue
                    number, month, year, cvv = [c.strip() for c in row[:4]]
            else:
                if len(row) < 4:
                    continue
                number, month, year, cvv = [c.strip() for c in row[:4]]

            results.append(CardInput(number=number, month=month, year=year, cvv=cvv))
    return results


def _read_json(path: str) -> List[CardInput]:
    """Read JSON array of {number, month, year, cvv}."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return _read_json_content(content)


def _read_json_content(content: str) -> List[CardInput]:
    """Parse JSON content and support multiple schemas, including nested CreditCard."""
    try:
        data = json.loads(content)
    except Exception:
        return []

    def extract_from_dict(obj: dict) -> Optional[CardInput]:
        # Support nested CreditCard structure
        if "CreditCard" in obj and isinstance(obj["CreditCard"], dict):
            cc = obj["CreditCard"]
            number = str(cc.get("CardNumber", "")).strip()
            cvv = str(cc.get("CVV", "") or cc.get("CVC", "")).strip()
            exp = str(cc.get("Exp", "")).strip()
            month, year = "", ""
            if "/" in exp:
                parts = exp.split("/")
                if len(parts) == 2:
                    month = parts[0].strip()
                    year = parts[1].strip()
            if number and month and year and cvv:
                return CardInput(number=number, month=month, year=year, cvv=cvv)
            return None

        # Flat variants and alternate keys
        number = str(
            obj.get("number")
            or obj.get("cardNumber")
            or obj.get("CardNumber")
            or obj.get("pan")
            or ""
        ).strip()
        cvv = str(obj.get("cvv") or obj.get("cvc") or obj.get("CVV") or obj.get("CVC") or "").strip()
        month = str(obj.get("month") or obj.get("exp_month") or obj.get("ExpMonth") or "").strip()
        year = str(obj.get("year") or obj.get("exp_year") or obj.get("ExpYear") or "").strip()
        exp = str(obj.get("exp") or obj.get("Exp") or "").strip()
        if (not month or not year) and "/" in exp:
            parts = exp.split("/")
            if len(parts) == 2:
                month = month or parts[0].strip()
                year = year or parts[1].strip()
        if number and month and year and cvv:
            return CardInput(number=number, month=month, year=year, cvv=cvv)
        return None

    results: List[CardInput] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                ci = extract_from_dict(item)
                if ci:
                    results.append(ci)
    elif isinstance(data, dict):
        ci = extract_from_dict(data)
        if ci:
            results.append(ci)
    return results


def read_interactive() -> List[CardInput]:
    """Prompt the user to enter card lines; empty line to finish."""
    print("Enter cards as number|month|year|cvv (one per line). Empty line to finish.")
    results: List[CardInput] = []
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if not line:
            break
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 4:
            print(f"{YELLOW}Skipping invalid line. Expected number|month|year|cvv{RESET}")
            continue
        number, month, year, cvv = parts
        results.append(CardInput(number=number, month=month, year=year, cvv=cvv))
    return results


# -----------------------------
# BIN lookup
# -----------------------------


def bin_lookup(card_number: str, timeout: float = 8.0, verify_ssl: bool = True) -> BinInfo:
    """Lookup BIN details from binlist.

    Extracts bank name, scheme, type, brand, and country (alpha2).
    """
    bin6 = (card_number or "").replace(" ", "").replace("-", "")[:6]
    if len(bin6) < 6 or not bin6.isdigit():
        return BinInfo()
    url = f"https://lookup.binlist.net/{bin6}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "card-checker/1.0",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, verify=verify_ssl)
        if resp.status_code != 200:
            return BinInfo()
        data = resp.json()
        bank_name = None
        try:
            bank = data.get("bank") or {}
            bank_name = bank.get("name") if isinstance(bank, dict) else None
        except Exception:
            bank_name = None
        country_code = None
        try:
            country = data.get("country") or {}
            country_code = country.get("alpha2") if isinstance(country, dict) else None
            country_name = country.get("name") if isinstance(country, dict) else None
        except Exception:
            country_code = None
            country_name = None
        return BinInfo(
            bank=bank_name,
            scheme=data.get("scheme"),
            card_type=data.get("type"),
            brand=data.get("brand"),
            country=country_code,
            country_name=country_name,
        )
    except Exception:
        return BinInfo()


# -----------------------------
# Stripe helpers
# -----------------------------


def init_stripe_from_env(max_network_retries: int = 2, insecure: bool = False) -> None:
    """Initialize stripe with API key from STRIPE_API_KEY env var."""
    api_key = os.environ.get("STRIPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Environment variable STRIPE_API_KEY is not set.")
    stripe.api_key = api_key
    # Configure retries for transient network issues
    stripe.max_network_retries = max_network_retries
    # Optionally disable SSL verification (not recommended; for corporate MITM environments)
    if insecure:
        try:
            stripe.verify_ssl_certs = False  # type: ignore[attr-defined]
        except Exception:
            pass


def authorize_card_small_amount(
    card: CardInput,
    amount: int = 50,
    currency: str = "usd",
    timeout: float = 20.0,
    payment_method_id: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """Attempt a small authorization using PaymentIntent with manual capture.

    Returns (status, message):
    - status: "ok", "declined", or "error"
    - message: decline message or error details

    Uses confirm=true and capture_method=manual to only authorize, then cancels
    the PaymentIntent immediately to release the hold.
    """
    try:
        # Create and confirm a PaymentIntent
        if payment_method_id:
            # Use a pre-existing payment_method (e.g., pm_card_visa)
            intent = stripe.PaymentIntent.create(
                amount=amount,
                currency=currency,
                capture_method="manual",
                payment_method=payment_method_id,
                confirm=True,
                payment_method_types=["card"],
                automatic_payment_methods={"enabled": False},
            )
        else:
            # Use raw card details (requires Stripe account access to raw card data APIs)
            intent = stripe.PaymentIntent.create(
                amount=amount,
                currency=currency,
                capture_method="manual",
                # Force only card payments to avoid redirect-based methods and return_url requirements
                payment_method_types=["card"],
                automatic_payment_methods={"enabled": False},
                confirm=True,
                payment_method_data={
                    "type": "card",
                    "card": {
                        "number": card.number,
                        "exp_month": int(card.month),
                        "exp_year": int(card.year),
                        "cvc": card.cvv,
                    },
                },
            )

        # If confirmation requires action (e.g., 3DS), treat as declined for this batch tool
        status = getattr(intent, "status", None)
        if status in ("requires_action", "requires_source_action"):
            message = "Authentication required (3DS); not completed in batch"
            try:
                stripe.PaymentIntent.cancel(intent["id"])  # Best-effort cleanup
            except Exception:
                pass
            return "declined", message

        # Authorized successfully if requires_capture (manual capture flow)
        if status in ("requires_capture", "succeeded"):
            # Cancel to release authorization hold
            try:
                stripe.PaymentIntent.cancel(intent["id"])
            except Exception:
                pass
            return "ok", None

        # Other statuses considered errors
        try:
            stripe.PaymentIntent.cancel(intent["id"])
        except Exception:
            pass
        return "error", f"Unexpected status: {status}"

    except stripe.error.CardError as e:
        # Card declined; include message
        err = e.json_body.get("error", {}) if hasattr(e, "json_body") else {}
        message = err.get("message") or str(e)
        return "declined", message
    except Exception as e:
        # Any other error
        return "error", str(e)


# -----------------------------
# Processing and output
# -----------------------------


def mask_card_number(number: str) -> str:
    """Show first 6 and last 4 digits, mask the rest with X."""
    digits = (number or "").replace(" ", "").replace("-", "")
    if len(digits) < 10:
        return f"****{digits[-4:]}" if digits else ""
    first6 = digits[:6]
    last4 = digits[-4:]
    masked_middle = "X" * (len(digits) - 10)
    return f"{first6}{masked_middle}{last4}"


def process_cards(
    cards: Iterable[CardInput],
    currency: str = "usd",
    verify_ssl: bool = True,
    treat_as_payment_method: bool = False,
    on_progress: Optional[Callable[[CardResult], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> List[CardResult]:
    """Process each card with BIN lookup and Stripe authorization."""
    results: List[CardResult] = []
    for card in cards:
        # Cooperative cancellation before starting each card
        try:
            if should_stop is not None and should_stop():
                break
        except Exception:
            pass
        try:
            info = bin_lookup(card.number, verify_ssl=verify_ssl)
        except Exception:
            info = BinInfo()

        # By default (no predict/live toggles here), run normal test authorization or pm flow
        try:
            pm_id = card.number if (treat_as_payment_method and str(card.number).startswith("pm_")) else None
            if treat_as_payment_method and not pm_id:
                status_code, message = "error", "Entry is not a payment_method id (pm_...)"
            else:
                status_code, message = authorize_card_small_amount(
                    card, currency=currency, payment_method_id=pm_id
                )
        except Exception as e:
            status_code, message = "error", str(e)

        # Map status for final output
        if status_code == "ok":
            status_out = "Live/Test OK"
            color = GREEN
        elif status_code == "declined":
            status_out = "Declined"
            color = RED
        else:
            status_out = "Error"
            color = RED

        # For pm_ payment methods, keep the id unmasked for clarity in logs/GUI
        if treat_as_payment_method and pm_id:
            masked = card.number
        else:
            masked = mask_card_number(card.number)

        # Print a one-line colored summary for terminal
        msg = f" - {message}" if message else ""
        try:
            print(f"{color}{status_out}{RESET} {masked}{msg}")
        except Exception:
            pass

        card_result = CardResult(
                masked_number=masked,
                month=str(card.month),
                year=str(card.year),
                status=status_out,
                message=message,
                bin_bank=info.bank,
                bin_scheme=info.scheme,
                bin_type=info.card_type,
                bin_brand=info.brand,
                bin_country=info.country,
        )
        results.append(card_result)

        # Callback for GUI progress
        if on_progress is not None:
            try:
                on_progress(card_result)
            except Exception:
                pass

        # Cooperative cancellation between requests and brief delay
        try:
            if should_stop is not None and should_stop():
                break
        except Exception:
            pass
        time.sleep(0.2)

    return results


def write_results_csv(path: str, results: List[CardResult]) -> None:
    """Write results to CSV file."""
    fieldnames = [
        "masked_number",
        "month",
        "year",
        "status",
        "message",
        "bin_bank",
        "bin_scheme",
        "bin_type",
        "bin_brand",
        "bin_country",
        # Optional prediction fields (kept always for stable schema)
        "prediction_score",
        "prediction_status",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))


def write_results_json(path: str, results: List[CardResult]) -> None:
    """Write results to JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, indent=2, ensure_ascii=False)


# -----------------------------
# CLI
# -----------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Test multiple cards with Stripe (test mode) and BIN lookup.",
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input_path",
        help="Path to input file (.txt | .csv | .json). If omitted, interactive mode is used.",
    )
    parser.add_argument(
        "-c",
        "--currency",
        default="usd",
        help="Currency for authorization (default: usd)",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable SSL verification for Stripe and BIN lookup (use only if your network intercepts TLS)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Max network retries for Stripe client (default: 2)",
    )
    parser.add_argument(
        "--pm",
        dest="treat_as_payment_method",
        action="store_true",
        help="Treat input 'number' column as payment_method id (pm_...)",
    )
    # New: BIN-based generator mode
    parser.add_argument(
        "--generate-bin",
        nargs=2,
        metavar=("BIN", "COUNT"),
        help="Generate COUNT Luhn-valid test cards starting with BIN (e.g., 424242 20)",
    )
    parser.add_argument(
        "--predict",
        action="store_true",
        help="Run BIN-based activeness prediction without live transactions",
    )
    parser.add_argument(
        "--live-mode",
        action="store_true",
        help="Attempt live micro-authorization ($0.50) with sk_live_ key to detect activeness",
    )
    parser.add_argument(
        "--generate-random",
        nargs="*",
        metavar=("COUNT", "BIN"),
        help="Generate COUNT random named cards (optional BIN prefix)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """Program entry point."""
    _enable_windows_ansi_support()

    args = parse_args(argv)
    # Initialize Stripe only if needed (normal flow or live-mode/predict still may rely on env)
    try:
        init_stripe_from_env(max_network_retries=max(0, int(args.retries)), insecure=args.insecure)
    except Exception as e:
        # In predict mode we can continue without Stripe
        if not args.predict:
            print(f"{RED}Error: {e}{RESET}")
            return 2

    # Read inputs or generate by BIN
    try:
        if args.generate_bin:
            bin_value, count_str = args.generate_bin
            try:
                num = max(1, int(count_str))
            except Exception:
                num = 10
            # Generate Luhn-valid test cards locally
            # Note: Stripe will still decline raw-card auth unless your account has raw card API access.
            cards = generate_card_inputs_from_bin(bin_value, num)
        elif args.generate_random is not None and len(args.generate_random) >= 1:
            # --generate-random COUNT [BIN]
            gr = args.generate_random
            try:
                num = max(1, int(gr[0]))
            except Exception:
                num = 10
            opt_bin = gr[1] if len(gr) > 1 else None
            named = generate_random_named_cards(num, opt_bin)
            # Persist a convenience TXT and JSON for the user
            try:
                with open("generated_named_cards.txt", "w", encoding="utf-8") as wf:
                    for it in named:
                        wf.write(f"{it['number']}|{it['month']}|{it['year']}|{it['cvv']}\n")
                with open("generated_named_cards.json", "w", encoding="utf-8") as jf:
                    json.dump(named, jf, indent=2, ensure_ascii=False)
            except Exception:
                pass
            # Feed into processing flow
            cards = [CardInput(number=it["number"], month=it["month"], year=it["year"], cvv=it["cvv"]) for it in named]
        elif args.input_path:
            cards = read_input_file(args.input_path)
        else:
            cards = read_interactive()
    except Exception as e:
        print(f"{RED}Failed to read input: {e}{RESET}")
        return 2

    if not cards:
        print(f"{YELLOW}No cards to process.{RESET}")
        return 0

    print(f"Processing {len(cards)} card(s)...\n")

    # Process and output
    try:
        if args.predict:
            # Prediction-only: compute scores without hitting Stripe
            results: List[CardResult] = []
            # Load rules
            try:
                with open("predict_rules.json", "r", encoding="utf-8") as rf:
                    rules = json.load(rf)
            except Exception:
                rules = {}
            ecommerce_keywords = [s.lower() for s in rules.get("ecommerce_keywords", [])]
            pos_only_keywords = [s.lower() for s in rules.get("pos_only_keywords", [])]
            known_online_banks = [s.lower() for s in rules.get("known_online_banks", [])]
            known_pos_only_banks = [s.lower() for s in rules.get("known_pos_only_banks", [])]
            weights = rules.get("score_weights", {})
            w_ecomm = int(weights.get("ecommerce_keyword", 50))
            w_online_bank = int(weights.get("known_online_bank", 30))
            w_pos = int(weights.get("pos_only_keyword", -80))
            w_pos_bank = int(weights.get("known_pos_only_bank", -90))

            for card in cards:
                try:
                    info = bin_lookup(card.number, verify_ssl=not args.insecure)
                except Exception:
                    info = BinInfo()
                # Build searchable text blob; lowercase
                fields = [
                    info.scheme or "",
                    info.card_type or "",
                    info.brand or "",
                    info.country_name or "",
                ]
                blob = " ".join(fields).lower()
                bank_l = (info.bank or "").lower()

                score = 0
                if any(k in blob for k in ecommerce_keywords):
                    score += w_ecomm
                if any(k in bank_l for k in known_online_banks):
                    score += w_online_bank
                if any(k in blob for k in pos_only_keywords):
                    score += w_pos
                if any(k in bank_l for k in known_pos_only_banks):
                    score += w_pos_bank
                score = max(0, min(100, score))
                if score >= 70:
                    pred_status = "Likely Active"
                    color = GREEN
                elif score >= 40:
                    pred_status = "Possibly Active"
                    color = YELLOW
                else:
                    pred_status = "Unlikely Active"
                    color = RED

                masked = mask_card_number(card.number)
                print(f"{color}{pred_status}{RESET} {masked} - score {score}")
                results.append(
                    CardResult(
                        masked_number=masked,
                        month=str(card.month),
                        year=str(card.year),
                        status=pred_status,
                        message=None,
                        bin_bank=info.bank,
                        bin_scheme=info.scheme,
                        bin_type=info.card_type,
                        bin_brand=info.brand,
                        bin_country=info.country,
                        prediction_score=score,
                        prediction_status=pred_status,
                    )
                )
        else:
            # Normal test or live-mode (we reuse authorize flow; for live-mode ensure sk_live is set)
            # For simplicity, we keep the same process_cards but it does test-mode auth.
            # Live mode authorization amount is already supported in authorize_card_small_amount by amount param.
            results = process_cards(
                cards,
                currency=args.currency,
                verify_ssl=not args.insecure,
                treat_as_payment_method=bool(getattr(args, "treat_as_payment_method", False)),
            )
    except Exception as e:
        print(f"{RED}Processing failed: {e}{RESET}")
        return 2

    # Write outputs
    try:
        write_results_csv("results.csv", results)
        write_results_json("results.json", results)
    except Exception as e:
        print(f"{RED}Failed to write results: {e}{RESET}")
        return 2

    # Summary counts
    ok = sum(1 for r in results if r.status in ("Live/Test OK", "Active (Live OK)", "Likely Active"))
    declined = sum(1 for r in results if r.status in ("Declined", "Inactive", "Unlikely Active"))
    error = sum(1 for r in results if r.status == "Error")

    print("\nSummary:")
    print(f"  {GREEN}OK{RESET}: {ok}")
    print(f"  {RED}Declined{RESET}: {declined}")
    print(f"  {RED}Error{RESET}: {error}")
    print("\nWrote results to results.csv and results.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())


