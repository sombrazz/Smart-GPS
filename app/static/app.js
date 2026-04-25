const SESSION_KEY = "portops_session";
const DATA_REFRESH_MS = 900;
const MAP_CENTER = [-2.565, -44.37];
const LERP_SNAP_METERS = 240;
const ROUTE_REGRESSION_TOLERANCE_M = 18;
const ROUTE_COMPATIBILITY_WINDOW_M = 120;
const DEBUG_ROUTE_ANIMATION = false;

const refs = {
  loginScreen: document.getElementById("loginScreen"),
  appLayout: document.getElementById("appLayout"),
  driverView: document.getElementById("driverView"),
  supervisorView: document.getElementById("supervisorView"),
  viewTitle: document.getElementById("viewTitle"),
  loginError: document.getElementById("loginError"),
  userBadge: document.getElementById("userBadge"),
  loginForm: document.getElementById("loginForm"),
  logoutBtn: document.getElementById("logoutBtn"),
  metricsGrid: document.getElementById("metricsGrid"),
  alertsList: document.getElementById("alertsList"),
  assetList: document.getElementById("assetList"),
  assetDetail: document.getElementById("assetDetail"),
  supervisorFlowBadge: document.getElementById("supervisorFlowBadge"),
  driverVehicleLabel: document.getElementById("driverVehicleLabel"),
  driverVehicleSelect: document.getElementById("driverVehicleSelect"),
  driverPrevVehicleBtn: document.getElementById("driverPrevVehicleBtn"),
  driverNextVehicleBtn: document.getElementById("driverNextVehicleBtn"),
  driverInstruction: document.getElementById("driverInstruction"),
  driverDistance: document.getElementById("driverDistance"),
  driverArrow: document.getElementById("driverArrow"),
  driverSpeed: document.getElementById("driverSpeed"),
  driverStatus: document.getElementById("driverStatus"),
  driverDestination: document.getElementById("driverDestination"),
  driverEta: document.getElementById("driverEta"),
  driverFlowBadge: document.getElementById("driverFlowBadge"),
  driverAlerts: document.getElementById("driverAlerts"),
  assetSearch: document.getElementById("assetSearch"),
  vehicleTypeFilter: document.getElementById("vehicleTypeFilter"),
  statusFilter: document.getElementById("statusFilter"),
  toggleRoutes: document.getElementById("toggleRoutes"),
  toggleTeams: document.getElementById("toggleTeams"),
  toggleCritical: document.getElementById("toggleCritical"),
  toggleZones: document.getElementById("toggleZones"),
  toggleTicks: document.getElementById("toggleTicks"),
  tickSecondsSelect: document.getElementById("tickSecondsSelect"),
  strategySelect: document.getElementById("strategySelect"),
  strategyHint: document.getElementById("strategyHint"),
  supervisorTabButtons: Array.from(document.querySelectorAll("[data-tab]")),
  supervisorTabPanels: Array.from(document.querySelectorAll("[data-tab-panel]")),
  startBtn: document.getElementById("startBtn"),
  pauseBtn: document.getElementById("pauseBtn"),
  stepBtn: document.getElementById("stepBtn"),
  resetBtn: document.getElementById("resetBtn"),
};

const state = {
  session: null,
  refreshTimer: null,
  supervisorSnapshot: null,
  driverSnapshot: null,
  driverSelectedVehicleId: null,
  activeAssetId: null,
  animationFrame: null,
  previousFrameAt: 0,
  routeCache: new Map(),
  routeVisibility: new Map(),
  teamMarkers: new Map(),
  eventMarkers: new Map(),
  zoneLayers: new Map(),
  criticalMarkers: new Map(),
  vehicleVisuals: new Map(),
  driverVehicleVisual: null,
  driverEventMarkers: new Map(),
  driverNumeric: {
    speed: { current: 0, target: 0 },
    eta: { current: 0, target: 0 },
    distance: { current: 0, target: 0 },
  },
  driverRouteSignature: "",
  driverFittedRoute: "",
  driverRouteBaseLine: null,
  driverRouteProgressLine: null,
  supervisorActiveTab: "filters",
};

const supervisorMap = L.map("supervisorMap", {
  zoomControl: true,
  attributionControl: true,
  preferCanvas: true,
}).setView(MAP_CENTER, 15);

const driverMap = L.map("driverMap", {
  zoomControl: false,
  attributionControl: true,
  dragging: false,
  scrollWheelZoom: false,
  doubleClickZoom: false,
  boxZoom: false,
  keyboard: false,
  preferCanvas: true,
}).setView(MAP_CENTER, 15);

[supervisorMap, driverMap].forEach((map) => {
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);
});

const layers = {
  supervisor: {
    zones: L.layerGroup().addTo(supervisorMap),
    routes: L.layerGroup().addTo(supervisorMap),
    assets: L.layerGroup().addTo(supervisorMap),
    teams: L.layerGroup().addTo(supervisorMap),
    critical: L.layerGroup().addTo(supervisorMap),
    events: L.layerGroup().addTo(supervisorMap),
  },
  driver: {
    route: L.layerGroup().addTo(driverMap),
    vehicle: L.layerGroup().addTo(driverMap),
    events: L.layerGroup().addTo(driverMap),
  },
};

function sessionToken() {
  return state.session?.token || localStorage.getItem(SESSION_KEY) || "";
}

function setSupervisorTab(tabId) {
  state.supervisorActiveTab = tabId;
  refs.supervisorTabButtons.forEach((button) => {
    const isActive = button.dataset.tab === tabId;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-selected", String(isActive));
  });
  refs.supervisorTabPanels.forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.tabPanel === tabId);
  });
  scheduleMapResize(supervisorMap);
}

function setSession(nextSession) {
  state.session = nextSession;
  if (nextSession?.token) {
    localStorage.setItem(SESSION_KEY, nextSession.token);
  } else {
    localStorage.removeItem(SESSION_KEY);
  }
}

async function api(path, options = {}) {
  const headers = {
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(options.headers || {}),
  };
  const token = sessionToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) {
    handleLogout(true);
    throw new Error("Sessao expirada");
  }
  if (!response.ok) {
    throw new Error(`Erro ${response.status}`);
  }
  const contentType = response.headers.get("Content-Type") || "";
  return contentType.includes("application/json") ? response.json() : response;
}

