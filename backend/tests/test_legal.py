"""Public legal pages stay draft and do not invent commercial promises."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGES = ("terms.html", "privacy.html", "shipping-and-returns.html")
BANNED = (
    "30-day",
    "14-day",
    "7-day",
    "money-back",
    "free delivery",
    "delivered within",
    "warranty period of",
    "we guarantee",
    "ISO 27001",
    "PayFast will",
    "tracking number is included on every",
)


def _page(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_legal_pages_are_drafts_with_placeholders() -> None:
    terms = _page("terms.html")
    privacy = _page("privacy.html")
    shipping = _page("shipping-and-returns.html")
    assert "v1.0-draft" in terms
    assert "v1.0-draft" in shipping
    assert "[Registered company name — to be confirmed]" in terms
    assert "[VAT number — to be confirmed]" in terms
    assert "ferdie@omniprod.co.za" in terms
    assert "010 010 0060" in terms
    assert "87 Piet Rautenbach St, Rosslyn, Akasia, 0200, South Africa" in terms
    assert "tel:0100100060" in terms
    assert "[Information officer — to be confirmed]" in privacy
    assert "[Retention period — to be confirmed]" in privacy
    assert "has not been confirmed" in terms
    assert "Consumer Protection Act" in terms
    assert "Protection of Personal Information Act" in privacy
    assert "stays unpaid until the payment provider verifies" in terms
    assert "sandbox" not in terms.lower()
    assert "simulated" not in terms.lower()
    for page in (terms, privacy, shipping):
        lowered = page.lower()
        for phrase in BANNED:
            assert phrase not in lowered
        assert 'name="viewport"' in page
        assert "site-footer" in page
        assert 'href="terms.html"' in page or page is terms
        assert 'href="privacy.html"' in page or page is privacy


def test_footer_and_checkout_link_to_the_legal_pages() -> None:
    for name in ("index.html", "checkout.html", "cart.html", "products.html", "product.html"):
        page = _page(name)
        assert 'href="terms.html"' in page or 'href="/terms.html"' in page
        assert 'href="privacy.html"' in page or 'href="/privacy.html"' in page
        assert 'href="shipping-and-returns.html"' in page or 'href="/shipping-and-returns.html"' in page
    checkout = _page("checkout.html")
    assert "I have read and agree to the" in checkout
    assert 'target="_blank"' in checkout
    assert 'name="accept_terms"' in checkout
    assert "v1.0-draft" in checkout
    script = (ROOT / "js" / "checkout.js").read_text(encoding="utf-8")
    assert "accept_terms: true" in script
    assert "Accept the Terms and Conditions before payment." in script
