from services.pii_scrubber import scrub_pii


def test_scrub_pii_masks_common_sensitive_values():
    text = "Contact test@example.com or 555-123-4567. SSN 123-45-6789."

    result = scrub_pii(text)

    assert "[REDACTED_EMAIL]" in result
    assert "[REDACTED_PHONE]" in result
    assert "[REDACTED_SSN]" in result
    assert "test@example.com" not in result
    assert "555-123-4567" not in result
    assert "123-45-6789" not in result


def test_scrub_pii_leaves_clean_text_unchanged():
    text = "Summarize Q1 operational risks."

    assert scrub_pii(text) == text


def test_scrub_pii_handles_empty_boundary_values():
    assert scrub_pii("") == ""
    assert scrub_pii(None) is None


def test_scrub_pii_masks_credit_card_boundary_pattern():
    result = scrub_pii("Payment reference 4111 1111 1111 1111 should not pass through.")

    assert "[REDACTED_CC]" in result
    assert "4111 1111 1111 1111" not in result