function svgSymbol(kind) {
  const symbols = {
    truck: `<path d="M7 17h2.2a2.8 2.8 0 1 0 5.6 0H17a2.8 2.8 0 1 0 5.6 0H25v-5.2L21.8 8H17V6H7z" fill="currentColor"/><circle cx="12" cy="17" r="1.6" fill="#070707"/><circle cx="20" cy="17" r="1.6" fill="#070707"/>`,
    utility: `<path d="M8 9.2 12.6 6H20l4 3.2V18H8z" fill="currentColor"/><circle cx="12" cy="18" r="1.6" fill="#070707"/><circle cx="20" cy="18" r="1.6" fill="#070707"/>`,
    pickup: `<path d="M7 15h6l2-4h6l4 4v4H7z" fill="currentColor"/><circle cx="12" cy="19" r="1.6" fill="#070707"/><circle cx="20" cy="19" r="1.6" fill="#070707"/>`,
    support: `<path d="M7 10h14l3 3v5H7z" fill="currentColor"/><path d="M10 8h8v2h-8z" fill="currentColor"/><circle cx="12" cy="18" r="1.6" fill="#070707"/><circle cx="20" cy="18" r="1.6" fill="#070707"/>`,
    train: `<path d="M10 7h12v10a6 6 0 0 1-12 0z" fill="currentColor"/><path d="M12 11h3M17 11h3M12 15h8" stroke="#070707" stroke-width="1.8" stroke-linecap="round"/><path d="M12 23l-2 3M20 23l2 3M13 24h6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>`,
    crane: `<path d="M9 25h14M11 25V10h4M15 10h8M19 10v4M15 14h6" stroke="currentColor" stroke-width="2.4" fill="none" stroke-linecap="round"/><path d="M21 14v5l-2 2" stroke="currentColor" stroke-width="2.4" fill="none" stroke-linecap="round"/>`,
    team: `<circle cx="16" cy="10" r="4" fill="currentColor"/><path d="M10 25c.6-5 3.5-8 6-8s5.4 3 6 8" stroke="currentColor" stroke-width="3" fill="none" stroke-linecap="round"/>`,
    warning: `<path d="M16 6 27 25H5z" fill="currentColor"/><path d="M16 12v6M16 22h.01" stroke="#070707" stroke-width="2.6" stroke-linecap="round"/>`,
    gate: `<path d="M8 24V8h4v16M20 24V8h4v16M8 10h16" stroke="currentColor" stroke-width="2.4" fill="none" stroke-linecap="round"/>`,
    rail: `<path d="M10 7h12l2 11-8 7-8-7z" fill="currentColor"/><path d="M12 10h8M10.5 14h11M10.8 18h10.4" stroke="#070707" stroke-width="1.6"/><path d="M12 22l-2 4M20 22l2 4" stroke="currentColor" stroke-width="2.2"/>`,
    pier: `<path d="M7 12h18M11 12v10M16 12v10M21 12v10M7 24c2-2 4-2 6 0 2-2 4-2 6 0 2-2 4-2 6 0" stroke="currentColor" stroke-width="2.2" fill="none" stroke-linecap="round"/>`,
    block: `<path d="M8 10h16v12H8z" fill="currentColor"/><path d="M10 12l12 8M22 12l-12 8" stroke="#070707" stroke-width="2.2"/>`,
  };
  return symbols[kind] || symbols.warning;
}

function makeIcon(kind, color, extraClass = "") {
  return L.divIcon({
    className: "",
    html: `<div class="map-icon ${extraClass}" style="color:${color}"><svg viewBox="0 0 32 32">${svgSymbol(kind)}</svg></div>`,
    iconSize: [34, 34],
    iconAnchor: [17, 17],
  });
}

function supportsVehicleHeading(vehicle) {
  return ["truck", "pickup", "support", "utility"].includes(vehicle?.type);
}

function assetIcon(vehicle, selected = false) {
  const iconKind = vehicle.type === "train"
    ? "train"
    : vehicle.type === "crane"
      ? "crane"
      : vehicle.type === "truck"
        ? "truck"
        : vehicle.type === "pickup"
          ? "pickup"
          : vehicle.type === "support"
            ? "support"
            : "utility";
  const colors = {
    idle: "#ececef",
    en_route: "#f6d470",
    assisting: "#90e4bc",
    returning: "#c1c5cd",
  };
  const selectedClass = selected ? "asset-selected" : "";
  return makeIcon(iconKind, colors[vehicle.status] || "#ececef", `vehicle-state-${vehicle.status} ${selectedClass}`.trim());
}

function teamIcon(active) {
  return makeIcon("team", active ? "#e7e9ef" : "#8f949d", active ? "team-active" : "");
}

function eventIcon(type) {
  return makeIcon(type === "block" ? "block" : "warning", type === "block" ? "#ff9b9b" : "#f6d470");
}

function zoneAnchorIcon(kind) {
  if (kind === "pier") return makeIcon("pier", "#d9dde6");
  if (kind === "rail") return makeIcon("rail", "#d9dde6");
  if (kind === "gate") return makeIcon("gate", "#d9dde6");
  return makeIcon("warning", "#d9dde6");
}

function fmtEta(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) return "-";
  const minutes = Math.max(1, Math.round(Number(seconds) / 60));
  return `${minutes} min`;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function lerp(current, target, factor) {
  return current + (target - current) * factor;
}

function formatDistance(meters) {
  const safeMeters = Math.max(0, Math.round(Number(meters) || 0));
  if (safeMeters >= 1000) {
    return `${(safeMeters / 1000).toFixed(1)} km ate a proxima acao`;
  }
  return `${safeMeters} m ate a proxima acao`;
}

function setDriverDirection(direction) {
  refs.driverArrow.classList.remove("direction-left", "direction-right", "direction-straight");
  refs.driverArrow.classList.add(`direction-${direction || "straight"}`);
}

function updateUserBadge() {
  if (!state.session?.user) {
    refs.userBadge.textContent = "";
    return;
  }
  refs.userBadge.textContent = `${state.session.user.name} | ${state.session.user.role === "driver" ? "Condutor" : "Supervisor"}`;
}

function scheduleMapResize(map) {
  requestAnimationFrame(() => {
    map.invalidateSize(false);
    setTimeout(() => map.invalidateSize(false), 120);
    setTimeout(() => map.invalidateSize(false), 280);
  });
}

function currentMode() {
  const hash = window.location.hash || "";
  if (hash.includes("condutor")) return "driver";
  if (hash.includes("supervisor")) return "supervisor";
  return state.session?.user?.role === "driver" ? "driver" : "supervisor";
}

function applyRoute(role) {
  if (!state.session?.user) {
    refs.loginScreen.classList.remove("hidden");
    refs.appLayout.classList.add("hidden");
    return;
  }

  refs.loginScreen.classList.add("hidden");
  refs.appLayout.classList.remove("hidden");

  const effectiveRole = role || state.session.user.role;
  const showDriver = currentMode() === "driver" || effectiveRole === "driver";

  refs.driverView.classList.toggle("hidden", !showDriver);
  refs.supervisorView.classList.toggle("hidden", showDriver);
  refs.viewTitle.textContent = showDriver ? "Modo Condutor" : "Modo Supervisor";

  if (showDriver) {
    scheduleMapResize(driverMap);
  } else {
    scheduleMapResize(supervisorMap);
  }
}

function clearRefreshTimer() {
  if (state.refreshTimer) {
    clearInterval(state.refreshTimer);
    state.refreshTimer = null;
  }
}

function handleLogout(silent = false) {
  setSession(null);
  clearRefreshTimer();
  state.supervisorSnapshot = null;
  state.driverSnapshot = null;
  state.activeAssetId = null;
  refs.assetDetail.textContent = "Selecione um ativo no mapa ou na lista.";
  if (!silent) {
    fetch("/api/auth/logout", { method: "POST" }).catch(() => null);
  }
  window.location.hash = "#/login";
  applyRoute();
}

function distanceBetween(from, to) {
  return supervisorMap.distance(from, to);
}

function toPlanar(point, referenceLat = MAP_CENTER[0]) {
  const latScale = 111320;
  const lonScale = 111320 * Math.cos((referenceLat * Math.PI) / 180);
  return {
    x: point[1] * lonScale,
    y: point[0] * latScale,
  };
}

