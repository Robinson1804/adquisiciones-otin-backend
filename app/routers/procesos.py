"""Procesos router — CRUD endpoints for the procesos resource.

Design decisions implemented here:
  D1 — soft delete via eliminado_en TIMESTAMP NULL
  D2 — id_proceso generation: pg_advisory_xact_lock + MAX+1 + retry
  D3 — CMN captured as E01 rows in etapas_registro at creation time
  D4 — historial_cambios deferred to C3 (no audit writes in C2)

Service layer is inline (helpers prefixed _) per design §1 decision.
"""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user, require_role
from app.models.etapa import EtapaRegistro
from app.models.montos import MontosProceso
from app.models.proceso import Proceso
from app.models.usuario import Usuario
from app.schemas.proceso import (
    CmnPorArea,
    MontosOut,
    PaginatedProcesos,
    ProcesoCreate,
    ProcesoOut,
    ProcesoUpdate,
)

router = APIRouter(prefix="/procesos", tags=["procesos"])

# ---------------------------------------------------------------------------
# Private helpers (inline service layer — C2 design decision)
# ---------------------------------------------------------------------------

_E01_NOMBRE = "Solicitud de requerimiento TIC (Áreas → OTIN)"
_MAX_ID_RETRIES = 3


def _generar_id_proceso(db: Session, anno: int) -> str:
    """Generate the next sequential id_proceso for the given year.

    Uses pg_advisory_xact_lock to serialize generation within the SAME
    transaction as the INSERT (autocommit=False guaranteed by SessionLocal).
    The UNIQUE constraint on id_proceso is the final safety net.
    Counts ALL rows for the year including soft-deleted ones — never recycles.
    """
    lock_key = f"proceso_seq_{anno}"
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": lock_key},
    )
    next_n = db.execute(
        text(
            "SELECT COALESCE(MAX(CAST(SPLIT_PART(id_proceso,'-',2) AS INTEGER)), 0) + 1 "
            "FROM procesos WHERE anno = :anno"
        ),
        {"anno": anno},
    ).scalar_one()
    return f"{anno}-{next_n:03d}"


def _crear_etapas_e01(
    db: Session,
    proceso_id: int,
    areas: list[str],
    cmn_por_area: list[CmnPorArea],
    usuario: str,
) -> None:
    """Insert one E01 etapas_registro row per area in areas_usuarias."""
    cmn_map = {c.area: c.cmn_adjunto for c in cmn_por_area}
    for area in areas:
        db.add(
            EtapaRegistro(
                proceso_id=proceso_id,
                codigo_etapa="E01",
                nombre_etapa=_E01_NOMBRE,
                area_responsable="AREAS",
                area_usuaria=area,
                cmn_adjunto=cmn_map.get(area, "NO"),
                estado_etapa="PENDIENTE",
                registrado_por=usuario,
            )
        )


def _get_active_proceso_or_404(db: Session, proceso_id: int) -> Proceso:
    """Return active (non-deleted) Proceso or raise 404."""
    proceso = db.get(Proceso, proceso_id)
    if proceso is None or proceso.eliminado_en is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proceso {proceso_id} no encontrado",
        )
    return proceso


# ---------------------------------------------------------------------------
# Estado transition validation
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "EN PROCESO": {"CULMINADO", "CANCELADO"},
    "CULMINADO": set(),
    "CANCELADO": set(),
}


def _validate_estado_transition(current: str, nuevo: str) -> None:
    allowed = _VALID_TRANSITIONS.get(current, set())
    if nuevo not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Transición de estado inválida: '{current}' → '{nuevo}'. "
                f"Transiciones permitidas: {sorted(allowed) or 'ninguna'}."
            ),
        )


# ---------------------------------------------------------------------------
# GET /procesos — paginated list (excludes soft-deleted)
# ---------------------------------------------------------------------------

