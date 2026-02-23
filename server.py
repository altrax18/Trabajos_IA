import json
import os
from pathlib import Path
from typing import List
import httpx
from dotenv import load_dotenv, find_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(find_dotenv())

# Configuración del servidor MCP
# Nombre del servidor y dependencias
mcp = FastMCP("Setlist Architect Music Server")

def _load_songs() -> List[dict]:
    # Carga el catalogo local desde songs.json para separar datos de la logica.
    songs_path = Path(__file__).with_name("songs.json")
    try:
        with songs_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []

# Base de datos local de canciones
DB_CANCIONES = _load_songs()

# Requisito 1: Tool para buscar canciones por género
@mcp.tool()
def buscar_canciones(genero: str) -> List[dict]:
    """
    Busca canciones en la base de datos por género.
    Args:
        genero: El género musical a buscar (ej: Rock, Pop, Reggaeton).
    Returns:
        Una lista de diccionarios con las canciones encontradas.
    """
    filtradas = [c for c in DB_CANCIONES if c["genero"].lower() == genero.lower()]
    return filtradas

def _spotify_token() -> str:
    # Obtiene un token de acceso de Spotify usando client credentials.
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        return ""

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                "https://accounts.spotify.com/api/token",
                data={"grant_type": "client_credentials"},
                auth=(client_id, client_secret),
            )
            response.raise_for_status()
        data = response.json()
        return data.get("access_token", "")
    except Exception:
        return ""

def _spotify_track_and_audio(title: str, artist: str) -> dict:
    # Busca un track en Spotify por titulo/artista y devuelve sus audio features.
    token = _spotify_token()
    if not token:
        return {}

    headers = {"Authorization": f"Bearer {token}"}
    query = f"track:{title} artist:{artist}"
    try:
        with httpx.Client(timeout=10.0) as client:
            search = client.get(
                "https://api.spotify.com/v1/search",
                headers=headers,
                params={"q": query, "type": "track", "limit": 1},
            )
            search.raise_for_status()
        search_data = search.json()
        items = search_data.get("tracks", {}).get("items", [])
        if not items:
            return {}

        track_id = items[0].get("id")
        if not track_id:
            return {}

        with httpx.Client(timeout=10.0) as client:
            audio = client.get(
                f"https://api.spotify.com/v1/audio-features/{track_id}",
                headers=headers,
            )
            audio.raise_for_status()
        return audio.json()
    except Exception:
        return {}

def _key_name(key: int, mode: int) -> str:
    # Convierte key/mode numericos de Spotify a notacion musical legible.
    keys = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    key_index = int(key)
    if key_index < 0 or key_index >= len(keys):
        return "Unknown"
    nota = keys[key_index]
    sufijo = "m" if int(mode) == 0 else ""
    return f"{nota}{sufijo}"

def _estimar_bpm_con_llm(titulo: str, artista: str) -> dict:
    """
    Fallback: usa Cohere para estimar BPM y tonalidad cuando Spotify no está disponible.
    """
    api_key = os.getenv("COHERE_API_KEY")
    if not api_key:
        return {}

    prompt_msg = (
        f"Para la canción '{titulo}' de '{artista}', estima el BPM (tempo) y la tonalidad musical. "
        f"Responde SOLO con un JSON exacto con este formato: "
        f'{{"bpm": 120, "key": "C"}}'
        f" donde bpm es un número entero y key es la nota musical (ej: C, Am, F#, Dm)."
    )
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                "https://api.cohere.com/v1/chat",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "message": prompt_msg,
                    "model": "command-r-08-2024",
                    "temperature": 0.2,
                },
            )
            response.raise_for_status()
        data = response.json()
        text = data.get("text", "")
        # Extraer JSON del texto
        import re
        match = re.search(r'\{[^}]+\}', text)
        if match:
            parsed = json.loads(match.group())
            bpm = int(parsed.get("bpm", 0))
            key = str(parsed.get("key", "Unknown"))
            if bpm > 0:
                return {"bpm": bpm, "key": key}
    except Exception:
        pass
    return {}


