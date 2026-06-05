"""Unit tests for scoring formulas."""

from src.scoring import (
    evidence_tier,
    realism_capexempt,
    realism_capsubject,
)


def test_capexempt_dampener_low_volume_low_realism():
    r = realism_capexempt(
        initial_approval_rate=0.95,
        initial_approvals=1,
        n_threshold=3,
        staffing_flag=False,
        layoff_penalty=0.0,
    )
    # 0.95 * (1/3) * 1 * 1 = 0.317
    assert 0.30 < r < 0.34


def test_capexempt_full_credit_at_threshold():
    r = realism_capexempt(
        initial_approval_rate=0.95,
        initial_approvals=3,
        n_threshold=3,
        staffing_flag=False,
        layoff_penalty=0.0,
    )
    assert 0.94 < r < 0.96


def test_capsubject_lottery_drag():
    """A high-approval-rate cap-subject sponsor still gets crushed by lottery."""
    r = realism_capsubject(
        initial_approval_rate=0.95,
        initial_approvals=100,
        pct_level_1=1.0,
        pct_level_2=0.0,
        pct_level_3=0.0,
        pct_level_4=0.0,
        n_threshold=10,
        wage_level_selection_rates={"1": 0.17, "2": 0.34, "3": 0.51, "4": 0.68},
        base_lottery_rate=0.35,
        staffing_flag=False,
        layoff_penalty=0.0,
    )
    # 0.95 * 0.17 * 1 = 0.16
    assert 0.14 < r < 0.18


def test_capsubject_level4_boosts_lottery():
    r_low = realism_capsubject(
        0.95, 100,
        pct_level_1=1.0, pct_level_2=0.0, pct_level_3=0.0, pct_level_4=0.0,
        n_threshold=10,
        wage_level_selection_rates={"1": 0.17, "2": 0.34, "3": 0.51, "4": 0.68},
        base_lottery_rate=0.35,
        staffing_flag=False, layoff_penalty=0.0,
    )
    r_high = realism_capsubject(
        0.95, 100,
        pct_level_1=0.0, pct_level_2=0.0, pct_level_3=0.0, pct_level_4=1.0,
        n_threshold=10,
        wage_level_selection_rates={"1": 0.17, "2": 0.34, "3": 0.51, "4": 0.68},
        base_lottery_rate=0.35,
        staffing_flag=False, layoff_penalty=0.0,
    )
    assert r_high > r_low * 3.5  # Level 4 ~4x Level 1


def test_capsubject_staffing_penalty():
    r = realism_capsubject(
        0.95, 100,
        pct_level_1=0.5, pct_level_2=0.5, pct_level_3=0.0, pct_level_4=0.0,
        n_threshold=10,
        wage_level_selection_rates={"1": 0.17, "2": 0.34, "3": 0.51, "4": 0.68},
        base_lottery_rate=0.35,
        staffing_flag=True, layoff_penalty=0.0,
    )
    r_no_staff = realism_capsubject(
        0.95, 100,
        pct_level_1=0.5, pct_level_2=0.5, pct_level_3=0.0, pct_level_4=0.0,
        n_threshold=10,
        wage_level_selection_rates={"1": 0.17, "2": 0.34, "3": 0.51, "4": 0.68},
        base_lottery_rate=0.35,
        staffing_flag=False, layoff_penalty=0.0,
    )
    # Staffing penalty is 70% reduction
    assert r < r_no_staff * 0.35


def test_evidence_tier():
    assert evidence_tier(50, 30) == "HIGH"
    assert evidence_tier(10, 5) == "MEDIUM"
    assert evidence_tier(1, None) == "LOW"
    assert evidence_tier(1, 0) == "LOW"
