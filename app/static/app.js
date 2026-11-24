const els = {
  search: document.getElementById("search"),
  stars: document.getElementById("stars"),
  country: document.getElementById("country"),
  hasProfile: document.getElementById("hasProfile"),
  eventSearch: document.getElementById("eventSearch"),
  eventSource: document.getElementById("eventSource"),
  eventSeason: document.getElementById("eventSeason"),
  eventYear: document.getElementById("eventYear"),
  eventCalendar: document.getElementById("eventCalendar"),
  eventCountry: document.getElementById("eventCountry"),
  eventSeasonWrap: document.getElementById("eventSeasonWrap"),
  eventYearWrap: document.getElementById("eventYearWrap"),
  eventCalendarWrap: document.getElementById("eventCalendarWrap"),
  eventCountryWrap: document.getElementById("eventCountryWrap"),
  runnerControls: document.getElementById("runnerControls"),
  eventControls: document.getElementById("eventControls"),
  pageTitle: document.getElementById("pageTitle"),
  pageLede: document.getElementById("pageLede"),
  tabRunners: document.getElementById("tabRunners"),
  tabEvents: document.getElementById("tabEvents"),
  stats: document.getElementById("stats"),
  grid: document.getElementById("grid"),
  drawer: document.getElementById("drawer"),
  drawerBody: document.getElementById("drawerBody"),
};

let debounceTimer = null;
let view = "runners";
let metaCache = null;
let eventRows = [];
let eventSort = { key: "date_sort", dir: "asc" };
let eventMetaFilled = { countries: false, years: false };

/** Cloudflare Pages / static export mode (body[data-static="1"]). */
const STATIC_MODE = document.body?.dataset?.static === "1";
const staticCache = {
  runners: null,
  events: null,
  rts: null,
};

async function loadStaticJson(name) {
  const res = await fetch(`/data/${name}.json`);
  if (!res.ok) throw new Error(`missing /data/${name}.json`);
  return res.json();
}

async function ensureStaticRunners() {
  if (!staticCache.runners) {
    staticCache.runners = await loadStaticJson("runners");
  }
  return staticCache.runners;
}

async function ensureStaticEvents() {
  if (!staticCache.events) {
    staticCache.events = await loadStaticJson("events");
  }
  return staticCache.events;
}

async function ensureStaticRts() {
  if (!staticCache.rts) {
    staticCache.rts = await loadStaticJson("rts-races");
  }
  return staticCache.rts;
}

function starText(n) {
  return "★".repeat(n);
}

function genderLabel(g) {
  if (!g) return "";
  return g.toUpperCase() === "F" ? "female" : "male";
}

