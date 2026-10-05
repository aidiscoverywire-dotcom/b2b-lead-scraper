"""Two-step email validation ONLY (blueprint 7.3).

Step 1: syntax via email-validator with check_deliverability=False
        (no DNS side-effects).
Step 2: MX lookup via dnspython with a strict 5-second timeout.

Result: 'valid' | 'invalid' | 'unknown'. NO SMTP mailbox probing — ever.
"""
import logging

# NOTE: dnspython and email-validator are imported lazily inside the functions
# below — they are only needed while a job validates emails, never at server
# startup.
log = logging.getLogger(__name__)

_MX_TIMEOUT = 5.0


def validate_email_format(email: str) -> bool:
    """Step 1 — syntax only."""
    from email_validator import EmailNotValidError, validate_email as _validate_syntax

    if not email or "@" not in email:
        return False
    try:
        _validate_syntax(email, check_deliverability=False)
        return True
    except EmailNotValidError:
        return False


def check_mx(domain: str) -> bool | None:
    """Step 2 — MX lookup. True = MX exists, False = no MX, None = unknown
    (timeout / DNS error)."""
    import dns.resolver

    if not domain:
        return False
    resolver = dns.resolver.Resolver()
    resolver.lifetime = _MX_TIMEOUT
    resolver.timeout = _MX_TIMEOUT
    try:
        answers = resolver.resolve(domain, "MX")
        return len(list(answers)) > 0
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return False
    except Exception as exc:  # timeout, NoNameservers, etc. -> unknown
        log.debug("MX lookup failed for %s: %s", domain, exc)
        return None


def validate_email(email: str) -> str:
    """Full 2-step validation -> 'valid' | 'invalid' | 'unknown'."""
    if not validate_email_format(email):
        return "invalid"
    domain = email.rsplit("@", 1)[-1].lower()
    mx = check_mx(domain)
    if mx is True:
        return "valid"
    if mx is False:
        return "invalid"
    return "unknown"
