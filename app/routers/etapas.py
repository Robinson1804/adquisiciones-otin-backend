"""Etapas router — endpoints for stage registration, updates, and loops.

C3a scope: mechanics only. No business rule enforcement (R1-R8 are C3b).

Endpoints:
  GET  /procesos/{id}/etapas            → grouped timeline + progreso
  POST /procesos/{id}/etapas            → register a stage row
  PUT  /etapas/{id}                     → update a stage row (with audit)
  POST /procesos/{id}/etapas/{cod}/bucle → add a loop round
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user, require_role
from app.models.etapa import EtapaRegistro
from app.models.proceso import Proceso
from app.models.usuario import Usuario
from app.schemas.etapa import (
    BucleCreate,
    EtapaCreate,
    EtapaOut,
    EtapasResponseOut,
    EtapaUpdate,
)
from app.services.etapas_catalogo import ETAPAS_CATALOGO
from app.services.etapas_service import (
    actualizar_etapa,
    agregar_ronda_bucle,
    agrupar_etapas,
    calcular_progreso,
    registrar_etapa,
)

router = APIRouter(tags=["etapas"])

_BUCLE_CODS: frozenset[str] = frozenset(
    cod for cod, spec in ETAPAS_CATALOGO.items() if spec.es_bucle
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_active_proceso_or_404(db: Session, proceso_id: int) -> Proceso:
    proceso = db.get(Proceso, proceso_id)
    if proceso is None or proceso.eliminado_en is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proceso {proceso_id} no encontrado",
        )
    return proceso


def _get_etapa_or_404(db: Session, etapa_id: int) -> EtapaRegistro:
    etapa = db.get(EtapaRegistro, etapa_id)
    if etapa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Etapa {etapa_id} no encontrada",
        )
    return etapa


def _etapa_to_out(etapa: EtapaRegistro) -> EtapaOut:
    """Convert EtapaRegistro ORM to EtapaOut, computing vencimiento_ocs."""
    from datetime import timedelta
    vencimiento_ocs = None
    if (
        etapa.codigo_etapa == "E19"
        and etapa.fecha_inicio
        and etapa.plazo_entrega is not None
    ):
        vencimiento_ocs = etapa.fecha_inicio + timedelta(days=etapa.plazo_entrega)

    out = EtapaOut.model_validate(etapa)
    out.vencimiento_ocs = vencimiento_ocs
    return out


# ---------------------------------------------------------------------------
# GET /procesos/{proceso_id}/etapas
# ---------------------------------------------------------------------------

@router.get(
    "/procesos/{proceso_id}/etapas",
    response_model=EtapasResponseOut,
)
def get_etapas(
    proceso_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> EtapasResponseOut:
    """Return all 27 stages grouped + progreso (all PENDIENTE if no rows yet)."""
    proceso = _get_active_proceso_or_404(db, proceso_id)

    rows = db.execute(
        select(EtapaRegistro).where(
            EtapaRegistro.proceso_id == proceso_id
        )
    ).scalars().all()

    etapas_agrupadas = agrupar_etapas(
        list(rows),
        areas_usuarias=proceso.areas_usuarias,
    )
    progreso = calcular_progreso(list(rows))

    return EtapasResponseOut(etapas=etapas_agrupadas, progreso=progreso)


# ---------------------------------------------------------------------------
# POST /procesos/{proceso_id}/etapas
# ---------------------------------------------------------------------------

@router.post(
    "/procesos/{proceso_id}/etapas",
    response_model=EtapaOut,
    status_code=status.HTTP_201_CREATED,
)
def post_etapa(
    proceso_id: int,
    body: EtapaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role("ADMIN", "EDITOR")),
) -> EtapaOut:
    """Register a new stage row for the proceso."""
    _get_active_proceso_or_404(db, proceso_id)
    # TODO C3b: call validaciones.validar_registro(db, proceso_id, body)
    etapa = registrar_etapa(db, proceso_id, body, current_user.username)
    db.commit()
    db.refresh(etapa)
    return _etapa_to_out(etapa)


# ---------------------------------------------------------------------------
# PUT /etapas/{etapa_id}
# ---------------------------------------------------------------------------

@router.put(
    "/etapas/{etapa_id}",
    response_model=EtapaOut,
)
def put_etapa(
    etapa_id: int,
    body: EtapaUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role("ADMIN", "EDITOR")),
) -> EtapaOut:
    """Update an existing stage row. Generates historial_cambios entries."""
    etapa = _get_etapa_or_404(db, etapa_id)
    etapa = actualizar_etapa(db, etapa, body, current_user.username)
    db.commit()
    db.refresh(etapa)
    return _etapa_to_out(etapa)


# ---------------------------------------------------------------------------
# POST /procesos/{proceso_id}/etapas/{cod}/bucle
# ---------------------------------------------------------------------------

@router.post(
    "/procesos/{proceso_id}/etapas/{cod}/bucle",
    response_model=EtapaOut,
    status_code=status.HTTP_201_CREATED,
)
def post_bucle(
    proceso_id: int,
    cod: str,
    body: BucleCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role("ADMIN", "EDITOR")),
) -> EtapaOut:
    """Add a new round for a loop-type stage (E05, E06, E08a, E08b)."""
    if cod not in _BUCLE_CODS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El código '{cod}' no es una etapa de bucle. "
                   f"Etapas de bucle válidas: {sorted(_BUCLE_CODS)}",
        )
    _get_active_proceso_or_404(db, proceso_id)
    # TODO C3b: call validaciones.validar_bucle(db, proceso_id, cod)
    etapa = agregar_ronda_bucle(db, proceso_id, cod, body, current_user.username)
    db.commit()
    db.refresh(etapa)
    return _etapa_to_out(etapa)
