import json, re, httpx, whisper, os, sys
from typing import List
from dotenv import load_dotenv, find_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(find_dotenv())

mcp = FastMCP("Setlist Architect Music Server")

# Cargar el modelo de Whisper (puede tomar unos segundos la primera vez)
try:
    print("Cargando modelo Whisper 'base'...", file=sys.stderr)
    whisper_model = whisper.load_model("base")
    print("Modelo Whisper cargado correctamente.", file=sys.stderr)
except Exception as e:
    print(f"Error cargando Whisper: {e}", file=sys.stderr)
    whisper_model = None
# ==============================
# TOOL 0: Generar término de búsqueda para iTunes
# ==============================
@mcp.tool()
def generar_terminos_busqueda(genero: str, vibe: str, cantidad: int = 8) -> List[str]:
    """
    Usa el LLM para generar términos de búsqueda inteligentes (artista + canción)
    que se ajusten al género y vibe indicados, en lugar de buscar literalmente
    los campos introducidos por el usuario.
    """
    api_key = os.getenv("COHERE_API_KEY")

    if not api_key:
        # Fallback básico si no hay API key
        return [f"{genero} {vibe}"]

    prompt_msg = f"""
    Eres un experto en música. Tu misión es generar una playlist para el usuario basada en estas dos criterios:
    - Género: '{genero}'
    - Vibe: '{vibe}'

    Ambos criterios son igual de importantes y deben cumplirse simultáneamente.
    El género define el estilo musical: estilo, instrumentación, estructura, subgénero.
    El vibe define la temática, el tempo, la energía y el enfoque emocional dentro de ese género.
    
    Debes elegir artistas cuya música, temática y estilo encajen específicamente con ambos criterios,
    no simplemente los más populares del género.

    Genera exactamente {cantidad} términos de búsqueda para iTunes.
    Cada término debe ser SOLO el nombre del artista, o "Artista Album" si conoces un álbum 
    real que encaje especialmente bien con el vibe pedido.
    NO inventes títulos de canciones ni álbumes. Es mejor un término simple que uno inventado.

    Reglas:
    - Devuelve SOLO un JSON array de strings. Sin explicaciones, sin texto extra.
    - Prioriza artistas cuya temática, letra o sonido conecte directamente con '{vibe}'.
    - Usa artistas reales y reconocibles.
    - Varía los artistas, no repitas el mismo más de una vez.
    - Evita elegir siempre los artistas más obvios o mainstream del género si no encajan con el vibe.
    - Usa SOLO el nombre del artista o banda. Nunca uses nombres que puedan confundirse 
      con títulos de canciones de otros géneros (ej: evita términos genéricos como 
      "Death", "Poison", "Warrant" si pueden coincidir con canciones de otros estilos).
    - Si el nombre del artista es ambiguo, añade una palabra del álbum más conocido para 
      dar contexto (ej: "Death Symbolic" en lugar de solo "Death").
    """

    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                "https://api.cohere.com/v2/chat",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "command-a-03-2025",
                    "messages": [{"role": "user", "content": prompt_msg}],
                    "temperature": 0.7,
                },
            )
            response.raise_for_status()

        data = response.json()
        content_blocks = data.get("message", {}).get("content", [])
        text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")

        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            terminos = json.loads(match.group())
            if isinstance(terminos, list) and terminos:
                print(f"Términos generados: {terminos}", file=sys.stderr)
                return terminos

    except Exception as e:
        print(f"ERROR generar_terminos_busqueda: {e}", file=sys.stderr)

    # Fallback si el LLM falla
    return [f"{genero} {vibe}"]


# ==============================
# TOOL 1: Buscar canciones iTunes
# ==============================
@mcp.tool()
def buscar_canciones_api_externa(termino: str, limite: int = 5) -> List[dict]:
    url = "https://itunes.apple.com/search"
    params = {"term": termino,
              "media": "music",
              "limit": int(limite),
              "attribute": "artistTerm"
            }
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
        print("ERROR ITUNES:", e, file=sys.stderr)
        return []

# ==============================
# TOOL 2: Analizar BPM (Cohere v2)
# ==============================
@mcp.tool()
def analizar_bpm_batch(canciones: List[dict]) -> List[dict]:
    api_key = os.getenv("COHERE_API_KEY")

    if not api_key:
        return [{"bpm": 0, "key": "Unknown"} for _ in canciones]

    lista_canciones = "\n".join(
        [f"- {c.get('titulo')} de {c.get('artista')}" for c in canciones]
    )

    prompt_msg = f"""
    Eres un experto en musicología y análisis musical. Para cada canción de la lista, estima su BPM real 
    y su tonalidad (key) basándote en tu conocimiento de la canción y el estilo del artista.

    Devuelve SOLO un JSON array con exactamente {len(canciones)} objetos, en el mismo orden que la lista.
    Cada objeto debe tener exactamente estos dos campos:
    - "bpm": número entero con el BPM real o estimado de la canción
    - "key": tonalidad en formato anglosajón (ej: "Am", "C#", "Dm", "G", "F#m"...)

    El BPM debe reflejar el tempo real de la canción:
    - No apliques ningún rango mínimo ni máximo artificial.
    - Una balada lenta puede estar en 50-70 BPM, un tema de Drum & Bass en 170-180 BPM.
    - Si conoces el BPM exacto de la canción, úsalo. Si no, estima uno coherente con 
    el género, la energía y el estilo del artista.

    Canciones a analizar (en este orden exacto):
    {lista_canciones}

    Responde ÚNICAMENTE con el JSON array. Sin explicaciones, sin texto adicional, sin markdown.
    Ejemplo de formato esperado para 3 canciones:
    [
    {{"bpm": 133, "key": "Am"}},
    {{"bpm": 72, "key": "F#m"}},
    {{"bpm": 165, "key": "Dm"}}
    ]
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
                    "model": "command-a-03-2025",
                    "messages": [
                        {"role": "user", "content": prompt_msg}
                    ],
                    "temperature": 0.0,
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
        print("ERROR BPM:", e, file=sys.stderr)

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
                    "model": "command-a-03-2025",
                    "messages": [
                        {"role": "user", "content": prompt_msg}
                    ],
                    "temperature": 0.2,
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
        print("ERROR CURADOR:", e, file=sys.stderr)

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
        print(f"Error en descargar_y_transcribir: {e}", file=sys.stderr)
        # Si falló, al menos no rompemos el agente
        return {"letra": "Error generando letra", "ruta_local": ""}

# ==============================
# Integración con VLC Player
# ==============================

@mcp.tool()
def reproducir_lista_m3u(ruta_m3u: str) -> str:
    """
    Valida que el archivo .m3u existe y devuelve su ruta absoluta.
    El lanzamiento real de VLC se delega al proceso cliente para evitar
    problemas de job objects en Windows.
    """
    if not ruta_m3u or not os.path.exists(ruta_m3u):
        return f"ERROR: Archivo no encontrado en {ruta_m3u}"
    
    return f"OK:{os.path.abspath(ruta_m3u)}"
 
# ==============================
# TRANSPORTES
# ==============================
if __name__ == "__main__":
    mcp.run(transport="stdio")