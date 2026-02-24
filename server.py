# -*- coding: utf-8 -*-
import json
import os
import re
from typing import List
import httpx
from dotenv import load_dotenv, find_dotenv
from mcp.server.fastmcp import FastMCP
import whisper

load_dotenv(find_dotenv())

mcp = FastMCP("Setlist Architect Music Server")

# Cargar el modelo de Whisper (puede tomar unos segundos la primera vez)
try:
    print("Cargando modelo Whisper 'base'...")
    whisper_model = whisper.load_model("base")
    print("Modelo Whisper cargado correctamente.")
except Exception as e:
    print(f"Error cargando Whisper: {e}")
    whisper_model = None


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
                    "nombre_archivo": nombre_archivo.replace('.m4a', '.mp3'),
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
# TOOL 4: Descargar y Transcribir (Whisper local)
# ==============================
@mcp.tool()
def descargar_y_transcribir(preview_url: str, artista: str, titulo: str, output_dir: str) -> dict:
    if not preview_url:
        return {"letra": "Sin audio disponible", "ruta_local": ""}
    
    os.makedirs(output_dir, exist_ok=True)
    
    # Sanitizar nombre de archivo
    nombre_base = f"{artista} - {titulo}"
    nombre_base = re.sub(r'[\\/*?:"<>|]', "", nombre_base)
    
    ruta_mp3 = os.path.join(output_dir, nombre_base + ".mp3")
    ruta_srt = os.path.join(output_dir, nombre_base + ".srt")
    
    try:
        # 1. Descargar audio (viene como m4a pero lo guardamos con extensión mp3 para obligar a VLC a tratarlo como audio estándar)
        with httpx.Client(timeout=15.0) as client:
            response = client.get(preview_url)
            response.raise_for_status()
            with open(ruta_mp3, "wb") as f:
                f.write(response.content)
                
        # 2. Transcribir con Whisper si está disponible
        if whisper_model is None:
            return {"letra": "El modelo Whisper no está cargado", "ruta_local": ruta_mp3}
            
        result = whisper_model.transcribe(ruta_mp3)
        
        # 3. Generar archivo .srt para VLC y recopilar letra completa
        letra_completa = ""
        with open(ruta_srt, "w", encoding="utf-8-sig") as f_srt:
            for index, segment in enumerate(result.get("segments", [])):
                start = segment.get("start", 0.0) # Segundos
                end = segment.get("end", start + 3.0) # Segundos
                text = segment.get("text", "").strip()
                
                # Formatear a HH:MM:SS,mmm
                def format_time(seconds):
                    h = int(seconds // 3600)
                    m = int((seconds % 3600) // 60)
                    s = int(seconds % 60)
                    ms = int((seconds - int(seconds)) * 1000)
                    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
                
                start_str = format_time(start)
                end_str = format_time(end)
                
                f_srt.write(f"{index + 1}\n")
                f_srt.write(f"{start_str} --> {end_str}\n")
                f_srt.write(f"{text}\n\n")
                
                letra_completa += text + "\n"
                
        return {"letra": letra_completa, "ruta_local": ruta_mp3}
        
    except Exception as e:
        print(f"Error en descargar_y_transcribir: {e}")
        # Si falló, al menos no rompemos el agente
        return {"letra": "Error generando letra", "ruta_local": ""}



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