# Requisito 2 (real): Tool de analisis BPM y tonalidad usando Spotify
@mcp.tool()
def analizar_bpm(cancion_id: str, titulo: str = "", artista: str = "") -> dict:
    """
    Analiza BPM y tonalidad usando Spotify Audio Features.
    Si Spotify no está disponible, usa Cohere LLM como fallback.
    Args:
        cancion_id: ID de la canción (puede ser de la BD local o de iTunes).
        titulo: Título de la canción (usado si no se encuentra en la BD local).
        artista: Artista de la canción (usado si no se encuentra en la BD local).
    """
    # Buscar en BD local; si no está, usar titulo/artista proporcionados
    cancion = next((c for c in DB_CANCIONES if c["id"] == str(cancion_id)), None)
    search_titulo = cancion["titulo"] if cancion else titulo
    search_artista = cancion["artista"] if cancion else artista

    if not search_titulo:
        return {"bpm": 0, "key": "Unknown"}

    # Intento 1: Spotify Audio Features
    audio = _spotify_track_and_audio(search_titulo, search_artista)
    if audio and audio.get("tempo"):
        bpm = round(audio.get("tempo", 0))
        key = _key_name(int(audio.get("key", -1)), int(audio.get("mode", -1)))
        return {"bpm": bpm, "key": key}

    # Intento 2: Estimación con Cohere LLM (fallback)
    estimacion = _estimar_bpm_con_llm(search_titulo, search_artista)
    if estimacion:
        return estimacion

    return {"bpm": 0, "key": "Unknown"}

@mcp.tool()
def analizar_bpm_batch(canciones: List[dict]) -> List[dict]:
    """
    Analiza BPM y tonalidad de TODAS las canciones en una sola llamada usando Cohere.
    Mucho más rápido que llamar analizar_bpm una por una.
    Args:
        canciones: Lista de dicts con al menos 'titulo' y 'artista'.
    Returns:
        Lista de dicts con 'titulo', 'bpm' y 'key' para cada canción.
    """
    import re
    api_key = os.getenv("COHERE_API_KEY")
    if not api_key:
        return [{"titulo": c.get("titulo", ""), "bpm": 0, "key": "Unknown"} for c in canciones]

    lista_canciones = "\n".join(
        [f"- {c.get('titulo', '?')} de {c.get('artista', '?')}" for c in canciones]
    )
    prompt_msg = (
        f"Para cada cancion de la siguiente lista, estima el BPM (tempo) y la tonalidad musical.\n"
        f"Lista:\n{lista_canciones}\n\n"
        f"Responde SOLO con un JSON array, un objeto por cancion, en el mismo orden. "
        f'Formato: [{{"titulo": "nombre", "bpm": 120, "key": "C"}}]. '
        f"BPM debe ser un numero entero realista. Key debe ser la nota (ej: C, Am, F#m, Bb)."
    )
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                "https://api.cohere.com/v1/chat",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "message": prompt_msg,
                    "model": "command-r-08-2024",
                    "temperature": 0.2,
                },
            )
            response.raise_for_status()
        data = response.json()
        text = data.get("text", "")
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            if isinstance(parsed, list):
                return parsed
    except Exception:
        pass
    return [{"titulo": c.get("titulo", ""), "bpm": 0, "key": "Unknown"} for c in canciones]