function stBadge(status) {
  const st = String(status || "");
  if (st === "suspect") return "DUV!";
  if (st.startsWith("guess") || st === "review" || st === "ambiguous_close") return "DUV?";
  return "DUV";
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function cardHtml(r, index) {
  const delay = Math.min(index * 18, 240);
  const profileBadge = r.has_profile
    ? `<span class="badge profile">Race profile</span>`
    : "";
  const rtsBadge =
    r.rts_url && String(r.rts_match_status || "").match(/^(seed|auto)/)
      ? `<span class="badge profile">RTS</span>`
      : "";
  const duvBadge = r.duv_url
    ? `<span class="badge profile">${stBadge(r.duv_match_status)}</span>`
    : "";
  const last = r.last_race
    ? `<span class="badge">LKR ${escapeHtml(r.last_race)}</span>`
    : "";
  return `
    <button class="card" type="button" data-kind="runner" data-id="${r.id}" style="animation-delay:${delay}ms">
      <div class="card-top">
        <h2 class="name">${escapeHtml(r.name)}</h2>
        <div class="stars s${r.stars}" aria-label="${r.stars} star">${starText(r.stars)}</div>
      </div>
      <p class="meta">${r.flag || ""} ${escapeHtml(r.country)} · ${genderLabel(r.gender)}</p>
      <p class="details">${r.points} GM points<br>Graduation: ${escapeHtml(r.graduated_label || "—")}</p>
      <div class="badges">${rtsBadge}${duvBadge}${profileBadge}${last}</div>
    </button>
  `;
}

function calendarLabel(cal) {
  if (cal === "championship") return "Champ";
  if (cal === "grandmaster") return "GM";
  if (cal === "candidate") return "Candidate";
  if (cal === "rts") return "RTS";
  return cal || "";
}

function atmToRow(e) {
  const place = [e.country_code || e.country, e.region].filter(Boolean).join(" · ");
  const links = [];
  if (e.announcement_url) links.push({ label: "A", url: e.announcement_url });
  if (e.report_url) links.push({ label: "R", url: e.report_url });
  if (e.results_url) links.push({ label: "Res", url: e.results_url });
  return {
    source: "atm",
    date_label: e.date_label || e.date_start || "TBC",
    date_sort: e.date_start || e.date_label || "",
    season: e.season ?? "",
    season_label: e.season != null ? `S${e.season}` : "—",
    name: e.name || "",
    place,
    distances: e.distances || "",
    calendar: e.calendar || "",
    status: e.status || "",
    finisher_count: null,
    links,
  };
}

function rtsToRow(r) {
  const years = r.years?.length ? r.years : r.year != null ? [r.year] : [];
  const year = years.length ? Math.max(...years) : null;
  const links = [];
  if (r.url) links.push({ label: "Results", url: r.url });
  if (r.export_url) links.push({ label: "XLS", url: r.export_url });
  return {
    source: "rts",
    date_label: years.length ? years.join(", ") : "—",
    date_sort: year != null ? `${year}-12-31` : "",
    season: year ?? "",
    season_label: r.rts_result_id != null ? `#${r.rts_result_id}` : "—",
    name: r.name || r.title || "",
    place: "—",
    distances: r.distances || "",
    calendar: "rts",
    status: "",
    finisher_count: r.finisher_count ?? 0,
    links,
  };
}

function sortIndicator(key) {
  if (eventSort.key !== key) return "";
  return eventSort.dir === "asc" ? " ↑" : " ↓";
}

function compareRows(a, b, key) {
  const av = a[key];
  const bv = b[key];
  const aEmpty = av == null || av === "";
  const bEmpty = bv == null || bv === "";
  if (aEmpty && bEmpty) return 0;
  if (aEmpty) return 1;
  if (bEmpty) return -1;
  if (typeof av === "number" && typeof bv === "number") return av - bv;
  return String(av).localeCompare(String(bv), undefined, {
    numeric: true,
    sensitivity: "base",
  });
}

function sortedEventRows() {
  const rows = [...eventRows];
  const { key, dir } = eventSort;
  rows.sort((a, b) => {
    const cmp = compareRows(a, b, key);
    return dir === "asc" ? cmp : -cmp;
  });
  return rows;
}

function eventRowHtml(e) {
  const status =
    e.status && e.status !== "scheduled"
      ? `<span class="status-pill">${escapeHtml(e.status)}</span>`
      : "";
  const links =
    e.links
      .map(
        (l) =>
          `<a href="${escapeHtml(l.url)}" target="_blank" rel="noopener">${escapeHtml(l.label)}</a>`
      )
      .join(" ") || "—";
  const fin =
    e.source === "rts"
      ? `<span class="muted-count">${e.finisher_count ?? 0} fin</span>`
      : "";
  return `
    <tr>
      <td class="col-date">${escapeHtml(e.date_label)}</td>
      <td class="col-season">${escapeHtml(e.season_label)}</td>
      <td class="col-name">${escapeHtml(e.name)}${status}</td>
      <td class="col-place">${escapeHtml(e.place || "—")}</td>
      <td class="col-dist">${escapeHtml(e.distances || "—")}</td>
      <td class="col-cal"><span class="cal-tag cal-${escapeHtml(e.calendar)}">${escapeHtml(calendarLabel(e.calendar))}</span></td>
      <td class="col-links">${links} ${fin}</td>
    </tr>
  `;
}

function renderEventsTable() {
  const rows = sortedEventRows();
  const th = (key, label) =>
    `<th class="sortable ${eventSort.key === key ? "sorted" : ""}" data-sort="${key}" scope="col">${label}${sortIndicator(key)}</th>`;
  els.grid.innerHTML = `
    <div class="table-wrap">
      <table class="events-table">
        <thead>
          <tr>
            ${th("date_sort", "Date / Year")}
            ${th("season_label", "S / ID")}
            ${th("name", "Race")}
            ${th("place", "Place")}
            ${th("distances", "Distance")}
            ${th("calendar", "Source")}
            <th>Links</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(eventRowHtml).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function syncEventSourceControls() {
  const src = els.eventSource.value;
  const atm = src === "atm" || src === "both";
  const rts = src === "rts" || src === "both";
  els.eventSeasonWrap.classList.toggle("hidden", !atm);
  els.eventCalendarWrap.classList.toggle("hidden", !atm);
  els.eventCountryWrap.classList.toggle("hidden", !atm);
  els.eventYearWrap.classList.toggle("hidden", !rts);
}

async function loadMeta() {
  const meta = STATIC_MODE
    ? await loadStaticJson("meta")
    : await (await fetch("/api/meta")).json();
  metaCache = meta;
  for (const c of meta.countries) {
    const opt = document.createElement("option");
    opt.value = c.code;
    opt.textContent = `${c.flag || ""} ${c.name}`.trim();
    els.country.appendChild(opt);
  }
  for (const s of meta.event_seasons || []) {
    const opt = document.createElement("option");
    opt.value = String(s);
    opt.textContent = `Season ${s}`;
    els.eventSeason.appendChild(opt);
  }
  return meta;
}

function queryParams() {
  const params = new URLSearchParams();
  const q = els.search.value.trim();
  if (q) params.set("q", q);
  if (els.stars.value) params.set("stars", els.stars.value);
  if (els.country.value) params.set("country", els.country.value);
  if (els.hasProfile.checked) params.set("has_profile", "true");
  return params;
}

function eventQueryParams() {
  const params = new URLSearchParams();
  const q = els.eventSearch.value.trim();
  if (q) params.set("q", q);
  if (els.eventSeason.value) params.set("season", els.eventSeason.value);
  if (els.eventCalendar.value) params.set("calendar", els.eventCalendar.value);
  if (els.eventCountry.value) params.set("country", els.eventCountry.value);
  return params;
}

function rtsQueryParams() {
  const params = new URLSearchParams();
  const q = els.eventSearch.value.trim();
  if (q) params.set("q", q);
  if (els.eventYear.value) params.set("year", els.eventYear.value);
  return params;
}

function filterRunnersLocal(all, params) {
  const q = (params.get("q") || "").toLowerCase();
  const stars = params.get("stars");
  const country = params.get("country");
  const hasProfile = params.get("has_profile");
  return all.filter((r) => {
    if (q && !String(r.name || "").toLowerCase().includes(q)) return false;
    if (stars && String(r.stars) !== stars) return false;
    if (country && String(r.country || "").toUpperCase() !== country.toUpperCase())
      return false;
    if (hasProfile === "true" && !r.has_profile) return false;
    return true;
  });
}

async function loadRunners() {
  els.grid.classList.remove("events-mode");
  const params = queryParams();
  let data;
  if (STATIC_MODE) {
    const bundle = await ensureStaticRunners();
    const runners = filterRunnersLocal(bundle.runners, params);
    data = { total: bundle.total, count: runners.length, runners };
  } else {
    const res = await fetch(`/api/runners?${params}`);
    data = await res.json();
  }
  els.stats.textContent = `Showing ${data.count} of ${data.total} Grandmasters`;
  if (!data.runners.length) {
    els.grid.innerHTML = `<p class="empty">No runners match those filters.</p>`;
    return;
  }
  els.grid.innerHTML = data.runners.map(cardHtml).join("");
}

function filterAtmEventsLocal(bundle, params) {
  const q = (params.get("q") || "").toLowerCase();
  const season = params.get("season");
  const calendar = params.get("calendar");
  const country = params.get("country");
  const events = bundle.events.filter((e) => {
    if (q) {
      const blob = `${e.name || ""} ${e.region || ""} ${e.country || ""}`.toLowerCase();
      if (!blob.includes(q)) return false;
    }
    if (season && String(e.season) !== season) return false;
    if (calendar && String(e.calendar || "").toLowerCase() !== calendar.toLowerCase())
      return false;
    if (
      country &&
      String(e.country_code || "").toUpperCase() !== country.toUpperCase()
    )
      return false;
    return true;
  });
  return {
    total: bundle.total,
    count: events.length,
    countries: bundle.countries,
    seasons: bundle.seasons,
    events,
  };
}

function filterRtsLocal(bundle, params) {
  const q = (params.get("q") || "").toLowerCase();
  const year = params.get("year");
  const races = bundle.races.filter((r) => {
    if (q) {
      const blob = `${r.name || ""} ${r.title || ""} ${r.distances || ""}`.toLowerCase();
      if (!blob.includes(q)) return false;
    }
    if (year && String(r.year) !== year) return false;
    return true;
  });
  return {
    total: bundle.total,
    count: races.length,
    years: bundle.years,
    races,
  };
}

async function fetchAtmEvents() {
  if (STATIC_MODE) {
    return filterAtmEventsLocal(await ensureStaticEvents(), eventQueryParams());
  }
  return (await fetch(`/api/events?${eventQueryParams()}`)).json();
}

async function fetchRtsRaces() {
  if (STATIC_MODE) {
    return filterRtsLocal(await ensureStaticRts(), rtsQueryParams());
  }
  return (await fetch(`/api/rts-races?${rtsQueryParams()}`)).json();
}

async function loadEvents() {
  els.grid.classList.add("events-mode");
  syncEventSourceControls();
  const src = els.eventSource.value;
  const rows = [];
  let atmCount = 0;
  let rtsCount = 0;
  let atmTotal = 0;
  let rtsTotal = 0;

  if (src === "atm" || src === "both") {
    const data = await fetchAtmEvents();
    atmCount = data.count;
    atmTotal = data.total;
    if (!eventMetaFilled.countries && data.countries?.length) {
      for (const c of data.countries) {
        const opt = document.createElement("option");
        opt.value = c.code;
        opt.textContent = `${c.name} (${c.count})`;
        els.eventCountry.appendChild(opt);
      }
      eventMetaFilled.countries = true;
    }
    rows.push(...data.events.map(atmToRow));
  }

  if (src === "rts" || src === "both") {
    const data = await fetchRtsRaces();
    rtsCount = data.count;
    rtsTotal = data.total;
    if (!eventMetaFilled.years && data.years?.length) {
      for (const y of data.years) {
        const opt = document.createElement("option");
        opt.value = String(y);
        opt.textContent = String(y);
        els.eventYear.appendChild(opt);
      }
      eventMetaFilled.years = true;
    }
    rows.push(...data.races.map(rtsToRow));
  }

  eventRows = rows;
  if (src === "both") {
    els.stats.textContent = `Showing ${atmCount} ATM (GM focus) + ${rtsCount} RTS = ${rows.length} rows`;
  } else if (src === "rts") {
    els.stats.textContent = `Showing ${rtsCount} of ${rtsTotal} RTS result races`;
  } else {
    els.stats.textContent = `Showing ${atmCount} of ${atmTotal} ATM events`;
  }

  if (!rows.length) {
    els.grid.innerHTML = `<p class="empty">No events match those filters.</p>`;
    return;
  }
  renderEventsTable();
}

async function openRunner(id) {
  let r;
  if (STATIC_MODE) {
    const bundle = await ensureStaticRunners();
    r = bundle.runners.find((x) => String(x.id) === String(id));
    if (!r) return;
  } else {
    const res = await fetch(`/api/runners/${id}`);
    if (!res.ok) return;
    r = await res.json();
  }
  const races =
    r.races?.length > 0
      ? `<h3 style="margin:1.2rem 0 0;font-family:var(--font-display);font-size:1.1rem;color:var(--forest)">Race history</h3>
         <ul class="race-list">${r.races
           .map((x) => `<li>${escapeHtml(x.label)}</li>`)
           .join("")}</ul>`
      : `<p class="sub" style="margin-top:1.1rem">No Hall of Fame race list archived for this runner yet.</p>`;

  const links = (r.links || [])
    .map(
      (l) =>
        `<a href="${escapeHtml(l.url)}" target="_blank" rel="noopener">${escapeHtml(l.label)}</a>`
    )
    .join("");
  const source = r.profile_url
    ? `<a class="secondary" href="${escapeHtml(r.profile_url)}" target="_blank" rel="noopener">ATM profile</a>`
    : "";
  const rts =
    r.rts_url && String(r.rts_match_status || "").match(/^(seed|auto)/)
      ? `<a href="${escapeHtml(r.rts_url)}" target="_blank" rel="noopener">Stone Age / RTS${r.rts_runner_id ? ` #${escapeHtml(r.rts_runner_id)}` : ""}</a>`
      : "";
  const duvLabel = (() => {
    if (!r.duv_url) return "";
    const st = String(r.duv_match_status || "");
    const id = r.duv_runner_id ? ` #${escapeHtml(r.duv_runner_id)}` : "";
    let label = "DUV";
    if (st === "suspect") label = "DUV check";
    else if (st.startsWith("guess") || st === "review" || st === "ambiguous_close") label = "DUV guess";
    else if (st.startsWith("verified") || st === "manual") label = "DUV ✓";
    return `<a class="secondary" href="${escapeHtml(r.duv_url)}" target="_blank" rel="noopener">${label}${id}</a>`;
  })();

  els.drawerBody.innerHTML = `
    <h2>${escapeHtml(r.name)}</h2>
    <p class="sub">${r.flag || ""} ${escapeHtml(r.country_name || r.country)} · ${genderLabel(r.gender)} · ${starText(r.stars)}</p>
    <div class="metrics">
      <div class="metric"><b>${r.points}</b><span>GM points</span></div>
      <div class="metric"><b>${r.stars}★</b><span>Stars</span></div>
      <div class="metric"><b>${escapeHtml(r.last_race || "—")}</b><span>Last known race</span></div>
    </div>
    <p class="sub">Graduation: ${escapeHtml(r.graduated_label || "—")}</p>
    <div class="actions">${rts}${duvLabel}${links}${source}</div>
    ${races}
  `;
  els.drawer.showModal();
}

