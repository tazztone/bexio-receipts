from bexio_receipts.extraction import clean_vat_snippet, validate_vat_snippet


def test_clean_vat_snippet_html():
    snippet = "<table><tr><td>8.1%</td><td>10.00</td></tr></table>"
    # HTML tables should be returned as-is (stripped)
    assert clean_vat_snippet(snippet) == snippet


def test_clean_vat_snippet_strip_summary_lines():
    snippet = """8.1% 10.00 0.81
Total 10.81
Summe 10.81
MWST inkl 0.81
2.6% 5.00 0.13
Endbetrag 15.94"""
    cleaned = clean_vat_snippet(snippet)
    expected = "8.1% 10.00 0.81\n2.6% 5.00 0.13"
    assert cleaned == expected


def test_clean_vat_snippet_case_insensitive_and_whitespace():
    snippet = "  total 10.81  \n  8.1% 10.00  "
    # Note: the current implementation does line.strip() before matching STRIP_LINES
    # but the STRIP_LINES regex itself uses ^ which matches start of string/line.
    # Actually, clean_vat_snippet does: if not STRIP_LINES.match(line.strip()):
    # so leading whitespace in the original line is removed before matching.
    assert clean_vat_snippet(snippet) == "8.1% 10.00"


def test_clean_vat_snippet_complex_keywords():
    snippet = """Zusammenfassung 8.1%
8.1% 100.00 8.10
Sie sparen 5.00
Netto 100.00
MWST exkl 8.10
Rundungsdifferenz 0.01"""
    cleaned = clean_vat_snippet(snippet)
    assert cleaned == "8.1% 100.00 8.10"


def test_clean_vat_snippet_empty():
    assert clean_vat_snippet("") == ""
    assert clean_vat_snippet("   ") == ""


def test_validate_vat_snippet_valid_html():
    snippet = "<table><tr><td>8.1%</td><td>10.00</td></tr></table>"
    assert validate_vat_snippet(snippet) is None


def test_validate_vat_snippet_html_no_numbers():
    snippet = "<table><tr><td>No numbers</td></tr></table>"
    assert (
        validate_vat_snippet(snippet) == "Table present but contains no numeric values"
    )


def test_validate_vat_snippet_valid_markdown():
    snippet = "| Rate | Base | VAT |\n|---|---|---|\n| 8.1% | 10.00 | 0.81 |"
    assert validate_vat_snippet(snippet) is None


def test_validate_vat_snippet_markdown_no_numbers():
    snippet = "| Rate | Base | VAT |\n|---|---|---|\n| % | | |"
    assert (
        validate_vat_snippet(snippet) == "Table present but contains no numeric values"
    )


def test_validate_vat_snippet_valid_plain_text():
    # At least one line with 2+ numeric tokens
    snippet = "8.1% 10.00 0.81"
    assert validate_vat_snippet(snippet) is None


def test_validate_vat_snippet_invalid_vertical_extraction():
    # Only one number per line
    snippet = "8.1%\n10.00\n0.81"
    assert "No line has 2+ numeric tokens" in validate_vat_snippet(snippet)


def test_validate_vat_snippet_no_numbers_at_all():
    snippet = "Just some text without numbers"
    assert "No line has 2+ numeric tokens" in validate_vat_snippet(snippet)