function segmentHeading(from, to) {
  const deltaLat = to[0] - from[0];
  const deltaLon = to[1] - from[1];
  return (Math.atan2(-deltaLat, deltaLon) * 180) / Math.PI;
}

function normalizeAngle(angle) {
  let next = angle;
  while (next > 180) next -= 360;
  while (next < -180) next += 360;
  return next;
}

function angleDelta(from, to) {
  return normalizeAngle(to - from);
}

function clampRouteDistance(distance, totalDistance) {
  return clamp(distance, 0, Math.max(totalDistance || 0, 0));
}

function debugRouteEvent(visual, reason, extra = {}) {
  if (!DEBUG_ROUTE_ANIMATION) {
    return;
  }
  console.debug("[route-animation]", {
    assetId: visual.id,
    routeId: visual.routeId || "",
    visualDistance: Number(visual.visualRouteDistance || 0).toFixed(1),
    logicalDistance: Number(visual.logicalRouteDistance || 0).toFixed(1),
    snapshotDistance: Number(visual.snapshotRouteDistance || 0).toFixed(1),
    reason,
    ...extra,
  });
}

function buildRouteModel(routeGeometry = []) {
  if (!routeGeometry || routeGeometry.length < 2) {
    return null;
  }

  const cumulative = [0];
  const headings = [];
  let total = 0;
  for (let index = 0; index < routeGeometry.length - 1; index += 1) {
    const start = routeGeometry[index];
    const end = routeGeometry[index + 1];
    const segmentLength = distanceBetween(start, end);
    total += segmentLength;
    cumulative.push(total);
    headings.push(segmentHeading(start, end));
  }

  return {
    points: routeGeometry,
    cumulative,
    headings,
    total,
  };
}

function interpolateAlongRoute(routeModel, distance) {
  if (!routeModel || routeModel.points.length < 2) {
    return null;
  }

  const clampedDistance = clampRouteDistance(distance, routeModel.total);
  for (let index = 0; index < routeModel.points.length - 1; index += 1) {
    const segmentStartDistance = routeModel.cumulative[index];
    const segmentEndDistance = routeModel.cumulative[index + 1];
    if (clampedDistance <= segmentEndDistance || index === routeModel.points.length - 2) {
      const segmentLength = Math.max(segmentEndDistance - segmentStartDistance, 0.001);
      const ratio = clamp((clampedDistance - segmentStartDistance) / segmentLength, 0, 1);
      const start = routeModel.points[index];
      const end = routeModel.points[index + 1];
      return {
        lat: start[0] + (end[0] - start[0]) * ratio,
        lon: start[1] + (end[1] - start[1]) * ratio,
        heading: routeModel.headings[index] ?? 0,
        segmentIndex: index,
      };
    }
  }

  const lastPoint = routeModel.points[routeModel.points.length - 1];
  return {
    lat: lastPoint[0],
    lon: lastPoint[1],
    heading: routeModel.headings[routeModel.headings.length - 1] ?? 0,
    segmentIndex: routeModel.points.length - 2,
  };
}

function sliceRouteToDistance(routeModel, distance) {
  if (!routeModel || routeModel.points.length < 2) {
    return [];
  }
  const clampedDistance = clampRouteDistance(distance, routeModel.total);
  const coords = [routeModel.points[0]];
  for (let index = 0; index < routeModel.points.length - 1; index += 1) {
    const segmentStartDistance = routeModel.cumulative[index];
    const segmentEndDistance = routeModel.cumulative[index + 1];
    const start = routeModel.points[index];
    const end = routeModel.points[index + 1];
    if (clampedDistance >= segmentEndDistance) {
      coords.push(end);
      continue;
    }
    if (clampedDistance > segmentStartDistance) {
      const segmentLength = Math.max(segmentEndDistance - segmentStartDistance, 0.001);
      const ratio = clamp((clampedDistance - segmentStartDistance) / segmentLength, 0, 1);
      coords.push([
        start[0] + (end[0] - start[0]) * ratio,
        start[1] + (end[1] - start[1]) * ratio,
      ]);
    }
    break;
  }
  return coords;
}

function projectPointToRoute(point, routeModel) {
  if (!routeModel || routeModel.points.length < 2) {
    return {
      distance: 0,
      point,
      heading: 0,
    };
  }

  const referenceLat = point[0];
  const source = toPlanar(point, referenceLat);
  let best = {
    distanceToRoute: Number.POSITIVE_INFINITY,
    distance: 0,
    point: routeModel.points[0],
    heading: routeModel.headings[0] ?? 0,
  };

  for (let index = 0; index < routeModel.points.length - 1; index += 1) {
    const start = routeModel.points[index];
    const end = routeModel.points[index + 1];
    const startXY = toPlanar(start, referenceLat);
    const endXY = toPlanar(end, referenceLat);
    const segmentX = endXY.x - startXY.x;
    const segmentY = endXY.y - startXY.y;
    const segmentLengthSquared = Math.max(segmentX * segmentX + segmentY * segmentY, 0.0001);
    const rawProjection = ((source.x - startXY.x) * segmentX + (source.y - startXY.y) * segmentY) / segmentLengthSquared;
    const t = clamp(rawProjection, 0, 1);
    const projected = {
      x: startXY.x + segmentX * t,
      y: startXY.y + segmentY * t,
    };
    const dx = source.x - projected.x;
    const dy = source.y - projected.y;
    const distanceToRoute = Math.sqrt(dx * dx + dy * dy);
    if (distanceToRoute < best.distanceToRoute) {
      const segmentDistance = routeModel.cumulative[index] + (routeModel.cumulative[index + 1] - routeModel.cumulative[index]) * t;
      best = {
        distanceToRoute,
        distance: segmentDistance,
        point: [
          start[0] + (end[0] - start[0]) * t,
          start[1] + (end[1] - start[1]) * t,
        ],
        heading: routeModel.headings[index] ?? 0,
      };
    }
  }

  return best;
}

function chooseRouteDistanceForReplan(currentVisualProjection, logicalProjection) {
  const projectedDelta = logicalProjection.distance - currentVisualProjection.distance;
  if (projectedDelta >= -ROUTE_COMPATIBILITY_WINDOW_M) {
    return Math.max(currentVisualProjection.distance, logicalProjection.distance);
  }
  return logicalProjection.distance;
}

function setMarkerHeading(visual, heading) {
  const iconNode = visual.marker?._icon?.querySelector(".map-icon");
  if (!iconNode) {
    return;
  }
  if (!visual.rotatesWithHeading) {
    visual.displayHeading = 0;
    iconNode.style.transform = "rotate(0deg)";
    iconNode.style.transformOrigin = "50% 50%";
    return;
  }
  const normalizedTarget = normalizeAngle(heading || 0);
  if (typeof visual.displayHeading !== "number") {
    visual.displayHeading = normalizedTarget;
  }
  visual.displayHeading = normalizeAngle(visual.displayHeading + angleDelta(visual.displayHeading, normalizedTarget) * 0.18);
  iconNode.style.transform = `rotate(${visual.displayHeading}deg)`;
  iconNode.style.transformOrigin = "50% 50%";
}

function setMarkerPosition(visual, lat, lon) {
  visual.displayLat = lat;
  visual.displayLon = lon;
  visual.targetLat = lat;
  visual.targetLon = lon;
  visual.visualRouteDistance = 0;
  visual.snapshotRouteDistance = 0;
  visual.marker.setLatLng([lat, lon]);
}

