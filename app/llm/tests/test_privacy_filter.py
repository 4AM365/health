"""
Privacy filter tests. Wargame W1 + W2 from docs/USER_FLOW.md.
"""

from __future__ import annotations

from app.llm.privacy import PrivacyFilter, screen_diagnostic_verbs


def test_rsid_blocked_canonical():
    f = PrivacyFilter()
    r = f.check("what does rs4988235 mean for me?")
    assert not r.ok
    assert any("rs" in m.lower() for m in r.matches)


def test_rsid_blocked_uppercase():
    f = PrivacyFilter()
    r = f.check("Looking up RS1801133")
    assert not r.ok


def test_rsid_blocked_underscored():
    f = PrivacyFilter()
    r = f.check("My r_s12345 results")
    assert not r.ok


def test_rsid_blocked_spaced():
    f = PrivacyFilter()
    r = f.check("Tell me about rs 4988235")
    assert not r.ok


def test_genotype_pair_blocked():
    f = PrivacyFilter()
    r = f.check("rs4988235 GG and rs1801133 CT — what do these mean?")
    assert not r.ok


def test_genotype_pair_lowercase():
    f = PrivacyFilter()
    r = f.check("My genotype: cc")  # near 'genotype' keyword
    assert not r.ok


def test_pasted_block_of_rsids_blocked():
    """Wargame W2 — exact scenario."""
    f = PrivacyFilter()
    payload = "rs4988235 GG\nrs1801133 CT\nrs7903146 TT"
    r = f.check(payload + "\n\nwhat do these mean?")
    assert not r.ok


def test_clean_text_passes():
    f = PrivacyFilter()
    r = f.check("How has my HDL been trending this year?")
    assert r.ok


def test_trait_question_passes():
    f = PrivacyFilter()
    r = f.check("What does my methylation trait look like?")
    assert r.ok


def test_pedigree_name_blocked_substring():
    """Wargame W1 — pedigree names never leave the process."""
    f = PrivacyFilter(pedigree_names=["mattie"])
    r = f.check("What does Mattie's GEDCOM say?")
    assert not r.ok


def test_pedigree_name_word_boundary():
    """Short names embedded in unrelated text should NOT trip."""
    f = PrivacyFilter(pedigree_names=["bob"])
    r = f.check("My carbohydrates went up")  # 'bob' not present
    assert r.ok


def test_pedigree_name_partial_word_no_match():
    """'mat' inside 'mathematics' should NOT trip — boundary required."""
    f = PrivacyFilter(pedigree_names=["mat"])
    # 'mat' is 3 chars so it loads; 'mathematics' contains 'mat' with a letter after,
    # so the boundary check rejects it.
    r = f.check("I'm reading about mathematics")
    assert r.ok


def test_screen_diagnostic_verbs():
    """W4 backstop."""
    assert screen_diagnostic_verbs("You have diabetes.")
    assert screen_diagnostic_verbs("You are diagnosed with celiac.")
    assert not screen_diagnostic_verbs("Your glucose is trending up.")
