"""해수 물성 계산 (UNESCO 1983, EOS-80).

수온과 염분을 함께 볼 때 필요한 어는점, 표층 밀도, 압력-수심 변환만 담았습니다.
검증값은 UNESCO Technical Papers in Marine Science 44 의 수치입니다.
"""

from __future__ import annotations

import math


def freezing_point_c(salinity: float, pressure_dbar: float = 0.0) -> float:
    """바닷물의 어는점(°C). Millero (1978)."""
    s = salinity
    return (-0.0575 + 1.710523e-3 * math.sqrt(s) - 2.154996e-4 * s) * s - 7.53e-4 * pressure_dbar


def density_surface(salinity: float, temperature_c: float) -> float:
    """대기압에서의 밀도(kg/m³). Millero & Poisson (1981)."""
    t, s = temperature_c, salinity
    rho_w = (
        999.842594
        + 6.793952e-2 * t
        - 9.095290e-3 * t**2
        + 1.001685e-4 * t**3
        - 1.120083e-6 * t**4
        + 6.536332e-9 * t**5
    )
    a = 8.24493e-1 - 4.0899e-3 * t + 7.6438e-5 * t**2 - 8.2467e-7 * t**3 + 5.3875e-9 * t**4
    b = -5.72466e-3 + 1.0227e-4 * t - 1.6546e-6 * t**2
    c = 4.8314e-4
    return rho_w + a * s + b * s**1.5 + c * s**2


def sigma_t(salinity: float, temperature_c: float) -> float:
    """밀도 이상값 σt = ρ(S, T, 0) - 1000. 깊은 층에서는 현장 온도 기준의 근사입니다."""
    return density_surface(salinity, temperature_c) - 1000.0


def depth_from_pressure(pressure_dbar: float, lat: float) -> float:
    """압력(dbar)을 수심(m)으로 변환합니다. Saunders & Fofonoff (1976)."""
    x = math.sin(math.radians(lat)) ** 2
    gravity = 9.780318 * (1.0 + (5.2788e-3 + 2.36e-5 * x) * x) + 1.092e-6 * pressure_dbar
    p = pressure_dbar
    return (((-1.82e-15 * p + 2.279e-10) * p - 2.2512e-5) * p + 9.72659) * p / gravity


def derive(temperature_c: float | None, salinity: float | None, pressure_dbar: float = 0.0) -> dict:
    """수온·염분이 모두 있을 때 파생값을 만듭니다. 없으면 None."""
    if salinity is None or salinity <= 0:
        return {"freezing_point_c": None, "sigma_t": None, "above_freezing_c": None}
    tf = freezing_point_c(salinity, pressure_dbar)
    if temperature_c is None:
        return {"freezing_point_c": round(tf, 3), "sigma_t": None, "above_freezing_c": None}
    return {
        "freezing_point_c": round(tf, 3),
        "sigma_t": round(sigma_t(salinity, temperature_c), 3),
        "above_freezing_c": round(temperature_c - tf, 3),
    }
