#!/usr/bin/env python3
"""Cleaner YouTube – tableau de bord de toutes vos vidéos likées, rapports par chaîne,
ouverture par lots et nettoyage optionnel de l'historique.

Exemples :
    python main.py                       # tableau de bord depuis le cache, ouvert dans le navigateur
    python main.py --refresh             # recharge les likes depuis l'API avant de générer
    python main.py --no-open             # génère sans rien ouvrir
    python main.py --open --batch-size 5 # ouvre aussi les vidéos des chaînes de channels.txt
    python main.py --asc --clean-history
"""

from __future__ import annotations

import argparse
import logging
import sys
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

if TYPE_CHECKING:
    from src.youtube_client import YouTubeClient

ROOT = Path(__file__).resolve().parent
console = Console()

# Entrées d'exemple livrées dans channels.txt : ignorées pour le filtre « Mes chaînes suivies ».
EXAMPLE_CHANNEL_HANDLES = {"googledevelopers"}


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"entier attendu : {value!r}") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("la valeur doit être ≥ 1")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cleaner-youtube",
        description="Génère un tableau de bord de vos vidéos YouTube likées (filtrable par chaîne, année et mot-clé).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--refresh", action="store_true", help="Force la mise à jour du cache des likes depuis l'API.")
    opening = parser.add_mutually_exclusive_group()
    opening.add_argument("--open", action="store_true",
                         help="Ouvre sans confirmation les vidéos des chaînes de channels.txt, par lots.")
    opening.add_argument("--no-open", action="store_true",
                         help="N'ouvre rien dans le navigateur (ni tableau de bord, ni vidéos).")
    parser.add_argument("--serve", action="store_true",
                        help="Sert le tableau de bord sur http://127.0.0.1 (permet d'autoriser les pop-ups "
                             "pour ouvrir 5 onglets d'un coup). Ctrl+C pour arrêter.")
    parser.add_argument("--port", type=positive_int, default=8765, help="Port utilisé avec --serve.")
    parser.add_argument("--batch-size", type=positive_int, default=5, help="Nombre d'onglets ouverts par lot.")
    parser.add_argument("--asc", action="store_true", help="Rapports par chaîne : du plus ancien au plus récent.")
    parser.add_argument("--clean-history", action="store_true", help="Nettoie l'historique YouTube via Playwright (optionnel).")
    parser.add_argument(
        "--clean-scope", choices=("channels", "all"), default="channels",
        help="Avec --clean-history : éléments des chaînes de channels.txt uniquement, ou tout l'historique.",
    )
    parser.add_argument("--channels-file", type=Path, default=ROOT / "channels.txt", help="Fichier des URL de chaînes suivies.")
    parser.add_argument("--client-secrets", type=Path, default=ROOT / "client_secrets.json", help="Identifiants OAuth.")
    parser.add_argument("--token", type=Path, default=ROOT / "token.json", help="Token OAuth sauvegardé.")
    parser.add_argument("--cache", type=Path, default=ROOT / "data" / "likes_cache.json", help="Cache local des likes.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output", help="Dossier des fichiers HTML générés.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Journalisation détaillée.")
    return parser


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False, rich_tracebacks=True)],
    )
    # Les bibliothèques Google sont très bavardes en DEBUG.
    for noisy in ("googleapiclient", "google_auth_httplib2", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def is_example_entry(url: str) -> bool:
    from src.youtube_client import ChannelResolutionError, parse_channel_url

    try:
        kind, value = parse_channel_url(url)
    except ChannelResolutionError:
        return False
    return kind == "handle" and value.lower() in EXAMPLE_CHANNEL_HANDLES


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


class LazyClient:
    """Ne s'authentifie auprès de l'API que si c'est réellement nécessaire."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self._client: YouTubeClient | None = None

    def get(self) -> "YouTubeClient":
        if self._client is None:
            from src.auth import build_youtube_service
            from src.youtube_client import YouTubeClient

            with console.status("Authentification OAuth…"):
                service = build_youtube_service(self.args.client_secrets, self.args.token)
            self._client = YouTubeClient(service, console)
        return self._client


def serve_dashboard(dashboard: Path, port: int, open_browser: bool = True) -> None:
    """Sert le dossier du tableau de bord en local (127.0.0.1 uniquement) jusqu'à Ctrl+C."""
    import functools
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    handler = functools.partial(QuietHandler, directory=str(dashboard.parent))
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError:
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)  # port occupé : port libre
    url = f"http://127.0.0.1:{server.server_address[1]}/{dashboard.name}"
    console.print(f"[green]✔ Tableau de bord servi sur[/green] [link={url}]{url}[/link] [dim](Ctrl+C pour arrêter)[/dim]")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("[dim]Serveur arrêté.[/dim]")
    finally:
        server.server_close()


