"""Catálogo de las 27 etapas del flujo de adquisición TIC.

Config en código (dict Python frozen dataclasses). Espeja 1:1 a
ETAPAS_CONFIG de frontend/src/lib/constants.ts — ambos derivan de CONTEXT.md §8.

Sin dependencias de BD ni I/O: importable en cualquier contexto (tests, scripts).

Decisión de diseño (D1): NO tabla DB. Estático, versionado, testeable; las 27 filas
cambian solo con deploy de código → no overhead de seed/migración/sincronía.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EtapaSpec:
    cod: str
    orden: int
    area_responsable: str
    nombre: str
    campos_extra: tuple[str, ...] = ()
    es_bucle: bool = False
    por_area: bool = False
    es_fin: bool = False
    prerequisitos: tuple[str, ...] = ()
    alerta_dias: int | None = None


# ---------------------------------------------------------------------------
# Catálogo canónico — 27 entradas (E01..E25 + E08a + E08b)
# Prerequisitos clave (Design D1): E02←E01, E05/E06←E04, E09←E08,
#   E12←E11, E25←E24. Los prerequisitos genéricos se validan en C3b
#   (validaciones.py); aquí solo se definen.
# ---------------------------------------------------------------------------

ETAPAS_CATALOGO: dict[str, EtapaSpec] = {
    "E01": EtapaSpec(
        cod="E01", orden=1, area_responsable="AREAS",
        nombre="Solicitud de requerimiento TIC (Áreas → OTIN)",
        campos_extra=("cmn_adjunto",),
        por_area=True,
    ),
    "E02": EtapaSpec(
        cod="E02", orden=2, area_responsable="OTIN",
        nombre="Elaboración TDR consolidado (OTIN)",
        prerequisitos=("E01",),
    ),
    "E03": EtapaSpec(
        cod="E03", orden=3, area_responsable="OTIN",
        nombre="Envío indagación de mercado (OTIN → OTA)",
    ),
    "E04": EtapaSpec(
        cod="E04", orden=4, area_responsable="OTA",
        nombre="OTA deriva expediente a OEAS (OTA → OEAS)",
    ),
    "E05": EtapaSpec(
        cod="E05", orden=5, area_responsable="BUCLE",
        nombre="Observaciones al TDR [BUCLE] (OEAS → OTIN)",
        campos_extra=("motivo_bucle",),
        es_bucle=True,
        prerequisitos=("E04",),
    ),
    "E06": EtapaSpec(
        cod="E06", orden=6, area_responsable="BUCLE",
        nombre="Corrección TDR [BUCLE] (OTIN → OEAS)",
        campos_extra=("motivo_bucle",),
        es_bucle=True,
        prerequisitos=("E04",),
    ),
    "E07": EtapaSpec(
        cod="E07", orden=7, area_responsable="OEAS",
        nombre="Evaluación técnica (OEAS → OTIN)",
        campos_extra=("resultado_eval",),
    ),
    "E08": EtapaSpec(
        cod="E08", orden=8, area_responsable="OTIN",
        nombre="Respuesta OTIN a evaluación técnica (OTIN → OEAS)",
        campos_extra=("resultado_eval",),
    ),
    "E08a": EtapaSpec(
        cod="E08a", orden=9, area_responsable="BUCLE",
        nombre="Observaciones al proveedor [BUCLE] (OEAS → Prov.)",
        campos_extra=("motivo_bucle",),
        es_bucle=True,
    ),
    "E08b": EtapaSpec(
        cod="E08b", orden=10, area_responsable="BUCLE",
        nombre="Subsanación + re-evaluación [BUCLE] (Prov→OEAS→OTIN)",
        campos_extra=("motivo_bucle",),
        es_bucle=True,
    ),
    "E09": EtapaSpec(
        cod="E09", orden=11, area_responsable="OEAS",
        nombre="Cuadro comparativo (OEAS → OTIN)",
        campos_extra=("monto_cert",),
        prerequisitos=("E08",),
    ),
    "E10": EtapaSpec(
        cod="E10", orden=12, area_responsable="OTIN",
        nombre="OTIN solicita anexo cert. + valida presupuesto (OTIN → Áreas)",
        campos_extra=("resultado_eval",),
    ),
    "E11": EtapaSpec(
        cod="E11", orden=13, area_responsable="AREAS",
        nombre="Solicitud cert. presupuestal (cada Área → OTIN)",
        campos_extra=("area_usuaria", "monto_cert"),
        por_area=True,
    ),
    "E12": EtapaSpec(
        cod="E12", orden=14, area_responsable="OTIN",
        nombre="Consolidación cert. presupuestales (OTIN)",
        prerequisitos=("E11",),
    ),
    "E13": EtapaSpec(
        cod="E13", orden=15, area_responsable="OTIN",
        nombre="Envío consolidado a Secretaría General (OTIN → SG)",
    ),
    "E14": EtapaSpec(
        cod="E14", orden=16, area_responsable="SEC_GENERAL",
        nombre="Aprobación Secretaría General (SG)",
    ),
    "E15": EtapaSpec(
        cod="E15", orden=17, area_responsable="SEC_GENERAL",
        nombre="Envío a OTPP (Sec. General → OTPP)",
    ),
    "E16": EtapaSpec(
        cod="E16", orden=18, area_responsable="OTPP",
        nombre="Certificación presupuestal — OTPP",
        campos_extra=("fecha_envio_otpp", "fecha_resp_otpp"),
        alerta_dias=20,
    ),
    "E17": EtapaSpec(
        cod="E17", orden=19, area_responsable="OTPP",
        nombre="OTPP envía a OTA (OTPP → OTA)",
    ),
    "E18": EtapaSpec(
        cod="E18", orden=20, area_responsable="OTA",
        nombre="OTA deriva a OEAS (OTA → OEAS)",
    ),
    "E19": EtapaSpec(
        cod="E19", orden=21, area_responsable="OEAS",
        nombre="Emisión orden de compra/servicio (OEAS)",
        campos_extra=("nro_ocs", "monto_ocs", "plazo_entrega"),
    ),
    "E20": EtapaSpec(
        cod="E20", orden=22, area_responsable="OEAS",
        nombre="Notificación al proveedor (OEAS → Proveedor)",
    ),
    "E21": EtapaSpec(
        cod="E21", orden=23, area_responsable="PROVEEDOR",
        nombre="Confirmación recepción OCS (Proveedor→OEAS→OTIN)",
    ),
    "E22": EtapaSpec(
        cod="E22", orden=24, area_responsable="PROVEEDOR",
        nombre="Inicio de servicio / entrega del bien",
    ),
    "E23": EtapaSpec(
        cod="E23", orden=25, area_responsable="OTIN",
        nombre="OTIN solicita conformidad (OTIN → Áreas)",
    ),
    "E24": EtapaSpec(
        cod="E24", orden=26, area_responsable="AREAS",
        nombre="Conformidad área usuaria [por área] (Áreas → OTIN)",
        campos_extra=("area_usuaria",),
        por_area=True,
        prerequisitos=("E23",),
    ),
    "E25": EtapaSpec(
        cod="E25", orden=27, area_responsable="OTIN",
        nombre="Conformidad final consolidada (OTIN) FIN",
        prerequisitos=("E24",),
        es_fin=True,
    ),
}

# Canonical order list — used for sorting and progreso calculation.
# E08a/E08b appear after E08 and before E09 (positions 9/10).
ORDEN_ETAPAS: list[str] = [
    spec.cod
    for spec in sorted(ETAPAS_CATALOGO.values(), key=lambda s: s.orden)
]

# Codes that are loop-type (excluded from progreso denominator)
_BUCLE_CODS: frozenset[str] = frozenset(
    cod for cod, spec in ETAPAS_CATALOGO.items() if spec.es_bucle
)

# Denominator used by calcular_progreso: 25 (total 27 minus 2 extra: E08a + E08b
# NOTE: 4 loop codes total (E05, E06, E08a, E08b). Design §D2 says "excludes
# es_bucle cods" but uses 25 as denominator. That means E05 and E06 ARE counted
# (they are distinct stages, just loopable). Only E08a and E08b are extras that
# push total beyond 25. Verified: ORDEN_ETAPAS = 27 entries; non-bucle = 23;
# design says denominator=25, so we keep 25 as the fixed constant per Design D2.
PROGRESO_DENOMINATOR: int = 25


def get_etapa_spec(cod: str) -> EtapaSpec:
    """Return EtapaSpec for the given code. Raises KeyError if unknown."""
    return ETAPAS_CATALOGO[cod]


def siguiente_etapa_registrable(
    etapas_completadas_cods: list[str],
) -> str | None:
    """Return the first cod in ORDEN_ETAPAS not in etapas_completadas_cods.

    'Completadas' here means ALL rows for that cod are COMPLETADO
    (semantics enforced by calcular_progreso, not here).
    Returns None when the proceso has completed all stages.
    """
    completadas = set(etapas_completadas_cods)
    for cod in ORDEN_ETAPAS:
        if cod not in completadas:
            return cod
    return None
