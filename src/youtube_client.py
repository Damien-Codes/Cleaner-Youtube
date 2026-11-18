"""Résolution des URL de chaînes, récupération paginée des likes et cache JSON local."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import unquote, urlparse

from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

logger = logging.getLogger(__name__)

LIKED_PLAYLIST_ID = "LL"
CACHE_VERSION = 1
API_RETRIES = 3

CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
_PAGE_ID_PATTERNS = (
    re.compile(r'<link rel="canonical" href="https?://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{22})"'),
    re.compile(r'"externalId":"(UC[A-Za-z0-9_-]{22})"'),
    re.compile(r'<meta itemprop="identifier" content="(UC[A-Za-z0-9_-]{22})"'),
    re.compile(r'"browseId":"(UC[A-Za-z0-9_-]{22})"'),
)
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}


class ChannelResolutionError(ValueError):
    """La chaîne n'a pas pu être résolue en channelId."""


# --------------------------------------------------------------------------- #
# Modèles
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ChannelInfo:
    channel_id: str
    title: str
    source_url: str
    handle: str | None = None

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/channel/{self.channel_id}"


@dataclass(slots=True)
class LikedVideo:
    video_id: str
    title: str
    url: str
    channel_id: str | None
    channel_title: str | None
    video_published_at: str | None
    liked_at: str | None
    thumbnail_url: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LikedVideo":
        return cls(
            video_id=data["video_id"],
            title=data.get("title", ""),
            url=data.get("url") or f"https://www.youtube.com/watch?v={data['video_id']}",
            channel_id=data.get("channel_id"),
            channel_title=data.get("channel_title"),
            video_published_at=data.get("video_published_at"),
            liked_at=data.get("liked_at"),
            thumbnail_url=data.get("thumbnail_url"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def published_datetime(self) -> datetime | None:
        return parse_iso_datetime(self.video_published_at)

    @property
    def liked_datetime(self) -> datetime | None:
        return parse_iso_datetime(self.liked_at)


def parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse une date RFC 3339 renvoyée par l'API (ex. 2023-05-01T12:00:00Z)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Lecture de channels.txt et analyse des URL
# --------------------------------------------------------------------------- #
def read_channels_file(path: Path) -> list[str]:
    """Lit une URL de chaîne par ligne en ignorant lignes vides et commentaires `#`."""
    if not path.exists():
        raise FileNotFoundError(f"Fichier de chaînes introuvable : {path}")
    urls: list[str] = []
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Commentaire en fin de ligne : « https://... # ma note »
        line = re.split(r"\s+#", line, maxsplit=1)[0].strip()
        if line and line not in seen:
            seen.add(line)
            urls.append(line)
    return urls


def parse_channel_url(raw: str) -> tuple[str, str]:
    """Identifie le type de référence d'une chaîne.

    Retourne un tuple (kind, value) avec kind parmi : "id", "handle", "user", "custom".
    Accepte aussi les valeurs nues : `@handle` ou `UCxxxxxxxxxxxxxxxxxxxxxx`.
    """
    text = raw.strip()
    if not text:
        raise ChannelResolutionError("Référence de chaîne vide.")

    if CHANNEL_ID_RE.match(text):
        return "id", text
    if text.startswith("@"):
        return "handle", unquote(text[1:].split("/")[0])

    if not re.match(r"^https?://", text, re.IGNORECASE):
        text = "https://" + text
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if host not in _YOUTUBE_HOSTS:
        raise ChannelResolutionError(f"URL non reconnue comme une URL YouTube : {raw}")

    parts = [unquote(p) for p in parsed.path.split("/") if p]
    if not parts:
        raise ChannelResolutionError(f"URL de chaîne incomplète : {raw}")

    first = parts[0]
    if first.startswith("@") and len(first) > 1:
        return "handle", first[1:]
    if first.lower() == "channel" and len(parts) > 1 and CHANNEL_ID_RE.match(parts[1]):
        return "id", parts[1]
    if first.lower() == "user" and len(parts) > 1:
        return "user", parts[1]
    if first.lower() == "c" and len(parts) > 1:
        return "custom", parts[1]
    # Ancien format court : youtube.com/NomPersonnalisé
    reserved = {"watch", "shorts", "playlist", "feed", "results", "embed", "live", "channel", "user", "c"}
    if first.lower() not in reserved:
        return "custom", first
    raise ChannelResolutionError(f"Impossible d'extraire une chaîne de l'URL : {raw}")


# --------------------------------------------------------------------------- #
# Client YouTube
# --------------------------------------------------------------------------- #
class YouTubeClient:
    def __init__(self, service: Resource, console: Console | None = None) -> None:
        self.service = service
        self.console = console or Console()

    # ---- Résolution des chaînes ------------------------------------------- #
    def _channels_list(self, **kwargs: Any) -> dict[str, Any] | None:
        response = (
            self.service.channels()
            .list(part="snippet", maxResults=1, **kwargs)
            .execute(num_retries=API_RETRIES)
        )
        items = response.get("items") or []
        return items[0] if items else None

    @staticmethod
    def _to_channel_info(item: dict[str, Any], source_url: str) -> ChannelInfo:
        snippet = item.get("snippet", {})
        custom_url = snippet.get("customUrl")
        return ChannelInfo(
            channel_id=item["id"],
            title=snippet.get("title") or item["id"],
            source_url=source_url,
            handle=custom_url if custom_url and custom_url.startswith("@") else None,
        )

    @staticmethod
    def _scrape_channel_id(url: str) -> str | None:
        """Récupère le channelId depuis la page HTML publique (utile pour les URL /c/...)."""
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
                # Évite la redirection vers la page de consentement cookies (UE).
                "Cookie": "SOCS=CAI; CONSENT=YES+cb",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                html = response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.debug("Lecture de la page %s impossible : %s", url, exc)
            return None
        for pattern in _PAGE_ID_PATTERNS:
            match = pattern.search(html)
            if match:
                return match.group(1)
        return None

    def resolve_channel(self, raw_url: str) -> ChannelInfo:
        kind, value = parse_channel_url(raw_url)
        item: dict[str, Any] | None = None

        if kind == "id":
            item = self._channels_list(id=value)
        elif kind == "handle":
            item = self._channels_list(forHandle=value)
        elif kind == "user":
            item = self._channels_list(forUsername=value)
            if item is None:
                item = self._channels_list(forHandle=value)
        elif kind == "custom":
            # L'API n'expose pas les URL personnalisées /c/... : on lit la page publique,
            # puis on tente le handle homonyme, et en dernier recours la recherche.
            page_url = raw_url if raw_url.lower().startswith("http") else f"https://{raw_url}"
            scraped_id = self._scrape_channel_id(page_url)
            if scraped_id:
                item = self._channels_list(id=scraped_id)
            if item is None:
                item = self._channels_list(forHandle=value)
            if item is None:
                item = self._search_channel(value)

        if item is None:
            raise ChannelResolutionError(f"Aucune chaîne trouvée pour : {raw_url}")
        return self._to_channel_info(item, raw_url)

    def _search_channel(self, query: str) -> dict[str, Any] | None:
        self.console.print(
            f"[yellow]⚠ Résolution par recherche pour « {query} » (coût : 100 unités de quota, "
            "résultat à vérifier).[/yellow]"
        )
        response = (
            self.service.search()
            .list(part="snippet", q=query, type="channel", maxResults=1)
            .execute(num_retries=API_RETRIES)
        )
        items = response.get("items") or []
        if not items:
            return None
        channel_id = items[0]["snippet"]["channelId"]
        return self._channels_list(id=channel_id)

    def resolve_channels(self, urls: Iterable[str]) -> tuple[list[ChannelInfo], list[tuple[str, str]]]:
        """Résout chaque URL. Retourne (chaînes résolues, [(url, erreur)])."""
        resolved: list[ChannelInfo] = []
        errors: list[tuple[str, str]] = []
        seen_ids: set[str] = set()
        for url in urls:
            try:
                info = self.resolve_channel(url)
            except ChannelResolutionError as exc:
                errors.append((url, str(exc)))
                continue
            except HttpError as exc:
                errors.append((url, f"Erreur API : {_http_error_message(exc)}"))
                continue
            if info.channel_id in seen_ids:
                logger.info("Chaîne en double ignorée : %s", url)
                continue
            seen_ids.add(info.channel_id)
            resolved.append(info)
        return resolved, errors

    # ---- Récupération des likes ------------------------------------------ #
    @staticmethod
    def _best_thumbnail(thumbnails: dict[str, Any]) -> str | None:
        for key in ("medium", "high", "standard", "default", "maxres"):
            if key in thumbnails and thumbnails[key].get("url"):
                return thumbnails[key]["url"]
        return None

    @classmethod
    def _item_to_video(cls, item: dict[str, Any]) -> LikedVideo | None:
        snippet = item.get("snippet", {})
        details = item.get("contentDetails", {})
        video_id = details.get("videoId") or snippet.get("resourceId", {}).get("videoId")
        if not video_id:
            return None
        return LikedVideo(
            video_id=video_id,
            title=snippet.get("title", ""),
            url=f"https://www.youtube.com/watch?v={video_id}",
            # snippet.channelId désigne le propriétaire de la playlist (vous) :
            # la chaîne de la vidéo est dans videoOwnerChannelId.
            channel_id=snippet.get("videoOwnerChannelId"),
            channel_title=snippet.get("videoOwnerChannelTitle"),
            video_published_at=details.get("videoPublishedAt"),
            liked_at=snippet.get("publishedAt"),
            thumbnail_url=cls._best_thumbnail(snippet.get("thumbnails") or {}),
        )

    def fetch_liked_videos(
        self,
        on_progress: Callable[[int, int | None], None] | None = None,
        show_progress: bool = True,
    ) -> list[LikedVideo]:
        """Parcourt toute la playlist « LL » (vidéos likées) avec pagination.

        `on_progress(traités, total)` est appelé après chaque page (utile pour afficher une
        progression ; il peut lever une exception pour interrompre la récupération).
        `show_progress=False` désactive la barre `rich` du terminal.
        """
        videos: list[LikedVideo] = []
        seen: set[str] = set()
        page_token: str | None = None
        done = 0

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]Récupération des likes"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self.console,
            disable=not show_progress,
        )
        with progress:
            task = progress.add_task("likes", total=None)
            while True:
                request = self.service.playlistItems().list(
                    part="snippet,contentDetails",
                    playlistId=LIKED_PLAYLIST_ID,
                    maxResults=50,
                    pageToken=page_token,
                )
                try:
                    response = request.execute(num_retries=API_RETRIES)
                except HttpError as exc:
                    raise RuntimeError(
                        f"Échec de lecture de la playlist des likes : {_http_error_message(exc)}"
                    ) from exc

                total = response.get("pageInfo", {}).get("totalResults")
                if total and progress.tasks[0].total != total:
                    progress.update(task, total=total)

                items = response.get("items", [])
                for item in items:
                    video = self._item_to_video(item)
                    if video and video.video_id not in seen:
                        seen.add(video.video_id)
                        videos.append(video)
                progress.advance(task, len(items))
                done += len(items)
                if on_progress is not None:
                    on_progress(done, total)

                page_token = response.get("nextPageToken")
                if not page_token:
                    break
            progress.update(task, total=progress.tasks[0].completed)
        return videos


