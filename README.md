# review-collector

[![tests](https://github.com/SamruddhBorker/review-collector/actions/workflows/tests.yml/badge.svg)](https://github.com/SamruddhBorker/review-collector/actions/workflows/tests.yml)

Politely ask your customers for **honest** Google reviews, a few hours after
their visit, by WhatsApp or email. Built for cafés, salons, clinics and
guesthouses that have great customers but few reviews.

**The problem:** happy customers rarely think to leave a review, so good small
businesses look less popular than they are. A short, well-timed message fixes that.

- Python 3.9+, **standard library only**, SQLite storage
- `console` mode prints messages instead of sending, so you can test safely

## Quick start

1. Find your Google **Place ID** (Google's Place ID Finder) and put it in `config.json` as `google_place_id`
2. Add customers **who agreed to be contacted**:

```bash
python collect.py add --name "Priya Naik" --phone 98765 43210 --visit "2026-11-18 13:00" --consent
python collect.py import visits.csv          # name,phone,email,visit,consent  (consent must be "yes")
python collect.py run --dry-run              # preview who would be messaged right now
python collect.py run                        # send; schedule it every 30 minutes
python collect.py reviewed 3                 # they reviewed: stop asking
python collect.py optout 919876543210        # they replied STOP (phone, email or id)
python collect.py feedback 3 "Service was slow"
python collect.py report
```

## What it does (and refuses to do)

**Does**
- Waits a few hours after the visit (default 3 h), respects quiet hours (default 8 pm to 10 am)
- Sends **one** follow-up after 3 days, then **never** contacts that person again
- Skips anyone who opted out or already reviewed, and anyone whose visit is over 14 days old
- Retries failed sends; never double-sends
- Shows how many people reviewed after being asked

**Refuses**
- **No consent, no customer.** The database itself rejects anyone without consent
- **No review gating.** Everyone gets the *same* message with the *same* public review
  link. The tool never asks for a rating first and then sends only happy customers to Google.
  That practice violates Google's review policies, and consumer-protection rules
  in several countries treat it as misleading
- **STOP is mandatory.** Every message template must include a way to opt out and the
  review link, or the tool won't run
- Private feedback is offered to *everyone* ("reply to tell us privately") alongside the public link

## Channels

| Channel | Needs |
|---|---|
| `console` | nothing (prints) |
| `whatsapp` | `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID` in `.env` |
| `email` | `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD` in `.env` |

> **WhatsApp rule:** a business may only start a conversation with an approved
> *template* message. Create and get a template approved in Meta Business Manager
> before using WhatsApp for first contact at scale. Email works without that.

Never offer discounts or gifts in exchange for reviews: that's also against Google's policy.

## Honest limits

- It can't see whether someone actually left a review (Google doesn't allow that); mark
  them with `reviewed` by hand when you spot one
- Replies to WhatsApp messages land in your WhatsApp inbox, not in this tool; log
  `STOP` replies with `optout` and feedback with `feedback`
- You are responsible for having genuine consent and following your local laws (for India, the DPDP Act)

## Layout

| File | Role |
|---|---|
| `collect.py` | command-line interface |
| `engine.py` | scheduling, templates, safety rules, report |
| `senders.py` | console, WhatsApp, email |
| `store.py` | SQLite storage |

## Tests

```bash
python -m unittest -v
```

## License

MIT
