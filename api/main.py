import os
from fastapi import FastAPI
from api.routers import reports, stations, heatmap, summary

app = FastAPI(title="Fuel Monitor API")
app.include_router(reports.router)
app.include_router(stations.router)
app.include_router(heatmap.router)
app.include_router(summary.router)

# Mount static web files only if the directory exists (web UI is Task 8)
_web_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
if os.path.isdir(_web_dir):
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_web_dir, html=True), name="web")
