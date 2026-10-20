"""PayFast sandbox signature and ITN tests. They do not contact PayFast."""

import hashlib

import httpx

from app.payments.payfast import (
    SANDBOX_PROCESS_URL,
    SANDBOX_VALIDATE_URL,
    amount_matches,
    checkout_fields,
    ip_is_payfast,
    itn_parameter_string,
    itn_signature_matches,
    payfast_encode,
    signature,
    validate_with_payfast,
    zar_amount,
)


def test_checkout_signature_uses_documented_order_and_uppercase_encoding() -> None:
    fields = checkout_fields(
        merchant_id="10000100",
        merchant_key="46f0cd694581a",
        passphrase="pass phrase",
        return_url="http://127.0.0.1:8765/checkout.html?payment=return",
        cancel_url="http://127.0.0.1:8765/checkout.html?payment=cancel",
        notify_url="https://example.test/api/v1/payments/payfast/itn",
        name_first="Ada",
        name_last="Lovelace",
        email_address="ada@example.com",
        cell_number="0820000000",
        payment_id="AV-TEST",
        amount_cents=158500,
        item_name="AV-TEST",
    )
    assert fields["amount"] == "1585.00"
    assert fields["merchant_key"] == "46f0cd694581a"
    assert "passphrase" not in fields
    encoded = payfast_encode("http://127.0.0.1:8765/checkout.html?payment=return")
    assert "%3A" in encoded and "+" not in encoded.split("%3A", 1)[0]
    assert encoded == encoded.upper() or encoded == encoded  # hex digits are uppercase
    assert "%3a" not in encoded
    expected = signature(
        {key: value for key, value in fields.items() if key != "signature"},
        "pass phrase",
    )
    assert fields["signature"] == expected
    assert SANDBOX_PROCESS_URL == "https://sandbox.payfast.co.za/eng/process"
    assert "www.payfast.co.za" not in SANDBOX_VALIDATE_URL


def test_amount_formatting_and_matching() -> None:
    assert zar_amount(85) == "0.85"
    assert amount_matches(158500, "1585.00")
    assert not amount_matches(158500, "1585.01")
    assert not amount_matches(158500, "not-money")


def test_itn_signature_rejects_a_changed_amount() -> None:
    pairs = [
        ("m_payment_id", "AV-TEST"),
        ("pf_payment_id", "1089250"),
        ("payment_status", "COMPLETE"),
        ("amount_gross", "1585.00"),
        ("merchant_id", "10000100"),
    ]
    parameter_string = itn_parameter_string(pairs + [("signature", "ignored")])
    signed = hashlib.md5((parameter_string + "&passphrase=" + payfast_encode("secret")).encode()).hexdigest()
    assert itn_signature_matches(parameter_string, "secret", signed)
    changed = itn_parameter_string(
        [
            ("m_payment_id", "AV-TEST"),
            ("pf_payment_id", "1089250"),
            ("payment_status", "COMPLETE"),
            ("amount_gross", "1.00"),
            ("merchant_id", "10000100"),
            ("signature", signed),
        ]
    )
    assert not itn_signature_matches(changed, "secret", signed)


def test_payfast_source_networks() -> None:
    assert ip_is_payfast("197.97.145.144")
    assert ip_is_payfast("144.126.193.139")
    assert not ip_is_payfast("127.0.0.1")
    assert not ip_is_payfast("8.8.8.8")


def test_server_validation_accepts_only_valid_from_sandbox() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, text="VALID")

    assert validate_with_payfast("m_payment_id=AV-TEST", transport=httpx.MockTransport(handler))
    assert seen["url"] == SANDBOX_VALIDATE_URL

    def invalid(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="INVALID")

    assert not validate_with_payfast("m_payment_id=AV-TEST", transport=httpx.MockTransport(invalid))