function setView(next) {
  view = next;
  const isRunners = view === "runners";
  els.tabRunners.classList.toggle("active", isRunners);
  els.tabEvents.classList.toggle("active", !isRunners);
  els.runnerControls.classList.toggle("hidden", !isRunners);
  els.eventControls.classList.toggle("hidden", isRunners);
  els.pageTitle.textContent = isRunners ? "Grandmasters" : "Events";
  els.pageLede.textContent = isRunners
    ? "Hall of Fame — search the quest by name, stars, or country."
    : "GM calendar + RTS results — sortable table; merge both sources or filter one.";
  if (isRunners) loadRunners();
  else loadEvents();
}

els.grid.addEventListener("click", (e) => {
  const sortTh = e.target.closest("th.sortable");
  if (sortTh && view === "events") {
    const key = sortTh.dataset.sort;
    if (eventSort.key === key) {
      eventSort.dir = eventSort.dir === "asc" ? "desc" : "asc";
    } else {
      eventSort = { key, dir: key === "date_sort" || key === "season_label" ? "asc" : "asc" };
    }
    renderEventsTable();
    return;
  }
  const card = e.target.closest(".card[data-kind='runner']");
  if (!card) return;
  openRunner(card.dataset.id);
});

function scheduleReload() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    if (view === "runners") loadRunners();
    else loadEvents();
  }, 120);
}

els.search.addEventListener("input", scheduleReload);
els.stars.addEventListener("change", loadRunners);
els.country.addEventListener("change", loadRunners);
els.hasProfile.addEventListener("change", loadRunners);

els.eventSearch.addEventListener("input", scheduleReload);
els.eventSource.addEventListener("change", loadEvents);
els.eventSeason.addEventListener("change", loadEvents);
els.eventYear.addEventListener("change", loadEvents);
els.eventCalendar.addEventListener("change", loadEvents);
els.eventCountry.addEventListener("change", loadEvents);

els.tabRunners.addEventListener("click", () => setView("runners"));
els.tabEvents.addEventListener("click", () => setView("events"));

await loadMeta();
await loadRunners();
