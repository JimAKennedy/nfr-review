---
name: test-data-pii
description: Reserved PII ranges for test fixtures — emails, phones, IPs, names, addresses, cards, SSNs, dates, domains. Use when creating or reviewing test data that contains personally identifiable information to avoid legal risk from accidental real-person matches.
---

# Test Data PII — Reserved Ranges

When tests need realistic-looking personally identifiable information, use only values from
officially reserved or fictional ranges. These are structurally impossible to belong to a
real person, eliminating legal exposure.

**Hard rule:** Never invent plausible PII. Always use the reserved ranges below.

## Quick Reference

| Data type | Reserved / fictional range | Source |
|-----------|---------------------------|--------|
| **Email** | `@example.com`, `@example.org`, `@example.net` | RFC 2606 |
| **Domain** | `example.com`, `example.org`, `example.net`, `*.test`, `*.example`, `*.invalid`, `*.localhost` | RFC 2606 / RFC 6761 |
| **IPv4** | `192.0.2.0/24` (TEST-NET-1), `198.51.100.0/24` (TEST-NET-2), `203.0.113.0/24` (TEST-NET-3) | RFC 5737 |
| **IPv6** | `2001:db8::/32` | RFC 3849 |
| **Phone (US)** | `+1-555-0100` through `+1-555-0199` (any area code) | NANPA 555 range |
| **Phone (UK)** | `+44 7700 900000` through `+44 7700 900999` | Ofcom drama/test range |
| **Phone (AU)** | `+61 491 570 006` through `+61 491 570 009` | ACMA test range |
| **SSN (US)** | `987-65-4320` through `987-65-4329`, or area `000`/`666`/`900-999` | SSA reserved ranges |
| **Credit card** | Stripe test: `4242 4242 4242 4242` (Visa), `5555 5555 5555 4444` (MC) | Stripe docs / Luhn-valid but non-routable |
| **Person names** | Use obviously fictional names: `Alice Testworth`, `Bob Exampleson`, `Jane Doe-Test` | Convention — avoid common real names |
| **Addresses** | Combine with reserved domains/fictional city names, or use `123 Test Street, Exampleville` | Convention |
| **Dates of birth** | Use dates far in the future (`2099-01-01`) or well-known fictional dates | Convention |
| **MAC address** | `00:00:5E:00:53:xx` (documentation range) | RFC 7042 |
| **ASN** | `64496-64511` (documentation), `65536-65551` | RFC 5398 |

## Examples

```python
# Good - reserved ranges
TEST_EMAIL = "alice@example.com"
TEST_IP = "192.0.2.42"
TEST_PHONE = "+1-555-0100"
TEST_SSN = "987-65-4320"
TEST_CARD = "4242424242424242"
TEST_DOMAIN = "api.example.com"
```

## Prohibited Values

Any SSN, credit card number, phone number, email address, or other PII value that does not
come from the reserved/fictional ranges listed above must never appear in the codebase —
not in test fixtures, not in documentation examples, not in code comments. Values that look
realistic but fall outside the reserved ranges risk matching a real person's data, creating
legal exposure even when the match is coincidental. The HYG-PRV-001 scanner enforces this
automatically: it flags non-reserved SSNs and non-test credit card numbers regardless of
where they appear.

## When This Skill Applies

- Writing or reviewing any test fixture, conftest, parametrize data, or sample data file
- Creating fixture repos with example configuration (Dockerfiles, K8s manifests, CI configs)
- Writing documentation examples that include PII-like values
- Building mock/stub responses that return user data

## Edge Cases

- **Git commit metadata in fixtures:** Use `test@example.com` for author email
- **API keys / tokens:** Use obviously fake prefixes like `sk-test-xxxx` or `FAKE-API-KEY-xxxx`
- **UUIDs:** Generate real v4 UUIDs — they're random and not PII
- **Passwords in test harnesses:** Use `P@ssw0rd-test-only` or similar; never use real passwords even in tests
