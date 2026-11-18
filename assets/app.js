/*
 * Cleaner YouTube — site 100 % statique (GitHub Pages).
 *
 * - Authentification côté client : Google Identity Services, modèle « jeton » (initTokenClient).
 *   Le jeton d'accès reste en mémoire (jamais stocké) et expire au bout d'environ une heure.
 * - Données : vidéos likées (playlist « LL ») lues directement via l'API YouTube Data v3 avec fetch,
 *   puis mises en cache uniquement dans ce navigateur (IndexedDB).
 * - Aucun serveur : rien n'est envoyé ailleurs qu'aux API Google.
 */
(() => {
  "use strict";

  const SCOPE = "https://www.googleapis.com/auth/youtube.readonly";
  const API = "https://www.googleapis.com/youtube/v3";
  const CLIENT_ID_KEY = "cleanerYoutube.clientId";
  const CLIENT_ID_RE = /^[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com$/;
  const BATCH = 5, PAGE = 48;

  const $ = id => document.getElementById(id);
  const norm = s => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const nf = new Intl.NumberFormat("fr-FR");
  const fmt = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", year: "numeric" });
  const fmtShort = new Intl.DateTimeFormat("fr-FR", { month: "short", year: "numeric" });
  const fmtStamp = new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short" });
  const plural = (n, a, b) => `${nf.format(n)} ${n > 1 ? b : a}`;
  const ms = iso => { if (!iso) return null; const t = Date.parse(iso); return Number.isNaN(t) ? null : t; };
  const fdate = t => t == null ? "—" : fmt.format(new Date(t));
  const sleep = d => new Promise(r => setTimeout(r, d));

  // ======================================================================= //
  // Stockage local (IndexedDB, repli en mémoire si indisponible)
  // ======================================================================= //
  const store = (() => {
    const DB = "cleaner-youtube", OS = "cache", KEY = "likes";
    let memory = null, dbPromise = null;
    function open() {
      if (!dbPromise) {
        dbPromise = new Promise((resolve, reject) => {
          if (!("indexedDB" in window)) return reject(new Error("IndexedDB indisponible"));
          const req = indexedDB.open(DB, 1);
          req.onupgradeneeded = () => req.result.createObjectStore(OS);
          req.onsuccess = () => resolve(req.result);
          req.onerror = () => reject(req.error);
        }).catch(err => { console.warn("Cache en mémoire uniquement :", err); return null; });
      }
      return dbPromise;
    }
    function run(mode, fn) {
      return open().then(db => {
        if (!db) return fn(null);
        return new Promise((resolve, reject) => {
          const tx = db.transaction(OS, mode);
          const req = fn(tx.objectStore(OS));
          tx.oncomplete = () => resolve(req && "result" in req ? req.result : undefined);
          tx.onerror = () => reject(tx.error);
          tx.onabort = () => reject(tx.error);
        });
      });
    }
    return {
      get: () => run("readonly", os => os ? os.get(KEY) : null).then(v => v ?? memory),
      put: rec => { memory = rec; return run("readwrite", os => os ? os.put(rec, KEY) : null); },
      clear: async () => {
        memory = null;
        await run("readwrite", os => os ? os.clear() : null);
        const db = await open();
        if (db) db.close();
        dbPromise = null;
        await new Promise(resolve => {
          const req = indexedDB.deleteDatabase(DB);
          req.onsuccess = req.onerror = req.onblocked = () => resolve();
        });
      },
    };
  })();

  // ======================================================================= //
  // Configuration (ID client)
  // ======================================================================= //
  const defaultClientId = (typeof GOOGLE_CLIENT_ID === "string" ? GOOGLE_CLIENT_ID : "").trim();
  function storedClientId() { try { return (localStorage.getItem(CLIENT_ID_KEY) || "").trim(); } catch (e) { return ""; } }
  function clientId() { return storedClientId() || defaultClientId; }
  function clientIdSource() {
    if (storedClientId()) return "ID client personnalisé (enregistré dans ce navigateur).";
    if (defaultClientId) return "ID client défini dans assets/config.js.";
    return "Aucun ID client configuré.";
  }

  // ======================================================================= //
  // Google Identity Services
  // ======================================================================= //
  let accessToken = null, tokenExpiry = 0, tokenClient = null, tokenClientFor = null, pendingToken = null;

  function gis() {
    return window.google && google.accounts && google.accounts.oauth2 ? google.accounts.oauth2 : null;
  }
  async function waitForGis(timeout = 10000) {
    const start = Date.now();
    while (!gis()) {
      if (Date.now() - start > timeout) throw new Error("Impossible de charger Google Identity Services (bloqueur de contenu ?).");
      await sleep(100);
    }
    return gis();
  }
  function ensureTokenClient() {
    const id = clientId();
    if (!id) throw new Error("Aucun ID client OAuth configuré : ouvrez « Configuration ».");
    if (!gis()) return null;
    if (tokenClient && tokenClientFor === id) return tokenClient;
    tokenClient = gis().initTokenClient({
      client_id: id,
      scope: SCOPE,
      callback: resp => {
        const p = pendingToken; pendingToken = null;
        if (!p) return;
        if (resp.error) return p.reject(new Error(oauthErrorMessage(resp.error, resp.error_description)));
        if (!gis().hasGrantedAllScopes(resp, SCOPE)) {
          return p.reject(new Error("Cochez l'accès « Afficher votre compte YouTube » pour utiliser le site."));
        }
        accessToken = resp.access_token;
        tokenExpiry = Date.now() + (Number(resp.expires_in) || 3600) * 1000 - 60000;
        p.resolve(accessToken);
      },
      error_callback: err => {
        const p = pendingToken; pendingToken = null;
        if (!p) return;
        const messages = {
          popup_closed: "Fenêtre de connexion fermée.",
          popup_failed_to_open: "La fenêtre de connexion Google a été bloquée : autorisez les pop-ups pour ce site.",
        };
        p.reject(new Error(messages[err && err.type] || "Connexion Google impossible."));
      },
    });
    tokenClientFor = id;
    return tokenClient;
  }
  function oauthErrorMessage(code, description) {
    if (code === "access_denied") return "Accès refusé. Si Google indique « Accès bloqué », demandez à être ajouté(e) aux utilisateurs tests.";
    return `Erreur Google : ${description || code}`;
  }
  function hasValidToken() { return accessToken && Date.now() < tokenExpiry; }

  /** Demande un jeton. À appeler depuis un clic (la fenêtre Google est un pop-up). */
  function requestToken(prompt) {
    return new Promise((resolve, reject) => {
      let client;
      try { client = ensureTokenClient(); } catch (e) { return reject(e); }
      const go = c => { pendingToken = { resolve, reject }; c.requestAccessToken({ prompt }); };
      if (client) return go(client);  // appel synchrone : conserve le geste utilisateur
      waitForGis().then(() => go(ensureTokenClient())).catch(reject);
    });
  }

  function revokeToken() {
    return new Promise(resolve => {
      if (!accessToken || !gis()) return resolve(false);
      const token = accessToken;
      accessToken = null; tokenExpiry = 0;
      try { gis().revoke(token, () => resolve(true)); } catch (e) { resolve(false); }
    });
  }

  // ======================================================================= //
  // API YouTube Data v3
  // ======================================================================= //
  class ApiError extends Error {
    constructor(message, status, reason) { super(message); this.status = status; this.reason = reason; }
  }
  const REASONS = {
    quotaExceeded: "Quota quotidien de l'API YouTube épuisé pour ce projet Google Cloud : réessayez demain.",
    accessNotConfigured: "L'API YouTube Data v3 n'est pas activée dans le projet Google Cloud de cet ID client.",
    playlistNotFound: "Playlist des vidéos likées introuvable pour ce compte.",
    insufficientPermissions: "Autorisation insuffisante : reconnectez-vous en acceptant l'accès YouTube.",
  };

  async function api(path, params, signal) {
    const url = new URL(`${API}/${path}`);
    Object.entries(params).forEach(([k, v]) => { if (v != null) url.searchParams.set(k, v); });
    for (let attempt = 0; ; attempt++) {
      let res;
      try {
        res = await fetch(url, { headers: { Authorization: `Bearer ${accessToken}` }, signal });
      } catch (e) {
        if (e.name === "AbortError") throw e;
        if (attempt < 3) { await sleep(500 * 2 ** attempt); continue; }
        throw new ApiError("Réseau indisponible.", 0, "network");
      }
      if (res.ok) return res.json();
      let body = {};
      try { body = await res.json(); } catch (e) { /* corps non JSON */ }
      const err = body.error || {};
      const reason = (err.errors && err.errors[0] && err.errors[0].reason) || "";
      if ((res.status >= 500 || reason === "rateLimitExceeded") && attempt < 3) { await sleep(800 * 2 ** attempt); continue; }
      if (res.status === 401) { accessToken = null; throw new ApiError("Session Google expirée : cliquez sur « Actualiser » pour vous reconnecter.", 401, reason); }
      throw new ApiError(REASONS[reason] || `Erreur API YouTube ${res.status} : ${err.message || res.statusText}`, res.status, reason);
    }
  }

  async function fetchAccount(signal) {
    const data = await api("channels", { part: "snippet", mine: "true" }, signal);
    const item = (data.items || [])[0];
    if (!item) throw new ApiError("Ce compte Google n'a pas de chaîne YouTube : aucune vidéo likée à afficher.", 404, "noChannel");
    return { id: item.id, title: item.snippet.title };
  }

  function bestThumb(t) {
    t = t || {};
    for (const k of ["medium", "high", "standard", "default", "maxres"]) if (t[k] && t[k].url) return t[k].url;
    return "";
  }

  async function fetchAllLikes(onProgress, signal) {
    const videos = [], seen = new Set();
    let pageToken = null, done = 0;
    do {
      const data = await api("playlistItems", {
        part: "snippet,contentDetails", playlistId: "LL", maxResults: 50, pageToken,
      }, signal);
      const total = data.pageInfo && data.pageInfo.totalResults;
      for (const item of data.items || []) {
        const s = item.snippet || {}, d = item.contentDetails || {};
        const id = d.videoId || (s.resourceId && s.resourceId.videoId);
        if (!id || seen.has(id)) continue;
        seen.add(id);
        videos.push({
          id,
          t: s.title || "",
          c: s.videoOwnerChannelId || "",       // chaîne de la vidéo (snippet.channelId = vous)
          ct: s.videoOwnerChannelTitle || "",
          p: d.videoPublishedAt || null,
          l: s.publishedAt || null,             // date d'ajout à « J'aime » = date du like
          th: bestThumb(s.thumbnails),
        });
      }
      done += (data.items || []).length;
      onProgress(done, total);
      pageToken = data.nextPageToken;
    } while (pageToken);
    return videos;
  }

  // ======================================================================= //
  // Vues
  // ======================================================================= //
  const views = ["view-home", "view-loading", "view-dash"];
  function show(view) {
    views.forEach(v => $(v).classList.toggle("hidden", v !== view));
    document.body.classList.remove("side-open");
  }
  function setMsg(el, text, kind) {
    el.textContent = text || "";
    el.classList.toggle("hidden", !text);
    if (kind) { el.classList.toggle("err", kind === "err"); el.classList.toggle("info", kind === "info"); }
  }
  function showHome(error, info) {
    setMsg($("homeError"), error, "err");
    setMsg($("homeInfo"), info, "info");
    updateSigninState();
    show("view-home");
  }
  function updateSigninState() {
    const btn = $("signin");
    if (location.protocol === "file:") {
      btn.disabled = true;
      setMsg($("homeError"), "Ouvrez ce site via http(s) (GitHub Pages ou un serveur local) : la connexion Google ne fonctionne pas depuis un fichier local.", "err");
    } else if (!clientId()) {
      btn.disabled = true;
      if ($("homeError").classList.contains("hidden")) {
        setMsg($("homeInfo"), "Aucun ID client OAuth n'est configuré pour ce site : ouvrez « Configuration » pour saisir le vôtre.", "info");
      }
    } else {
      btn.disabled = false;
    }
  }
  function banner(text, kind) { setMsg($("banner"), text, kind || "info"); }

  // ======================================================================= //
  // Synchronisation (connexion + récupération)
  // ======================================================================= //
  let current = null;          // enregistrement en cache affiché
  let syncAbort = null;

  async function sync() {
    if (syncAbort) return;
    const hadData = !!current;
    // 1. Jeton (depuis le clic : pas d'await avant requestAccessToken)
    try {
      if (!hasValidToken()) await requestToken(hadData ? "" : "select_account");
    } catch (e) {
      return hadData ? banner(e.message, "err") : showHome(e.message);
    }
    // 2. Récupération
    syncAbort = new AbortController();
    const bar = $("loadBar"), text = $("loadText");
    bar.classList.add("indeterminate"); bar.firstElementChild.style.width = "0";
    text.textContent = "Connexion à YouTube…";
    $("loadWho").textContent = "Lecture de votre playlist « J'aime » sur YouTube.";
    show("view-loading");
    try {
      const account = await fetchAccount(syncAbort.signal);
      $("loadWho").textContent = `Bonjour ${account.title} ! Lecture de votre playlist « J'aime » sur YouTube.`;
      const videos = await fetchAllLikes((done, total) => {
        if (total) {
          bar.classList.remove("indeterminate");
          const pct = Math.min(100, done / total * 100);
          bar.firstElementChild.style.width = `${pct.toFixed(1)}%`;
          bar.setAttribute("aria-valuenow", String(Math.round(pct)));
          text.textContent = `${nf.format(done)} / ${nf.format(total)} vidéos`;
        } else {
          text.textContent = `${nf.format(done)} vidéos`;
        }
      }, syncAbort.signal);
      const rec = { version: 1, account, fetchedAt: Date.now(), videos };
      try { await store.put(rec); } catch (e) { console.warn("Cache local impossible :", e); }
      dashboard.load(rec);
      banner(`${plural(videos.length, "vidéo likée récupérée", "vidéos likées récupérées")}.`);
    } catch (e) {
      const message = e.name === "AbortError" ? "Récupération annulée." : e.message;
      if (hadData) { dashboard.load(current); banner(message, "err"); } else { showHome(message); }
    } finally {
      syncAbort = null;
    }
  }

  async function deleteLocalData() {
    if (!confirm("Supprimer le cache de vos likes dans ce navigateur et révoquer l'accès de ce site à votre compte Google ?")) return;
    if (syncAbort) syncAbort.abort();
    const revoked = await revokeToken();
    await store.clear();
    try { sessionStorage.clear(); } catch (e) { /* ignoré */ }
    current = null;
    showHome(null, revoked
      ? "Vos données locales ont été supprimées et l'accès a été révoqué."
      : "Vos données locales ont été supprimées. Pour retirer aussi l'accès accordé à ce site : myaccount.google.com/permissions.");
  }

  // ======================================================================= //
  // Tableau de bord
  // ======================================================================= //
  const dashboard = (() => {
    let CH = [], V = [];
    const state = { sel: new Set(), q: "", mode: "p", year: "", order: "desc", chq: "" };
    let filtered = [], cursor = 0, likeRange = null, pubRange = null, realChannels = 0;
    const shown = new Map(), closed = new Set();

    function load(rec) {
      current = rec;
      const counts = new Map(), titles = new Map();
      for (const v of rec.videos) {
        counts.set(v.c, (counts.get(v.c) || 0) + 1);
        if (v.c && v.ct) {
          const l = ms(v.l) || 0, prev = titles.get(v.c);
          if (!prev || l >= prev[0]) titles.set(v.c, [l, v.ct]);  // titre le plus récent
        }
      }
      const ids = [...counts.keys()].filter(Boolean).sort((a, b) =>
        counts.get(b) - counts.get(a) || (titles.get(a)?.[1] || a).localeCompare(titles.get(b)?.[1] || b, "fr"));
      if (counts.has("")) ids.push("");
      const index = new Map(ids.map((id, i) => [id, i]));
      CH = ids.map((id, i) => {
        const t = id ? (titles.get(id)?.[1] || id) : "Vidéos indisponibles (supprimées / privées)";
        return { id, t, n: counts.get(id), u: !id, i, k: norm(t) };
      });
      V = rec.videos.map(v => {
        const p = ms(v.p), l = ms(v.l);
        return {
          id: v.id, t: v.t, c: index.get(v.c), p, l,
          py: p == null ? null : new Date(p).getFullYear(),
          ly: l == null ? null : new Date(l).getFullYear(),
          th: v.th, k: norm(v.t), url: `https://www.youtube.com/watch?v=${encodeURIComponent(v.id)}`,
        };
      });
      likeRange = range("l"); pubRange = range("p");
      realChannels = CH.filter(c => !c.u).length;

      $("account").textContent = `👤 ${rec.account ? rec.account.title : ""} · likes du ${fmtStamp.format(new Date(rec.fetchedAt))}`;
      $("chCount").textContent = nf.format(realChannels);
      Object.assign(state, { q: "", mode: "p", year: "", order: "desc", chq: "" });
      state.sel.clear(); closed.clear();
      $("q").value = ""; $("chq").value = ""; $("mode").value = "p"; $("order").value = "desc";
      banner("");
      renderYears(); renderChannels(); applyFilters();
      show("view-dash");
    }

    function range(key) {
      let min = Infinity, max = -Infinity;
      for (const v of V) { const x = v[key]; if (x != null) { if (x < min) min = x; if (x > max) max = x; } }
      return min === Infinity ? null : [min, max];
    }
    const span = r => r ? `${fmtShort.format(new Date(r[0]))} → ${fmtShort.format(new Date(r[1]))}` : "—";

    function renderStats() {
      const chSel = new Set(filtered.filter(v => !CH[v.c].u).map(v => v.c)).size;
      $("stats").innerHTML = [
        [nf.format(V.length), "vidéos likées"],
        [nf.format(realChannels), "chaînes distinctes"],
        [span(likeRange), "période des likes"],
        [span(pubRange), "période de publication"],
        [nf.format(filtered.length), `affichées · ${plural(chSel, "chaîne", "chaînes")}`, "sel"],
      ].map(([v, l, c]) => `<div class="stat ${c || ""}"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join("");
    }

    function renderChannels() {
      const q = norm(state.chq), html = [];
      for (const c of CH) {
        if (q && !c.k.includes(q)) continue;
        const on = state.sel.has(c.i);
        html.push(`<div class="ch${on ? " on" : ""}${c.u ? " unavailable" : ""}" data-i="${c.i}" role="option" aria-selected="${on}">` +
          `<input type="checkbox" tabindex="-1" ${on ? "checked" : ""} aria-label="Ajouter à la sélection">` +
          `<span class="name" title="${esc(c.t)}">${esc(c.t)}</span>` +
          `<span class="n">${nf.format(c.n)}</span></div>`);
      }
      $("chlist").innerHTML = html.join("") || '<div class="notice">Aucune chaîne trouvée.</div>';
      $("allCh").classList.toggle("on", state.sel.size === 0);
      $("selInfo").textContent = state.sel.size
        ? `${plural(state.sel.size, "chaîne sélectionnée", "chaînes sélectionnées")} · case ou Ctrl/⌘ + clic pour en ajouter`
        : "Clic : une chaîne · case ou Ctrl/⌘ + clic : plusieurs";
    }

    function renderYears() {
      const key = state.mode === "p" ? "py" : "ly";
      const years = [...new Set(V.map(v => v[key]).filter(y => y != null))].sort((a, b) => b - a);
      const hasUnknown = V.some(v => v[key] == null);
      if (state.year && state.year !== "none" && !years.includes(+state.year)) state.year = "";
      $("year").innerHTML = `<option value="">Toutes les années</option>` +
        years.map(y => `<option value="${y}">${y}</option>`).join("") +
        (hasUnknown ? `<option value="none">Date inconnue</option>` : "");
      $("year").value = state.year;
    }

    function applyFilters() {
      const key = state.mode === "p" ? "py" : "ly", sortKey = state.mode;
      const words = norm(state.q).split(/\s+/).filter(Boolean);
      filtered = V.filter(v =>
        (state.sel.size === 0 || state.sel.has(v.c)) &&
        (!state.year || (state.year === "none" ? v[key] == null : v[key] === +state.year)) &&
        (!words.length || words.every(w => v.k.includes(w))));
      const dir = state.order === "asc" ? 1 : -1;
      filtered.sort((a, b) => {
        const x = a[sortKey], y = b[sortKey];
        if (x == null) return y == null ? 0 : 1;
        if (y == null) return -1;
        return (x - y) * dir;
      });
      cursor = 0;
      hidePending();
      shown.clear();
      renderContent();
      renderStats();
      updateOpenButton();
    }

    function groups() {
      const key = state.mode === "p" ? "py" : "ly", map = new Map();
      for (const v of filtered) {
        const y = v[key] == null ? "Date inconnue" : String(v[key]);
        if (!map.has(y)) map.set(y, []);
        map.get(y).push(v);
      }
      return map;
    }

    function card(v) {
      const c = CH[v.c];
      const img = v.th
        ? `<img src="${esc(v.th)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
        : `<span class="ph">Miniature indisponible</span>`;
      return `<article class="card">` +
        `<a class="thumb" href="${v.url}" target="_blank" rel="noopener noreferrer">${img}</a>` +
        `<div class="body">` +
        `<a class="vt" href="${v.url}" target="_blank" rel="noopener noreferrer" title="${esc(v.t)}">${esc(v.t || v.id)}</a>` +
        `<button class="vc" type="button" data-ch="${v.c}" title="Filtrer sur cette chaîne">${esc(c.t)}</button>` +
        `<div class="meta"><span>Publiée le <b>${fdate(v.p)}</b></span><span>Likée le <b>${fdate(v.l)}</b></span></div>` +
        `</div></article>`;
    }

    function section(year, list) {
      const n = Math.min(shown.get(year) || PAGE, list.length);
      shown.set(year, n);
      const rest = list.length - n;
      const more = rest > 0 ? `<button class="more" type="button" data-more="${esc(year)}">Afficher plus (${nf.format(rest)} restantes)</button>` : "";
      return `<details data-year="${esc(year)}" ${closed.has(year) ? "" : "open"}>` +
        `<summary>${esc(year)} <span class="count">${plural(list.length, "vidéo", "vidéos")}</span></summary>` +
        `<div class="grid">${list.slice(0, n).map(card).join("")}${more}</div></details>`;
    }

    function renderContent() {
      const g = groups();
      $("content").innerHTML = g.size
        ? [...g].map(([y, list]) => section(y, list)).join("")
        : `<p class="empty">Aucune vidéo ne correspond à ces filtres.</p>`;
    }

    // ---- Ouverture par lots (gestion des pop-ups bloquées) --------------- //
    function setInfo(text, warn) { const el = $("openInfo"); el.textContent = text; el.classList.toggle("warn", !!warn); }
    function updateOpenButton() {
      const left = filtered.length - cursor, n = Math.min(BATCH, left), btn = $("openBatch");
      btn.disabled = left <= 0;
      if (!filtered.length) btn.textContent = "Aucune vidéo à ouvrir";
      else if (left <= 0) btn.textContent = "Toutes les vidéos ont été ouvertes";
      else btn.textContent = `Ouvrir ${n} vidéo${n > 1 ? "s" : ""} (${nf.format(cursor + 1)}–${nf.format(cursor + n)} sur ${nf.format(filtered.length)})`;
      $("openReset").classList.toggle("hidden", cursor === 0);
      if (cursor === 0) setInfo("");
    }
    function hidePending() { $("pending").classList.add("hidden"); $("pending").innerHTML = ""; }
    function showPending(blocked) {
      $("pending").innerHTML =
        `<p>Le navigateur a bloqué ${plural(blocked.length, "onglet", "onglets")}. Cliquez sur chaque lien pour l'ouvrir :</p>` +
        `<div class="links">${blocked.map((v, k) =>
          `<a href="${v.url}" target="_blank" rel="noopener noreferrer" title="${esc(v.t)}">${k + 1}. ${esc(v.t || v.id)}</a>`).join("")}</div>` +
        `<small>Pour ouvrir 5 onglets d'un coup : cliquez sur l'icône de fenêtre bloquée dans la barre d'adresse → ` +
        `« Toujours autoriser les pop-ups » pour ce site, puis recliquez sur le bouton.</small>`;
      $("pending").classList.remove("hidden");
    }
    function openBatch() {
      const batch = filtered.slice(cursor, cursor + BATCH), blocked = [];
      for (const v of batch) {
        const w = window.open(v.url, "_blank");
        if (w) { try { w.opener = null; } catch (e) { /* autre origine */ } } else blocked.push(v);
      }
      cursor += batch.length;
      updateOpenButton();
      if (blocked.length) {
        showPending(blocked);
        setInfo(`${batch.length - blocked.length}/${batch.length} onglet(s) ouvert(s) automatiquement.`, true);
      } else {
        hidePending();
        setInfo(`${nf.format(cursor)} / ${nf.format(filtered.length)} ouvertes. Recliquez pour le lot suivant.`);
      }
    }

    // ---- Export ----------------------------------------------------------- //
    const iso = t => t == null ? "" : new Date(t).toISOString();
    const rows = () => filtered.map(v => ({
      titre: v.t, url: v.url, chaine: CH[v.c].u ? "" : CH[v.c].t, channel_id: CH[v.c].id,
      publiee_le: iso(v.p), likee_le: iso(v.l), video_id: v.id,
    }));
    const stamp = () => new Date().toISOString().slice(0, 10).replace(/-/g, "");
    function download(name, mime, content) {
      const url = URL.createObjectURL(new Blob([content], { type: mime }));
      const a = Object.assign(document.createElement("a"), { href: url, download: name });
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    }
    function exportCsv() {
      const data = rows();
      if (!data.length) return;
      const cols = Object.keys(data[0]);
      const cell = x => `"${String(x).replace(/"/g, '""')}"`;
      // Séparateur « ; » et BOM UTF-8 : ouverture directe dans Excel en français.
      download(`likes_selection_${stamp()}.csv`, "text/csv;charset=utf-8",
        "﻿" + [cols.join(";"), ...data.map(r => cols.map(c => cell(r[c])).join(";"))].join("\r\n"));
      setInfo(`${plural(data.length, "vidéo exportée", "vidéos exportées")} (CSV).`);
    }
    function exportJson() {
      const data = rows();
      if (!data.length) return;
      download(`likes_selection_${stamp()}.json`, "application/json", JSON.stringify(data, null, 2));
      setInfo(`${plural(data.length, "vidéo exportée", "vidéos exportées")} (JSON).`);
    }
    async function copyLinks() {
      const text = filtered.map(v => v.url).join("\n");
      if (!text) return;
      try { await navigator.clipboard.writeText(text); }
      catch (e) {
        const ta = Object.assign(document.createElement("textarea"), { value: text });
        document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
      }
      setInfo(`${plural(filtered.length, "lien copié", "liens copiés")} dans le presse-papiers.`);
    }

    // ---- Événements ------------------------------------------------------- //
    function selectChannels(indices, additive) {
      if (!additive) state.sel.clear();
      for (const i of indices) { if (additive && state.sel.has(i)) state.sel.delete(i); else state.sel.add(i); }
      renderChannels();
      applyFilters();
    }
    function bind() {
      let qTimer;
      $("q").addEventListener("input", e => { clearTimeout(qTimer); qTimer = setTimeout(() => { state.q = e.target.value; applyFilters(); }, 150); });
      $("chq").addEventListener("input", e => { state.chq = e.target.value; renderChannels(); });
      $("mode").addEventListener("change", e => { state.mode = e.target.value; state.year = ""; closed.clear(); renderYears(); applyFilters(); });
      $("year").addEventListener("change", e => { state.year = e.target.value; applyFilters(); });
      $("order").addEventListener("change", e => { state.order = e.target.value; applyFilters(); });
      $("chlist").addEventListener("click", e => {
        const row = e.target.closest(".ch");
        if (!row) return;
        const i = +row.dataset.i;
        const additive = e.ctrlKey || e.metaKey || e.target.matches("input");
        if (!additive && state.sel.size === 1 && state.sel.has(i)) return selectChannels([], false);
        selectChannels([i], additive);
        if (!additive) document.body.classList.remove("side-open");
      });
      $("allCh").addEventListener("click", () => selectChannels([], false));
      $("content").addEventListener("click", e => {
        const more = e.target.closest("[data-more]");
        if (more) {
          const y = more.dataset.more;
          shown.set(y, (shown.get(y) || PAGE) + PAGE * 2);
          more.closest("details").outerHTML = section(y, groups().get(y));
          return;
        }
        const ch = e.target.closest("[data-ch]");
        if (ch) { selectChannels([+ch.dataset.ch], false); window.scrollTo({ top: 0 }); }
      });
      $("content").addEventListener("toggle", e => {
        const d = e.target;
        if (!(d instanceof HTMLDetailsElement)) return;
        if (d.open) closed.delete(d.dataset.year); else closed.add(d.dataset.year);
      }, true);
      $("expand").addEventListener("click", () => { closed.clear(); document.querySelectorAll("#content details").forEach(d => { d.open = true; }); });
      $("collapse").addEventListener("click", () => document.querySelectorAll("#content details").forEach(d => { d.open = false; }));
      $("reset").addEventListener("click", () => {
        Object.assign(state, { q: "", mode: "p", year: "", order: "desc", chq: "" });
        state.sel.clear(); closed.clear();
        $("q").value = ""; $("chq").value = ""; $("mode").value = "p"; $("order").value = "desc";
        renderYears(); renderChannels(); applyFilters();
      });
      $("toggleSide").addEventListener("click", () => document.body.classList.toggle("side-open"));
      $("pending").addEventListener("click", e => {
        const a = e.target.closest("a");
        if (!a) return;
        a.classList.add("done");
        if (![...$("pending").querySelectorAll(".links a")].some(x => !x.classList.contains("done"))) setTimeout(hidePending, 400);
      });
      $("openBatch").addEventListener("click", openBatch);
      $("openReset").addEventListener("click", () => { cursor = 0; hidePending(); updateOpenButton(); });
      $("csv").addEventListener("click", exportCsv);
      $("json").addEventListener("click", exportJson);
      $("copy").addEventListener("click", copyLinks);
    }

    return { load, bind };
  })();

  // ======================================================================= //
  // Dialogue de configuration
  // ======================================================================= //
  function openConfig() {
    $("clientIdInput").value = clientId();
    $("cfgSource").textContent = clientIdSource();
    $("cfgOrigin").textContent = location.origin && location.origin !== "null" ? location.origin : "(ouvrez le site via http/https)";
    setMsg($("cfgError"), "", "err");
    $("cfgReset").disabled = !storedClientId();
    $("configDialog").showModal();
  }
  function applyClientIdChange() {
    tokenClient = null; tokenClientFor = null; accessToken = null; tokenExpiry = 0;
    try { ensureTokenClient(); } catch (e) { /* pas d'ID */ }
    if (!$("view-home").classList.contains("hidden")) showHome();
  }
  function bindConfig() {
    document.querySelectorAll("[data-open-config]").forEach(b => b.addEventListener("click", openConfig));
    $("cfgClose").addEventListener("click", () => $("configDialog").close());
    $("cfgSave").addEventListener("click", () => {
      const value = $("clientIdInput").value.trim();
      if (!CLIENT_ID_RE.test(value)) {
        return setMsg($("cfgError"), "Format attendu : 123456789012-xxxxxxxx.apps.googleusercontent.com (ID client, pas le « code secret »).", "err");
      }
      try {
        if (value === defaultClientId) localStorage.removeItem(CLIENT_ID_KEY);
        else localStorage.setItem(CLIENT_ID_KEY, value);
      } catch (e) {
        return setMsg($("cfgError"), "Impossible d'enregistrer dans ce navigateur (stockage bloqué).", "err");
      }
      $("configDialog").close();
      applyClientIdChange();
    });
    $("cfgReset").addEventListener("click", () => {
      try { localStorage.removeItem(CLIENT_ID_KEY); } catch (e) { /* ignoré */ }
      $("configDialog").close();
      applyClientIdChange();
    });
  }

  // ======================================================================= //
  // Démarrage
  // ======================================================================= //
  async function init() {
    dashboard.bind();
    bindConfig();
    $("signin").addEventListener("click", () => sync());
    $("refresh").addEventListener("click", () => sync());
    $("deleteData").addEventListener("click", deleteLocalData);
    $("loadCancel").addEventListener("click", () => { if (syncAbort) syncAbort.abort(); });
    // Prépare le client OAuth dès que GIS est chargé, pour ouvrir la fenêtre Google sans délai au clic.
    if (clientId() && location.protocol !== "file:") waitForGis().then(() => { try { ensureTokenClient(); } catch (e) { /* ignoré */ } }).catch(() => {});

    let rec = null;
    try { rec = await store.get(); } catch (e) { console.warn(e); }
    if (rec && Array.isArray(rec.videos)) dashboard.load(rec);
    else showHome();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
