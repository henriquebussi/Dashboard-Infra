"""Administrator-only performance report schedules."""
from enum import Enum
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr

from schemas import DashboardFilterParams, Environment, TimePeriod, UserRBACContext, UserRole
from security import require_role
from services import report_schedule

router = APIRouter()


class Frequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class Format(str, Enum):
    CSV = "csv"
    XLSX = "xlsx"
    PDF = "pdf"


class ReportScheduleInput(BaseModel):
    recipient: EmailStr
    frequency: Frequency
    environment: Environment
    period: TimePeriod
    format: Format


@router.get("/reports/schedules")
def list_report_schedules(admin: UserRBACContext = Depends(require_role(UserRole.INFRA_ADMIN))):
    return report_schedule.list_schedules()


@router.post("/reports/schedules", status_code=201)
def create_report_schedule(config: ReportScheduleInput, admin: UserRBACContext = Depends(require_role(UserRole.INFRA_ADMIN))):
    if config.period == TimePeriod.CUSTOM:
        raise HTTPException(422, "Selecione uma janela fixa para o agendamento")
    ident = report_schedule.save_schedule(config.model_dump(mode="json"), admin.user_id)
    return {"id": ident}


@router.put("/reports/schedules/{ident}")
def update_report_schedule(ident: UUID, config: ReportScheduleInput, admin: UserRBACContext = Depends(require_role(UserRole.INFRA_ADMIN))):
    if config.period == TimePeriod.CUSTOM:
        raise HTTPException(422, "Selecione uma janela fixa para o agendamento")
    try:
        report_schedule.save_schedule(config.model_dump(mode="json"), admin.user_id, str(ident))
    except KeyError:
        raise HTTPException(404, "Agendamento não encontrado")
    return {"id": str(ident)}


@router.delete("/reports/schedules/{ident}", status_code=204)
def delete_report_schedule(ident: UUID, admin: UserRBACContext = Depends(require_role(UserRole.INFRA_ADMIN))):
    try:
        report_schedule.delete_schedule(str(ident), admin.user_id)
    except KeyError:
        raise HTTPException(404, "Agendamento não encontrado")


@router.get("/reports/download")
async def download_performance_report(
    request: Request,
    environment: Environment,
    period: TimePeriod,
    format: Format,
    admin: UserRBACContext = Depends(require_role(UserRole.INFRA_ADMIN)),
):
    from fastapi.responses import Response
    from services.export_service import export_metrics_report

    if period == TimePeriod.CUSTOM:
        raise HTTPException(422, "Selecione uma janela fixa")
    service = getattr(request.app.state, "gcp_service", None)
    if service is None:
        raise HTTPException(503, "Integração GCP indisponível")
    payload = await service.get_overview_payload(DashboardFilterParams(period=period, env=environment))
    if payload.data_source != "gcp":
        raise HTTPException(503, "Dados reais indisponíveis")
    content, media_type, filename = export_metrics_report(payload, format.value)
    return Response(content, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
