"""
workshop_api.py — Steam Workshop API client para RipoWall.
Sin dependencias GTK. Consume la Steam Web API para buscar, filtrar
y suscribirse a wallpapers del Workshop de Wallpaper Engine (appid 431960).

Endpoints:
  IPublishedFileService/QueryFiles/v1/  — búsqueda y navegación (requiere API key)
  ISteamRemoteStorage/GetPublishedFileDetails/v1/ — detalles de un item (público)
  steamcommunity.com/sharedfiles/subscribe/   — suscribirse (requiere cookie)
  steamcommunity.com/sharedfiles/unsubscribe/ — desuscribirse (requiere cookie)
"""  # noqa: D100

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
import urllib.parse
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path

# ── Constantes ──────────────────────────────────────────────────────────────

STEAM_API_BASE = "https://api.steampowered.com"
STEAM_COMMUNITY = "https://steamcommunity.com"
WORKSHOP_APPID = 431960  # Wallpaper Engine

# EPublishedFileInfoMatchingFileType (valores oficiales de steam-rs)
# NOTA: Todos los wallpapers de WE son file_type=0 (Items), no 3 (Videos).
# El filetype 3 retorna 0 resultados para appid 431960.
FILE_TYPE_ALL = -1         # No filtrar (no pasa el parametro)
FILE_TYPE_VIDEO = 0        # Items — todos los wallpapers de WE
FILE_TYPE_SCENE = 0        # Scene = también Items
FILE_TYPE_WEB = 0          # Web = también Items

# EPublishedFileQueryType
QUERY_RANKED_BY_VOTE = 0
QUERY_RANKED_BY_DATE = 1
QUERY_RANKED_BY_TREND = 3
QUERY_RANKED_BY_SUBSCRIPTIONS = 9
QUERY_RANKED_BY_VOTES_UP = 11
QUERY_RANKED_BY_TEXT_SEARCH = 12
QUERY_RANKED_BY_LAST_UPDATED = 21

# Paths de configuración
CONFIG_DIR = Path.home() / ".config" / "ripowall"
API_KEY_PATH = CONFIG_DIR / "steam_api_key"
SESSION_PATH = CONFIG_DIR / "steam_session"
CACHE_DIR = Path.home() / ".cache" / "ripowall" / "workshop"

# Rate limiting
_MIN_REQUEST_INTERVAL = 1.0  # segundos entre requests
_CACHE_TTL = 300             # 5 minutos

# User-Agent (Steam cliente Linux)
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Valve/Steam Client"
)

# ── Estado interno ──────────────────────────────────────────────────────────

_last_request_time: float = 0.0
_lock = threading.Lock()
_cache: dict[str, tuple[float, object]] = {}  # key -> (timestamp, data)


# ── Dataclasses ─────────────────────────────────────────────────────────────


@dataclass
class WorkshopItem:
    """Un wallpaper del Steam Workshop."""

    publishedfileid: str
    title: str = ""
    description: str = ""
    preview_url: str = ""
    file_url: str = ""
    file_size: int = 0
    file_type: int = 0
    subscriptions: int = 0
    favorited: int = 0
    lifetime_subscriptions: int = 0
    creator_name: str = ""
    creator_id: str = ""
    tags: list[str] = field(default_factory=list)
    time_created: int = 0
    time_updated: int = 0
    is_subscribed: bool = False
    age_rating: str = "everyone"  # everyone, partial_nudity, mature
    content_descriptors: list[str] = field(default_factory=list)

    @property
    def size_mb(self) -> float:
        return self.file_size / (1024 * 1024) if self.file_size else 0.0


@dataclass
class SearchResult:
    """Resultado paginado de una búsqueda."""

    items: list[WorkshopItem]
    total: int
    page: int
    pages: int
    next_cursor: str = ""


# ── Helpers ─────────────────────────────────────────────────────────────────


