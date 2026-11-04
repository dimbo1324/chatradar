import locale

import pytest

locale.setlocale(locale.LC_ALL, "C")
raise SystemExit(
    pytest.main(
        [
            "--lf",
            "-q",
            "--basetemp=../../audit_evidence/locale-check-temp",
            "--junitxml=../../audit_evidence/locale-check.xml",
        ]
    )
)