def _http_error_message(exc: HttpError) -> str:
    try:
        payload = json.loads(exc.content.decode("utf-8"))
        error = payload.get("error", {})
        reason = (error.get("errors") or [{}])[0].get("reason", "")
        return f"{error.get('code', exc.status_code)} {reason} – {error.get('message', '')}".strip()
    except (ValueError, AttributeError):
        return str(exc)


# --------------------------------------------------------------------------- #
# Cache JSON
# --------------------------------------------------------------------------- #
def load_cache(cache_path: Path) -> list[LikedVideo] | None:
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Cache illisible (%s), il sera reconstruit.", exc)
        return None
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return None
    try:
        return [LikedVideo.from_dict(v) for v in data.get("videos", [])]
    except (KeyError, TypeError) as exc:
        logger.warning("Cache corrompu (%s), il sera reconstruit.", exc)
        return None


def cache_fetched_at(cache_path: Path) -> str | None:
    try:
        return json.loads(cache_path.read_text(encoding="utf-8")).get("fetched_at")
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def save_cache(cache_path: Path, videos: list[LikedVideo]) -> None:
    """Écriture atomique du cache (fichier temporaire puis remplacement)."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": CACHE_VERSION,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(videos),
        "videos": [v.to_dict() for v in videos],
    }
    fd, tmp_name = tempfile.mkstemp(prefix="likes_", suffix=".json", dir=cache_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_name, cache_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def get_liked_videos(
    client: YouTubeClient, cache_path: Path, refresh: bool = False
) -> tuple[list[LikedVideo], bool]:
    """Retourne (vidéos likées, depuis_le_cache)."""
    if not refresh:
        cached = load_cache(cache_path)
        if cached is not None:
            return cached, True
    videos = client.fetch_liked_videos()
    save_cache(cache_path, videos)
    return videos, False


# --------------------------------------------------------------------------- #
# Filtrage
# --------------------------------------------------------------------------- #
def filter_by_channel(videos: Iterable[LikedVideo], channel_id: str) -> list[LikedVideo]:
    return [v for v in videos if v.channel_id == channel_id]