function ensureVehicleVisual(vehicle) {
  let visual = state.vehicleVisuals.get(vehicle.id);
  if (!visual) {
    const marker = L.marker([vehicle.lat, vehicle.lon], {
      icon: assetIcon(vehicle, state.activeAssetId === vehicle.id),
      zIndexOffset: state.activeAssetId === vehicle.id ? 900 : 600,
    });
    marker.on("click", () => selectAsset(vehicle.id));
    marker.addTo(layers.supervisor.assets);
    visual = {
      id: vehicle.id,
      marker,
      data: vehicle,
      displayLat: vehicle.lat,
      displayLon: vehicle.lon,
      targetLat: vehicle.lat,
      targetLon: vehicle.lon,
      routeModel: null,
      routeId: "",
      routeSignature: "",
      visualRouteDistance: 0,
      logicalRouteDistance: 0,
      maxRouteDistance: 0,
      snapshotRouteDistance: 0,
      snapshotAt: performance.now(),
      logicalSpeedMps: 0,
      displayHeading: 0,
      rotatesWithHeading: supportsVehicleHeading(vehicle),
      visible: true,
    };
    state.vehicleVisuals.set(vehicle.id, visual);
  }
  return visual;
}

function syncVisualRouteState(visual, vehicle) {
  const signature = routeSignature(vehicle.route_geometry || []);
  const routeId = vehicle.route_id || signature;
  const backendRouteDistance = Math.max(0, Number(vehicle.route_progress_m || 0));
  visual.logicalSpeedMps = Number(vehicle.speed_kmh || 0) * (1000 / 3600);
  visual.snapshotAt = performance.now();

  if (!vehicle.route_geometry || vehicle.route_geometry.length < 2) {
    visual.routeModel = null;
    visual.routeId = "";
    visual.routeSignature = "";
    visual.logicalRouteDistance = 0;
    visual.maxRouteDistance = 0;
    visual.snapshotRouteDistance = 0;
    visual.visualRouteDistance = 0;
    debugRouteEvent(visual, "route-cleared");
    return;
  }

  if (visual.routeId !== routeId || visual.routeSignature !== signature) {
    const nextRouteModel = buildRouteModel(vehicle.route_geometry);
    const currentVisualProjection = projectPointToRoute([visual.displayLat, visual.displayLon], nextRouteModel);
    const logicalProjection = projectPointToRoute([vehicle.lat, vehicle.lon], nextRouteModel);
    const projectedBackendDistance = backendRouteDistance > 0
      ? clampRouteDistance(backendRouteDistance, nextRouteModel.total)
      : logicalProjection.distance;
    const anchoredDistance = clampRouteDistance(
      chooseRouteDistanceForReplan(currentVisualProjection, { ...logicalProjection, distance: projectedBackendDistance }),
      nextRouteModel.total,
    );
    visual.routeModel = nextRouteModel;
    visual.routeId = routeId;
    visual.routeSignature = signature;
    visual.visualRouteDistance = anchoredDistance;
    visual.logicalRouteDistance = anchoredDistance;
    visual.maxRouteDistance = anchoredDistance;
    visual.snapshotRouteDistance = projectedBackendDistance;
    const anchored = interpolateAlongRoute(nextRouteModel, anchoredDistance);
    if (anchored) {
      visual.displayLat = anchored.lat;
      visual.displayLon = anchored.lon;
      visual.marker.setLatLng([anchored.lat, anchored.lon]);
      setMarkerHeading(visual, anchored.heading);
    }
    debugRouteEvent(visual, "route-changed", {
      backendRouteDistance: projectedBackendDistance.toFixed(1),
      projectedDistance: logicalProjection.distance.toFixed(1),
    });
    return;
  }

  if (!visual.routeModel) {
    visual.routeModel = buildRouteModel(vehicle.route_geometry);
  }
  const logicalProjection = projectPointToRoute([vehicle.lat, vehicle.lon], visual.routeModel);
  const projectedBackendDistance = backendRouteDistance > 0
    ? clampRouteDistance(backendRouteDistance, visual.routeModel.total)
    : logicalProjection.distance;
  const regressedBy = visual.logicalRouteDistance - projectedBackendDistance;

  if (regressedBy > ROUTE_REGRESSION_TOLERANCE_M) {
    visual.snapshotRouteDistance = visual.logicalRouteDistance;
    debugRouteEvent(visual, "blocked-regression", {
      receivedDistance: projectedBackendDistance.toFixed(1),
      regressedBy: regressedBy.toFixed(1),
    });
    return;
  }

  const nextLogicalDistance = Math.max(visual.logicalRouteDistance, projectedBackendDistance);
  visual.logicalRouteDistance = clampRouteDistance(nextLogicalDistance, visual.routeModel.total);
  visual.maxRouteDistance = Math.max(visual.maxRouteDistance, visual.logicalRouteDistance);
  visual.snapshotRouteDistance = visual.logicalRouteDistance;
  debugRouteEvent(visual, "accepted-snapshot", {
    receivedDistance: projectedBackendDistance.toFixed(1),
  });
}

function updateVehicleVisual(vehicle) {
  const visual = ensureVehicleVisual(vehicle);
  visual.data = vehicle;
  visual.rotatesWithHeading = supportsVehicleHeading(vehicle);
  visual.targetLat = vehicle.lat;
  visual.targetLon = vehicle.lon;
  syncVisualRouteState(visual, vehicle);

  if (!visual.routeModel && distanceBetween([visual.displayLat, visual.displayLon], [vehicle.lat, vehicle.lon]) > LERP_SNAP_METERS) {
    setMarkerPosition(visual, vehicle.lat, vehicle.lon);
  }

  visual.marker.setIcon(assetIcon(vehicle, state.activeAssetId === vehicle.id));
  visual.marker.setZIndexOffset(state.activeAssetId === vehicle.id ? 900 : 600);
  visual.marker.setPopupContent(
    `<strong>${vehicle.id}</strong><br>${vehicle.type}<br>${vehicle.status}<br>ETA: ${fmtEta(vehicle.eta_seconds)}`
  );

  if (!visual.visible) {
    visual.marker.addTo(layers.supervisor.assets);
    visual.visible = true;
  }
}

function syncVehicleVisuals(vehicles) {
  const present = new Set();
  vehicles.forEach((vehicle) => {
    present.add(vehicle.id);
    updateVehicleVisual(vehicle);
  });

  state.vehicleVisuals.forEach((visual, vehicleId) => {
    if (!present.has(vehicleId)) {
      layers.supervisor.assets.removeLayer(visual.marker);
      state.vehicleVisuals.delete(vehicleId);
    }
  });
}

function routeSignature(routeGeometry = []) {
  return routeGeometry.map((point) => `${point[0].toFixed(5)}:${point[1].toFixed(5)}`).join("|");
}

