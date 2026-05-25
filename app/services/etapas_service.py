"""Service layer for etapas mechanics — C3a scope.

NO business rule enforcement here. All R1-R8 logic lives in validaciones.py (C3b).
Audit (historial_cambios) is written only on PUT (actualizar_etapa).

Key design decisions:
  D2 — progreso is derived from rows, never persisted.
  D4 — GET response is grouped: rondas[] for loop stages, filas[] for others.

Functions > 50 lines are split into private helpers per coding conventions.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.etapa import EtapaRegistro
from app.models.historial import HistorialCambio
from app.schemas.etapa import (
    BucleCreate,
    EtapaAgrupadaOut,
    EtapaCreate,
    EtapaUpdate,
    FilaAreaOut,
    ProgresoOut,
    RondaBucleOut,
)
from app.services.etapas_catalogo import (
    ETAPAS_CATALOGO,
    ORDEN_ETAPAS,
    PROGRESO_DENOMINATOR,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BUCLE_CODS: frozenset[str] = frozenset(
    cod for cod, spec in ETAPAS_CATALOGO.items() if spec.es_bucle
)


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def registrar_etapa(
    db: Session,
    proceso_id: int,
    payload: EtapaCreate,
    current_user_username: str,
) -> EtapaRegistro:
    """Insert a new etapas_registro row. No rule validation (C3b adds that).

    For the first registration of a loop stage, nro_ronda is set to 1.
    For subsequent rounds use agregar_ronda_bucle instead.
    """
    spec = ETAPAS_CATALOGO.get(payload.codigo_etapa)
    es_bucle = spec.es_bucle if spec else False

    row = EtapaRegistro(
        proceso_id=proceso_id,
        codigo_etapa=payload.codigo_etapa,
        nombre_etapa=payload.nombre_etapa,
        area_responsable=spec.area_responsable if spec else None,
        fecha_inicio=payload.fecha_inicio,
        fecha_fin=payload.fecha_fin,
        estado_etapa=payload.estado_etapa,
        responsable=payload.responsable,
        oficio_correo=payload.oficio_correo,
        observaciones=payload.observaciones,
        area_usuaria=payload.area_usuaria,
        cmn_adjunto=payload.cmn_adjunto,
        monto_cert=payload.monto_cert,
        resultado_eval=payload.resultado_eval,
        motivo_bucle=payload.motivo_bucle,
        fecha_envio_otpp=payload.fecha_envio_otpp,
        fecha_resp_otpp=payload.fecha_resp_otpp,
        nro_ocs=payload.nro_ocs,
        monto_ocs=payload.monto_ocs,
        plazo_entrega=payload.plazo_entrega,
        es_bucle=es_bucle,
        nro_ronda=1,
        registrado_por=current_user_username,
    )
    db.add(row)
    db.flush()
    # TODO C3b: sync_montos(db, proceso_id, payload.codigo_etapa, row)
    return row


def actualizar_etapa(
    db: Session,
    etapa: EtapaRegistro,
    payload: EtapaUpdate,
    current_user_username: str,
) -> EtapaRegistro:
    """Update an existing etapas_registro row; audit each changed field."""
    _mutable_fields = [
        "nombre_etapa", "fecha_inicio", "fecha_fin", "estado_etapa",
        "responsable", "oficio_correo", "observaciones", "area_usuaria",
        "cmn_adjunto", "monto_cert", "resultado_eval", "motivo_bucle",
        "fecha_envio_otpp", "fecha_resp_otpp", "nro_ocs", "monto_ocs",
        "plazo_entrega",
    ]
    for campo in _mutable_fields:
        nuevo = getattr(payload, campo, None)
        if nuevo is None:
            continue
        antes = getattr(etapa, campo)
        if str(antes) == str(nuevo):
            continue
        _registrar_auditoria(
            db,
            proceso_id=etapa.proceso_id,
            etapa_id=etapa.id,
            campo=campo,
            antes=str(antes) if antes is not None else None,
            nuevo=str(nuevo),
            usuario=current_user_username,
        )
        setattr(etapa, campo, nuevo)

    etapa.actualizado_por = current_user_username
    etapa.actualizado_en = datetime.now(timezone.utc).replace(tzinfo=None)
    db.flush()
    # TODO C3b: sync_montos(db, etapa.proceso_id, etapa.codigo_etapa, etapa)
    return etapa


def agregar_ronda_bucle(
    db: Session,
    proceso_id: int,
    cod: str,
    payload: BucleCreate,
    current_user_username: str,
) -> EtapaRegistro:
    """Add a new round for a loop-type stage.

    Computes nro_ronda = MAX(nro_ronda WHERE proceso_id, codigo_etapa) + 1.
    No rule enforcement (C3b validates R6).
    """
    max_ronda = db.execute(
        select(func.max(EtapaRegistro.nro_ronda)).where(
            EtapaRegistro.proceso_id == proceso_id,
            EtapaRegistro.codigo_etapa == cod,
        )
    ).scalar_one_or_none() or 0

    spec = ETAPAS_CATALOGO.get(cod)
    row = EtapaRegistro(
        proceso_id=proceso_id,
        codigo_etapa=cod,
        nombre_etapa=spec.nombre if spec else cod,
        area_responsable=spec.area_responsable if spec else None,
        es_bucle=True,
        nro_ronda=max_ronda + 1,
        motivo_bucle=payload.motivo_bucle,
        estado_etapa="PENDIENTE",
        registrado_por=current_user_username,
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Audit helper (Spec §F — only called from actualizar_etapa)
# ---------------------------------------------------------------------------

def _registrar_auditoria(
    db: Session,
    proceso_id: int | None,
    etapa_id: int,
    campo: str,
    antes: str | None,
    nuevo: str,
    usuario: str,
) -> None:
    """Insert one historial_cambios row for a changed field."""
    db.add(
        HistorialCambio(
            proceso_id=proceso_id,
            etapa_id=etapa_id,
            campo_modificado=campo,
            valor_anterior=antes,
            valor_nuevo=nuevo,
            modificado_por=usuario,
        )
    )


# ---------------------------------------------------------------------------
# Progreso calculation (pure function — Design D2)
# ---------------------------------------------------------------------------

def calcular_progreso(etapas_rows: list[EtapaRegistro]) -> ProgresoOut:
    """Derive etapa_actual and progress % from etapas_registro rows.

    Algorithm (Design D2):
    - Iterate ORDEN_ETAPAS.
    - Per cod, gather all rows for that cod.
    - Estado consolidado = COMPLETADO if:
        - por_area=True → ALL rows are COMPLETADO (OMITIDO treated as non-completado)
        - es_bucle=True → last ronda (highest nro_ronda) is COMPLETADO
        - simple  → single row is COMPLETADO
    - etapa_actual = first cod whose consolidated estado != COMPLETADO
    - progreso % = (completadas / PROGRESO_DENOMINATOR) * 100
    - PROGRESO_DENOMINATOR = 25 (loop cods E05/E06/E08a/E08b excluded from
      denominator per Design D2; but only E08a and E08b are "extra" cods
      that push ORDEN_ETAPAS beyond 25 — both are excluded from the count)
    """
    # Group rows by codigo_etapa
    by_cod: dict[str, list[EtapaRegistro]] = {}
    for row in etapas_rows:
        by_cod.setdefault(row.codigo_etapa, []).append(row)

    completadas = 0
    etapa_actual: str | None = None

    for cod in ORDEN_ETAPAS:
        spec = ETAPAS_CATALOGO[cod]
        rows_for_cod = by_cod.get(cod, [])

        estado = _estado_consolidado(spec, rows_for_cod)

        if estado == "COMPLETADO":
            # Only count non-bucle cods in progress denominator
            if not spec.es_bucle:
                completadas += 1
        else:
            if etapa_actual is None:
                etapa_actual = cod

    # Default to first stage when no rows at all
    if etapa_actual is None and completadas == 0:
        etapa_actual = ORDEN_ETAPAS[0] if ORDEN_ETAPAS else None

    porcentaje = round((completadas / PROGRESO_DENOMINATOR) * 100, 1)

    return ProgresoOut(
        etapa_actual=etapa_actual,
        porcentaje=porcentaje,
        completadas=completadas,
        total=PROGRESO_DENOMINATOR,
    )


def _estado_consolidado(spec, rows: list[EtapaRegistro]) -> str:
    """Compute the consolidated estado for one stage code.

    OMITIDO rows are treated as non-completado (Design D3 — reinicio TDR
    marks them OMITIDO to preserve audit, but they don't count as done).
    """
    if not rows:
        return "PENDIENTE"

    if spec.es_bucle:
        # Last ronda (highest nro_ronda) determines the estado
        last = max(rows, key=lambda r: r.nro_ronda)
        return last.estado_etapa

    if spec.por_area:
        # ALL rows must be COMPLETADO (OMITIDO is not COMPLETADO)
        if all(r.estado_etapa == "COMPLETADO" for r in rows):
            return "COMPLETADO"
        if any(r.estado_etapa in ("EN CURSO", "COMPLETADO") for r in rows):
            return "EN_CURSO"
        return "PENDIENTE"

    # Simple stage: single row (take first, there should only be one)
    row = rows[0]
    return row.estado_etapa


# ---------------------------------------------------------------------------
# Grouping for GET response (Design D4)
# ---------------------------------------------------------------------------

def agrupar_etapas(
    etapas_rows: list[EtapaRegistro],
    areas_usuarias: list[str] | None = None,
) -> list[EtapaAgrupadaOut]:
    """Group etapas_registro rows into the canonical GET response format.

    One EtapaAgrupadaOut per cod in ORDEN_ETAPAS (all 27 entries, even with
    no rows — those appear as PENDIENTE with empty filas/rondas).
    """
    by_cod: dict[str, list[EtapaRegistro]] = {}
    for row in etapas_rows:
        by_cod.setdefault(row.codigo_etapa, []).append(row)

    today = date.today()
    result: list[EtapaAgrupadaOut] = []

    for cod in ORDEN_ETAPAS:
        spec = ETAPAS_CATALOGO[cod]
        rows = by_cod.get(cod, [])
        estado = _estado_consolidado(spec, rows)

        # Normalize EN_CURSO vs EN CURSO (DB stores "EN CURSO" with space)
        # EtapaAgrupadaOut.estado uses COMPLETADO|EN_CURSO|PENDIENTE (underscore)
        estado_norm = _normalize_estado(estado)

        entry = EtapaAgrupadaOut(
            cod=cod,
            nombre=spec.nombre,
            area_responsable=spec.area_responsable,
            es_bucle=spec.es_bucle,
            por_area=spec.por_area,
            estado=estado_norm,
        )

        if spec.es_bucle:
            entry.rondas = _build_rondas(rows)
        else:
            entry.filas = _build_filas(rows, cod)

        if cod == "E16":
            entry.alerta_otpp = _calcular_alerta_e16(rows, today)

        if cod == "E11" and rows:
            entry.monto_total = _sum_monto_cert(rows)

        result.append(entry)

    return result


def _normalize_estado(estado: str) -> str:
    """Normalize DB estado strings to underscore-separated form for JSON."""
    return estado.replace(" ", "_")


def _build_rondas(rows: list[EtapaRegistro]) -> list[RondaBucleOut]:
    """Build rondas list sorted by nro_ronda ASC."""
    sorted_rows = sorted(rows, key=lambda r: r.nro_ronda)
    return [
        RondaBucleOut(
            id=r.id,
            nro_ronda=r.nro_ronda,
            motivo_bucle=r.motivo_bucle,
            estado_etapa=r.estado_etapa,
            fecha_inicio=r.fecha_inicio,
            fecha_fin=r.fecha_fin,
            dias=r.dias,
        )
        for r in sorted_rows
    ]


def _build_filas(rows: list[EtapaRegistro], cod: str) -> list[FilaAreaOut]:
    """Build filas list sorted by area_usuaria ASC (then id for stability)."""
    sorted_rows = sorted(
        rows,
        key=lambda r: (r.area_usuaria or "", r.id),
    )
    filas = []
    for r in sorted_rows:
        vencimiento_ocs = _calcular_vencimiento_ocs(r) if cod == "E19" else None
        filas.append(
            FilaAreaOut(
                id=r.id,
                area_usuaria=r.area_usuaria,
                estado_etapa=r.estado_etapa,
                fecha_inicio=r.fecha_inicio,
                fecha_fin=r.fecha_fin,
                dias=r.dias,
                cmn_adjunto=r.cmn_adjunto,
                monto_cert=r.monto_cert,
                resultado_eval=r.resultado_eval,
                nro_ocs=r.nro_ocs,
                monto_ocs=r.monto_ocs,
                plazo_entrega=r.plazo_entrega,
                fecha_envio_otpp=r.fecha_envio_otpp,
                fecha_resp_otpp=r.fecha_resp_otpp,
                responsable=r.responsable,
                oficio_correo=r.oficio_correo,
                observaciones=r.observaciones,
                registrado_por=r.registrado_por,
                vencimiento_ocs=vencimiento_ocs,
            )
        )
    return filas


def _calcular_vencimiento_ocs(row: EtapaRegistro) -> date | None:
    """Compute vencimiento_ocs = fecha_inicio + plazo_entrega days (derived, never stored)."""
    from datetime import timedelta
    if row.fecha_inicio and row.plazo_entrega is not None:
        return row.fecha_inicio + timedelta(days=row.plazo_entrega)
    return None


def _calcular_alerta_e16(rows: list[EtapaRegistro], today: date) -> bool:
    """Return True if any E16 row exceeds the 20-day response threshold.

    Triggered when:
    - fecha_resp_otpp - fecha_envio_otpp > 20 days, OR
    - today - fecha_envio_otpp > 20 days AND fecha_resp_otpp is None
    """
    for r in rows:
        if r.fecha_envio_otpp is None:
            continue
        if r.fecha_resp_otpp is not None:
            if (r.fecha_resp_otpp - r.fecha_envio_otpp).days > 20:
                return True
        else:
            if (today - r.fecha_envio_otpp).days > 20:
                return True
    return False


def _sum_monto_cert(rows: list[EtapaRegistro]) -> Decimal | None:
    """Sum monto_cert across all E11 rows (None if no values)."""
    total: Decimal = Decimal("0.00")
    has_value = False
    for r in rows:
        if r.monto_cert is not None:
            total += r.monto_cert
            has_value = True
    return total if has_value else None
