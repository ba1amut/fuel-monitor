import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from api.routers import reports, stations, heatmap, summary

app = FastAPI(title="Fuel Monitor API")
app.include_router(reports.router)
app.include_router(stations.router)
app.include_router(heatmap.router)
app.include_router(summary.router)

# Mount static web files (Task 8: public map dashboard)
_web_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
app.mount("/", StaticFiles(directory=_web_dir, html=True), name="web")