function updateRouteLayers(vehicles) {
  const showRoutes = refs.toggleRoutes.checked;
  const visibleIds = new Set();
  const scopedVehicles = state.activeAssetId
    ? vehicles.filter((vehicle) => vehicle.id === state.activeAssetId)
    : vehicles;

  scopedVehicles.forEach((vehicle) => {
    if (!vehicle.route_geometry || vehicle.route_geometry.length < 2) {
      return;
    }

    const key = vehicle.id;
    const signature = routeSignature(vehicle.route_geometry);
    visibleIds.add(key);

    let line = state.routeCache.get(key);
    if (!line) {
      line = L.polyline(vehicle.route_geometry, {
        color: "#f1f2f4",
        weight: state.activeAssetId === vehicle.id ? 5 : 3,
        opacity: 0.52,
        interactive: false,
      });
      state.routeCache.set(key, line);
    }

    if (state.routeVisibility.get(key) !== signature) {
      line.setLatLngs(vehicle.route_geometry);
      state.routeVisibility.set(key, signature);
    }

    line.setStyle({
      weight: state.activeAssetId === vehicle.id ? 5 : 3,
      opacity: showRoutes ? (state.activeAssetId === vehicle.id ? 0.78 : 0.46) : 0,
    });

    if (showRoutes && !layers.supervisor.routes.hasLayer(line)) {
      line.addTo(layers.supervisor.routes);
    }
    if (!showRoutes && layers.supervisor.routes.hasLayer(line)) {
      layers.supervisor.routes.removeLayer(line);
    }
  });

  state.routeCache.forEach((line, vehicleId) => {
    if (!visibleIds.has(vehicleId)) {
      layers.supervisor.routes.removeLayer(line);
      state.routeCache.delete(vehicleId);
      state.routeVisibility.delete(vehicleId);
    }
  });
}

function updateTeamMarkers(teams) {
  const showTeams = refs.toggleTeams.checked && !state.activeAssetId;
  const present = new Set();

  teams.forEach((team) => {
    present.add(team.id);
    let marker = state.teamMarkers.get(team.id);
    if (!marker) {
      marker = L.marker([team.lat, team.lon], {
        icon: teamIcon(team.active_request),
        zIndexOffset: 450,
      }).bindPopup(`<strong>${team.id}</strong><br>${team.role}<br>${team.zone_id}`);
      state.teamMarkers.set(team.id, marker);
    }

    marker.setLatLng([team.lat, team.lon]);
    marker.setIcon(teamIcon(team.active_request));
    marker.setPopupContent(`<strong>${team.id}</strong><br>${team.role}<br>${team.zone_id}`);

    if (showTeams && !layers.supervisor.teams.hasLayer(marker)) {
      marker.addTo(layers.supervisor.teams);
    }
    if (!showTeams && layers.supervisor.teams.hasLayer(marker)) {
      layers.supervisor.teams.removeLayer(marker);
    }
  });

  state.teamMarkers.forEach((marker, teamId) => {
    if (!present.has(teamId)) {
      layers.supervisor.teams.removeLayer(marker);
      state.teamMarkers.delete(teamId);
    }
  });
}

function renderZones(zones) {
  if (!refs.toggleZones.checked) {
    layers.supervisor.zones.clearLayers();
    state.zoneLayers.clear();
    state.zoneSignature = "";
    return;
  }
  const signature = JSON.stringify(zones.map((zone) => [zone.id, zone.vehicle_density, zone.waiting_teams]));
  if (state.zoneSignature === signature) {
    return;
  }
  state.zoneSignature = signature;
  layers.supervisor.zones.clearLayers();
  state.zoneLayers.clear();

  zones.forEach((zone) => {
    const circle = L.circle(zone.center, {
      radius: zone.radius_m,
      color: "#6f737d",
      weight: 1,
      fillColor: zone.color,
      fillOpacity: 0.07,
      interactive: false,
    });
    circle.bindTooltip(`${zone.label}<br>Veiculos: ${zone.vehicle_density}<br>Demandas: ${zone.waiting_teams}`);
    circle.addTo(layers.supervisor.zones);

    const marker = L.marker(zone.center, { icon: zoneAnchorIcon(zone.icon), interactive: false });
    marker.addTo(layers.supervisor.zones);
    state.zoneLayers.set(zone.id, { circle, marker });
  });
}

function renderCriticalPoints(points) {
  const showCritical = refs.toggleCritical.checked;
  const present = new Set();

  points.forEach((point) => {
    present.add(point.id);
    let marker = state.criticalMarkers.get(point.id);
    if (!marker) {
      marker = L.marker(point.position, { icon: zoneAnchorIcon(point.icon), interactive: true }).bindTooltip(point.label);
      state.criticalMarkers.set(point.id, marker);
    }
    marker.setLatLng(point.position);
    marker.setTooltipContent(point.label);
    if (showCritical && !layers.supervisor.critical.hasLayer(marker)) {
      marker.addTo(layers.supervisor.critical);
    }
    if (!showCritical && layers.supervisor.critical.hasLayer(marker)) {
      layers.supervisor.critical.removeLayer(marker);
    }
  });

  state.criticalMarkers.forEach((marker, id) => {
    if (!present.has(id)) {
      layers.supervisor.critical.removeLayer(marker);
      state.criticalMarkers.delete(id);
    }
  });
}

function edgeMidpoint(event, snapshot) {
  const edge = snapshot.graph.edges.find(
    (item) => item.from === event.edge?.[0] && item.to === event.edge?.[1] && item.key === event.edge_key
  );
  if (!edge?.coordinates?.length) {
    return snapshot.meta?.port_center ? [snapshot.meta.port_center.lat, snapshot.meta.port_center.lon] : MAP_CENTER;
  }
  return edge.coordinates[Math.floor(edge.coordinates.length / 2)];
}

function renderSupervisorEvents(events, snapshot) {
  const present = new Set();

  events.forEach((event) => {
    present.add(event.id);
    const position = edgeMidpoint(event, snapshot);
    let marker = state.eventMarkers.get(event.id);
    if (!marker) {
      marker = L.marker(position, { icon: eventIcon(event.event_type || "congestion"), zIndexOffset: 700 })
        .bindTooltip(event.message || event.event_type || "Evento");
      state.eventMarkers.set(event.id, marker);
    }
    marker.setLatLng(position);
    marker.setIcon(eventIcon(event.event_type || "congestion"));
    marker.setTooltipContent(event.message || event.event_type || "Evento");
    if (!layers.supervisor.events.hasLayer(marker)) {
      marker.addTo(layers.supervisor.events);
    }
  });

  state.eventMarkers.forEach((marker, id) => {
    if (!present.has(id)) {
      layers.supervisor.events.removeLayer(marker);
      state.eventMarkers.delete(id);
    }
  });
}

function filteredVehicles(snapshot) {
  const search = refs.assetSearch.value.trim().toLowerCase();
  const typeFilter = refs.vehicleTypeFilter.value;
  const statusFilter = refs.statusFilter.value;

  return snapshot.vehicles.filter((vehicle) => {
    const matchesSearch = !search || vehicle.id.toLowerCase().includes(search);
    const matchesType = typeFilter === "all" || vehicle.type === typeFilter;
    const matchesStatus = statusFilter === "all" || vehicle.status === statusFilter;
    return matchesSearch && matchesType && matchesStatus;
  });
}

function syncVehicleVisibility(visibleVehicles) {
  const visibleIds = new Set(visibleVehicles.map((vehicle) => vehicle.id));
  state.vehicleVisuals.forEach((visual, vehicleId) => {
    const shouldShow = state.activeAssetId ? vehicleId === state.activeAssetId : visibleIds.has(vehicleId);
    if (shouldShow && !visual.visible) {
      visual.marker.addTo(layers.supervisor.assets);
      visual.visible = true;
    }
    if (!shouldShow && visual.visible) {
      layers.supervisor.assets.removeLayer(visual.marker);
      visual.visible = false;
    }
  });
}