@router.get("", response_model=PaginatedProcesos)
def list_procesos(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    anno: int | None = None,
    estado: str | None = None,
    tipo: str | None = None,
    search: str | None = None,
    area: str | None = None,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> PaginatedProcesos:
    base = select(Proceso).where(Proceso.eliminado_en.is_(None))

    if anno is not None:
        base = base.where(Proceso.anno == anno)
    if estado is not None:
        base = base.where(Proceso.estado == estado)
    if tipo is not None:
        base = base.where(Proceso.tipo == tipo)
    if search is not None:
        pattern = f"%{search}%"
        base = base.where(
            Proceso.requerimiento.ilike(pattern) | Proceso.id_proceso.ilike(pattern)
        )
    if area is not None:
        base = base.where(Proceso.areas_usuarias.any(area))

    total: int = db.execute(
        select(func.count()).select_from(base.subquery())
    ).scalar_one()

    rows = db.execute(
        base.order_by(Proceso.fecha_creacion.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()

    return PaginatedProcesos.build(
        items=[ProcesoOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# POST /procesos — create (ADMIN or EDITOR)
# ---------------------------------------------------------------------------

@router.post("", response_model=ProcesoOut, status_code=status.HTTP_201_CREATED)
def create_proceso(
    body: ProcesoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role("ADMIN", "EDITOR")),
) -> ProcesoOut:
    for attempt in range(_MAX_ID_RETRIES):
        try:
            id_proceso = _generar_id_proceso(db, body.anno)
            proceso = Proceso(
                id_proceso=id_proceso,
                requerimiento=body.requerimiento,
                tipo=body.tipo,
                unidad_resp=body.unidad_resp,
                areas_usuarias=body.areas_usuarias,
                pim=body.pim,
                anno=body.anno,
                estado="EN PROCESO",
                creado_por=current_user.username,
            )
            db.add(proceso)
            db.flush()  # assigns proceso.id without committing
            _crear_etapas_e01(
                db,
                proceso.id,
                body.areas_usuarias,
                body.cmn_por_area,
                current_user.username,
            )
            db.commit()
            db.refresh(proceso)
            return ProcesoOut.model_validate(proceso)
        except IntegrityError:
            db.rollback()
            if attempt == _MAX_ID_RETRIES - 1:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="No se pudo generar un id_proceso único. Intente de nuevo.",
                )

    # Unreachable but satisfies type checkers
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error interno")


# ---------------------------------------------------------------------------
# GET /procesos/{id} — detail (any authenticated user)
# ---------------------------------------------------------------------------

@router.get("/{proceso_id}", response_model=ProcesoOut)
def get_proceso(
    proceso_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> ProcesoOut:
    proceso = _get_active_proceso_or_404(db, proceso_id)
    return ProcesoOut.model_validate(proceso)


# ---------------------------------------------------------------------------
# GET /procesos/{id}/montos — montos consolidados para la ficha S4 (C3b)
# ---------------------------------------------------------------------------

@router.get("/{proceso_id}/montos", response_model=MontosOut | None)
def get_montos_proceso(
    proceso_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> MontosOut | None:
    _get_active_proceso_or_404(db, proceso_id)
    montos = db.execute(
        select(MontosProceso).where(MontosProceso.proceso_id == proceso_id)
    ).scalar_one_or_none()
    return MontosOut.model_validate(montos) if montos else None


# ---------------------------------------------------------------------------
# PUT /procesos/{id} — update (ADMIN or EDITOR)
# ---------------------------------------------------------------------------

@router.put("/{proceso_id}", response_model=ProcesoOut)
def update_proceso(
    proceso_id: int,
    body: ProcesoUpdate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role("ADMIN", "EDITOR")),
) -> ProcesoOut:
    proceso = _get_active_proceso_or_404(db, proceso_id)

    # Validate estado transition first (before any mutation)
    if body.estado is not None and body.estado != proceso.estado:
        _validate_estado_transition(proceso.estado, body.estado)

    # Enforce motivo_cancel when transitioning to CANCELADO
    nuevo_estado = body.estado if body.estado is not None else proceso.estado
    if nuevo_estado == "CANCELADO" and not (body.motivo_cancel or proceso.motivo_cancel):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="motivo_cancel es requerido al cancelar un proceso.",
        )

    # Apply non-None fields
    for field in ("requerimiento", "tipo", "unidad_resp", "areas_usuarias", "pim", "estado", "motivo_cancel"):
        value = getattr(body, field)
        if value is not None:
            setattr(proceso, field, value)

    db.commit()
    db.refresh(proceso)
    return ProcesoOut.model_validate(proceso)


# ---------------------------------------------------------------------------
# DELETE /procesos/{id} — soft delete (ADMIN or EDITOR)
# ---------------------------------------------------------------------------

@router.delete("/{proceso_id}")
def delete_proceso(
    proceso_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role("ADMIN", "EDITOR")),
) -> dict:
    proceso = _get_active_proceso_or_404(db, proceso_id)
    proceso.eliminado_en = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return {"message": "Proceso eliminado", "id": proceso_id}
