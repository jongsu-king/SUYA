"""기본 수집 지점. 사용자가 준 두 링크의 지점, 기지, 해역 대표 지점으로 구성합니다."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .i18n import get_language


@dataclass(frozen=True)
class Location:
    id: str
    name: str
    name_en: str
    lat: float
    lon: float
    group: str  # link | station | ocean

    def as_dict(self) -> dict:
        return asdict(self)


LOCATIONS: tuple[Location, ...] = (
    Location("link_nullschool", "nullschool 링크 지점", "nullschool link point", -80.012, 152.723, "link"),
    Location("link_windy", "Windy 링크 지점", "Windy link point", -67.052, -66.257, "link"),
    Location("king_sejong", "세종과학기지", "King Sejong Station", -62.223, -58.787, "station"),
    Location("jang_bogo", "장보고과학기지", "Jang Bogo Station", -74.625, 164.229, "station"),
    Location("south_pole", "아문센-스콧 (남극점)", "Amundsen-Scott (South Pole)", -89.99, 0.0, "station"),
    Location("mcmurdo", "맥머도", "McMurdo", -77.846, 166.676, "station"),
    Location("vostok", "보스토크", "Vostok", -78.464, 106.837, "station"),
    Location("concordia", "콩코르디아", "Concordia", -75.100, 123.333, "station"),
    Location("rothera", "로세라", "Rothera", -67.568, -68.127, "station"),
    Location("palmer", "파머", "Palmer", -64.774, -64.053, "station"),
    Location("neumayer", "노이마이어 III", "Neumayer III", -70.674, -8.274, "station"),
    Location("syowa", "쇼와", "Syowa", -69.004, 39.582, "station"),
    Location("davis", "데이비스", "Davis", -68.577, 77.968, "station"),
    Location("casey", "케이시", "Casey", -66.282, 110.527, "station"),
    Location("weddell", "웨델해", "Weddell Sea", -68.0, -40.0, "ocean"),
    Location("maud_rise", "모드 라이즈", "Maud Rise", -65.0, 3.0, "ocean"),
    Location("cosmonaut", "코스모넛해", "Cosmonaut Sea", -65.0, 45.0, "ocean"),
    Location("prydz", "프리즈만 앞바다", "Off Prydz Bay", -65.5, 75.0, "ocean"),
    Location("davis_sea", "데이비스해", "Davis Sea", -63.0, 95.0, "ocean"),
    Location("adelie", "아델리 해안 앞바다", "Off Adélie Coast", -64.5, 140.0, "ocean"),
    Location("ross", "로스해", "Ross Sea", -74.5, 178.0, "ocean"),
    Location("amundsen", "아문젠해", "Amundsen Sea", -71.5, -115.0, "ocean"),
    Location("bellingshausen", "벨링스하우젠해", "Bellingshausen Sea", -68.0, -85.0, "ocean"),
    Location("drake", "드레이크 해협", "Drake Passage", -60.0, -60.0, "ocean"),
)

LOCATION_BY_ID = {loc.id: loc for loc in LOCATIONS}
OCEAN_LOCATIONS = tuple(loc for loc in LOCATIONS if loc.group == "ocean")


def location_label(item: Location | dict) -> str:
    """현재 언어에 맞는 지점 이름."""
    if isinstance(item, dict):
        return item["name_en"] if get_language() == "en" else item["name"]
    return item.name_en if get_language() == "en" else item.name