def _ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _get_api_key() -> str | None:
    """Lee la Steam Web API Key desde el archivo de configuración."""
    try:
        path = API_KEY_PATH.expanduser()
        if path.exists():
            return path.read_text().strip()
    except OSError:
        pass
    return None


def _get_session_cookie() -> str | None:
    """Lee la cookie de sesión de Steam desde el archivo de configuración."""
    try:
        path = SESSION_PATH.expanduser()
        if path.exists():
            return path.read_text().strip()
    except OSError:
        pass
    return None


def save_session_cookie(cookie: str) -> None:
    """Guarda la cookie de sesión de Steam para usar en subscribe/unsubscribe."""
    _ensure_dirs()
    path = SESSION_PATH.expanduser()
    path.write_text(cookie.strip())
    path.chmod(0o600)


def save_api_key(key: str) -> None:
    """Guarda la Steam Web API Key."""
    _ensure_dirs()
    path = API_KEY_PATH.expanduser()
    path.write_text(key.strip())
    path.chmod(0o600)


def has_api_key() -> bool:
    return bool(_get_api_key())


def has_session() -> bool:
    return bool(_get_session_cookie())


def _rate_limit() -> None:
    """Espera si es necesario para respetar el rate limiting."""
    global _last_request_time
    with _lock:
        elapsed = time.monotonic() - _last_request_time
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
        _last_request_time = time.monotonic()


def _cache_key(prefix: str, **kwargs) -> str:
    """Genera una clave de caché determinista."""
    raw = prefix + ":" + json.dumps(kwargs, sort_keys=True, default=str)
    return raw


def _cache_get(key: str) -> object | None:
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        ts, data = entry
        if time.monotonic() - ts > _CACHE_TTL:
            del _cache[key]
            return None
        return data


def _cache_set(key: str, data: object) -> None:
    with _lock:
        # Limpiar entradas expiradas
        now = time.monotonic()
        expired = [k for k, (ts, _) in _cache.items() if now - ts > _CACHE_TTL]
        for k in expired:
            del _cache[k]
        _cache[key] = (now, data)


def _http_get(url: str, headers: dict | None = None) -> dict | None:
    """GET request con rate limiting y User-Agent. Retorna JSON parseado o None."""
    _rate_limit()
    req_headers = {"User-Agent": _USER_AGENT}
    if headers:
        req_headers.update(headers)
    try:
        req = urllib.request.Request(url, headers=req_headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)
    except urllib.error.HTTPError as e:
        _log_error(f"HTTP {e.code} en GET {url[:80]}")
    except urllib.error.URLError as e:
        _log_error(f"URL error en GET {url[:80]}: {e.reason}")
    except json.JSONDecodeError:
        _log_error(f"JSON inválido en respuesta de {url[:80]}")
    except Exception as e:
        _log_error(f"Error en GET {url[:80]}: {e}")
    return None


