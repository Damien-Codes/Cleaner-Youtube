"""Nettoyage optionnel de l'historique YouTube via Playwright (Google My Activity).

L'API YouTube Data v3 ne permet pas de supprimer l'historique de visionnage. Ce module
pilote donc un vrai navigateur (profil persistant) sur https://myactivity.google.com.

Deux modes :
  * "channels" : recherche chaque chaîne cible dans My Activity et supprime, élément par
    élément, les entrées dont la carte mentionne le nom de la chaîne ;
  * "all"      : utilise le menu « Supprimer » → « Toute la période » de Google.

La connexion au compte Google se fait manuellement par vous dans la fenêtre ouverte
(le profil est conservé dans data/playwright_profile pour les fois suivantes).
L'interface de Google évolue régulièrement : si un sélecteur ne fonctionne plus, le
script vous laisse terminer l'opération à la main dans la fenêtre ouverte.

Playwright est importé de manière conditionnelle : le reste du projet fonctionne sans.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Sequence

from rich.console import Console
from rich.prompt import Confirm, Prompt

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:  # pragma: no cover - dépend de l'environnement
    PLAYWRIGHT_AVAILABLE = False
    PlaywrightError = Exception  # type: ignore[assignment, misc]
    PlaywrightTimeoutError = Exception  # type: ignore[assignment, misc]

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Page, Playwright

MY_ACTIVITY_URL = "https://myactivity.google.com/product/youtube"
CONFIRMATION_WORD = "SUPPRIMER"
CleanScope = Literal["channels", "all"]

# Libellés FR/EN de l'interface My Activity.
_RE_DELETE_BUTTON = re.compile(r"^\s*(supprimer|delete)\s*$", re.IGNORECASE)
_RE_ALL_TIME = re.compile(r"(toute la période|depuis toujours|toujours|all time)", re.IGNORECASE)
_RE_NEXT = re.compile(r"^\s*(suivant|next)\s*$", re.IGNORECASE)
_RE_CONFIRM_DELETE = re.compile(r"^\s*(supprimer|delete)\s*$", re.IGNORECASE)
_RE_GOT_IT = re.compile(r"(ok|j'ai compris|got it|compris|fermer|close)", re.IGNORECASE)
_RE_SEARCH = re.compile(r"(rechercher|search)", re.IGNORECASE)

# Marque (attribut data-ytcleaner) les boutons « Supprimer l'élément » des cartes dont le texte
# contient le nom de la chaîne. Une carte = plus petit ancêtre contenant exactement un lien vidéo.
_MARK_ITEMS_JS = r"""
(channel) => {
  const norm = s => (s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const target = norm(channel);
  const labelRe = /(supprimer l.?[ée]l[ée]ment|delete activity item|supprimer l.activit|delete item)/i;
  document.querySelectorAll('[data-ytcleaner]').forEach(el => el.removeAttribute('data-ytcleaner'));
  let count = 0;
  const buttons = [...document.querySelectorAll('button[aria-label], [role="button"][aria-label]')]
    .filter(b => labelRe.test(b.getAttribute('aria-label')));
  for (const btn of buttons) {
    let node = btn.parentElement;
    let card = null;
    for (let depth = 0; node && depth < 12; depth++, node = node.parentElement) {
      const links = node.querySelectorAll('a[href*="youtube.com/watch"], a[href*="youtube.com/shorts"]');
      if (links.length === 1) { card = node; break; }
      if (links.length > 1) break;
    }
    if (card && norm(card.innerText).includes(target)) {
      btn.setAttribute('data-ytcleaner', '1');
      count++;
    }
  }
  return count;
}
"""


class HistoryCleanerUnavailable(RuntimeError):
    """Playwright n'est pas installé."""


def ensure_available() -> None:
    if not PLAYWRIGHT_AVAILABLE:
        raise HistoryCleanerUnavailable(
            "Playwright n'est pas installé. Pour activer --clean-history :\n"
            "    pip install playwright\n"
            "    python -m playwright install chromium"
        )


# --------------------------------------------------------------------------- #
# Navigateur
# --------------------------------------------------------------------------- #
def _launch_context(pw: "Playwright", profile_dir: Path, console: Console) -> "BrowserContext":
    """Lance un contexte persistant, en préférant Google Chrome installé (mieux accepté par Google)."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    common = {
        "user_data_dir": str(profile_dir),
        "headless": False,
        "viewport": None,
        "locale": "fr-FR",
        "args": ["--disable-blink-features=AutomationControlled", "--start-maximized"],
        "ignore_default_args": ["--enable-automation"],
    }
    try:
        return pw.chromium.launch_persistent_context(channel="chrome", **common)
    except PlaywrightError:
        console.print("[dim]Google Chrome introuvable, utilisation de Chromium (Playwright).[/dim]")
        return pw.chromium.launch_persistent_context(**common)


def _wait_for_login(page: "Page", console: Console) -> bool:
    page.goto(MY_ACTIVITY_URL, wait_until="domcontentloaded")
    console.print(
        "\n[bold]Une fenêtre de navigateur est ouverte sur Google My Activity.[/bold]\n"
        "Connectez-vous au compte Google concerné si nécessaire (vous saisissez vous-même vos "
        "identifiants), puis revenez ici."
    )
    while True:
        try:
            Prompt.ask("Appuyez sur Entrée une fois la page My Activity affichée", default="", show_default=False)
        except (EOFError, KeyboardInterrupt):
            return False
        if "myactivity.google.com" in page.url and "signin" not in page.url:
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except PlaywrightTimeoutError:
                pass
            return True
        console.print(f"[yellow]La page actuelle n'est pas My Activity ({page.url}).[/yellow]")
        if not Confirm.ask("Réessayer ?", default=True):
            return False
        page.goto(MY_ACTIVITY_URL, wait_until="domcontentloaded")


def _click_first(page: "Page", candidates: Sequence, timeout: int = 5_000) -> bool:
    """Clique le premier localisateur visible parmi `candidates`."""
    for locator in candidates:
        try:
            target = locator.first
            target.wait_for(state="visible", timeout=timeout)
            target.click()
            return True
        except (PlaywrightTimeoutError, PlaywrightError):
            continue
    return False


def _manual_fallback(console: Console, message: str) -> None:
    console.print(
        f"[yellow]⚠ {message}[/yellow]\n"
        "L'interface de Google a peut-être changé : terminez l'opération manuellement dans la "
        "fenêtre ouverte."
    )
    try:
        Prompt.ask("Appuyez sur Entrée quand vous avez terminé", default="", show_default=False)
    except (EOFError, KeyboardInterrupt):
        pass


# --------------------------------------------------------------------------- #
# Mode « all »
# --------------------------------------------------------------------------- #
def _delete_all(page: "Page", console: Console) -> None:
    console.print("Ouverture du menu « Supprimer »…")
    if not _click_first(page, [
        page.get_by_role("button", name=_RE_DELETE_BUTTON),
        page.get_by_role("button", name=re.compile(r"supprimer|delete", re.I)),
    ]):
        _manual_fallback(console, "Bouton « Supprimer » introuvable.")
        return

    if not _click_first(page, [
        page.get_by_role("menuitem", name=_RE_ALL_TIME),
        page.get_by_role("option", name=_RE_ALL_TIME),
        page.get_by_text(_RE_ALL_TIME),
    ]):
        _manual_fallback(console, "Option « Toute la période » introuvable.")
        return

    # Certaines versions affichent une étape de sélection des produits (« Suivant »).
    _click_first(page, [page.get_by_role("button", name=_RE_NEXT)], timeout=4_000)

    dialog = page.get_by_role("dialog")
    if not _click_first(page, [
        dialog.get_by_role("button", name=_RE_CONFIRM_DELETE),
        page.get_by_role("button", name=_RE_CONFIRM_DELETE).last,
    ], timeout=8_000):
        _manual_fallback(console, "Bouton de confirmation introuvable.")
        return

    _click_first(page, [page.get_by_role("button", name=_RE_GOT_IT)], timeout=8_000)
    console.print("[green]✔ Demande de suppression de tout l'historique YouTube envoyée.[/green]")


# --------------------------------------------------------------------------- #
# Mode « channels »
# --------------------------------------------------------------------------- #
def _search(page: "Page", query: str) -> bool:
    page.goto(MY_ACTIVITY_URL, wait_until="domcontentloaded")
    candidates = [
        page.get_by_role("searchbox"),
        page.get_by_role("textbox", name=_RE_SEARCH),
        page.get_by_role("combobox", name=_RE_SEARCH),
        page.locator("input[type='search'], input[type='text']"),
    ]
    for locator in candidates:
        try:
            box = locator.first
            box.wait_for(state="visible", timeout=6_000)
            box.fill(query)
            box.press("Enter")
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(1_500)
            return True
        except (PlaywrightTimeoutError, PlaywrightError):
            continue
    return False


def _load_all_results(page: "Page", channel: str, max_rounds: int = 200) -> int:
    """Fait défiler la page jusqu'à ce qu'aucun nouvel élément ne se charge."""
    previous_height = -1
    stable_rounds = 0
    for _ in range(max_rounds):
        height = page.evaluate("document.body.scrollHeight")
        if height == previous_height:
            stable_rounds += 1
            if stable_rounds >= 3:
                break
        else:
            stable_rounds = 0
        previous_height = height
        page.mouse.wheel(0, 4_000)
        page.wait_for_timeout(900)
    page.evaluate("window.scrollTo(0, 0)")
    return int(page.evaluate(_MARK_ITEMS_JS, channel))


def _delete_channel_items(page: "Page", channel: str, console: Console) -> int:
    if not _search(page, channel):
        _manual_fallback(console, "Champ de recherche My Activity introuvable.")
        return 0

    found = _load_all_results(page, channel)
    if found == 0:
        console.print(f"  Aucun élément d'historique trouvé pour « {channel} ».")
        return 0

    if not Confirm.ask(
        f"  {found} élément(s) mentionnant « {channel} » trouvé(s). Les supprimer ?", default=False
    ):
        console.print("  [dim]Ignoré.[/dim]")
        return 0

    deleted = 0
    failures = 0
    while failures < 5:
        remaining = int(page.evaluate(_MARK_ITEMS_JS, channel))
        if remaining == 0:
            # Des éléments supplémentaires peuvent se charger après suppression.
            page.mouse.wheel(0, 4_000)
            page.wait_for_timeout(1_200)
            if int(page.evaluate(_MARK_ITEMS_JS, channel)) == 0:
                break
            continue
        button = page.locator("[data-ytcleaner='1']").first
        try:
            button.scroll_into_view_if_needed(timeout=5_000)
            button.click(timeout=5_000)
            # Éventuelle boîte de confirmation.
            _click_first(page, [page.get_by_role("dialog").get_by_role("button", name=_RE_CONFIRM_DELETE)], timeout=1_000)
            page.wait_for_timeout(700)
            deleted += 1
            failures = 0
            console.print(f"  [green]✔[/green] {deleted} supprimé(s)", end="\r")
        except (PlaywrightTimeoutError, PlaywrightError):
            failures += 1
            page.wait_for_timeout(1_000)
    console.print(f"  [green]✔ {deleted} élément(s) supprimé(s) pour « {channel} ».[/green]")
    return deleted


# --------------------------------------------------------------------------- #
# Point d'entrée
# --------------------------------------------------------------------------- #
def clean_history(
    channel_titles: Sequence[str],
    scope: CleanScope = "channels",
    profile_dir: Path = Path("data/playwright_profile"),
    console: Console | None = None,
) -> None:
    """Nettoie l'historique YouTube après confirmation explicite de l'utilisateur."""
    console = console or Console()
    ensure_available()

    if scope == "channels" and not channel_titles:
        console.print("[yellow]Aucune chaîne cible : rien à nettoyer.[/yellow]")
        return

    console.rule("[bold red]Nettoyage de l'historique YouTube")
    if scope == "all":
        console.print("[bold red]TOUT votre historique d'activité YouTube (toute la période)[/bold red] sera supprimé.")
    else:
        console.print("Les éléments d'historique mentionnant ces chaînes seront supprimés :")
        for title in channel_titles:
            console.print(f"  • {title}")
    console.print("[bold]Cette action est irréversible.[/bold]")
    try:
        answer = Prompt.ask(f"Tapez [bold]{CONFIRMATION_WORD}[/bold] pour confirmer", default="", show_default=False)
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer.strip() != CONFIRMATION_WORD:
        console.print("[yellow]Nettoyage annulé.[/yellow]")
        return

    with sync_playwright() as pw:
        context = _launch_context(pw, profile_dir, console)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            if not _wait_for_login(page, console):
                console.print("[yellow]Nettoyage annulé.[/yellow]")
                return
            if scope == "all":
                _delete_all(page, console)
            else:
                total = 0
                for title in channel_titles:
                    console.print(f"\n[bold cyan]Chaîne : {title}[/bold cyan]")
                    total += _delete_channel_items(page, title, console)
                console.print(f"\n[bold green]Total : {total} élément(s) supprimé(s).[/bold green]")
        finally:
            context.close()
