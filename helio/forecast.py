"""Solar generation forecasting and household demand profiles.

Models (all deterministic given a seed):
  - Clear-sky solar generation: a solar-geometry model computes the sun's
    elevation from day-of-year, latitude, and hour, then converts to
    plane-of-array irradiance. A seeded cloud-cover process multiplies the
    clear-sky output by a smooth random factor in [0.25, 1.0].
  - Household demand: a base load plus Gaussian morning, midday (home-office
    archetype), and evening peaks, with seeded per-household variation and
    small measurement noise. Some households are pure consumers (no PV).

Nothing here reads meters or weather APIs — every input is simulated.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import List

# Solar constant-ish peak irradiance on a tilted residential roof (W/m^2).
PEAK_IRRADIANCE_W_M2 = 1000.0


@dataclass
class HouseholdProfile:
    """Static characteristics of one household.

    Attributes:
        household_id: Stable identifier, e.g. "H0".
        pv_capacity_kw: Nameplate rooftop PV capacity in kW.
        latitude_deg: Latitude used by the solar-geometry model.
        base_load_kw: Always-on background load in kW.
        morning_peak_kw: Extra load around 07:30.
        evening_peak_kw: Extra load around 19:00.
        peak_jitter: Fractional household-to-household variation of peaks.
    """

    household_id: str
    pv_capacity_kw: float
    latitude_deg: float = 39.7  # ~Peru, Indiana
    base_load_kw: float = 0.35
    morning_peak_kw: float = 0.9
    evening_peak_kw: float = 1.6
    midday_peak_kw: float = 0.0      # extra load ~13:00 (home-office archetype)
    peak_jitter: float = 0.25
    azimuth_shift_h: float = 0.0    # roof orientation: - = east-facing
                                    # (earlier peak), + = west-facing (later)


@dataclass
class ForecastResult:
    """Per-interval forecast for one household over the simulation window."""

    household_id: str
    hours: List[float]                      # absolute hour index since sim start
    generation_kw: List[float] = field(default_factory=list)
    demand_kw: List[float] = field(default_factory=list)

    @property
    def surplus_kw(self) -> List[float]:
        """Positive entries mean surplus generation; negative mean deficit."""
        return [g - d for g, d in zip(self.generation_kw, self.demand_kw)]


def _solar_elevation_sin(day_of_year: int, hour: float, latitude_deg: float) -> float:
    """Sine of the solar elevation angle (Cooper's declination model)."""
    lat = math.radians(latitude_deg)
    decl = math.radians(-23.44) * math.cos(math.radians(360.0 / 365.0 * (day_of_year + 10)))
    hour_angle = math.radians(15.0 * (hour - 12.0))
    sin_elev = (math.sin(lat) * math.sin(decl)
                + math.cos(lat) * math.cos(decl) * math.cos(hour_angle))
    return max(0.0, sin_elev)


def clear_sky_generation_kw(profile: HouseholdProfile, day_of_year: int,
                            hour: float) -> float:
    """Clear-sky PV output in kW (no clouds, deterministic physics).

    `azimuth_shift_h` shifts solar noon to model east/west-facing roofs.
    """
    sin_elev = _solar_elevation_sin(day_of_year, hour - profile.azimuth_shift_h,
                                    profile.latitude_deg)
    # Mildly nonlinear response at low sun, capped at nameplate.
    capacity_factor = min(1.0, sin_elev ** 1.15)
    return profile.pv_capacity_kw * capacity_factor


def household_demand_kw(profile: HouseholdProfile, hour: float, rng: random.Random) -> float:
    """Simulated instantaneous demand in kW at a given hour of day."""
    def gauss(center: float, width: float) -> float:
        return math.exp(-((hour - center) ** 2) / (2 * width ** 2))

    morning = profile.morning_peak_kw * gauss(7.5, 1.1)
    evening = profile.evening_peak_kw * gauss(19.0, 1.8)
    midday = profile.midday_peak_kw * gauss(13.0, 1.5)
    jitter = 1.0 + rng.uniform(-profile.peak_jitter, profile.peak_jitter) * 0.2
    noise = rng.gauss(0.0, 0.05)
    return max(0.05, (profile.base_load_kw + morning + midday + evening)
                 * jitter + noise)


def make_profiles(n_households: int, seed: int) -> List[HouseholdProfile]:
    """Generate diverse household profiles deterministically from a seed.

    Archetypes (seeded): standard prosumer, east/west-facing roofs, pure
    consumers (no PV — they only ever bid), and home-office households with
    a midday demand peak.
    """
    rng = random.Random(seed)
    profiles = []
    for i in range(n_households):
        roll = rng.random()
        pv_kw = round(rng.uniform(2.5, 7.5), 2)
        azimuth = 0.0
        midday = 0.0
        if roll < 0.25:
            pv_kw = 0.0                                     # pure consumer
        elif roll < 0.45:
            azimuth = round(rng.uniform(-2.0, -0.5), 1)      # east-facing
        elif roll < 0.65:
            azimuth = round(rng.uniform(0.5, 2.0), 1)        # west-facing
        elif roll < 0.80:
            midday = round(rng.uniform(0.6, 1.5), 2)         # home-office
        profiles.append(HouseholdProfile(
            household_id=f"H{i}",
            pv_capacity_kw=pv_kw,
            base_load_kw=round(rng.uniform(0.25, 0.55), 2),
            morning_peak_kw=round(rng.uniform(0.4, 1.4), 2),
            evening_peak_kw=round(rng.uniform(0.8, 2.4), 2),
            midday_peak_kw=midday,
            azimuth_shift_h=azimuth,
        ))
    return profiles


def forecast(profile: HouseholdProfile, day_of_year: int, n_days: int,
             interval_hours: float, seed: int) -> ForecastResult:
    """Full-window generation/demand forecast for one household.

    Deterministic: identical (profile, day_of_year, n_days, interval_hours,
    seed) always yields identical output.

    Cloud model: a smooth random-walk cloud-cover factor in [0.25, 1.0] that
    changes slowly (updates each interval, mean-reverting), multiplying the
    clear-sky generation.
    """
    rng = random.Random(seed)
    n = int(n_days * 24 / interval_hours)
    result = ForecastResult(household_id=profile.household_id, hours=[])

    cloud = rng.uniform(0.7, 1.0)  # 1.0 = perfectly clear
    for step in range(n):
        abs_hour = step * interval_hours
        hour_of_day = abs_hour % 24
        day = day_of_year + int(abs_hour // 24)

        # Mean-reverting smooth cloud random walk.
        cloud += rng.gauss(0.0, 0.08)
        cloud += (0.8 - cloud) * 0.05
        cloud = min(1.0, max(0.25, cloud))

        gen = clear_sky_generation_kw(profile, day, hour_of_day) * cloud
        dem = household_demand_kw(profile, hour_of_day, rng)

        result.hours.append(abs_hour)
        result.generation_kw.append(round(gen, 4))
        result.demand_kw.append(round(dem, 4))
    return result