# Requisito 2 (real): Tool que consume API externa gratuita (iTunes)
@mcp.tool()
def buscar_canciones_api_externa(termino: str, limite: int = 5) -> List[dict]:
    """
    Busca canciones reales usando la API pública de iTunes (sin API key).
    Args:
        termino: Término de búsqueda (artista, canción o género).
        limite: Número máximo de resultados.
    Returns:
        Lista de canciones con campos básicos.
    """
    url = "https://itunes.apple.com/search"
    params = {"term": termino, "media": "music", "limit": int(limite)}
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
        data = response.json()
        results = []
        for item in data.get("results", []):
            results.append(
                {
                    "track_id": str(item.get("trackId", "")),
                    "titulo": item.get("trackName", ""),
                    "artista": item.get("artistName", ""),
                    "album": item.get("collectionName", ""),
                    "preview_url": item.get("previewUrl", ""),
                }
            )
        return results
    except Exception:
        return []

# Requisito 2 (real): Tool con API externa Serper (Google Search)
@mcp.tool()
def buscar_canciones_serper(termino: str, limite: int = 5) -> List[dict]:
    """
    Busca resultados en la Web usando Serper (Google Search API).
    Requiere SERPER_API_KEY en .env
    Args:
        termino: Consulta de busqueda (artista, cancion, genero, etc.).
        limite: Numero maximo de resultados.
    Returns:
        Lista de resultados con titulo, snippet y enlace.
    """
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        return []

    url = "https://google.serper.dev/search"
    payload = {"q": termino, "num": int(limite)}
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        data = response.json()
        organic = data.get("organic", [])
        results = []
        for item in organic:
            results.append(
                {
                    "titulo": item.get("title", ""),
                    "snippet": item.get("snippet", ""),
                    "link": item.get("link", ""),
                }
            )
        return results
    except Exception:
        return []

def _curar_con_llm(canciones: List[dict], vibe: str) -> List[dict]:
    """
    Usa Cohere para ordenar una lista de canciones segun el vibe.
    Requiere COHERE_API_KEY en .env
    """
    # Si no hay key, devuelve la lista sin cambios.
    api_key = os.getenv("COHERE_API_KEY")
    if not api_key:
        return canciones

    prompt = {
        "message": "Ordena la lista de canciones segun el vibe indicado y devuelve solo los IDs en orden.",
        "preamble": "Eres un curador musical experto. Responde solo con una lista JSON de IDs en orden.",
        "model": "command-r-08-2024",
        "temperature": 0.3,
        "chat_history": [],
        "documents": [],
        "response_format": {"type": "json_object"},
        "input": {
            "vibe": vibe,
            "canciones": [{"id": c.get("id"), "titulo": c.get("titulo"), "artista": c.get("artista")} for c in canciones],
        },
    }

    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                "https://api.cohere.com/v1/chat",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=prompt,
            )
            response.raise_for_status()
        data = response.json()
        text = data.get("text") or data.get("message") or ""
        ids = []
        try:
            parsed = json.loads(text)
            ids = parsed.get("ids", []) if isinstance(parsed, dict) else parsed
        except Exception:
            ids = []

        if not ids:
            return canciones

        id_map = {str(c.get("id")): c for c in canciones}
        ordered = [id_map[i] for i in ids if str(i) in id_map]
        if len(ordered) != len(canciones):
            remaining = [c for c in canciones if str(c.get("id")) not in {str(i) for i in ids}]
            ordered.extend(remaining)
        return ordered
    except Exception:
        return canciones

# Requisito 3 (real): Tool con LLM (Cohere) para ordenar el setlist
@mcp.tool()
def curador_musical(canciones: List[dict], vibe: str) -> List[dict]:
    """
    Ordena canciones usando un LLM (Cohere).
    Requiere COHERE_API_KEY en .env
    """
    return _curar_con_llm(canciones, vibe)

if __name__ == "__main__":
    import sys
    # Soporte para ejecución stdio (local) o streamable-http (remoto).
    if "http" in sys.argv:
        # Levanta servidor MCP sobre streamable-http.
        print("Iniciando servidor MCP streamable-http en puerto 8000...")
        mcp.run(transport="streamable-http")
    else:
        # Levanta servidor MCP por stdio para cliente local (agente/desktop).
        print("Iniciando servidor MCP stdio...", file=sys.stderr)
        mcp.run(transport="stdio")
