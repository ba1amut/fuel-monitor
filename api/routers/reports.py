from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from api.services.report_processor import process_report
from api.schemas import ReportResult

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.post("", response_model=ReportResult)
async def create_report(
    telegram_user_id: int = Form(...),
    text: str | None = Form(None),
    user_lat: float | None = Form(None),
    user_lon: float | None = Form(None),
    photo: UploadFile | None = File(None),
    voice: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
):
    image_bytes = await photo.read() if photo else None
    voice_bytes = await voice.read() if voice else None
    result = await process_report(
        db, telegram_user_id=telegram_user_id,
        text=text, image_bytes=image_bytes, voice_bytes=voice_bytes,
        user_lat=user_lat, user_lon=user_lon,
    )
    return ReportResult(
        success=result.success,
        station_name=result.station_name,
        parse_failed=result.parse_failed,
        fuels=[{"grade": f.grade, "available": f.available, "price": f.price} for f in result.fuels],
        station_id=result.station_id,
    )