def run(args: argparse.Namespace) -> int:
    # Imports différés : `--help` reste instantané.
    from googleapiclient.errors import HttpError

    from src.auth import AuthError
    from src.browser_opener import ask_to_open, open_in_batches
    from src.report_generator import flatten, generate_dashboard, generate_report, group_by_year
    from src.youtube_client import (
        ChannelInfo,
        cache_fetched_at,
        filter_by_channel,
        load_cache,
        read_channels_file,
        save_cache,
    )

    if args.batch_size > 10:
        console.print(f"[yellow]⚠ Lots de {args.batch_size} onglets : la mémoire du navigateur risque de saturer.[/yellow]")

    lazy = LazyClient(args)

    # 1. Likes : cache par défaut, API si --refresh ou si le cache est absent
    likes = None if args.refresh else load_cache(args.cache)
    if likes is not None:
        console.print(
            f"[dim]{len(likes)} likes chargés depuis le cache ({cache_fetched_at(args.cache) or 'date inconnue'}). "
            "Utilisez --refresh pour le mettre à jour.[/dim]"
        )
    else:
        try:
            client = lazy.get()
            likes = client.fetch_liked_videos()
        except AuthError as exc:
            console.print(f"[red]{exc}[/red]")
            return 2
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/red]")
            return 1
        save_cache(args.cache, likes)
        console.print(f"[green]✔ {len(likes)} likes récupérés et mis en cache dans {display_path(args.cache)}.[/green]")

    # 2. Chaînes suivies (channels.txt), hors exemples livrés avec le projet
    try:
        urls = [u for u in read_channels_file(args.channels_file) if not is_example_entry(u)]
    except FileNotFoundError:
        urls = []
    followed: list[ChannelInfo] = []
    if urls:
        try:
            client = lazy.get()
            with console.status("Résolution des chaînes de channels.txt…"):
                followed, errors = client.resolve_channels(urls)
            for url, message in errors:
                console.print(f"[red]✘ {url}[/red] : {message}")
        except (AuthError, HttpError) as exc:
            console.print(f"[yellow]⚠ Chaînes de channels.txt non résolues ({exc}) : filtre « Mes chaînes suivies » désactivé.[/yellow]")

    # 3. Tableau de bord global
    dashboard = generate_dashboard(likes, args.output_dir, followed)
    channel_count = len({v.channel_id for v in likes if v.channel_id})
    console.print(
        f"[green]✔ Tableau de bord généré :[/green] [link={dashboard.as_uri()}]{display_path(dashboard)}[/link] "
        f"({len(likes)} vidéos, {channel_count} chaînes"
        f"{f', {len(followed)} chaîne(s) suivie(s)' if followed else ''})"
    )

    # 4. Rapports par chaîne suivie
    to_open = []
    if followed:
        summary = Table(title="Chaînes suivies (channels.txt)", header_style="bold cyan")
        summary.add_column("Chaîne")
        summary.add_column("Vidéos likées", justify="right")
        summary.add_column("Répartition par année")
        summary.add_column("Rapport HTML")
        for channel in followed:
            matched = filter_by_channel(likes, channel.channel_id)
            grouped = group_by_year(matched, ascending=args.asc)
            report = generate_report(channel, grouped, args.output_dir, ascending=args.asc)
            breakdown = ", ".join(f"{year}: {len(videos)}" for year, videos in grouped.items()) or "—"
            summary.add_row(channel.title, str(len(matched)), breakdown,
                            f"[link={report.as_uri()}]{display_path(report)}[/link]")
            to_open.extend(flatten(grouped))
        console.print(summary)
    elif args.open:
        console.print("[yellow]--open ne concerne que les chaînes de channels.txt : utilisez le bouton "
                      "« Ouvrir 5 vidéos » du tableau de bord.[/yellow]")

    # 5. Ouverture par lots des vidéos des chaînes suivies
    if to_open and not args.no_open and (args.open or ask_to_open(len(to_open), console)):
        open_in_batches(to_open, args.batch_size, console)

    # 6. Nettoyage optionnel de l'historique
    exit_code = 0
    if args.clean_history:
        from src.history_cleaner import HistoryCleanerUnavailable, clean_history

        try:
            clean_history(
                [c.title for c in followed],
                scope=args.clean_scope,
                profile_dir=args.cache.parent / "playwright_profile",
                console=console,
            )
        except HistoryCleanerUnavailable as exc:
            console.print(f"[red]{exc}[/red]")
            exit_code = 1

    # 7. Ouverture du tableau de bord
    if args.serve:
        serve_dashboard(dashboard, args.port, open_browser=not args.no_open)
    elif not args.no_open:
        if webbrowser.open(dashboard.as_uri()):
            console.print("[dim]Tableau de bord ouvert dans le navigateur.[/dim]")
        else:
            console.print(f"[yellow]Ouvrez manuellement : {dashboard}[/yellow]")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)
    try:
        return run(args)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrompu.[/yellow]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