function renderAssetList(snapshot) {
  const vehicles = filteredVehicles(snapshot);
  refs.assetList.innerHTML = vehicles.length
    ? vehicles.map((vehicle) => `
        <div class="asset-item ${state.activeAssetId === vehicle.id ? "active" : ""}" data-asset-id="${vehicle.id}">
          <strong>${vehicle.id}</strong>
          <span>${vehicle.type} | ${vehicle.status}</span>
          <small>${vehicle.current_zone_id} -> ${vehicle.base_zone_id}</small>
        </div>
      `).join("")
    : `<div class="event-item">Nenhum ativo corresponde aos filtros atuais.</div>`;

  refs.assetList.querySelectorAll("[data-asset-id]").forEach((node) => {
    node.addEventListener("click", () => selectAsset(node.dataset.assetId));
  });

  syncVehicleVisibility(vehicles);
}

function renderMetrics(metrics) {
  const entries = [
    ["Veiculos ativos", metrics.active_vehicles],
    ["Veiculos totais", metrics.vehicles_total],
    ["Equipes aguardando", metrics.teams_waiting],
    ["Bloqueios", metrics.blocked_segments],
    ["Velocidade media", `${Math.round(metrics.avg_speed_kmh || 0)} km/h`],
    ["Tempo medio", fmtEta(metrics.avg_travel_time_s)],
  ];

  refs.metricsGrid.innerHTML = entries
    .map(([label, value]) => `<div class="metric-card"><span class="label">${label}</span><span class="value">${value}</span></div>`)
    .join("");

  refs.supervisorFlowBadge.textContent = metrics.dominant_flow || "-";
}

function renderAlerts(alerts = []) {
  refs.alertsList.innerHTML = alerts.length
    ? alerts
        .slice(0, 6)
        .map((alert) => `<div class="event-item"><strong>${alert.message}</strong><div>Zona: ${alert.zone_id || "n/a"}</div></div>`)
        .join("")
    : `<div class="event-item">Sem alertas ativos.</div>`;
}

function renderAssetDetail(asset) {
  if (!asset) {
    refs.assetDetail.textContent = "Selecione um ativo no mapa ou na lista.";
    return;
  }

  const rows = Object.entries(asset)
    .filter(([key]) => !["history", "position", "kind"].includes(key))
    .map(([key, value]) => `<div><strong>${key}</strong><br>${value ?? "-"}</div>`)
    .join("");

  refs.assetDetail.innerHTML = `
    <div class="panel-header">
      <strong>${asset.id}</strong>
      <button id="clearAssetFocusBtn" class="ghost">Mostrar todos</button>
    </div>
    <div class="detail-grid">${rows}</div>
  `;
  document.getElementById("clearAssetFocusBtn")?.addEventListener("click", () => clearAssetFocus());
}

async function selectAsset(assetId) {
  if (state.activeAssetId === assetId) {
    clearAssetFocus();
    return;
  }
  state.activeAssetId = assetId;
  setSupervisorTab("detail");
  if (!state.session?.user) return;
  const detail = await api(`/api/assets/${assetId}`);
  renderAssetDetail(detail);

  state.vehicleVisuals.forEach((visual) => {
    visual.marker.setIcon(assetIcon(visual.data, visual.id === state.activeAssetId));
    visual.marker.setZIndexOffset(visual.id === state.activeAssetId ? 900 : 600);
  });

  if (state.supervisorSnapshot) {
    renderAssetList(state.supervisorSnapshot);
    updateRouteLayers(filteredVehicles(state.supervisorSnapshot));
    updateTeamMarkers(state.supervisorSnapshot.teams || []);
  }
}

function clearAssetFocus() {
  state.activeAssetId = null;
  renderAssetDetail(null);

  state.vehicleVisuals.forEach((visual) => {
    visual.marker.setIcon(assetIcon(visual.data, false));
    visual.marker.setZIndexOffset(600);
  });

  if (state.supervisorSnapshot) {
    renderAssetList(state.supervisorSnapshot);
    updateRouteLayers(filteredVehicles(state.supervisorSnapshot));
    updateTeamMarkers(state.supervisorSnapshot.teams || []);
  }
}

function syncDriverRoute(routeGeometry) {
  const signature = routeSignature(routeGeometry || []);
  if (state.driverRouteSignature === signature) {
    return;
  }
  state.driverRouteSignature = signature;
  layers.driver.route.clearLayers();
  state.driverRouteBaseLine = null;
  state.driverRouteProgressLine = null;

  if (!routeGeometry || routeGeometry.length < 2) {
    return;
  }

  state.driverRouteBaseLine = L.polyline(routeGeometry, {
    color: "#ffffff",
    weight: 5,
    opacity: 0.26,
    lineJoin: "round",
    lineCap: "round",
  }).addTo(layers.driver.route);

  state.driverRouteProgressLine = L.polyline([routeGeometry[0]], {
    color: "#ffffff",
    weight: 6,
    opacity: 0.9,
    lineJoin: "round",
    lineCap: "round",
  }).addTo(layers.driver.route);

  if (state.driverFittedRoute !== signature) {
    driverMap.fitBounds(state.driverRouteBaseLine.getBounds(), { padding: [30, 30] });
    state.driverFittedRoute = signature;
  }
}

function updateDriverRouteProgress() {
  if (!state.driverRouteProgressLine || !state.driverVehicleVisual?.routeModel) {
    return;
  }
  const progressCoords = sliceRouteToDistance(
    state.driverVehicleVisual.routeModel,
    state.driverVehicleVisual.visualRouteDistance,
  );
  if (progressCoords.length >= 2) {
    state.driverRouteProgressLine.setLatLngs(progressCoords);
  }
}

function syncDriverVehicle(snapshot) {
  const vehicle = snapshot.vehicle;
  if (!state.driverVehicleVisual) {
    const marker = L.marker([vehicle.lat, vehicle.lon], {
      icon: assetIcon(vehicle, true),
      zIndexOffset: 900,
    }).addTo(layers.driver.vehicle);
    state.driverVehicleVisual = {
      marker,
      displayLat: vehicle.lat,
      displayLon: vehicle.lon,
      targetLat: vehicle.lat,
      targetLon: vehicle.lon,
      routeModel: null,
      routeId: "",
      routeSignature: "",
      visualRouteDistance: 0,
      logicalRouteDistance: 0,
      maxRouteDistance: 0,
      snapshotRouteDistance: 0,
      snapshotAt: performance.now(),
      logicalSpeedMps: 0,
      displayHeading: 0,
      rotatesWithHeading: supportsVehicleHeading(vehicle),
      data: vehicle,
    };
  }

  const visual = state.driverVehicleVisual;
  visual.data = vehicle;
  visual.rotatesWithHeading = supportsVehicleHeading(vehicle);
  visual.targetLat = vehicle.lat;
  visual.targetLon = vehicle.lon;
  visual.marker.setIcon(assetIcon(vehicle, true));
  syncVisualRouteState(visual, vehicle);

  if (!visual.routeModel && driverMap.distance([visual.displayLat, visual.displayLon], [vehicle.lat, vehicle.lon]) > LERP_SNAP_METERS) {
    setMarkerPosition(visual, vehicle.lat, vehicle.lon);
  }
}

