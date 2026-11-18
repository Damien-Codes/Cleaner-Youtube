"""Génération des sorties HTML autonomes (thème sombre).

* `generate_report`    : rapport d'une chaîne, groupé par année de publication.
* `generate_dashboard` : tableau de bord global de tous les likes, filtrable en JavaScript.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, OrderedDict
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Iterable, Sequence

from .youtube_client import ChannelInfo, LikedVideo

UNKNOWN_YEAR = "Date inconnue"

_MOIS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


# --------------------------------------------------------------------------- #
# Classement
# --------------------------------------------------------------------------- #
def group_by_year(
    videos: Iterable[LikedVideo], ascending: bool = False
) -> "OrderedDict[str, list[LikedVideo]]":
    """Classe les vidéos par année de publication.

    Par défaut du plus récent au plus ancien (années et vidéos). Les vidéos sans date
    de publication sont regroupées à la fin.
    """
    dated: dict[int, list[LikedVideo]] = {}
    undated: list[LikedVideo] = []
    for video in videos:
        published = video.published_datetime
        if published is None:
            undated.append(video)
        else:
            dated.setdefault(published.year, []).append(video)

    grouped: OrderedDict[str, list[LikedVideo]] = OrderedDict()
    for year in sorted(dated, reverse=not ascending):
        grouped[str(year)] = sorted(
            dated[year],
            key=lambda v: v.published_datetime,  # type: ignore[arg-type, return-value]
            reverse=not ascending,
        )
    if undated:
        grouped[UNKNOWN_YEAR] = undated
    return grouped


def flatten(grouped: "OrderedDict[str, list[LikedVideo]]") -> list[LikedVideo]:
    return [video for videos in grouped.values() for video in videos]


# --------------------------------------------------------------------------- #
# Utilitaires
# --------------------------------------------------------------------------- #
def format_date_fr(value: datetime | None) -> str:
    if value is None:
        return "—"
    local = value.astimezone() if value.tzinfo else value
    return f"{local.day} {_MOIS[local.month - 1]} {local.year}"


def slugify(text: str, max_length: int = 60) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", normalized).strip("_").lower()
    return (slug[:max_length].rstrip("_")) or "chaine"


def report_path(output_dir: Path, channel: ChannelInfo, when: datetime | None = None) -> Path:
    stamp = (when or datetime.now()).strftime("%Y%m%d")
    return output_dir / f"liked_{slugify(channel.title)}_{stamp}.html"


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


# --------------------------------------------------------------------------- #
# Rendu HTML
# --------------------------------------------------------------------------- #
_CSS = """
:root {
  --bg: #0f1115; --panel: #171a21; --panel-2: #1e222b; --border: #2a2f3a;
  --text: #e6e8ee; --muted: #9aa3b2; --accent: #ff4e45; --accent-2: #3ea6ff;
}
* { box-sizing: border-box; }
html { color-scheme: dark; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
a { color: inherit; text-decoration: none; }
header {
  position: sticky; top: 0; z-index: 10; background: rgba(15,17,21,.92);
  backdrop-filter: blur(8px); border-bottom: 1px solid var(--border);
}
.wrap { max-width: 1280px; margin: 0 auto; padding: 0 20px; }
.head { display: flex; flex-wrap: wrap; gap: 12px 24px; align-items: center; padding: 16px 0 12px; }
.head h1 { font-size: 22px; margin: 0; flex: 1 1 auto; }
.head h1 a:hover { color: var(--accent-2); }
.badge { background: var(--accent); color: #fff; border-radius: 999px; padding: 2px 10px; font-size: 13px; font-weight: 600; }
.sub { color: var(--muted); font-size: 13px; }
.tools { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding-bottom: 12px; }
.tools input {
  flex: 1 1 260px; min-width: 0; background: var(--panel-2); color: var(--text);
  border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; font-size: 14px;
}
.tools input:focus { outline: 2px solid var(--accent-2); outline-offset: -1px; }
button {
  background: var(--panel-2); color: var(--text); border: 1px solid var(--border);
  border-radius: 8px; padding: 8px 12px; font-size: 13px; cursor: pointer;
}
button:hover { border-color: var(--accent-2); }
nav.years { display: flex; flex-wrap: wrap; gap: 6px; padding-bottom: 12px; }
nav.years a {
  font-size: 12px; padding: 3px 10px; border-radius: 999px; background: var(--panel-2);
  border: 1px solid var(--border); color: var(--muted);
}
nav.years a:hover { color: var(--text); border-color: var(--accent); }
main { padding: 20px 0 60px; }
details { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 16px; scroll-margin-top: 170px; }
summary {
  list-style: none; cursor: pointer; padding: 14px 18px; display: flex; align-items: center; gap: 12px;
  font-size: 18px; font-weight: 700; user-select: none;
}
summary::-webkit-details-marker { display: none; }
summary::before { content: "▸"; color: var(--accent); transition: transform .15s; }
details[open] > summary::before { transform: rotate(90deg); }
summary .count { font-size: 13px; font-weight: 500; color: var(--muted); background: var(--panel-2); padding: 2px 10px; border-radius: 999px; }
.grid {
  display: grid; gap: 16px; padding: 4px 18px 18px;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
}
.card { background: var(--panel-2); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; display: flex; flex-direction: column; transition: transform .12s, border-color .12s; }
.card:hover { transform: translateY(-2px); border-color: var(--accent); }
.thumb { position: relative; aspect-ratio: 16 / 9; background: #000; }
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.thumb .ph { position: absolute; inset: 0; display: grid; place-items: center; color: var(--muted); font-size: 12px; }
.body { padding: 10px 12px 12px; display: flex; flex-direction: column; gap: 6px; }
.title { font-weight: 600; font-size: 14px; line-height: 1.35; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.title:hover { color: var(--accent-2); }
.meta { font-size: 12px; color: var(--muted); display: flex; flex-direction: column; gap: 2px; }
.meta b { color: var(--text); font-weight: 500; }
.empty { color: var(--muted); text-align: center; padding: 40px 0; }
.hidden { display: none !important; }
footer { color: var(--muted); font-size: 12px; text-align: center; padding: 20px 0 40px; }
@media (max-width: 520px) {
  .wrap { padding: 0 12px; }
  .grid { grid-template-columns: 1fr; padding: 4px 12px 12px; }
  details { scroll-margin-top: 220px; }
}
"""

_JS = """
(() => {
  const input = document.getElementById('q');
  const sections = [...document.querySelectorAll('details.year')];
  const empty = document.getElementById('empty');
  const norm = s => s.normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase();
  input.addEventListener('input', () => {
    const q = norm(input.value.trim());
    let visibleTotal = 0;
    sections.forEach(sec => {
      let visible = 0;
      sec.querySelectorAll('.card').forEach(card => {
        const show = !q || card.dataset.search.includes(q);
        card.classList.toggle('hidden', !show);
        if (show) visible++;
      });
      sec.classList.toggle('hidden', visible === 0);
      if (q && visible) sec.open = true;
      visibleTotal += visible;
    });
    empty.classList.toggle('hidden', visibleTotal !== 0);
  });
  document.getElementById('expand').addEventListener('click', () => sections.forEach(s => s.open = true));
  document.getElementById('collapse').addEventListener('click', () => sections.forEach(s => s.open = false));
})();
"""


def _search_key(video: LikedVideo) -> str:
    text = unicodedata.normalize("NFKD", video.title).encode("ascii", "ignore").decode("ascii")
    return escape(text.lower(), quote=True)


def _render_card(video: LikedVideo) -> str:
    url = escape(video.url, quote=True)
    title = escape(video.title or video.video_id)
    if video.thumbnail_url:
        thumb = (
            f'<img src="{escape(video.thumbnail_url, quote=True)}" alt="" loading="lazy" '
            f'referrerpolicy="no-referrer">'
        )
    else:
        thumb = '<div class="ph">Miniature indisponible</div>'
    return (
        f'<article class="card" data-search="{_search_key(video)}">'
        f'<a class="thumb" href="{url}" target="_blank" rel="noopener noreferrer">{thumb}</a>'
        f'<div class="body">'
        f'<a class="title" href="{url}" target="_blank" rel="noopener noreferrer" title="{title}">{title}</a>'
        f'<div class="meta">'
        f'<span>Publiée le <b>{format_date_fr(video.published_datetime)}</b></span>'
        f'<span>Likée le <b>{format_date_fr(video.liked_datetime)}</b></span>'
        f"</div></div></article>"
    )


def render_html(
    channel: ChannelInfo,
    grouped: "OrderedDict[str, list[LikedVideo]]",
    generated_at: datetime | None = None,
    ascending: bool = False,
) -> str:
    generated_at = generated_at or datetime.now()
    total = sum(len(v) for v in grouped.values())
    channel_title = escape(channel.title)
    channel_url = escape(channel.url, quote=True)
    order_label = "du plus ancien au plus récent" if ascending else "du plus récent au plus ancien"

    nav = "".join(
        f'<a href="#y-{escape(slugify(year), quote=True)}">{escape(year)} · {len(videos)}</a>'
        for year, videos in grouped.items()
    )
    sections = "".join(
        f'<details class="year" id="y-{escape(slugify(year), quote=True)}" open>'
        f'<summary>{escape(year)} <span class="count">{_plural(len(videos), "vidéo", "vidéos")}</span></summary>'
        f'<div class="grid">{"".join(_render_card(v) for v in videos)}</div>'
        f"</details>"
        for year, videos in grouped.items()
    )
    empty_hidden = "" if total == 0 else " hidden"

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Likes – {channel_title}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <div class="wrap">
    <div class="head">
      <h1><a href="{channel_url}" target="_blank" rel="noopener noreferrer">{channel_title}</a></h1>
      <span class="badge">{_plural(total, "vidéo likée", "vidéos likées")}</span>
      <span class="sub">Généré le {format_date_fr(generated_at)} à {generated_at:%H:%M} · tri {order_label}</span>
    </div>
    <div class="tools">
      <input id="q" type="search" placeholder="Filtrer par titre…" aria-label="Filtrer par titre">
      <button id="expand" type="button">Tout déplier</button>
      <button id="collapse" type="button">Tout replier</button>
    </div>
    <nav class="years">{nav}</nav>
  </div>
</header>
<main class="wrap">
  {sections}
  <p id="empty" class="empty{empty_hidden}">Aucune vidéo ne correspond.</p>
</main>
<footer class="wrap">Rapport généré par Cleaner YouTube · chaîne {escape(channel.channel_id)}</footer>
<script>{_JS}</script>
</body>
</html>
"""


def generate_report(
    channel: ChannelInfo,
    grouped: "OrderedDict[str, list[LikedVideo]]",
    output_dir: Path,
    ascending: bool = False,
) -> Path:
    """Écrit le rapport HTML et retourne son chemin."""
    now = datetime.now()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = report_path(output_dir, channel, now)
    path.write_text(render_html(channel, grouped, now, ascending), encoding="utf-8")
    return path


# =========================================================================== #
# Tableau de bord global
# =========================================================================== #
DASHBOARD_FILENAME = "dashboard.html"
UNAVAILABLE_CHANNEL_LABEL = "Vidéos indisponibles (supprimées / privées)"


def _epoch(value: datetime | None) -> int | None:
    return int(value.timestamp()) if value else None


def build_dashboard_data(
    videos: Sequence[LikedVideo],
    followed: Sequence[ChannelInfo] = (),
    generated_at: datetime | None = None,
) -> dict:
    """Prépare les données compactes embarquées dans le tableau de bord."""
    generated_at = generated_at or datetime.now()
    followed_ids = {c.channel_id for c in followed}

    counts: Counter[str] = Counter()
    titles: dict[str, tuple[int, str]] = {}
    for video in videos:
        key = video.channel_id or ""
        counts[key] += 1
        if video.channel_id and video.channel_title:
            # Titre associé au like le plus récent : suit les renommages de chaîne.
            liked = _epoch(video.liked_datetime) or 0
            if key not in titles or liked >= titles[key][0]:
                titles[key] = (liked, video.channel_title)

    for channel in followed:  # chaînes suivies sans aucun like : visibles quand même
        counts.setdefault(channel.channel_id, 0)
        titles.setdefault(channel.channel_id, (0, channel.title))

    ordered = sorted(
        (cid for cid in counts if cid),
        key=lambda cid: (-counts[cid], titles.get(cid, (0, cid))[1].lower()),
    )
    if "" in counts:
        ordered.append("")
    index = {cid: i for i, cid in enumerate(ordered)}

    channels = [
        {
            "id": cid,
            "t": titles[cid][1] if cid in titles else (cid or UNAVAILABLE_CHANNEL_LABEL),
            "n": counts[cid],
            "f": 1 if cid in followed_ids else 0,
            "u": 1 if cid == "" else 0,
        }
        for cid in ordered
    ]

    rows = []
    for video in videos:
        thumb: int | str = 0
        if video.thumbnail_url:
            standard = f"https://i.ytimg.com/vi/{video.video_id}/mqdefault.jpg"
            thumb = 1 if video.thumbnail_url == standard else video.thumbnail_url
        rows.append([
            video.video_id,
            video.title,
            index[video.channel_id or ""],
            _epoch(video.published_datetime),
            _epoch(video.liked_datetime),
            thumb,
        ])

    return {
        "generated": generated_at.isoformat(timespec="seconds"),
        "channels": channels,
        "videos": rows,
    }


def render_dashboard(data: dict, toolbar_html: str = "") -> str:
    """Rend le tableau de bord. `toolbar_html` (HTML de confiance) s'insère dans l'en-tête :
    paramètre conservé pour des intégrations personnalisées (vide par défaut)."""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # Empêche toute fermeture prématurée de la balise <script> (échappements JSON valides).
    payload = payload.replace("<", "\\u003c")
    return _DASHBOARD_TEMPLATE.replace("__TOOLBAR__", toolbar_html).replace("__DATA__", payload)


def generate_dashboard(
    videos: Sequence[LikedVideo],
    output_dir: Path,
    followed: Sequence[ChannelInfo] = (),
) -> Path:
    """Écrit `output/dashboard.html` (toutes les vidéos likées) et retourne son chemin."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / DASHBOARD_FILENAME
    path.write_text(render_dashboard(build_dashboard_data(videos, followed)), encoding="utf-8")
    return path


_DASHBOARD_TEMPLATE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mes vidéos likées</title>
<style>
:root {
  --bg: #0f1115; --panel: #171a21; --panel-2: #1e222b; --panel-3: #262b36; --border: #2a2f3a;
  --text: #e6e8ee; --muted: #9aa3b2; --accent: #ff4e45; --accent-2: #3ea6ff; --gold: #f2cc60;
  --side: 300px;
}
* { box-sizing: border-box; }
html { color-scheme: dark; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
a { color: inherit; text-decoration: none; }
button, select, input { font: inherit; color: var(--text); }
button { background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px;
  padding: 7px 12px; cursor: pointer; white-space: nowrap; }
button:hover:not(:disabled) { border-color: var(--accent-2); }
button:disabled { opacity: .45; cursor: default; }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600; }
button.primary:hover:not(:disabled) { filter: brightness(1.1); border-color: var(--accent); }
button.chip.on { background: var(--accent-2); border-color: var(--accent-2); color: #0b0d11; font-weight: 600; }
input[type=search], select { background: var(--panel-2); border: 1px solid var(--border);
  border-radius: 8px; padding: 7px 10px; min-width: 0; }
input:focus, select:focus { outline: 2px solid var(--accent-2); outline-offset: -1px; }

.layout { display: grid; grid-template-columns: var(--side) minmax(0, 1fr); min-height: 100vh; }
aside { position: sticky; top: 0; height: 100vh; display: flex; flex-direction: column;
  background: var(--panel); border-right: 1px solid var(--border); }
.side-head { padding: 16px 14px 10px; display: flex; flex-direction: column; gap: 8px; border-bottom: 1px solid var(--border); }
.side-head h2 { margin: 0; font-size: 15px; display: flex; justify-content: space-between; align-items: baseline; }
.side-head h2 small { color: var(--muted); font-weight: 400; font-size: 12px; }
.quick { display: flex; flex-wrap: wrap; gap: 6px; }
.quick button { padding: 4px 10px; font-size: 12px; border-radius: 999px; }
.chlist { flex: 1; overflow-y: auto; padding: 6px 6px 20px; }
.ch { display: grid; grid-template-columns: 18px minmax(0, 1fr) auto; gap: 8px; align-items: center;
  padding: 5px 8px; border-radius: 6px; cursor: pointer; user-select: none; }
.ch:hover { background: var(--panel-2); }
.ch.on { background: var(--panel-3); }
.ch input { margin: 0; accent-color: var(--accent-2); }
.ch .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ch .star { color: var(--gold); margin-left: 4px; }
.ch .n { font-size: 12px; color: var(--muted); background: var(--panel-2); border-radius: 999px; padding: 0 8px; }
.ch.on .n { background: var(--accent-2); color: #0b0d11; }
.ch.unavailable .name { color: var(--muted); font-style: italic; }

main { min-width: 0; }
header { position: sticky; top: 0; z-index: 5; background: rgba(15,17,21,.94); backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--border); padding: 14px 20px 12px; display: flex; flex-direction: column; gap: 12px; }
.title-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; }
.title-row h1 { margin: 0; font-size: 20px; flex: 1 1 auto; }
.title-row .gen { color: var(--muted); font-size: 12px; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.stat { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 8px 12px; }
.stat .v { font-size: 19px; font-weight: 700; }
.stat .l { font-size: 12px; color: var(--muted); }
.stat.sel .v { color: var(--accent-2); }
.filters { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.filters input[type=search] { flex: 1 1 220px; }
.filters label { color: var(--muted); font-size: 12px; display: flex; align-items: center; gap: 6px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.actions .sep { flex: 1; }
.notice { font-size: 12px; color: var(--muted); }
.notice.warn { color: var(--gold); }
.pending { background: #2a2414; border: 1px solid #6b5a22; border-radius: 10px; padding: 10px 12px;
  display: flex; flex-direction: column; gap: 8px; font-size: 13px; }
.pending p { margin: 0; color: var(--gold); }
.pending .links { display: flex; flex-wrap: wrap; gap: 6px; }
.pending .links a { background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; padding: 5px 10px;
  max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pending .links a:hover { border-color: var(--accent-2); }
.pending .links a.done { opacity: .4; text-decoration: line-through; }
.pending small { color: var(--muted); }
.user { color: var(--muted); font-size: 13px; }
button.danger { border-color: #6e2a2a; color: #ff9a94; }
button.danger:hover:not(:disabled) { border-color: var(--accent); }
.toggle-side { display: none; }

.content { padding: 18px 20px 60px; }
details { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 14px; }
summary { list-style: none; cursor: pointer; padding: 12px 16px; display: flex; align-items: center; gap: 12px;
  font-size: 17px; font-weight: 700; user-select: none; }
summary::-webkit-details-marker { display: none; }
summary::before { content: "▸"; color: var(--accent); transition: transform .15s; }
details[open] > summary::before { transform: rotate(90deg); }
summary .count { font-size: 12px; font-weight: 500; color: var(--muted); background: var(--panel-2); padding: 2px 10px; border-radius: 999px; }
.grid { display: grid; gap: 14px; padding: 2px 16px 16px; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); }
.card { background: var(--panel-2); border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
  display: flex; flex-direction: column; transition: transform .12s, border-color .12s; }
.card:hover { transform: translateY(-2px); border-color: var(--accent); }
.thumb { aspect-ratio: 16 / 9; background: #000; display: block; position: relative; }
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.thumb .ph { position: absolute; inset: 0; display: grid; place-items: center; color: var(--muted); font-size: 12px; }
.body { padding: 9px 11px 11px; display: flex; flex-direction: column; gap: 5px; }
.vt { font-weight: 600; line-height: 1.35; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.vt:hover { color: var(--accent-2); }
.vc { font-size: 12px; color: var(--accent-2); background: none; border: 0; padding: 0; text-align: left;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.vc:hover { text-decoration: underline; }
.meta { font-size: 12px; color: var(--muted); display: flex; flex-direction: column; }
.meta b { color: var(--text); font-weight: 500; }
.more { grid-column: 1 / -1; justify-self: center; }
.empty { color: var(--muted); text-align: center; padding: 50px 0; }
.hidden { display: none !important; }

@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
  aside { position: fixed; inset: 0 auto 0 0; width: min(88vw, 340px); z-index: 20; transform: translateX(-100%);
    transition: transform .2s; box-shadow: 0 0 40px rgba(0,0,0,.6); }
  body.side-open aside { transform: none; }
  .toggle-side { display: inline-block; }
  header { position: static; padding: 12px; }
  .content { padding: 14px 12px 50px; }
  .grid { grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); padding: 2px 10px 12px; }
}
</style>
</head>
<body>
<div class="layout">
  <aside id="side" aria-label="Chaînes">
    <div class="side-head">
      <h2>Chaînes <small id="chCount"></small></h2>
      <input id="chq" type="search" placeholder="Rechercher une chaîne…" aria-label="Rechercher une chaîne">
      <div class="quick">
        <button id="allCh" class="chip on" type="button">Toutes les chaînes</button>
        <button id="followed" class="chip hidden" type="button" title="Chaînes listées dans channels.txt">★ Mes chaînes suivies (channels.txt)</button>
      </div>
      <div class="notice" id="selInfo"></div>
    </div>
    <div class="chlist" id="chlist" role="listbox" aria-multiselectable="true"></div>
  </aside>

  <main>
    <header>
      <div class="title-row">
        <button class="toggle-side" id="toggleSide" type="button">☰ Chaînes</button>
        <h1>Mes vidéos YouTube likées</h1>
        <span class="gen" id="gen"></span>
        __TOOLBAR__
      </div>
      <div class="stats" id="stats"></div>
      <div class="filters">
        <input id="q" type="search" placeholder="Mot-clé dans le titre…" aria-label="Mot-clé dans le titre">
        <label>Année de
          <select id="mode" aria-label="Type d'année">
            <option value="p">publication</option>
            <option value="l">like</option>
          </select>
        </label>
        <select id="year" aria-label="Année"></select>
        <select id="order" aria-label="Tri">
          <option value="desc">Plus récentes d'abord</option>
          <option value="asc">Plus anciennes d'abord</option>
        </select>
        <button id="reset" type="button">Réinitialiser</button>
      </div>
      <div class="actions">
        <button id="openBatch" class="primary" type="button">Ouvrir 5 vidéos</button>
        <button id="openReset" type="button" class="hidden">Recommencer</button>
        <span class="notice" id="openInfo"></span>
        <span class="sep"></span>
        <button id="expand" type="button">Tout déplier</button>
        <button id="collapse" type="button">Tout replier</button>
        <button id="copy" type="button">Copier les liens</button>
        <button id="csv" type="button">Exporter CSV</button>
        <button id="json" type="button">Exporter JSON</button>
      </div>
      <div class="pending hidden" id="pending" role="status"></div>
    </header>
    <div class="content" id="content"></div>
  </main>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
(() => {
  "use strict";
  const BATCH = 5, PAGE = 48;
  const D = JSON.parse(document.getElementById("data").textContent);
  const norm = s => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", year: "numeric" });
  const fmtShort = new Intl.DateTimeFormat("fr-FR", { month: "short", year: "numeric" });
  const nf = new Intl.NumberFormat("fr-FR");
  const dt = s => s == null ? null : new Date(s * 1000);
  const fdate = s => s == null ? "—" : fmt.format(dt(s));
  const plural = (n, a, b) => `${nf.format(n)} ${n > 1 ? b : a}`;

  const CH = D.channels.map((c, i) => ({ ...c, i, k: norm(c.t) }));
  const V = D.videos.map(a => {
    const p = a[3], l = a[4];
    return {
      id: a[0], t: a[1], c: a[2], p, l,
      py: p == null ? null : dt(p).getFullYear(),
      ly: l == null ? null : dt(l).getFullYear(),
      th: a[5] === 1 ? `https://i.ytimg.com/vi/${a[0]}/mqdefault.jpg` : (a[5] || ""),
      k: norm(a[1]),
      url: `https://www.youtube.com/watch?v=${a[0]}`,
    };
  });
  const followedIdx = CH.filter(c => c.f).map(c => c.i);

  const $ = id => document.getElementById(id);
  const state = { sel: new Set(), q: "", mode: "p", year: "", order: "desc", chq: "" };
  let filtered = [], cursor = 0;
  const shown = new Map();   // année -> nombre de cartes affichées
  const closed = new Set();  // sections repliées par l'utilisateur

  // ---- Statistiques globales ------------------------------------------------
  function range(key) {
    let min = Infinity, max = -Infinity;
    for (const v of V) { const x = v[key]; if (x != null) { if (x < min) min = x; if (x > max) max = x; } }
    return min === Infinity ? null : [min, max];
  }
  const likeRange = range("l"), pubRange = range("p");
  const realChannels = CH.filter(c => !c.u && c.n > 0).length;
  const span = r => r ? `${fmtShort.format(dt(r[0]))} → ${fmtShort.format(dt(r[1]))}` : "—";
  $("gen").textContent = `Généré le ${fmt.format(new Date(D.generated))}`;
  $("chCount").textContent = nf.format(realChannels);

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

  // ---- Barre latérale des chaînes -------------------------------------------
  function renderChannels() {
    const q = norm(state.chq);
    const html = [];
    for (const c of CH) {
      if (q && !c.k.includes(q)) continue;
      const on = state.sel.has(c.i);
      html.push(`<div class="ch${on ? " on" : ""}${c.u ? " unavailable" : ""}" data-i="${c.i}" role="option" aria-selected="${on}">` +
        `<input type="checkbox" tabindex="-1" ${on ? "checked" : ""} aria-label="Ajouter à la sélection">` +
        `<span class="name" title="${esc(c.t)}">${esc(c.t)}${c.f ? '<span class="star" title="channels.txt">★</span>' : ""}</span>` +
        `<span class="n">${nf.format(c.n)}</span></div>`);
    }
    $("chlist").innerHTML = html.join("") || '<div class="notice" style="padding:10px">Aucune chaîne trouvée.</div>';
    const isFollowed = followedIdx.length > 0 && state.sel.size === followedIdx.length && followedIdx.every(i => state.sel.has(i));
    $("allCh").classList.toggle("on", state.sel.size === 0);
    $("followed").classList.toggle("on", isFollowed);
    $("selInfo").textContent = state.sel.size
      ? `${plural(state.sel.size, "chaîne sélectionnée", "chaînes sélectionnées")} · case ou Ctrl/⌘ + clic pour en ajouter`
      : "Clic : une chaîne · case ou Ctrl/⌘ + clic : plusieurs";
  }

  // ---- Années ----------------------------------------------------------------
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

  // ---- Filtrage et rendu -----------------------------------------------------
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
    const key = state.mode === "p" ? "py" : "ly";
    const map = new Map();
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
    const more = rest > 0
      ? `<button class="more" type="button" data-more="${esc(year)}">Afficher plus (${nf.format(rest)} restantes)</button>`
      : "";
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

  // ---- Ouverture par lots ----------------------------------------------------
  function setInfo(text, warn) { const el = $("openInfo"); el.textContent = text; el.classList.toggle("warn", !!warn); }
  function updateOpenButton() {
    const left = filtered.length - cursor, n = Math.min(BATCH, left);
    const btn = $("openBatch");
    btn.disabled = left <= 0;
    if (!filtered.length) btn.textContent = "Aucune vidéo à ouvrir";
    else if (left <= 0) btn.textContent = "Toutes les vidéos ont été ouvertes";
    else btn.textContent = `Ouvrir ${n} vidéo${n > 1 ? "s" : ""} (${nf.format(cursor + 1)}–${nf.format(cursor + n)} sur ${nf.format(filtered.length)})`;
    $("openReset").classList.toggle("hidden", cursor === 0);
    if (cursor === 0) setInfo("");
  }
  // Les navigateurs n'autorisent qu'UN window.open par clic tant que les fenêtres pop-up ne sont pas
  // autorisées pour le site : les onglets bloqués sont proposés en liens cliquables (1 clic = 1 onglet).
  function hidePending() { $("pending").classList.add("hidden"); $("pending").innerHTML = ""; }
  function showPending(blocked) {
    const isFile = location.protocol === "file:";
    const how = isFile
      ? "Un fichier local ne peut pas recevoir l'autorisation des pop-ups : lancez <code>python main.py --serve</code> pour ouvrir 5 onglets d'un coup."
      : "Pour ouvrir 5 onglets d'un coup : cliquez sur l'icône de fenêtre bloquée dans la barre d'adresse → « Toujours autoriser les pop-ups » pour ce site, puis recliquez sur le bouton.";
    $("pending").innerHTML =
      `<p>Le navigateur a bloqué ${plural(blocked.length, "onglet", "onglets")}. Cliquez sur chaque lien pour l'ouvrir :</p>` +
      `<div class="links">${blocked.map((v, k) =>
        `<a href="${v.url}" target="_blank" rel="noopener noreferrer" title="${esc(v.t)}">${k + 1}. ${esc(v.t || v.id)}</a>`).join("")}</div>` +
      `<small>${how}</small>`;
    $("pending").classList.remove("hidden");
  }
  $("pending").addEventListener("click", e => {
    const a = e.target.closest("a");
    if (!a) return;
    a.classList.add("done");
    if (![...$("pending").querySelectorAll(".links a")].some(x => !x.classList.contains("done"))) setTimeout(hidePending, 400);
  });
  $("openBatch").addEventListener("click", () => {
    const batch = filtered.slice(cursor, cursor + BATCH);
    const blocked = [];
    for (const v of batch) {
      const w = window.open(v.url, "_blank");
      if (w) { try { w.opener = null; } catch (e) { /* onglet d'une autre origine */ } }
      else blocked.push(v);
    }
    cursor += batch.length;
    updateOpenButton();
    const opened = batch.length - blocked.length;
    if (blocked.length) {
      showPending(blocked);
      setInfo(`${opened}/${batch.length} onglet(s) ouvert(s) automatiquement.`, true);
    } else {
      hidePending();
      setInfo(`${nf.format(cursor)} / ${nf.format(filtered.length)} ouvertes. Recliquez pour le lot suivant.`);
    }
  });
  $("openReset").addEventListener("click", () => { cursor = 0; hidePending(); updateOpenButton(); });

  // ---- Export ----------------------------------------------------------------
  const iso = s => s == null ? "" : dt(s).toISOString();
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
  $("csv").addEventListener("click", () => {
    const data = rows();
    if (!data.length) return;
    const cols = Object.keys(data[0]);
    const cell = x => `"${String(x).replace(/"/g, '""')}"`;
    // Séparateur « ; » et BOM UTF-8 : ouverture directe dans Excel en français.
    const csv = "﻿" + [cols.join(";"), ...data.map(r => cols.map(c => cell(r[c])).join(";"))].join("\r\n");
    download(`likes_selection_${stamp()}.csv`, "text/csv;charset=utf-8", csv);
    setInfo(`${plural(data.length, "vidéo exportée", "vidéos exportées")} (CSV).`);
  });
  $("json").addEventListener("click", () => {
    const data = rows();
    if (!data.length) return;
    download(`likes_selection_${stamp()}.json`, "application/json", JSON.stringify(data, null, 2));
    setInfo(`${plural(data.length, "vidéo exportée", "vidéos exportées")} (JSON).`);
  });
  $("copy").addEventListener("click", async () => {
    const text = filtered.map(v => v.url).join("\n");
    if (!text) return;
    try { await navigator.clipboard.writeText(text); }
    catch (e) {
      const ta = Object.assign(document.createElement("textarea"), { value: text });
      document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
    }
    setInfo(`${plural(filtered.length, "lien copié", "liens copiés")} dans le presse-papiers.`);
  });

  // ---- Événements ------------------------------------------------------------
  let qTimer;
  $("q").addEventListener("input", e => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => { state.q = e.target.value; applyFilters(); }, 150);
  });
  $("chq").addEventListener("input", e => { state.chq = e.target.value; renderChannels(); });
  $("mode").addEventListener("change", e => { state.mode = e.target.value; state.year = ""; closed.clear(); renderYears(); applyFilters(); });
  $("year").addEventListener("change", e => { state.year = e.target.value; applyFilters(); });
  $("order").addEventListener("change", e => { state.order = e.target.value; applyFilters(); });

  function selectChannels(indices, additive) {
    if (!additive) state.sel.clear();
    for (const i of indices) {
      if (additive && state.sel.has(i)) state.sel.delete(i); else state.sel.add(i);
    }
    renderChannels();
    applyFilters();
  }
  $("chlist").addEventListener("click", e => {
    const row = e.target.closest(".ch");
    if (!row) return;
    const i = +row.dataset.i;
    const additive = e.ctrlKey || e.metaKey || e.target.matches("input");
    if (!additive && state.sel.size === 1 && state.sel.has(i)) { selectChannels([], false); return; }
    selectChannels([i], additive);
    if (!additive) document.body.classList.remove("side-open");
  });
  $("allCh").addEventListener("click", () => selectChannels([], false));
  if (followedIdx.length) {
    $("followed").classList.remove("hidden");
    $("followed").addEventListener("click", () => selectChannels(followedIdx, false));
  }
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
  $("expand").addEventListener("click", () => { closed.clear(); document.querySelectorAll("#content details").forEach(d => d.open = true); });
  $("collapse").addEventListener("click", () => document.querySelectorAll("#content details").forEach(d => d.open = false));
  $("reset").addEventListener("click", () => {
    Object.assign(state, { q: "", mode: "p", year: "", order: "desc", chq: "" });
    state.sel.clear(); closed.clear();
    $("q").value = ""; $("chq").value = ""; $("mode").value = "p"; $("order").value = "desc";
    renderYears(); renderChannels(); applyFilters();
  });
  $("toggleSide").addEventListener("click", () => document.body.classList.toggle("side-open"));

  renderYears();
  renderChannels();
  applyFilters();
})();
</script>
</body>
</html>
"""
