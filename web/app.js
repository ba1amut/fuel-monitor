const map = L.map("map").setView([62, 95], 4);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "© OpenStreetMap"
}).addTo(map);

const markers = L.markerClusterGroup();
let heatLayer = null;
map.addLayer(markers);

const greenIcon = L.divIcon({className:"", html:'<div style="width:12px;height:12px;background:#4CAF50;border-radius:50%;border:2px solid white"></div>'});
const redIcon   = L.divIcon({className:"", html:'<div style="width:12px;height:12px;background:#f44336;border-radius:50%;border:2px solid white"></div>'});
const greyIcon  = L.divIcon({className:"", html:'<div style="width:12px;height:12px;background:#9e9e9e;border-radius:50%;border:2px solid white"></div>'});
const blueIcon  = L.divIcon({
    className: "",
    html: '<div style="width:12px;height:12px;border-radius:50%;background:#3388ff;opacity:0.6;border:2px solid #fff"></div>',
    iconSize: [12, 12],
    iconAnchor: [6, 6],
});

function pickIcon(station) {
    if (station.is_approximate) return blueIcon;
    const states = station.fuel_states || [];
    if (states.length === 0) return greyIcon;
    const hasAny = states.some(f => f.available);
    return hasAny ? greenIcon : redIcon;
}

function ago(iso) {
  const diff = Math.floor((Date.now() - new Date(iso)) / 60000);
  if (diff < 60) return `${diff} мин назад`;
  if (diff < 1440) return `${Math.floor(diff/60)} ч назад`;
  return `${Math.floor(diff/1440)} дн назад`;
}

function buildPopup(s) {
  const name = s.aliases[0] || "АЗС";
  const brand = s.brand || "";
  const approxNote = s.is_approximate ? '<br><em style="color:#888">⚠ позиция по городу</em>' : '';
  let html = `<div class="popup-title">${brand} ${name}</div>`;
  for (const fs of s.fuel_states) {
    const status = fs.available ? "✅" : "❌";
    const price  = fs.available && fs.price ? ` ${fs.price}₽/л` : fs.available ? " (цена не указана)" : "";
    html += `<div class="fuel-row"><span>${fs.grade}: ${status}${price}</span><span class="fuel-ago">${ago(fs.updated_at)}</span></div>`;
  }
  html += approxNote;
  return html;
}


async function loadStations() {
  const brand = document.getElementById("filter-brand").value;
  const grade = document.getElementById("filter-grade").value;
  const params = new URLSearchParams();
  if (brand) params.set("brand", brand);
  if (grade) params.set("grade", grade);
  const r = await fetch(`/api/stations?${params}`);
  const stations = await r.json();

  markers.clearLayers();
  const brands = new Set();

  for (const s of stations) {
    if (s.brand) brands.add(s.brand);
    const loc = s.location;
    if (!loc) continue;
    const [lon, lat] = loc.coordinates;
    const m = L.marker([lat, lon], {icon: pickIcon(s)});
    m.bindPopup(buildPopup(s));
    markers.addLayer(m);
  }

  const sel = document.getElementById("filter-brand");
  const cur = sel.value;
  sel.innerHTML = '<option value="">Все бренды</option>';
  for (const b of [...brands].sort()) {
    const opt = document.createElement("option");
    opt.value = b; opt.textContent = b;
    if (b === cur) opt.selected = true;
    sel.appendChild(opt);
  }

  await loadHeatmap(brand, grade);
}

async function loadHeatmap(brand, grade) {
  try {
    const params = new URLSearchParams();
    if (brand) params.set("brand", brand);
    if (grade) params.set("grade", grade);
    const r = await fetch(`/api/heatmap?${params}`);
    const regions = await r.json();
    if (heatLayer) map.removeLayer(heatLayer);
    // Тепловой слой по центроидам регионов (упрощённо — используем данные из БД)
    // В production заменить на реальные координаты центров субъектов РФ
    const points = regions
      .filter(region => region.deficit_ratio > 0 && region._lat && region._lon)
      .map(region => [region._lat, region._lon, region.deficit_ratio]);
    if (points.length > 0) {
      heatLayer = L.heatLayer(points, {radius: 40, blur: 25, maxZoom: 6}).addTo(map);
    }
  } catch (e) {
    console.warn("Heatmap load failed, skipping:", e);
  }
}

document.getElementById("btn-refresh").addEventListener("click", loadStations);
document.getElementById("filter-brand").addEventListener("change", loadStations);
document.getElementById("filter-grade").addEventListener("change", loadStations);

loadStations();
setInterval(loadStations, 5 * 60 * 1000);