function syncDriverEvents(snapshot) {
  const present = new Set();
  snapshot.events.forEach((event) => {
    const key = event.id;
    present.add(key);
    const position = [snapshot.vehicle.lat, snapshot.vehicle.lon];
    let marker = state.driverEventMarkers.get(key);
    if (!marker) {
      marker = L.marker(position, { icon: eventIcon(event.event_type || "congestion"), zIndexOffset: 800 }).addTo(layers.driver.events);
      state.driverEventMarkers.set(key, marker);
    }
    marker.setLatLng(position);
    marker.setIcon(eventIcon(event.event_type || "congestion"));
  });

  state.driverEventMarkers.forEach((marker, key) => {
    if (!present.has(key)) {
      layers.driver.events.removeLayer(marker);
      state.driverEventMarkers.delete(key);
    }
  });
}

function updateDriverText(snapshot) {
  refs.driverVehicleLabel.textContent = `${snapshot.vehicle.id} | ${snapshot.vehicle.type}`;
  refs.driverInstruction.textContent = snapshot.navigation.primary;
  refs.driverStatus.textContent = snapshot.vehicle.status;
  refs.driverDestination.textContent = snapshot.destination || "-";
  refs.driverFlowBadge.textContent = snapshot.vehicle.flow_type || "-";
  refs.driverAlerts.innerHTML = snapshot.alerts
    .map((alert) => `<div class="alert-chip">${alert}</div>`)
    .join("");
  setDriverDirection(snapshot.navigation.direction || "straight");

  state.driverNumeric.speed.target = Number(snapshot.vehicle.speed_kmh || 0);
  state.driverNumeric.distance.target = Number(snapshot.navigation.distance_to_action_m || 0);
  state.driverNumeric.eta.target = Number(snapshot.eta_seconds || 0);
}

function syncDriverVehicleOptions(snapshot) {
  const options = snapshot.vehicle_options || [];
  const selectedId = snapshot.selected_vehicle_id || snapshot.vehicle?.id;
  state.driverSelectedVehicleId = selectedId;
  refs.driverVehicleSelect.innerHTML = options
    .map((vehicle) => `<option value="${vehicle.id}" ${vehicle.id === selectedId ? "selected" : ""}>${vehicle.id} | ${vehicle.type}</option>`)
    .join("");
}

function cycleDriverVehicle(step) {
  const options = Array.from(refs.driverVehicleSelect.options).map((option) => option.value).filter(Boolean);
  if (!options.length) return;
  const currentIndex = Math.max(0, options.indexOf(state.driverSelectedVehicleId || refs.driverVehicleSelect.value || options[0]));
  const nextIndex = (currentIndex + step + options.length) % options.length;
  state.driverSelectedVehicleId = options[nextIndex];
  refs.driverVehicleSelect.value = options[nextIndex];
  refreshDashboard().catch(() => null);
}

function syncSupervisorSnapshot(snapshot) {
  state.supervisorSnapshot = snapshot;
  const visibleVehicles = filteredVehicles(snapshot);
  refs.toggleTicks.checked = Boolean(snapshot.meta?.ticks_enabled);
  refs.tickSecondsSelect.value = String(snapshot.meta?.tick_mode_seconds || 10);
  refs.tickSecondsSelect.disabled = !refs.toggleTicks.checked;
  refs.strategySelect.value = snapshot.meta?.strategy || "rule";
  refs.strategyHint.textContent = snapshot.meta?.model_loaded
    ? `Estrategia atual: ${refs.strategySelect.value === "ml" ? "IA / ML" : "Regra deterministica"}.`
    : "Modelo de IA nao carregado; o modo ML faz fallback para a regra.";
  renderMetrics(snapshot.metrics);
  renderAlerts(snapshot.alerts || []);
  renderZones(snapshot.zones || []);
  renderCriticalPoints(snapshot.critical_points || []);
  renderSupervisorEvents(snapshot.events || [], snapshot);
  syncVehicleVisuals(snapshot.vehicles || []);
  updateTeamMarkers(snapshot.teams || []);
  updateRouteLayers(visibleVehicles);
  renderAssetList(snapshot);

  if (state.activeAssetId) {
    const selected = snapshot.assets?.find((asset) => asset.id === state.activeAssetId);
    if (selected) {
      renderAssetDetail(selected);
    }
  }
}

async function updateRuntimeSettings() {
  await api("/api/runtime", {
    method: "POST",
    body: JSON.stringify({
      ticks_enabled: refs.toggleTicks.checked,
      tick_seconds: Number(refs.tickSecondsSelect.value || 10),
    }),
  });
  await refreshDashboard();
}

async function updateStrategySettings() {
  await api("/api/strategy", {
    method: "POST",
    body: JSON.stringify({
      strategy: refs.strategySelect.value || "rule",
    }),
  });
  await refreshDashboard();
}

function syncDriverSnapshot(snapshot) {
  state.driverSnapshot = snapshot;
  syncDriverVehicleOptions(snapshot);
  updateDriverText(snapshot);
  syncDriverRoute(snapshot.route_geometry || []);
  syncDriverVehicle(snapshot);
  syncDriverEvents(snapshot);
}

function animateNumber(channel, dt) {
  const factor = 1 - Math.pow(0.12, dt / 16.67);
  channel.current = lerp(channel.current, channel.target, clamp(factor, 0.08, 0.3));
  if (Math.abs(channel.current - channel.target) < 0.02) {
    channel.current = channel.target;
  }
}

function updateDriverNumericUI() {
  refs.driverSpeed.textContent = `${Math.round(state.driverNumeric.speed.current)} km/h`;
  refs.driverDistance.textContent = formatDistance(state.driverNumeric.distance.current);
  refs.driverEta.textContent = fmtEta(state.driverNumeric.eta.current);
}

function animateVisualPosition(visual, dt, map, frameAt) {
  if (visual.routeModel && visual.routeModel.total > 0) {
    const logicalElapsedSeconds = Math.min(
      Math.max(0, (frameAt - visual.snapshotAt) / 1000),
      (DATA_REFRESH_MS / 1000) * 1.35,
    );
    const predictedLogicalDistance = clampRouteDistance(
      Math.max(visual.snapshotRouteDistance, visual.logicalRouteDistance) + visual.logicalSpeedMps * logicalElapsedSeconds,
      visual.routeModel.total,
    );
    const targetDistance = Math.max(
      visual.visualRouteDistance,
      visual.logicalRouteDistance,
      predictedLogicalDistance,
      visual.maxRouteDistance,
    );
    const visualSpeedMps = Math.max(visual.logicalSpeedMps, 0);
    const minimumCrawlMps = visualSpeedMps > 0.4 ? 0.85 : 0;
    const frameAdvance = Math.max(visualSpeedMps, minimumCrawlMps) * (dt / 1000);

    if (targetDistance - visual.visualRouteDistance <= Math.max(frameAdvance, 0.15)) {
      visual.visualRouteDistance = targetDistance;
    } else {
      visual.visualRouteDistance = clampRouteDistance(
        visual.visualRouteDistance + frameAdvance,
        visual.routeModel.total,
      );
    }
    visual.maxRouteDistance = Math.max(visual.maxRouteDistance, visual.visualRouteDistance);

    const routedPosition = interpolateAlongRoute(visual.routeModel, visual.visualRouteDistance);
    if (routedPosition) {
      visual.displayLat = routedPosition.lat;
      visual.displayLon = routedPosition.lon;
      visual.marker.setLatLng([routedPosition.lat, routedPosition.lon]);
      setMarkerHeading(visual, routedPosition.heading);
      return;
    }
  }

  const factor = 1 - Math.pow(0.08, dt / 16.67);
  visual.displayLat = lerp(visual.displayLat, visual.targetLat, clamp(factor, 0.08, 0.32));
  visual.displayLon = lerp(visual.displayLon, visual.targetLon, clamp(factor, 0.08, 0.32));

  const current = [visual.displayLat, visual.displayLon];
  const target = [visual.targetLat, visual.targetLon];
  if (map.distance(current, target) < 1) {
    visual.displayLat = visual.targetLat;
    visual.displayLon = visual.targetLon;
  }
  visual.marker.setLatLng([visual.displayLat, visual.displayLon]);
}

