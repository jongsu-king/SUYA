"""SUYA — Antarctic Ocean Monitor. 남극해 수온·염분·기온 실시간 수집 프로그램.

Copyright (c) 2026 Jongsu Lim <imjongsu1102@gmail.com> and Suyeon Park <dbsnt110@inu.ac.kr>,
Incheon National University. MIT License, see LICENSE.
"""

__version__ = "0.1.2"
__app_name__ = "SUYA"
__author__ = "Jongsu Lim"
__email__ = "imjongsu1102@gmail.com"
__license__ = "MIT"
__url__ = "https://github.com/jongsu-king/SUYA"
__concept_doi__ = "10.5281/zenodo.23937852"

AUTHORS = (
    {
        "name": "Jongsu Lim",
        "name_ko": "임종수",
        "email": "imjongsu1102@gmail.com",
        "affiliation": (
            "Undergraduate Researcher, Hybrid Materials & Optoelectronics Laboratory (HMOL), "
            "Department of Physics, Incheon National University"
        ),
        "affiliation_ko": "인천대학교 물리학과 학부연구생, Hybrid Materials & Optoelectronics Laboratory (HMOL)",
        "orcid": "0009-0000-3395-1484",
        "url": "https://sites.google.com/view/h-mol",
    },
    {
        "name": "Suyeon Park",
        "name_ko": "박수연",
        "email": "dbsnt110@inu.ac.kr",
        "affiliation": (
            "M.S. Student, Clean Energy and Materials Lab (CELLMATE), "
            "Department of Materials Science and Engineering, Incheon National University"
        ),
        "affiliation_ko": "인천대학교 신소재공학과 석사과정, Clean Energy and Materials Lab (CELLMATE)",
        "orcid": "",
        "url": "https://cellmate.inu.ac.kr/",
    },
)
__copyright__ = "Copyright (c) 2026 " + " and ".join(a["name"] for a in AUTHORS)