def _http_post(url: str, data: dict, headers: dict | None = None) -> bool:
    """POST request con rate limiting. Retorna True si 2xx."""
    _rate_limit()
    req_headers = {
        "User-Agent": _USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if headers:
        req_headers.update(headers)
    try:
        encoded = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(url, data=encoded, headers=req_headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        _log_error(f"HTTP {e.code} en POST {url[:80]}")
    except urllib.error.URLError as e:
        _log_error(f"URL error en POST {url[:80]}: {e.reason}")
    except Exception as e:
        _log_error(f"Error en POST {url[:80]}: {e}")
    return False


def _log_error(msg: str) -> None:
    """Log silencioso, sin spam en consola."""
    pass  # TODO: integrar con logging del daemon


# Content descriptor IDs de Steam (EUserUGCContentDescriptorID)
_DESCRIPTOR_LABELS: dict[int, str] = {
    1: "Nudity or Sexual Content",
    2: "Frequent Violence or Gore",
    3: "Adult Only Sexual Content",
    4: "Gratuitous Sexual Content",
    5: "General Mature Content",
}


def _classify_age_rating(descriptor_ids: list[int], maybe_sex: bool) -> str:
    """Clasifica un wallpaper segun sus content descriptors de Steam.

    Logica igual a Wallpaper Engine:
      - Mature (18+): descriptor 3 presente (Adult Only)
      - Partial Nudity: descriptor 1 presente sin 3
      - Everyone: sin descriptores relevantes
    """
    ids = set(descriptor_ids) if descriptor_ids else set()

    if 3 in ids:
        return "mature"
    elif 1 in ids:
        return "partial_nudity"
    elif maybe_sex:
        return "partial_nudity"
    else:
        return "everyone"


def _get_content_descriptor_labels(descriptor_ids: list[int]) -> list[str]:
    """Convierte IDs de content descriptors a etiquetas legibles."""
    return [_DESCRIPTOR_LABELS.get(d, f"Unknown({d})") for d in (descriptor_ids or [])]


def _parse_workshop_item(raw: dict) -> WorkshopItem:
    """Convierte un dict de respuesta de la API en un WorkshopItem."""
    tags = []
    for t in raw.get("tags", []):
        if isinstance(t, dict):
            # display_name es más legible que tag (ej: "2560 x 1440" vs "2560x1440")
            tag_name = t.get("display_name", "") or t.get("tag", "")
            if tag_name:
                tags.append(tag_name)
        elif isinstance(t, str):
            tags.append(t)

    return WorkshopItem(
        publishedfileid=str(raw.get("publishedfileid", "")),
        title=raw.get("title", ""),
        description=raw.get("short_description", ""),
        preview_url=raw.get("preview_url", ""),
        file_url=raw.get("url", ""),
        file_size=int(raw.get("file_size", 0)),
        file_type=int(raw.get("file_type", 0)),
        subscriptions=int(raw.get("subscriptions", 0)),
        favorited=int(raw.get("favorited", 0)),
        lifetime_subscriptions=int(raw.get("lifetime_subscriptions", 0)),
        creator_name="",
        creator_id=str(raw.get("creator", "")),
        tags=tags,
        time_created=int(raw.get("time_created", 0)),
        time_updated=int(raw.get("time_updated", 0)),
        age_rating=_classify_age_rating(
            raw.get("content_descriptorids", []),
            raw.get("maybe_inappropriate_sex", False),
        ),
        content_descriptors=_get_content_descriptor_labels(
            raw.get("content_descriptorids", [])
        ),
    )


# ── API pública ─────────────────────────────────────────────────────────────


def search_workshop(
    query: str = "",
    tags: list[str] | None = None,
    filetype: int = FILE_TYPE_VIDEO,
    sort: str = "trending",
    page: int = 1,
    per_page: int = 100,
    cursor: str = "*",
) -> SearchResult | None:
    """Busca wallpapers en el Workshop de Wallpaper Engine.

    Args:
        query: Texto de búsqueda (vacío = sin filtro de texto).
        tags: Lista de tags requeridos.
        filetype: EPublishedFileInfoMatchingFileType (3 = Videos, 0 = Todos).
        sort: trending, popular, recent, updated, text_search.
        page: Página (solo cosmético, la API usa cursor).
        per_page: Resultados por página (máx 100, impuesto por Steam API).
        cursor: Cursor de paginación (* = primera página).

    Returns:
        SearchResult con items, total y paginación, o None si hay error.
    """
    api_key = _get_api_key()
    if not api_key:
        _log_error("search_workshop: no hay API key configurada")
        return None

    query_type = {
        "trending": QUERY_RANKED_BY_TREND,
        "popular": QUERY_RANKED_BY_SUBSCRIPTIONS,
        "recent": QUERY_RANKED_BY_DATE,
        "updated": QUERY_RANKED_BY_LAST_UPDATED,
        "votes": QUERY_RANKED_BY_VOTES_UP,
        "text_search": QUERY_RANKED_BY_TEXT_SEARCH,
    }.get(sort, QUERY_RANKED_BY_TREND)

    # Si hay query, usar text search
    if query.strip():
        query_type = QUERY_RANKED_BY_TEXT_SEARCH

    # Solo incluir parámetros con valor (evitar strings vacíos que la API rechaza)
    params: dict[str, str | int] = {
        "key": api_key,
        "query_type": query_type,
        "page": page,
        "cursor": cursor,
        "numperpage": min(per_page, 100),
        "creator_appid": WORKSHOP_APPID,
        "appid": WORKSHOP_APPID,
        "return_vote_data": "true",
        "return_tags": "true",
        "return_previews": "true",
        "return_short_description": "true",
    }

    if filetype != FILE_TYPE_ALL:
        params["filetype"] = filetype

    if tags:
        params["requiredtags"] = ",".join(tags)
        params["match_all_tags"] = "true"

    if query.strip():
        params["search_text"] = query.strip()

    cache_k = _cache_key("search", **{k: str(v) for k, v in params.items()})
    cached = _cache_get(cache_k)
    if cached is not None:
        return cached

    url = f"{STEAM_API_BASE}/IPublishedFileService/QueryFiles/v1/?" + urllib.parse.urlencode(params)
    data = _http_get(url)
    if data is None:
        return None

    try:
        resp = data.get("response", {})
        total = int(resp.get("total", 0))
        raw_items = resp.get("publishedfiledetails", [])
        items = [_parse_workshop_item(i) for i in raw_items]
        next_cursor = resp.get("next_cursor", "")

        result = SearchResult(
            items=items,
            total=total,
            page=page,
            pages=max(1, (total + per_page - 1) // per_page) if total else 1,
            next_cursor=next_cursor,
        )
        _cache_set(cache_k, result)
        return result
    except Exception as e:
        _log_error(f"Error parseando respuesta de QueryFiles: {e}")
        return None


def get_wallpaper_details(publishedfileid: str) -> WorkshopItem | None:
    """Obtiene los detalles de un wallpaper específico (público, sin API key).

    Endpoint: ISteamRemoteStorage/GetPublishedFileDetails/v1/ (POST).
    """
    cache_k = _cache_key("details", publishedfileid=publishedfileid)
    cached = _cache_get(cache_k)
    if cached is not None:
        return cached

    url = f"{STEAM_API_BASE}/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
    body = {
        "itemcount": 1,
        "publishedfileids[0]": publishedfileid,
    }

    _rate_limit()
    try:
        req = urllib.request.Request(
            url,
            data=urllib.parse.urlencode(body).encode("utf-8"),
            headers={
                "User-Agent": _USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        _log_error(f"Error en GetPublishedFileDetails: {e}")
        return None

    try:
        files = data.get("response", {}).get("publishedfiledetails", [])
        if not files:
            return None
        item = _parse_workshop_item(files[0])
        _cache_set(cache_k, item)
        return item
    except Exception as e:
        _log_error(f"Error parseando GetPublishedFileDetails: {e}")
        return None


def get_trending(page: int = 1, per_page: int = 100) -> SearchResult | None:
    return search_workshop(sort="trending", page=page, per_page=per_page)


def get_popular(page: int = 1, per_page: int = 100) -> SearchResult | None:
    return search_workshop(sort="popular", page=page, per_page=per_page)


def get_recent(page: int = 1, per_page: int = 100) -> SearchResult | None:
    return search_workshop(sort="recent", page=page, per_page=per_page)


def get_updated(page: int = 1, per_page: int = 100) -> SearchResult | None:
    return search_workshop(sort="updated", page=page, per_page=per_page)


def search_by_text(query: str, page: int = 1, per_page: int = 100) -> SearchResult | None:
    return search_workshop(query=query, sort="text_search", page=page, per_page=per_page)


def search_multi(
    query: str = "",
    tags: list[str] | None = None,
    sort: str = "trending",
    target_count: int = 300,
) -> list[WorkshopItem]:
    """Busca wallpapers concatenando multiples paginas de la API.

    La Steam API limita a 100 items por request. Esta funcion
    encadena hasta 4 paginas para alcanzar ~300 items.

    Args:
        query: Texto de busqueda.
        tags: Tags requeridos.
        sort: Ordenamiento.
        target_count: Cantidad objetivo de items (default 300).

    Returns:
        Lista plana de WorkshopItem (sin paginacion).
    """
    api_key = _get_api_key()
    if not api_key:
        _log_error("search_multi: no hay API key configurada")
        return []

    all_items: list[WorkshopItem] = []
    seen: set[str] = set()
    cursor = "*"
    pages_to_fetch = max(1, (target_count + 99) // 100)  # ceil(target/100)

    for page_num in range(1, pages_to_fetch + 1):
        query_type = {
            "trending": QUERY_RANKED_BY_TREND,
            "popular": QUERY_RANKED_BY_SUBSCRIPTIONS,
            "recent": QUERY_RANKED_BY_DATE,
            "updated": QUERY_RANKED_BY_LAST_UPDATED,
            "text_search": QUERY_RANKED_BY_TEXT_SEARCH,
        }.get(sort, QUERY_RANKED_BY_TREND)

        if query.strip():
            query_type = QUERY_RANKED_BY_TEXT_SEARCH

        params: dict[str, str | int] = {
            "key": api_key,
            "query_type": query_type,
            "page": page_num,
            "cursor": cursor,
            "numperpage": 100,
            "creator_appid": WORKSHOP_APPID,
            "appid": WORKSHOP_APPID,
            "return_vote_data": "true",
            "return_tags": "true",
            "return_previews": "true",
            "return_short_description": "true",
        }

        if tags:
            params["requiredtags"] = ",".join(tags)
            params["match_all_tags"] = "true"

        if query.strip():
            params["search_text"] = query.strip()

        url = f"{STEAM_API_BASE}/IPublishedFileService/QueryFiles/v1/?" + urllib.parse.urlencode(params)
        data = _http_get(url)
        if data is None:
            break

        try:
            resp = data.get("response", {})
            raw_items = resp.get("publishedfiledetails", [])
            for raw in raw_items:
                item = _parse_workshop_item(raw)
                if item.publishedfileid not in seen:
                    seen.add(item.publishedfileid)
                    all_items.append(item)

            next_cursor = resp.get("next_cursor", "")
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor

            if len(raw_items) < 100:
                break  # ultima pagina
        except Exception as e:
            _log_error(f"Error en search_multi pagina {page_num}: {e}")
            break

    return all_items


def download_preview(url: str, publishedfileid: str) -> str | None:
    """Descarga una imagen preview y la guarda en caché local.

    Returns:
        Path local a la imagen descargada, o None si falla.
    """
    _ensure_dirs()
    ext = ".jpg"
    if url:
        parsed = urllib.parse.urlparse(url)
        base = os.path.basename(parsed.path)
        if "." in base:
            ext = os.path.splitext(base)[1] or ".jpg"

    dest = CACHE_DIR / f"{publishedfileid}_preview{ext}"
    if dest.exists():
        return str(dest)

    if not url:
        return None

    _rate_limit()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            dest.write_bytes(resp.read())
        return str(dest)
    except Exception as e:
        _log_error(f"Error descargando preview {publishedfileid}: {e}")
        return None


def subscribe(publishedfileid: str) -> bool:
    """Se suscribe a un wallpaper del Workshop.

    Requiere cookie de sesión de Steam (steamcommunity.com).
    La cookie se lee de ~/.config/ripowall/steam_session.
    """
    session_cookie = _get_session_cookie()
    if not session_cookie:
        _log_error("subscribe: no hay cookie de sesión")
        return False

    # Extraer sessionid de la cookie si está presente
    session_id = ""
    for part in session_cookie.split(";"):
        part = part.strip()
        if part.startswith("sessionid="):
            session_id = part.split("=", 1)[1]
            break

    url = f"{STEAM_COMMUNITY}/sharedfiles/subscribe/"
    headers = {
        "Cookie": session_cookie,
        "Origin": STEAM_COMMUNITY,
        "Referer": f"{STEAM_COMMUNITY}/sharedfiles/filedetails/?id={publishedfileid}",
    }
    data = {
        "id": publishedfileid,
        "appid": WORKSHOP_APPID,
    }
    if session_id:
        data["sessionid"] = session_id

    return _http_post(url, data, headers)


def unsubscribe(publishedfileid: str) -> bool:
    """Se desuscribe de un wallpaper del Workshop.

    Requiere cookie de sesión de Steam.
    """
    session_cookie = _get_session_cookie()
    if not session_cookie:
        _log_error("unsubscribe: no hay cookie de sesión")
        return False

    session_id = ""
    for part in session_cookie.split(";"):
        part = part.strip()
        if part.startswith("sessionid="):
            session_id = part.split("=", 1)[1]
            break

    url = f"{STEAM_COMMUNITY}/sharedfiles/unsubscribe/"
    headers = {
        "Cookie": session_cookie,
        "Origin": STEAM_COMMUNITY,
        "Referer": f"{STEAM_COMMUNITY}/sharedfiles/filedetails/?id={publishedfileid}",
    }
    data = {
        "id": publishedfileid,
        "appid": WORKSHOP_APPID,
    }
    if session_id:
        data["sessionid"] = session_id

    return _http_post(url, data, headers)


def fetch_trending_tags(limit: int = 20) -> list[str]:
    """Obtiene los tags más comunes de los wallpapers en tendencia."""
    result = get_trending(page=1, per_page=50)
    if result is None:
        return _default_tags()

    tag_counts: dict[str, int] = {}
    for item in result.items:
        for tag in item.tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
    return [t for t, _ in sorted_tags[:limit]]


def _default_tags() -> list[str]:
    """Tags populares de Wallpaper Engine como fallback."""
    return [
        "Anime", "Nature", "Abstract", "Sci-Fi", "Fantasy",
        "Cyberpunk", "Space", "City", "Music Visualizer",
        "Minimalist", "Game", "Landscape", "Water", "Fire",
        "Particles", "3D", "4K", "Ultrawide", "Dual Monitor",
    ]


# ── Test ────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    print("=== workshop_api.py — test ===\n")
    print(f"API key:  {'✓' if has_api_key() else '✗ (sin key, solo GetPublishedFileDetails)'}")
    print(f"Session:  {'✓' if has_session() else '✗ (sin cookie, no subscribe)'}")
    print(f"Cache:    {CACHE_DIR}")
    print()

    if has_api_key():
        print("→ Buscando trending...")
        result = get_trending(per_page=5)
        if result:
            print(f"  {result.total} resultados, mostrando {len(result.items)}:")
            for item in result.items[:5]:
                print(f"  - [{item.publishedfileid}] {item.title[:60]}")
                print(f"    Tags: {', '.join(item.tags[:5])}")
                print(f"    Subs: {item.subscriptions:,}  Favs: {item.favorited:,}")
            print(f"  Página {result.page} de {result.pages}")
        else:
            print("  (falló — ¿API key inválida?)")
    else:
        print("→ Probar GetPublishedFileDetails con un ID conocido...")
        # ID de ejemplo del Workshop de WE
        test_id = "3428224188"
        details = get_wallpaper_details(test_id)
        if details:
            print(f"  {details.title}")
            print(f"  Tags: {', '.join(details.tags)}")
            print(f"  Size: {details.size_mb:.1f} MB")
        else:
            print("  (falló o ID no encontrado)")
