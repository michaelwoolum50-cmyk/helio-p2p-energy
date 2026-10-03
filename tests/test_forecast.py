"""Forecast tests: determinism and physical sanity."""

from helio.forecast import (HouseholdProfile, forecast, make_profiles,
                            clear_sky_generation_kw)


def _profile():
    return HouseholdProfile(household_id="H0", pv_capacity_kw=5.0)


def test_forecast_is_deterministic():
    p = _profile()
    a = forecast(p, day_of_year=200, n_days=2, interval_hours=1.0, seed=7)
    b = forecast(p, day_of_year=200, n_days=2, interval_hours=1.0, seed=7)
    assert a.generation_kw == b.generation_kw
    assert a.demand_kw == b.demand_kw
    assert a.hours == b.hours


def test_different_seeds_give_different_clouds():
    p = _profile()
    a = forecast(p, day_of_year=200, n_days=2, interval_hours=1.0, seed=7)
    b = forecast(p, day_of_year=200, n_days=2, interval_hours=1.0, seed=8)
    assert a.generation_kw != b.generation_kw


def test_no_generation_at_night():
    p = _profile()
    for hour in (0, 1, 2, 22, 23):
        assert clear_sky_generation_kw(p, 200, hour) == 0.0


def test_midday_generation_positive_and_capped():
    p = _profile()
    gen = clear_sky_generation_kw(p, 200, 12.0)
    assert 0.0 < gen <= p.pv_capacity_kw


def test_demand_has_evening_peak_above_night():
    p = _profile()
    import random
    rng = random.Random(1)
    evening = sum(_demand(p, 19.0, rng) for _ in range(20)) / 20
    night = sum(_demand(p, 3.0, rng) for _ in range(20)) / 20
    assert evening > night


def _demand(profile, hour, rng):
    from helio.forecast import household_demand_kw
    return household_demand_kw(profile, hour, rng)


def test_make_profiles_deterministic_and_diverse():
    a = make_profiles(6, seed=42)
    b = make_profiles(6, seed=42)
    assert [p.pv_capacity_kw for p in a] == [p.pv_capacity_kw for p in b]
    assert len({p.pv_capacity_kw for p in a}) > 1  # households differ


def test_series_length_matches_window():
    f = forecast(_profile(), day_of_year=200, n_days=3,
                 interval_hours=0.5, seed=3)
    assert len(f.generation_kw) == 3 * 24 * 2
    assert len(f.surplus_kw) == len(f.generation_kw)
