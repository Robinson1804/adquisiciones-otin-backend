"""Tests for the 27-stage catalog (etapas_catalogo.py).

Sync strategy (APPLY-TIME RISK #2):
constants.ts is parsed via regex to extract cod values. If the file is
unreachable or the regex yields 0 results, the test falls back to a
hardcoded canonical list of 27 codes (E01..E25, E08a, E08b).
This is documented by design decision: CONTEXT.md §8 is the canonical source;
both backend catalog and frontend constants.ts derive from it.
"""
import re
from pathlib import Path

import pytest

from app.services.etapas_catalogo import (
    ETAPAS_CATALOGO,
    ORDEN_ETAPAS,
    get_etapa_spec,
    siguiente_etapa_registrable,
)

# ---------------------------------------------------------------------------
# Canonical 27 codes (hardcoded as sync fallback — mirrors CONTEXT.md §8)
# ---------------------------------------------------------------------------
_CANONICAL_CODES: list[str] = [
    "E01", "E02", "E03", "E04", "E05", "E06", "E07", "E08",
    "E08a", "E08b", "E09", "E10", "E11", "E12", "E13", "E14",
    "E15", "E16", "E17", "E18", "E19", "E20", "E21", "E22",
    "E23", "E24", "E25",
]

_EXPECTED_BUCLE: frozenset[str] = frozenset({"E05", "E06", "E08a", "E08b"})
_EXPECTED_POR_AREA: frozenset[str] = frozenset({"E01", "E11", "E24"})


# ---------------------------------------------------------------------------
# Basic catalog tests
# ---------------------------------------------------------------------------

def test_catalog_has_27_codes():
    assert len(ETAPAS_CATALOGO) == 27


def test_orden_etapas_has_27():
    assert len(ORDEN_ETAPAS) == 27


def test_orden_etapas_no_duplicates():
    assert len(set(ORDEN_ETAPAS)) == len(ORDEN_ETAPAS)


def test_bucle_flags():
    """es_bucle is True only for E05, E06, E08a, E08b."""
    actual = frozenset(c for c, s in ETAPAS_CATALOGO.items() if s.es_bucle)
    assert actual == _EXPECTED_BUCLE


def test_por_area_flags():
    """por_area is True only for E01, E11, E24."""
    actual = frozenset(c for c, s in ETAPAS_CATALOGO.items() if s.por_area)
    assert actual == _EXPECTED_POR_AREA


def test_prerequisitos_defined():
    """Key prerequisito chains from Design D1 are present."""
    assert "E01" in ETAPAS_CATALOGO["E02"].prerequisitos
    assert "E04" in ETAPAS_CATALOGO["E05"].prerequisitos
    assert "E04" in ETAPAS_CATALOGO["E06"].prerequisitos
    assert "E08" in ETAPAS_CATALOGO["E09"].prerequisitos
    assert "E11" in ETAPAS_CATALOGO["E12"].prerequisitos
    assert "E24" in ETAPAS_CATALOGO["E25"].prerequisitos


def test_e25_is_fin():
    assert ETAPAS_CATALOGO["E25"].es_fin is True


def test_e16_alerta_dias():
    assert ETAPAS_CATALOGO["E16"].alerta_dias == 20


def test_orden_etapas_matches_catalogo_keys():
    """ORDEN_ETAPAS must contain exactly the same codes as ETAPAS_CATALOGO."""
    assert set(ORDEN_ETAPAS) == set(ETAPAS_CATALOGO.keys())


def test_get_etapa_spec_known():
    spec = get_etapa_spec("E01")
    assert spec.cod == "E01"
    assert spec.por_area is True


def test_get_etapa_spec_unknown():
    with pytest.raises(KeyError):
        get_etapa_spec("E99")


def test_siguiente_etapa_registrable_empty():
    """No completed stages → first stage is next."""
    assert siguiente_etapa_registrable([]) == ORDEN_ETAPAS[0]


def test_siguiente_etapa_registrable_partial():
    """Skip already-completed codes."""
    completed = ORDEN_ETAPAS[:3]  # E01, E02, E03
    result = siguiente_etapa_registrable(completed)
    assert result == ORDEN_ETAPAS[3]


def test_siguiente_etapa_registrable_all_done():
    """All done → returns None."""
    result = siguiente_etapa_registrable(ORDEN_ETAPAS)
    assert result is None


# ---------------------------------------------------------------------------
# Sync test: backend catalog vs. frontend constants.ts (APPLY-TIME RISK #2)
#
# Strategy: parse frontend/src/lib/constants.ts via regex to extract cod
# values. If constants.ts is unreachable (wrong path, encoding issues, or
# parse yields 0 codes), fall back to the hardcoded canonical list and
# document the choice via a warning in the test output.
# ---------------------------------------------------------------------------

def _parse_constants_ts() -> list[str] | None:
    """Extract cod values from ETAPAS_CONFIG in constants.ts via regex.

    Returns list of codes if successful, None if file not found.
    The regex finds: { cod: 'E01',  ... (no TS parsing needed — pattern is stable)
    """
    candidates = [
        Path(__file__).parents[3] / "frontend" / "src" / "lib" / "constants.ts",
        Path(__file__).parents[2] / "frontend" / "src" / "lib" / "constants.ts",
    ]
    for path in candidates:
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8")
                codes = re.findall(r"cod:\s*'(E[0-9]{2,3}[ab]?)'", content)
                return codes if codes else None
            except Exception:
                return None
    return None


def test_catalogo_sincronizado():
    """Backend catalog codes match frontend ETAPAS_CONFIG codes.

    If constants.ts is not reachable, uses the hardcoded canonical list
    (derived from CONTEXT.md §8). This is the documented fallback:
    both files share CONTEXT §8 as source of truth.
    """
    fe_codes = _parse_constants_ts()

    if fe_codes is None:
        # Fallback: compare against hardcoded canonical list
        import warnings
        warnings.warn(
            "frontend/src/lib/constants.ts not found — using hardcoded canonical "
            "list for sync test. Both sources derive from CONTEXT.md §8.",
            stacklevel=2,
        )
        fe_codes = _CANONICAL_CODES

    be_codes = set(ETAPAS_CATALOGO.keys())
    fe_codes_set = set(fe_codes)

    missing_in_be = fe_codes_set - be_codes
    extra_in_be = be_codes - fe_codes_set

    assert not missing_in_be, f"Frontend codes missing in backend: {sorted(missing_in_be)}"
    assert not extra_in_be, f"Backend codes not in frontend: {sorted(extra_in_be)}"
    assert len(fe_codes) == 27, f"Expected 27 codes in frontend, got {len(fe_codes)}"


def test_catalogo_bucle_flags_sync():
    """Backend es_bucle flags match expected set (mirrors FE es_bucle: true entries)."""
    be_bucle = frozenset(c for c, s in ETAPAS_CATALOGO.items() if s.es_bucle)
    assert be_bucle == _EXPECTED_BUCLE


def test_catalogo_por_area_flags_sync():
    """Backend por_area flags match expected set (mirrors FE por_area: true entries)."""
    be_por_area = frozenset(c for c, s in ETAPAS_CATALOGO.items() if s.por_area)
    assert be_por_area == _EXPECTED_POR_AREA
