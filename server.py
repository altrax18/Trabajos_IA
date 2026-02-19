import asyncio
import json
from typing import List, Optional
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

# Configuración del servidor MCP
# Nombre del servidor y dependencias
mcp = FastMCP("Setlist Architect Music Server")

# Base de datos simulada de canciones (Requisito: Al menos 10 canciones variadas)
DB_CANCIONES = [
    {"id": "1", "titulo": "Bohemian Rhapsody", "artista": "Queen", "genero": "Rock"},
    {"id": "2", "titulo": "Shape of You", "artista": "Ed Sheeran", "genero": "Pop"},
    {"id": "3", "titulo": "Billie Jean", "artista": "Michael Jackson", "genero": "Pop"},
    {"id": "4", "titulo": "Smells Like Teen Spirit", "artista": "Nirvana", "genero": "Rock"},
    {"id": "5", "titulo": "Despacito", "artista": "Luis Fonsi", "genero": "Reggaeton"},
    {"id": "6", "titulo": "Hotel California", "artista": "Eagles", "genero": "Rock"},
    {"id": "7", "titulo": "Blinding Lights", "artista": "The Weeknd", "genero": "Pop"},
    {"id": "8", "titulo": "Sweet Child O' Mine", "artista": "Guns N' Roses", "genero": "Rock"},
    {"id": "9", "titulo": "Levitating", "artista": "Dua Lipa", "genero": "Pop"},
    {"id": "10", "titulo": "Gasolina", "artista": "Daddy Yankee", "genero": "Reggaeton"},
    {"id": "11", "titulo": "Enter Sandman", "artista": "Metallica", "genero": "Metal"},
    {"id": "12", "titulo": "Rolling in the Deep", "artista": "Adele", "genero": "Soul"},
]

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

# Requisito 2: Tool de análisis (Simulación API Externa)
@mcp.tool()
def analizar_bpm(cancion_id: str) -> dict:
    """
    Simula el análisis de una canción para obtener su BPM y tonalidad.
    Args:
        cancion_id: El ID de la canción a analizar.
    Returns:
        Diccionario con bpm y tonalidad simulados.
    """
    # Simulación simple basada en el ID para consistencia
    # En un caso real, aquí se llamaría a la API de Spotify o similar
    try:
        id_int = int(cancion_id)
        bpm = 90 + (id_int * 5) % 80  # BPM entre 90 y 170
        keys = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        key = keys[id_int % len(keys)] + ("m" if id_int % 2 == 0 else "")
        return {"bpm": bpm, "key": key}
    except ValueError:
        return {"bpm": 0, "key": "Unknown"}

# Requisito 3: Tool de Curador Musical (Simulación o LLM)
@mcp.tool()
def curador_musical(canciones: List[dict], vibe: str) -> List[dict]:
    """
    Ordena y selecciona canciones basándose en un 'vibe' u objetivo.
    Esta función simula la inteligencia de un curador experto.
    Args:
        canciones: Lista de canciones a curar.
        vibe: El objetivo o estillo deseado (ej: 'High Energy', 'Chill').
    Returns:
        Lista de canciones ordenadas para el setlist.
    """
    # En una implementación real, aquí usaríamos un LLM para decidir el orden
    # Para esta demo, simulamos la lógica:
    
    # Si analizamos los BPMs (que deberían venir ya enriquecidos, pero si no, simulamos)
    # Aquí asumimos que el Agente ya llamó a analizar_bpm y pasó la data, 
    # o simplificamos reordenando por "energía" simulada.
    
    import random
    
    lista_curada = list(canciones)
    
    if "chill" in vibe.lower() or "relax" in vibe.lower():
        # Simula orden para relax (por ejemplo, inversa al ID que usamos para BPM)
        lista_curada.sort(key=lambda x: x["titulo"], reverse=True) 
    elif "energy" in vibe.lower() or "party" in vibe.lower():
        # Aleatorio para fiesta
        random.shuffle(lista_curada)
    else:
        # Orden alfabético por defecto
        lista_curada.sort(key=lambda x: x["titulo"])
        
    return lista_curada

if __name__ == "__main__":
    import sys
    # Soporte para ejecución stdio (por defecto para agentes locales) o http (SSE)
    if "http" in sys.argv:
        # Ejecuta como servidor SSE sobre FastAPI
        # FastMCP ya monta esto automáticamente con .run(transport='sse') o similar
        # Pero para ser explícitos con FastAPI como pide el enunciado:
        print("Iniciando servidor HTTP SSE en puerto 8000...")
        mcp.run(transport="sse") # Usa el puerto 8000 por defecto
    else:
        # Ejecución estándar stdio para comunicación directa con clientes CLI/Desktop
        print("Iniciando servidor MCP stdio...", file=sys.stderr)
        mcp.run(transport="stdio")
