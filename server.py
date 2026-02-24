# -*- coding: utf-8 -*-
import json
import os
import re
from typing import List
import httpx
from dotenv import load_dotenv, find_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(find_dotenv())

mcp = FastMCP("Setlist Architect Music Server")

# ==============================
# TOOL 1: Buscar canciones iTunes
# ==============================
@mcp.tool()
def buscar_canciones_api_externa(termino: str, limite: int = 5) -> List[dict]:
    url = "https://itunes.apple.com/search"
    params = {"term": termino, "media": "music", "limit": int(limite)}

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()

        data = response.json()
        unique = {}

        for item in data.get("results", []):
            titulo = item.get("trackName", "")
            artista = item.get("artistName", "")
            clave = (titulo.lower(), artista.lower())

            if clave not in unique:
                nombre_archivo = f"{titulo} - {artista}.m4a"
                nombre_archivo = re.sub(r'[\\/*?:"<>|]', "", nombre_archivo)

                unique[clave] = {
                    "track_id": str(item.get("trackId", "")),
                    "titulo": titulo,
                    "artista": artista,
                    "album": item.get("collectionName", ""),
                    "preview_url": item.get("previewUrl", ""),
                    "nombre_archivo": nombre_archivo,
                }

        return list(unique.values())

    except Exception as e:
        print("ERROR ITUNES:", e)
        return []


# ==============================
# TOOL 2: Analizar BPM (Cohere v2)
# ==============================
@mcp.tool()

@mcp.tool()
def analizar_bpm_batch(canciones: List[dict]) -> List[dict]:
    api_key = os.getenv("COHERE_API_KEY")

    if not api_key:
        return [{"bpm": 0, "key": "Unknown"} for _ in canciones]

    lista_canciones = "\n".join(
        [f"- {c.get('titulo')} de {c.get('artista')}" for c in canciones]
    )

    prompt_msg = f"""
Devuelve SOLO un JSON array como este ejemplo:

[
  {{"bpm":120,"key":"Am"}}
]

Reglas:
- No expliques nada.
- No añadas texto fuera del JSON.
- Devuelve exactamente el mismo número de canciones.
- Mantén el mismo orden.
- BPM entre 80 y 180.

Canciones:
{lista_canciones}
"""

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                "https://api.cohere.com/v2/chat",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "command-r7b-12-2024",
                    "messages": [
                        {"role": "user", "content": prompt_msg}
                    ],
                    "temperature": 0.4,
                },
            )
            response.raise_for_status()

        data = response.json()

        content_blocks = data.get("message", {}).get("content", [])
        text = ""

        for block in content_blocks:
            if block.get("type") == "text":
                text += block.get("text", "")

        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            parsed = json.loads(match.group())

            # Si el modelo devuelve menos elementos, rellenamos
            if len(parsed) < len(canciones):
                for _ in range(len(canciones) - len(parsed)):
                    parsed.append({"bpm": 0, "key": "Unknown"})

            return parsed

    except Exception as e:
        print("ERROR BPM:", e)

    return [{"bpm": 0, "key": "Unknown"} for _ in canciones]
# ==============================
# TOOL 3: Curador musical (Cohere v2)
# ==============================
def _curar_con_llm(canciones: List[dict], vibe: str) -> List[dict]:
    api_key = os.getenv("COHERE_API_KEY")

    if not api_key:
        return canciones

    prompt_msg = (
        f"Ordena la siguiente lista de canciones según el vibe '{vibe}'. "
        f"Devuelve SOLO un JSON array con los track_id en orden.\n\n"
        f"{json.dumps(canciones, ensure_ascii=False)}"
    )

    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                "https://api.cohere.com/v2/chat",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "command-r7b-12-2024",
                    "messages": [
                        {"role": "user", "content": prompt_msg}
                    ],
                    "temperature": 0.3,
                },
            )
            response.raise_for_status()

        data = response.json()

        content_blocks = data.get("message", {}).get("content", [])
        text = ""

        for block in content_blocks:
            if block.get("type") == "text":
                text += block.get("text", "")

        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            ids = json.loads(match.group())
            id_map = {str(c.get("track_id")): c for c in canciones}
            ordered = [id_map[i] for i in ids if i in id_map]

            if len(ordered) != len(canciones):
                remaining = [c for c in canciones if str(c.get("track_id")) not in ids]
                ordered.extend(remaining)

            return ordered

    except Exception as e:
        print("ERROR CURADOR:", e)

    return canciones


@mcp.tool()
def curador_musical(canciones: List[dict], vibe: str) -> List[dict]:
    return _curar_con_llm(canciones, vibe)


# ==============================
# TRANSPORTES
# ==============================
if __name__ == "__main__":
    import sys

    if "http" in sys.argv:
        print("Iniciando servidor MCP streamable-http en puerto 8000...")
        mcp.run(transport="streamable-http")
    else:
        print("Iniciando servidor MCP stdio...", file=sys.stderr)
        mcp.run(transport="stdio")