"""One-time setup so `kind: phone` stacks can dial hosted voice agents (Maqsam, Nabrah, Vapi, Retell... any number).

    .venv/bin/python scripts/setup_sip.py            # dry run: checks keys and permissions, prints what it would create
    .venv/bin/python scripts/setup_sip.py --apply    # creates it (changes your Twilio and LiveKit accounts)

What --apply creates (re-running reuses what already exists):
  1. Twilio Elastic SIP trunk "lk-bench" with a termination domain <random>.pstn.twilio.com
  2. a Twilio credential list "lk-bench" (random username/password) attached to that trunk
  3. a LiveKit SIP outbound trunk pointing at the Twilio domain with those credentials; TWILIO_FROM_NUMBER is the
     caller ID (it only has to be a number on your Twilio account: it is NOT moved onto the trunk, so its own
     incoming-call webhook keeps working; pass --attach-number only if you want inbound calls on the trunk)
  4. BENCH_SIP_TRUNK_ID=<id> appended to .env

The Twilio key needs Voice SIP permissions. A Standard API key has them; a Restricted key needs at least
SIP trunks (create, list, read), the trunk's credential lists (create) and SIP credential lists + credentials
(create, list). Also, in the Twilio console (not scriptable here): Voice > Settings > Geo permissions: allow the
countries you will dial (Saudi Arabia +966, UAE +971, Qatar +974, Kuwait +965, Bahrain +973, Oman +968). Calls cost
Twilio's per-minute rate to that country; check pricing before a large batch.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bench.config  # noqa: E402,F401  (loads .env)

ACC = os.environ.get("TWILIO_ACCOUNT_SID", "")
KEY = os.environ.get("TWILIO_API_KEY_SID", "")
SECRET = os.environ.get("TWILIO_API_KEY_SECRET", "")
FROM = os.environ.get("TWILIO_FROM_NUMBER", "")
API = f"https://api.twilio.com/2010-04-01/Accounts/{ACC}"
TRUNKS = "https://trunking.twilio.com/v1/Trunks"
NAME = "lk-bench"


def tw(method: str, url: str, data: dict | None = None) -> dict:
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{KEY}:{SECRET}".encode()).decode())
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"{}")


def missing_permissions() -> list[str]:
    """Twilio names the missing permission in its 401 body; collect them for the two APIs we need."""
    missing = []
    for url in (TRUNKS, f"{API}/SIP/CredentialLists.json"):
        try:
            tw("GET", url)
        except urllib.error.HTTPError as e:
            msg = json.loads(e.read() or b"{}").get("message", "")
            missing.append(msg.split("permission ")[-1].split(" is")[0] if "permission" in msg else f"HTTP {e.code} on {url}")
    return missing


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="create the trunks (changes your accounts)")
    ap.add_argument("--attach-number", action="store_true",
                    help="also move TWILIO_FROM_NUMBER onto the trunk (replaces its incoming-call webhook)")
    args = ap.parse_args()
    missing = [k for k, v in {"TWILIO_ACCOUNT_SID": ACC, "TWILIO_API_KEY_SID": KEY, "TWILIO_API_KEY_SECRET": SECRET,
                              "TWILIO_FROM_NUMBER": FROM}.items() if not v]
    if missing:
        raise SystemExit("missing in .env: " + ", ".join(missing))
    if os.environ.get("BENCH_SIP_TRUNK_ID"):
        raise SystemExit("BENCH_SIP_TRUNK_ID is already set; nothing to do")

    nums = tw("GET", f"{API}/IncomingPhoneNumbers.json?" + urllib.parse.urlencode({"PhoneNumber": FROM}))
    if not nums.get("incoming_phone_numbers"):
        raise SystemExit(f"TWILIO_FROM_NUMBER {FROM[:-4]}**** is not a number on this Twilio account")
    num = nums["incoming_phone_numbers"][0]
    hook = urllib.parse.urlparse(num.get("voice_url") or "").netloc
    print(f"Twilio account ok; caller ID {FROM[:-4]}**** (incoming calls go to: {hook or 'nothing'})")

    perms = missing_permissions()
    if perms:
        print("\n✗ The Twilio API key can't manage SIP trunks. Missing: " + ", ".join(perms))
        print("  Fix in the Twilio console (Account > API keys & tokens): give this key the Voice SIP permissions,")
        print("  or create a Standard API key and replace TWILIO_API_KEY_SID / TWILIO_API_KEY_SECRET in .env. Then re-run.")
        raise SystemExit(1)

    existing = next((t for t in tw("GET", TRUNKS).get("trunks", []) if t["friendly_name"] == NAME), None)
    domain = existing["domain_name"] if existing else f"{NAME}-{secrets.token_hex(4)}.pstn.twilio.com"
    user, pwd = f"lkbench{secrets.token_hex(3)}", secrets.token_urlsafe(18) + "A1"
    print("\nPlan:")
    print(f"  Twilio: SIP trunk '{NAME}' {'(exists, reused)' if existing else '(new)'}, termination {domain}")
    print(f"  Twilio: credential list '{NAME}' with a new user {user} (random password), attached to the trunk")
    if args.attach_number:
        print(f"  Twilio: move {FROM[:-4]}**** onto the trunk (its incoming webhook to {hook or '-'} stops)")
    print(f"  LiveKit: outbound trunk -> {domain}, caller ID {FROM[:-4]}****")
    print("  .env: BENCH_SIP_TRUNK_ID=<new id>")
    if not args.apply:
        print("\nDry run only. Re-run with --apply to create it.")
        return

    trunk = existing or tw("POST", TRUNKS, {"FriendlyName": NAME, "DomainName": domain})
    cl = tw("POST", f"{API}/SIP/CredentialLists.json", {"FriendlyName": f"{NAME}-{secrets.token_hex(2)}"})
    tw("POST", f"{API}/SIP/CredentialLists/{cl['sid']}/Credentials.json", {"Username": user, "Password": pwd})
    tw("POST", f"{TRUNKS}/{trunk['sid']}/CredentialLists", {"CredentialListSid": cl["sid"]})
    if args.attach_number:
        tw("POST", f"{TRUNKS}/{trunk['sid']}/PhoneNumbers", {"PhoneNumberSid": num["sid"]})
    print(f"Twilio trunk {trunk['sid']} ready")

    async def lk() -> str:
        from livekit import api

        async with api.LiveKitAPI() as client:
            t = await client.sip.create_outbound_trunk(api.CreateSIPOutboundTrunkRequest(trunk=api.SIPOutboundTrunkInfo(
                name=f"{NAME} (Twilio)", address=domain, numbers=[FROM], auth_username=user, auth_password=pwd)))
            return t.sip_trunk_id

    tid = asyncio.run(lk())
    with (ROOT / ".env").open("a") as f:
        f.write(f"\nBENCH_SIP_TRUNK_ID={tid}\n")
    print(f"LiveKit outbound trunk {tid} ready; BENCH_SIP_TRUNK_ID written to .env")
    print("Next: allow the Gulf countries in Twilio's Voice geo permissions, then `bench run -s agent-<x> -c <scenario>`")


if __name__ == "__main__":
    main()
