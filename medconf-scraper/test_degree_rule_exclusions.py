"""Adversarial review (2026-10-27): 7/26 non-degree titles were classed as degree."""
import pytest

from extractors import degree_rule

FALSE_POSITIVES = [
    "MSc Student Prize Lecture",
    "BSc Nursing Open Day",
    "PhD viva workshop",
    "Masters of Endoscopy Live 2027",
    "Advanced Certificate in Clinical Education: info session",
    "MPH Alumni networking evening",
    "Doctorate in Clinical Psychology interview day",
]


@pytest.mark.parametrize("t", FALSE_POSITIVES)
def test_not_degree(t):
    assert degree_rule.is_degree_title(t) is False


@pytest.mark.parametrize("t", ["MSc in Clinical Oncology", "Advanced Certificate in Clinical Education",
                               "Doctorate in Clinical Psychology", "Master's of Public Health"])
def test_real_degrees_still_degree(t):
    assert degree_rule.is_degree_title(t) is True
