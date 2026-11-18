"""Ouverture interactive des vidéos dans le navigateur par défaut, par lots."""

from __future__ import annotations

import time
import webbrowser
from typing import Sequence

from rich.console import Console
from rich.prompt import Confirm, Prompt

from .youtube_client import LikedVideo

DEFAULT_BATCH_SIZE = 5
# Petite pause entre deux onglets : certains navigateurs perdent des onglets ouverts trop vite.
_TAB_DELAY_SECONDS = 0.35


def ask_to_open(count: int, console: Console) -> bool:
    """Demande confirmation dans le terminal. Retourne False si l'entrée n'est pas interactive."""
    if count == 0:
        return False
    try:
        return Confirm.ask(
            f"Ouvrir les [bold]{count}[/bold] vidéo(s) dans le navigateur ?",
            default=False,
            console=console,
        )
    except (EOFError, KeyboardInterrupt):
        console.print()
        return False


def open_in_batches(
    videos: Sequence[LikedVideo],
    batch_size: int = DEFAULT_BATCH_SIZE,
    console: Console | None = None,
) -> int:
    """Ouvre les vidéos par lots de `batch_size` onglets, avec Entrée entre chaque lot.

    Retourne le nombre de vidéos effectivement ouvertes.
    """
    console = console or Console()
    if batch_size < 1:
        raise ValueError("batch_size doit être supérieur ou égal à 1.")
    if not videos:
        console.print("[yellow]Aucune vidéo à ouvrir.[/yellow]")
        return 0

    total = len(videos)
    batches = [videos[i : i + batch_size] for i in range(0, total, batch_size)]
    opened = 0

    for index, batch in enumerate(batches, start=1):
        console.print(
            f"[bold cyan]Lot {index}/{len(batches)}[/bold cyan] "
            f"(vidéos {opened + 1}–{opened + len(batch)} sur {total})"
        )
        for video in batch:
            published = video.published_datetime
            year = f"{published.year}" if published else "????"
            console.print(f"  • [dim]{year}[/dim] {video.title}")
            if not webbrowser.open_new_tab(video.url):
                console.print(f"    [red]Impossible d'ouvrir {video.url}[/red]")
            else:
                opened += 1
            time.sleep(_TAB_DELAY_SECONDS)

        if index < len(batches):
            try:
                answer = Prompt.ask(
                    "[dim]Entrée pour le lot suivant, « q » pour arrêter[/dim]",
                    default="",
                    show_default=False,
                    console=console,
                )
            except (EOFError, KeyboardInterrupt):
                console.print()
                answer = "q"
            if answer.strip().lower() in {"q", "quit", "stop", "n"}:
                console.print("[yellow]Ouverture interrompue.[/yellow]")
                break

    console.print(f"[green]✔ {opened} vidéo(s) ouverte(s).[/green]")
    return opened
