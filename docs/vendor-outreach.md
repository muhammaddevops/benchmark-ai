# Getting a pilot agent from each vendor (bracket E)

Most Gulf voice-agent platforms are sales-only, so the phone-agent comparison starts with a short request. You send
it (your email or LinkedIn); nothing here is sent automatically. Self-serve platforms need you to sign up and paste
the brief yourself.

## What to ask each vendor for

1. **A test agent set up with our brief**, using their default Arabic voice and model. `bench brief <scenario>` prints
   it for each of the three scenarios (clinic booking, telecom bill dispute, declined bank card). Or a trial login so
   you can paste it in yourself.
2. **How to call it:** a SIP address (preferred: no phone network in the way) and/or a phone number, and which
   country the number is in.
3. **Buyer facts:** their price per minute for the AI agent, and the country where calls and data are processed.
4. **OK to be named** in a published comparison. Offer to share their own results with them first.

Before sending: the clinic brief lists slots on "Sunday 9 November" and "Tuesday 11 November", which are now in the
past. A platform that tells its agent today's date may refuse them. Decide whether to move the dates (the earlier
runs would then need re-running) or accept the risk.

## Message template

> **Subject:** Test agent for an independent Gulf Arabic voice AI benchmark
>
> Hi [name],
>
> I'm running an independent benchmark of voice AI agents for Gulf businesses choosing a vendor for their customer
> calls. Every agent takes the same three scripted calls from a Saudi customer who switches between Gulf Arabic,
> formal Arabic and English. Each call is scored on response time, replying in the caller's language, answer quality
> and whether the task gets done.
>
> I'd like to include [vendor]. Could you set up a test agent with the attached instructions (a clinic booking, a
> telecom bill dispute and a declined bank card), using your default Arabic voice and model, and send me:
>
> - a SIP address for the agent (preferred), or a phone number;
> - your per-minute price for the AI agent, and where calls and data are processed.
>
> I'll share [vendor]'s results with you before anything is published.
>
> [your name]

Attach the three briefs: `.venv/bin/python -m bench brief <scenario>` for `clinic_booking_codeswitch`,
`telecom_billing_gulf` and `bank_card_msa`.

## Who to ask (from `providers.yaml`)

| Vendor | Based in | Access | What you do |
|---|---|---|---|
| Nabrah | Riyadh | self-serve (app.nabrah.ai) | sign up, paste the briefs, take its number or SIP address |
| Hamsa | MENA | self-serve (agents.tryhamsa.com) | as Nabrah |
| Maqsam | Riyadh | sales | send the template |
| Unifonic | Riyadh | sales | send the template |
| Hams.AI | Riyadh | sales / demo | send the template |
| Sawt | Riyadh | sales | send the template |
| Wittify.ai | Riyadh | beta / sales | send the template |
| Dayl (Neurolab) | UAE | quote-based pilots | send the template |
| ZIWO | Dubai | demo / sales | send the template |
| Arabic.AI | Abu Dhabi / Dubai | enterprise sales | send the template (optional) |
| ElevenLabs Agents, Vapi, Retell | global | self-serve | sign up, paste the briefs |
| Synthflow, Bland | global | self-serve | only once their Arabic support is confirmed |

When an agent is ready: put its number in `.env` as `<X>_AGENT_NUMBER` (the `agent-<x>` stack already exists). For
a SIP address `sip:<user>@<host>`, add a LiveKit outbound trunk with address `<host>` (and the vendor's login, if
any), put its id in `.env` as `<X>_SIP_TRUNK_ID`, set the stack's `phone.trunk_env` to that name, and put `<user>` in
`<X>_AGENT_NUMBER`. Then
`.venv/bin/python -m bench run -s agent-<x> -c all`.
