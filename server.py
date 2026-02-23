import json
import os
import re
from typing import List
import httpx
from dotenv import load_dotenv, find_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(find_dotenv())

# Configuración del servidor MCP
mcp = FastMCP("Setlist Architect Music Server")


# Tool 1: Buscar canciones en iTunes (API externa gratuita)
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


# Tool 2: Analizar BPM y tonalidad en batch usando Cohere LLM
@mcp.tool()
def analizar_bpm_batch(canciones: List[dict]) -> List[dict]:
    """
    Analiza BPM y tonalidad de TODAS las canciones en una sola llamada usando Cohere.
    Args:
        canciones: Lista de dicts con al menos 'titulo' y 'artista'.
    Returns:
        Lista de dicts con 'titulo', 'bpm' y 'key' para cada canción.
    """
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


# Tool 3: Curador musical con LLM (Cohere) para ordenar el setlist
def _curar_con_llm(canciones: List[dict], vibe: str) -> List[dict]:
    """
    Usa Cohere para ordenar una lista de canciones segun el vibe.
    Requiere COHERE_API_KEY en .env
    """
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


@mcp.tool()
def curador_musical(canciones: List[dict], vibe: str) -> List[dict]:
    """
    Ordena canciones usando un LLM (Cohere).
    Requiere COHERE_API_KEY en .env
    """
    return _curar_con_llm(canciones, vibe)

if __name__ == "__main__":
    import sys
    if "http" in sys.argv:
        print("Iniciando servidor MCP streamable-http en puerto 8000...")
        mcp.run(transport="streamable-http")
    else:
        print("Iniciando servidor MCP stdio...", file=sys.stderr)
        mcp.run(transport="stdio")
