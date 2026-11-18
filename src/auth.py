"""Gestion de l'authentification OAuth 2.0 pour l'API YouTube Data v3."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build

logger = logging.getLogger(__name__)

# Lecture seule : suffisant pour lire la playlist des vidéos likées et résoudre les chaînes.
SCOPES: list[str] = ["https://www.googleapis.com/auth/youtube.readonly"]


class AuthError(RuntimeError):
    """Erreur levée lorsque l'authentification ne peut pas aboutir."""


def _load_token(token_path: Path) -> Credentials | None:
    """Charge un token existant s'il est lisible et couvre les scopes requis."""
    if not token_path.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning("token.json illisible (%s) : une nouvelle autorisation sera demandée.", exc)
        return None
    if creds.scopes and not set(SCOPES).issubset(set(creds.scopes)):
        logger.warning("token.json ne couvre pas les scopes requis : nouvelle autorisation.")
        return None
    return creds


def _save_token(creds: Credentials, token_path: Path) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")


def _run_local_flow(client_secrets_path: Path) -> Credentials:
    if not client_secrets_path.exists():
        raise AuthError(
            f"Fichier d'identifiants OAuth introuvable : {client_secrets_path}\n"
            "Créez un ID client « Application de bureau » dans Google Cloud Console et enregistrez son JSON "
            "sous ce nom (voir README.md, section B.1 ; modèle : client_secrets.example.json)."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_path), SCOPES)
    # port=0 : un port libre est choisi automatiquement pour la redirection locale.
    return flow.run_local_server(
        port=0,
        prompt="consent",
        authorization_prompt_message="Ouverture du navigateur pour autoriser l'accès : {url}",
        success_message="Autorisation terminée, vous pouvez fermer cet onglet.",
        open_browser=True,
    )


def get_credentials(client_secrets_path: Path, token_path: Path) -> Credentials:
    """Retourne des identifiants valides, en les rafraîchissant ou en relançant le flux OAuth."""
    creds = _load_token(token_path)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds, token_path)
            return creds
        except RefreshError as exc:
            logger.warning("Rafraîchissement du token impossible (%s) : nouvelle autorisation.", exc)

    creds = _run_local_flow(client_secrets_path)
    _save_token(creds, token_path)
    return creds


def build_youtube_service(client_secrets_path: Path, token_path: Path) -> Resource:
    """Construit le client `youtube` v3 authentifié."""
    creds = get_credentials(client_secrets_path, token_path)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)
