"""바닷물의 이온 조성 환산 (기준 조성, Millero 외 2008).

바닷물에 녹은 주요 이온의 비율은 어느 바다에서나 거의 같아서, 실용 염분 한 값에서 이온별 양을 환산할 수 있습니다.
기준 염분 S_R = (35.16504 / 35) × S_P [g/kg] 에 기준 조성의 질량 분율을 곱하면 이온별 g/kg 가 되고,
몰질량으로 나누면 mmol/kg 가 됩니다. 질량 분율과 몰질량은 Millero, Feistel, Wright, McDougall (2008),
Deep-Sea Research I 55, 50–72 의 기준 조성 수치입니다. 단위의 kg 은 바닷물 1 kg 입니다.

여기서 나오는 값은 측정값이 아니라 환산값입니다. 실제 바닷물의 조성은 기준 조성과 조금 다르고,
해빙 주변의 브라인이나 강물이 섞이는 곳에서는 비율 자체가 달라질 수 있습니다. 탄산·붕산 계열 성분은
표준 조건의 기준 조성 값이며 수온과 pH 에 따른 실제 화학종 분포를 따르지 않습니다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import seawater

METHOD = "millero2008-rc/1"
REFERENCE_SALINITY_AT_35 = 35.16504
REFERENCE_SALINITY_FACTOR = REFERENCE_SALINITY_AT_35 / 35.0
CHLORINITY_FACTOR = 1.80655
VOLUME_TEMPERATURE_C = (-3.0, 40.0)
VOLUME_SALINITY_MAX = 42.0
"""부피 기준 환산에 쓰는 1기압 밀도 식(Millero & Poisson 1981)의 범위. 식은 -2…40 °C, 염분 0…42 에서 맞춘 것이고
과냉각된 물만 조금 더 받습니다."""


@dataclass(frozen=True)
class Component:
    """기준 조성의 성분 하나. mass_fraction 은 녹은 염 전체 질량에서 차지하는 몫입니다."""

    key: str
    symbol: str
    name: str
    mass_fraction: float
    molar_mass: float
    charge: int

    @property
    def grams_per_salinity(self) -> float:
        """실용 염분 1 당 g/kg."""
        return self.mass_fraction * REFERENCE_SALINITY_FACTOR

    @property
    def mmol_per_salinity(self) -> float:
        """실용 염분 1 당 mmol/kg."""
        return self.grams_per_salinity / self.molar_mass * 1000.0


COMPONENTS: tuple[Component, ...] = (
    Component("chloride", "Cl⁻", "염화 이온", 0.5503396, 35.453, -1),
    Component("sodium", "Na⁺", "나트륨 이온", 0.3065958, 22.98977, 1),
    Component("sulfate", "SO₄²⁻", "황산 이온", 0.0771319, 96.0626, -2),
    Component("magnesium", "Mg²⁺", "마그네슘 이온", 0.0365055, 24.305, 2),
    Component("calcium", "Ca²⁺", "칼슘 이온", 0.0117186, 40.078, 2),
    Component("potassium", "K⁺", "칼륨 이온", 0.0113495, 39.0983, 1),
    Component("bicarbonate", "HCO₃⁻", "탄산수소 이온", 0.0029805, 61.0168, -1),
    Component("bromide", "Br⁻", "브롬화 이온", 0.0019134, 79.904, -1),
    Component("boric_acid", "B(OH)₃", "붕산", 0.0005527, 61.833, 0),
    Component("carbonate", "CO₃²⁻", "탄산 이온", 0.0004078, 60.0089, -2),
    Component("strontium", "Sr²⁺", "스트론튬 이온", 0.0002260, 87.62, 2),
    Component("borate", "B(OH)₄⁻", "붕산 이온", 0.0002259, 78.8404, -1),
    Component("fluoride", "F⁻", "플루오린화 이온", 0.0000369, 18.9984, -1),
    Component("hydroxide", "OH⁻", "수산화 이온", 0.0000038, 17.0073, -1),
    Component("carbon_dioxide", "CO₂", "이산화 탄소", 0.0000121, 44.0095, 0),
)

MAJOR: tuple[Component, ...] = COMPONENTS[:8]
"""DB 와 엑셀에 쌓는 성분. 녹은 염 질량의 99.85 % 입니다."""

BY_KEY: dict[str, Component] = {component.key: component for component in COMPONENTS}


def usable(salinity: float | None) -> bool:
    """환산할 수 있는 염분인지. 없는 값, 0 이하, 유한하지 않은 값은 쓰지 않습니다."""
    if salinity is None or isinstance(salinity, bool):
        return False
    try:
        value = float(salinity)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and value > 0.0


def reference_salinity(salinity: float | None) -> float | None:
    """기준 염분 S_R (g/kg). 실용 염분 35 가 35.16504 g/kg 입니다."""
    if not usable(salinity):
        return None
    return float(salinity) * REFERENCE_SALINITY_FACTOR


def grams_per_kg(salinity: float | None, components: tuple[Component, ...] = COMPONENTS) -> dict[str, float]:
    """성분별 g/kg. 환산할 수 없는 염분이면 빈 dict 입니다."""
    if not usable(salinity):
        return {}
    value = float(salinity)
    return {component.key: value * component.grams_per_salinity for component in components}


def mmol_per_kg(salinity: float | None, components: tuple[Component, ...] = COMPONENTS) -> dict[str, float]:
    """성분별 mmol/kg. 환산할 수 없는 염분이면 빈 dict 입니다."""
    if not usable(salinity):
        return {}
    value = float(salinity)
    return {component.key: value * component.mmol_per_salinity for component in components}


def chlorinity(salinity: float | None) -> float | None:
    """염소량 Cl = S_P / 1.80655 (g/kg). 염화 이온의 질량과는 다른 양입니다."""
    if not usable(salinity):
        return None
    return float(salinity) / CHLORINITY_FACTOR


def ionic_strength(salinity: float | None) -> float | None:
    """이온 세기 I = ½ Σ m z² (mol/kg-물). 실용 염분 35 에서 0.7226 입니다."""
    if not usable(salinity):
        return None
    value = float(salinity)
    per_kg_seawater = 0.5 * sum(value * c.mmol_per_salinity / 1000.0 * c.charge**2 for c in COMPONENTS)
    water_fraction = 1.0 - value * REFERENCE_SALINITY_FACTOR / 1000.0
    if water_fraction <= 0.0:
        return None
    return per_kg_seawater / water_fraction


def volume_basis(
    salinity: float | None, temperature_c: float | None, components: tuple[Component, ...] = MAJOR
) -> dict | None:
    """부피 기준 환산: 1기압 밀도(kg/m³)와 성분별 mmol/L. 수온이 없거나 밀도 식의 범위 밖이면 None 입니다.

    mmol/L = mmol/kg × 밀도 / 1000 입니다. 밀도는 그 수온과 염분에서 대기압일 때의 값이라 현장 압력은 들어가지
    않습니다. 깊은 물의 실제 밀도는 이보다 큽니다(1000 m 에서 0.4 % 남짓).
    """
    if not usable(salinity) or temperature_c is None or isinstance(temperature_c, bool):
        return None
    try:
        value, temperature = float(salinity), float(temperature_c)
    except (TypeError, ValueError):
        return None
    low, high = VOLUME_TEMPERATURE_C
    if not math.isfinite(temperature) or not low <= temperature <= high or value > VOLUME_SALINITY_MAX:
        return None
    density = seawater.density_surface(value, temperature)
    return {
        "temperature_c": temperature,
        "density_kg_m3": density,
        "mmol_per_l": {
            component.key: seawater.molar_per_litre(value * component.mmol_per_salinity, density)
            for component in components
        },
    }


def derive(salinity: float | None, temperature_c: float | None = None) -> dict | None:
    """화면과 내보내기에 쓰는 환산 결과 한 묶음. 환산할 수 없는 염분이면 None 입니다.

    수온을 함께 주고 그 값으로 밀도를 낼 수 있으면 1기압 밀도와 성분별 mmol/L 을 더합니다.
    """
    if not usable(salinity):
        return None
    value = float(salinity)
    result = {
        "practical_salinity": value,
        "reference_salinity": reference_salinity(value),
        "chlorinity": chlorinity(value),
        "ionic_strength": ionic_strength(value),
        "method": METHOD,
        "ions": [
            {
                "key": component.key,
                "symbol": component.symbol,
                "name": component.name,
                "charge": component.charge,
                "g_per_kg": value * component.grams_per_salinity,
                "mmol_per_kg": value * component.mmol_per_salinity,
                "mass_percent": component.mass_fraction * 100.0,
            }
            for component in COMPONENTS
        ],
    }
    volume = volume_basis(value, temperature_c, COMPONENTS)
    if volume is not None:
        result["temperature_c"] = volume["temperature_c"]
        result["density_kg_m3"] = volume["density_kg_m3"]
        for ion in result["ions"]:
            ion["mmol_per_l"] = volume["mmol_per_l"][ion["key"]]
    return result
