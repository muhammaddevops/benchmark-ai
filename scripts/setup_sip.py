"""One-time setup so `kind: phone` stacks can dial hosted voice agents (Maqsam, Wittify, Vapi, Retell... any number).

    .venv/bin/python scripts/setup_sip.py            # dry run: checks your keys and prints what it would create
    .venv/bin/python scripts/setup_sip.py --apply    # creates it (changes your Twilio and LiveKit accounts)

What --apply creates:
  1. Twilio Elastic SIP trunk "lk-bench" with a termination domain <random>.pstn.twilio.com
  2. a Twilio credential list (random username/password) attached to that trunk
  3. your TWILIO_FROM_NUMBER moved onto the trunk, so calls show it as caller ID
     (a number on a SIP trunk stops using its Voice webhook: use a spare number)
  4. a LiveKit SIP outbound trunk pointing at the Twilio domain with those credentials
  5. BENCH_SIP_TRUNK_ID=<id> appended to .env

Also needed, in the Twilio console (not scriptable here): Voice > Settings > Geo permissions: allow the countries
you will dial (Saudi Arabia +966, UAE +971, Qatar +974, Kuwait +965, Bahrain +973, Oman +968). Calls cost Twilio's
per-minute rate to that country; check pricing before a large batch.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import secrets
import sys
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


def tw(method: str, url: str, data: dict | None = None) -> dict:
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{KEY}:{SECRET}".encode()).decode())
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"{}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="create the trunks (changes your accounts)")
    args = ap.parse_args()
    missing = [k for k, v in {"TWILIO_ACCOUNT_SID": ACC, "TWILIO_API_KEY_SID": KEY, "TWILIO_API_KEY_SECRET": SECRET,
                              "TWILIO_FROM_NUMBER": FROM}.items() if not v]
    if missing:
        raise SystemExit("missing in .env: " + ", ".join(missing))
    if os.environ.get("BENCH_SIP_TRUNK_ID"):
        raise SystemExit(f"BENCH_SIP_TRUNK_ID is already set ({os.environ['BENCH_SIP_TRUNK_ID']}); nothing to do")

    nums = tw("GET", f"https://api.twilio.com/2010-04-01/Accounts/{ACC}/IncomingPhoneNumbers.json?"
                     + urllib.parse.urlencode({"PhoneNumber": FROM}))
    if not nums.get("incoming_phone_numbers"):
        raise SystemExit(f"TWILIO_FROM_NUMBER {FROM[:-4]}**** is not a number on this Twilio account")
    num = nums["incoming_phone_numbers"][0]
    print(f"Twilio account ok; caller ID {FROM[:-4]}**** found (currently trunk: {num.get('trunk_sid') or 'none'})")
    domain = f"lk-bench-{secrets.token_hex(4)}.pstn.twilio.com"
    user, pwd = f"lkbench{secrets.token_hex(3)}", secrets.token_urlsafe(18) + "A1"
    print("\nPlan:")
    print(f"  Twilio: SIP trunk 'lk-bench', termination {domain}, credential list with user {user}")
    print(f"  Twilio: move {FROM[:-4]}**** onto the trunk")
    print(f"  LiveKit: outbound trunk -> {domain}, numbers [{FROM[:-4]}****]")
    print("  .env: BENCH_SIP_TRUNK_ID=<new id>")
    if not args.apply:
        print("\nDry run only. Re-run with --apply to create it.")
        return

    trunk = tw("POST", "https://trunking.twilio.com/v1/Trunks", {"FriendlyName": "lk-bench", "DomainName": domain})
    cl = tw("POST", f"https://api.twilio.com/2010-04-01/Accounts/{ACC}/SIP/CredentialLists.json", {"FriendlyName": "lk-bench"})
    tw("POST", f"https://api.twilio.com/2010-04-01/Accounts/{ACC}/SIP/CredentialLists/{cl['sid']}/Credentials.json",
       {"Username": user, "Password": pwd})
    tw("POST", f"https://trunking.twilio.com/v1/Trunks/{trunk['sid']}/CredentialLists", {"CredentialListSid": cl["sid"]})
    tw("POST", f"https://trunking.twilio.com/v1/Trunks/{trunk['sid']}/PhoneNumbers", {"PhoneNumberSid": num["sid"]})
    print(f"Twilio trunk {trunk['sid']} ready")

    async def lk() -> str:
        from livekit import api

        async with api.LiveKitAPI() as client:
            t = await client.sip.create_outbound_trunk(api.CreateSIPOutboundTrunkRequest(trunk=api.SIPOutboundTrunkInfo(
                name="lk-bench (Twilio)", address=domain, numbers=[FROM], auth_username=user, auth_password=pwd)))
            return t.sip_trunk_id

    tid = asyncio.run(lk())
    with (ROOT / ".env").open("a") as f:
        f.write(f"\nBENCH_SIP_TRUNK_ID={tid}\n")
    print(f"LiveKit outbound trunk {tid} ready; BENCH_SIP_TRUNK_ID written to .env")
    print("Next: allow the Gulf countries in Twilio's Voice geo permissions, then `bench run -s <phone stack> -c <scenario>`")


if __name__ == "__main__":
    main()