function renderLoop(frameAt) {
  if (!state.previousFrameAt) {
    state.previousFrameAt = frameAt;
  }
  const dt = clamp(frameAt - state.previousFrameAt, 8, 34);
  state.previousFrameAt = frameAt;

  state.vehicleVisuals.forEach((visual) => {
    if (visual.visible) {
      animateVisualPosition(visual, dt, supervisorMap, frameAt);
    }
  });

  if (state.driverVehicleVisual) {
    animateVisualPosition(state.driverVehicleVisual, dt, driverMap, frameAt);
    updateDriverRouteProgress();
    driverMap.panTo([state.driverVehicleVisual.displayLat, state.driverVehicleVisual.displayLon], {
      animate: false,
      noMoveStart: true,
    });
  }

  animateNumber(state.driverNumeric.speed, dt);
  animateNumber(state.driverNumeric.distance, dt);
  animateNumber(state.driverNumeric.eta, dt);
  updateDriverNumericUI();

  state.animationFrame = requestAnimationFrame(renderLoop);
}

async function refreshDashboard() {
  if (!state.session?.user) return;
  if (state.session.user.role === "driver") {
    const vehicleParam = state.driverSelectedVehicleId ? `?vehicle_id=${encodeURIComponent(state.driverSelectedVehicleId)}` : "";
    const payload = await api(`/api/dashboard/driver${vehicleParam}`);
    syncDriverSnapshot(payload);
    return;
  }
  const payload = await api("/api/dashboard/supervisor");
  syncSupervisorSnapshot(payload);
}

function startRefreshing() {
  clearRefreshTimer();
  refreshDashboard().catch(() => null);
  state.refreshTimer = setInterval(() => {
    refreshDashboard().catch(() => null);
  }, DATA_REFRESH_MS);
}

async function bootstrapSession() {
  const token = localStorage.getItem(SESSION_KEY);
  if (!token) {
    applyRoute();
    return;
  }
  try {
    const payload = await api("/api/auth/me", { headers: { Authorization: `Bearer ${token}` } });
    setSession({ token, user: payload.user });
    updateUserBadge();
    window.location.hash = payload.user.role === "driver" ? "#/condutor" : "#/supervisor";
    applyRoute();
    startRefreshing();
  } catch {
    handleLogout(true);
  }
}

async function submitLogin(event) {
  event.preventDefault();
  refs.loginError.textContent = "";
  const form = new FormData(event.currentTarget);
  try {
    const payload = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        identifier: form.get("identifier"),
        password: form.get("password"),
      }),
    });
    setSession({ token: payload.token, user: payload.user });
    updateUserBadge();
    window.location.hash = payload.user.role === "driver" ? "#/condutor" : "#/supervisor";
    applyRoute(payload.user.role);
    startRefreshing();
  } catch {
    refs.loginError.textContent = "Credenciais invalidas. Use os usuarios demo.";
  }
}

function attachControlHandlers() {
  setSupervisorTab(state.supervisorActiveTab);
  refs.loginForm.addEventListener("submit", submitLogin);
  refs.logoutBtn.addEventListener("click", () => handleLogout(false));

  refs.startBtn.addEventListener("click", async () => {
    await api("/api/start", { method: "POST" });
    await refreshDashboard();
  });
  refs.pauseBtn.addEventListener("click", async () => {
    await api("/api/pause", { method: "POST" });
    await refreshDashboard();
  });
  refs.stepBtn.addEventListener("click", async () => {
    await api("/api/step?steps=1", { method: "POST" });
    await refreshDashboard();
  });
  refs.resetBtn.addEventListener("click", async () => {
    await api("/api/reset", { method: "POST" });
    await refreshDashboard();
  });

  refs.supervisorTabButtons.forEach((button) => {
    button.addEventListener("click", () => {
      setSupervisorTab(button.dataset.tab || "filters");
    });
  });

  [refs.assetSearch, refs.vehicleTypeFilter, refs.statusFilter].forEach((node) => {
    const eventName = node.tagName === "SELECT" ? "change" : "input";
    node.addEventListener(eventName, () => {
      if (!state.supervisorSnapshot) return;
      setSupervisorTab("assets");
      renderAssetList(state.supervisorSnapshot);
      updateRouteLayers(filteredVehicles(state.supervisorSnapshot));
    });
  });

  refs.toggleRoutes.addEventListener("change", () => {
    if (state.supervisorSnapshot) {
      updateRouteLayers(filteredVehicles(state.supervisorSnapshot));
    }
  });

  refs.toggleTeams.addEventListener("change", () => {
    if (state.supervisorSnapshot) {
      updateTeamMarkers(state.supervisorSnapshot.teams || []);
    }
  });

  refs.toggleCritical.addEventListener("change", () => {
    if (state.supervisorSnapshot) {
      renderCriticalPoints(state.supervisorSnapshot.critical_points || []);
    }
  });

  refs.driverVehicleSelect.addEventListener("change", () => {
    state.driverSelectedVehicleId = refs.driverVehicleSelect.value || null;
    refreshDashboard().catch(() => null);
  });
  refs.driverPrevVehicleBtn.addEventListener("click", () => cycleDriverVehicle(-1));
  refs.driverNextVehicleBtn.addEventListener("click", () => cycleDriverVehicle(1));

  refs.toggleZones.addEventListener("change", () => {
    if (state.supervisorSnapshot) {
      renderZones(state.supervisorSnapshot.zones || []);
    }
  });

  refs.toggleTicks.addEventListener("change", () => {
    refs.tickSecondsSelect.disabled = !refs.toggleTicks.checked;
    updateRuntimeSettings().catch(() => null);
  });
  refs.tickSecondsSelect.addEventListener("change", () => {
    updateRuntimeSettings().catch(() => null);
  });
  refs.strategySelect.addEventListener("change", () => {
    refs.strategyHint.textContent = refs.strategySelect.value === "ml"
      ? "Aplicando selecao por IA / ML na alocacao."
      : "Aplicando regra deterministica na alocacao.";
    updateStrategySettings().catch(() => null);
  });

  window.addEventListener("hashchange", () => applyRoute());
  window.addEventListener("resize", () => {
    scheduleMapResize(supervisorMap);
    scheduleMapResize(driverMap);
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      scheduleMapResize(supervisorMap);
      scheduleMapResize(driverMap);
    }
  });
}

attachControlHandlers();
state.animationFrame = requestAnimationFrame(renderLoop);
bootstrapSession();
