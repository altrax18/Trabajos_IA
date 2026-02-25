import asyncio, json, os, sys, subprocess
from pathlib import Path
from typing import TypedDict, List
from langgraph.graph import StateGraph, START, END
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Estado del Grafo
class AgentState(TypedDict):
    genero: str
    vibe: str
    terminos_busqueda: List[str]
    canciones_encontradas: List[dict]
    canciones_enriquecidas: List[dict]
    canciones_locales: List[dict]
    setlist_final: List[dict]
    archivo_guardado: str
    vlc: bool

# Configuración del servidor MCP propio (stdio)
server_script = Path(__file__).parent / "server.py"
music_server_params = StdioServerParameters(
    command=sys.executable, 
    args=[str(server_script)], 
    env=None
)

# Configuración del servidor MCP de terceros: Filesystem (Anthropic)
# Permite al agente leer/escribir archivos via MCP en vez de hacerlo directamente
output_dir = str(Path(__file__).parent / "output")
filesystem_server_params = StdioServerParameters(
    command="npx",
    args=["-y", "@modelcontextprotocol/server-filesystem", output_dir],
    env=None
)
# Funcion auxiliar para ejecutar VLC Player después de que el agente termine
def _lanzar_vlc(ruta_m3u: str) -> None:
    """
    Lanza VLC desde el proceso principal de Python (no desde el servidor MCP).
    Esto evita que VLC quede asociado al job object del subprocess de server.py.
    """
    vlc_exe = r'C:\Program Files\VideoLAN\VLC\vlc.exe'
    if not os.path.exists(vlc_exe):
        vlc_exe = r'C:\Program Files (x86)\VideoLAN\VLC\vlc.exe'
    if not os.path.exists(vlc_exe):
        print("VLC no encontrado.", file=sys.stderr)
        return

    ruta_abs = os.path.abspath(ruta_m3u)

    DETACHED_PROCESS        = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    CREATE_BREAKAWAY_FROM_JOB = 0x01000000

    try:
        subprocess.Popen(
            [vlc_exe, ruta_abs],
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"  ✓ VLC lanzado desde el proceso principal: {os.path.basename(ruta_abs)}")
    except Exception as e:
        print(f"  Error lanzando VLC: {e}", file=sys.stderr)

# Función lógica para el Conditional Edge
def trig(state: AgentState):
    if state.get("vlc"):
        return "reproducir"
    return "fin"

def _get_safe_errlog():
    """
    Devuelve un file object seguro para usar como errlog en stdio_client.
    Streamlit reemplaza sys.stderr con un objeto sin fileno(), lo que rompe
    subprocess.Popen. Usamos os.devnull como fallback seguro.
    """
    try:
        sys.stderr.fileno()
        return sys.stderr
    except Exception:
        return open("mcp_server_err.log", "a", encoding="utf-8")

async def run_agent(genero: str, vibe: str, vlc: bool):
    """
    Función principal que orquesta el flujo usando LangGraph y conecta a los servidores MCP.
    Usa dos servidores MCP:
      - Servidor propio (server.py): tools de música (iTunes, Cohere)
      - Servidor Filesystem (terceros): escritura de archivos .m3u
    """
    
    # Crear directorio de salida si no existe
    os.makedirs(output_dir, exist_ok=True)
    
    errlog = _get_safe_errlog()
    
    # Conexión a AMBOS servidores MCP simultáneamente
    async with stdio_client(music_server_params, errlog=errlog) as (m_read, m_write):
        async with ClientSession(m_read, m_write) as music_session:
            await music_session.initialize()
            print("✓ Servidor MCP propio conectado (music tools)")
            
            async with stdio_client(filesystem_server_params, errlog=errlog) as (f_read, f_write):
                async with ClientSession(f_read, f_write) as fs_session:
                    await fs_session.initialize()
                    print("✓ Servidor MCP Filesystem conectado (terceros)")
                    
                    # --- Pasos del Grafo ---
                    async def generar_terminos_step(state: AgentState):
                        print(f"--- GENERANDO TÉRMINOS DE BÚSQUEDA: {state['genero']} / {state['vibe']} ---")
                        try:
                            result = await music_session.call_tool(
                                "generar_terminos_busqueda",
                                arguments={"genero": state['genero'], "vibe": state['vibe'], "cantidad": 8}
                            )
                            terminos = [item.text for item in result.content if item.text.strip()]
                            if not terminos:
                                raise ValueError("Lista de términos vacía")
                            print(f"  Términos generados: {terminos}")
                        except Exception as e:
                            print(f"  Error generando términos, usando fallback: {e}")
                            terminos = [f"{state['genero']} {state['vibe']}"]

                        return {"terminos_busqueda": terminos}
                
                    async def buscar_step(state: AgentState):
                        print(f"--- BUSCANDO CANCIONES EN ITUNES ---")
                        canciones_list = []
                        ids_vistos = set()

                        for termino in state['terminos_busqueda']:
                            try:
                                result = await music_session.call_tool(
                                    "buscar_canciones_api_externa",
                                    arguments={"termino": termino, "limite": 2}
                                )
                                for item in result.content:
                                    parsed = json.loads(item.text)
                                    canciones_raw = parsed if isinstance(parsed, list) else [parsed]
                                    for song in canciones_raw:
                                        clave = (song.get("titulo", "").lower(), song.get("artista", "").lower())
                                        if clave not in ids_vistos:
                                            ids_vistos.add(clave)
                                            canciones_list.append({
                                                "id": f"itunes_{len(canciones_list)}",
                                                "titulo": song.get("titulo", ""),
                                                "artista": song.get("artista", ""),
                                                "genero": state['genero'],
                                                "preview_url": song.get("preview_url", ""),
                                            })
                            except Exception as e:
                                print(f"  Error buscando '{termino}': {e}")

                        print(f"  Total canciones encontradas: {len(canciones_list)}")
                        return {"canciones_encontradas": canciones_list}

                    async def enriquecer_step(state: AgentState):
                        print("--- ENRIQUECIENDO CON BPM (batch) ---")
                        canciones = []
                        for cancion in state['canciones_encontradas']:
                            if isinstance(cancion, str):
                                cancion = json.loads(cancion)
                            canciones.append(cancion)
                        
                        # Una sola llamada para todas las canciones
                        try:
                            result = await music_session.call_tool("analizar_bpm_batch", arguments={"canciones": canciones})
                            bpm_list = []
                            for item in result.content:
                                parsed = json.loads(item.text)
                                if isinstance(parsed, list):
                                    bpm_list.extend(parsed)
                                else:
                                    bpm_list.append(parsed)
                            
                            # Mapear BPMs por posición (mismo orden que la petición)
                            enriquecidas = []
                            for i, cancion in enumerate(canciones):
                                if i < len(bpm_list):
                                    bpm_val = bpm_list[i].get("bpm", 0)
                                    key_val = bpm_list[i].get("key", "Unknown")
                                    cancion["bpm"] = int(bpm_val) if bpm_val else 0
                                    cancion["key"] = str(key_val) if key_val else "Unknown"
                                enriquecidas.append(cancion)
                            print(f"  BPM estimado para {len(bpm_list)} canciones")
                        except Exception as e:
                            print(f"  Error en batch BPM: {e}")
                            enriquecidas = canciones
                        
                        # Filtrar outliers de BPM: mantener canciones dentro de ±40 BPM de la mediana
                        con_bpm = [c for c in enriquecidas if c.get('bpm', 0) > 0]
                        sin_bpm = [c for c in enriquecidas if c.get('bpm', 0) == 0]
                        
                        if len(con_bpm) >= 3:
                            bpms = sorted([c['bpm'] for c in con_bpm])
                            mediana = bpms[len(bpms) // 2]
                            filtradas = [c for c in con_bpm if abs(c['bpm'] - mediana) <= 40]
                            descartadas = len(con_bpm) - len(filtradas)
                            if descartadas > 0:
                                print(f"  Filtrado BPM: mediana={mediana}, descartadas {descartadas} canciones fuera de rango")
                            filtradas.sort(key=lambda c: c['bpm'])
                            enriquecidas = filtradas + sin_bpm
                            print(f"  Canciones tras filtro: {len(enriquecidas)}")
                        
                        return {"canciones_enriquecidas": enriquecidas}

                    async def preview_step(state: AgentState):
                        print("--- OBTENIENDO PREVIEW URLs DE iTUNES ---")
                        canciones_con_preview = []
                        for cancion in state['canciones_enriquecidas']:
                            if isinstance(cancion, str):
                                cancion = json.loads(cancion)
                            # Si ya tiene preview_url (de iTunes en buscar_step), no refetch
                            if cancion.get("preview_url"):
                                print(f"  ✓ Preview ya disponible: {cancion.get('titulo')}")
                                canciones_con_preview.append(cancion)
                                continue
                            try:
                                query = f"{cancion.get('titulo', '')} {cancion.get('artista', '')}"
                                result = await music_session.call_tool("buscar_canciones_api_externa", arguments={"termino": query, "limite": 1})
                                itunes_results = []
                                for item in result.content:
                                    parsed = json.loads(item.text)
                                    if isinstance(parsed, list):
                                        itunes_results.extend(parsed)
                                    else:
                                        itunes_results.append(parsed)
                                if itunes_results and itunes_results[0].get("preview_url"):
                                    cancion["preview_url"] = itunes_results[0]["preview_url"]
                                    print(f"  ✓ Preview encontrado para: {cancion.get('titulo')}")
                                else:
                                    cancion["preview_url"] = ""
                                    print(f"  ✗ Sin preview para: {cancion.get('titulo')}")
                            except Exception as e:
                                print(f"  Error buscando preview de {cancion.get('titulo', '?')}: {e}")
                                cancion["preview_url"] = ""
                            canciones_con_preview.append(cancion)
                        return {"canciones_enriquecidas": canciones_con_preview}

                    async def transcribir_step(state: AgentState):
                        print("--- DESCARGANDO Y TRANSCRIBIENDO PREVIEWS (WHISPER) ---")
                        run_dir_name = f"setlist_{state['genero']}_{state['vibe'].replace(' ', '_')}"
                        run_output_dir = str(Path(output_dir) / run_dir_name)
                        canciones = []
                        for cancion in state['canciones_enriquecidas']:
                            if isinstance(cancion, str):
                                cancion = json.loads(cancion)
                            url = cancion.get("preview_url")
                            if url:
                                try:
                                    res = await music_session.call_tool(
                                        "descargar_y_transcribir", 
                                        arguments={
                                            "preview_url": url, 
                                            "artista": cancion.get("artista", "Unknown"), 
                                            "titulo": cancion.get("titulo", "Unknown"),
                                            "output_dir": run_output_dir
                                        }
                                    )
                                    parsed = json.loads(res.content[0].text)
                                    cancion["letra"] = parsed.get("letra", "")
                                    cancion["ruta_local"] = parsed.get("ruta_local", "")
                                    print(f"  ✓ Transcrito y guardado local: {cancion.get('titulo')}")
                                except Exception as e:
                                    print(f"  Error transcribiendo {cancion.get('titulo')}: {e}")
                                    cancion["letra"] = ""
                                    cancion["ruta_local"] = ""
                            else:
                                cancion["letra"] = ""
                                cancion["ruta_local"] = ""
                            canciones.append(cancion)
                        return {"canciones_locales": canciones}

                    async def curar_step(state: AgentState):
                        print(f"--- CURANDO LISTA CON VIBE: {state['vibe']} ---")
                        try:
                            result = await music_session.call_tool("curador_musical", arguments={
                                "canciones": state['canciones_locales'], 
                                "vibe": state['vibe']
                            })
                            curada = []
                            for item in result.content:
                                parsed = json.loads(item.text)
                                if isinstance(parsed, list):
                                    curada.extend(parsed)
                                else:
                                    curada.append(parsed)
                            return {"setlist_final": curada}
                        except Exception as e:
                            print(f"Error curando lista: {e}")
                            return {"setlist_final": state['canciones_locales']}

                    async def guardar_step(state: AgentState):
                        print("--- GUARDANDO ARCHIVO .M3U (con rutas absolutas para VLC) ---")
                        
                        # 1. Definir y crear la estructura de directorios: /output/setlist_genero_vibe/
                        run_dir_name = f"setlist_{state['genero']}_{state['vibe'].replace(' ', '_')}"
                        run_output_dir = str(Path(output_dir) / run_dir_name)
                        os.makedirs(run_output_dir, exist_ok=True)
                        
                        # 2. Definir la ruta del archivo .m3u dentro de esa carpeta
                        nombre_archivo = f"{run_dir_name}.m3u"
                        ruta_completa = str(Path(run_output_dir) / nombre_archivo)
                        
                        # 3. Generar el contenido del archivo M3U
                        contenido = "#EXTM3U\n"
                        for c in state['setlist_final']:
                            # Información de metadatos para el reproductor
                            contenido += f"#EXTINF:-1,{c.get('artista')} - {c.get('titulo')} (BPM: {c.get('bpm', 'N/A')})\n"
                            
                            ruta_local = c.get('ruta_local', '')
                            if ruta_local and os.path.exists(ruta_local):
                                # REQUISITO CLAVE: Usamos la ruta absoluta completa de Windows.
                                # Esto garantiza que el proceso independiente de VLC encuentre el archivo.
                                abs_path = os.path.abspath(ruta_local)
                                contenido += f"{abs_path}\n"
                            else:
                                contenido += f"# Sin audio local disponible para: {c.get('titulo')}\n"
                        
                        # 4. Intentar guardar el archivo usando el servidor MCP Filesystem
                        try:
                            await fs_session.call_tool("write_file", arguments={
                                "path": ruta_completa,
                                "content": contenido
                            })
                            print(f"  ✓ Archivo guardado via MCP Filesystem: {ruta_completa}")
                            return {"archivo_guardado": ruta_completa}
                        except Exception as e:
                            print(f"  Aviso: Error guardando via MCP Filesystem ({e}). Intentando guardado directo...")
                            
                            # Fallback: Escritura directa en disco si el servidor MCP falla
                            try:
                                Path(ruta_completa).write_text(contenido, encoding='utf-8')
                                print(f"  ✓ Archivo guardado (directamente): {ruta_completa}")
                                return {"archivo_guardado": ruta_completa}
                            except Exception as e2:
                                print(f"  Error crítico al guardar el archivo: {e2}")
                                return {"archivo_guardado": "Error"}
                            
                    async def reproducir_step(state: AgentState):
                        print("--- MARCANDO PARA REPRODUCCIÓN EN VLC ---")
                        # Solo marcamos el estado; el lanzamiento real ocurre fuera del contexto MCP
                        return state
                    
                    # --- Construcción del Grafo ---
                    workflow = StateGraph(AgentState)
                    workflow.add_node("generar_terminos", generar_terminos_step)
                    workflow.add_node("buscar", buscar_step)
                    workflow.add_node("enriquecer", enriquecer_step)
                    workflow.add_node("preview", preview_step)
                    workflow.add_node("transcribir", transcribir_step)
                    workflow.add_node("curar", curar_step)
                    workflow.add_node("guardar", guardar_step)
                    workflow.add_node("reproducir", reproducir_step)
                    
                    workflow.add_edge(START, "generar_terminos")
                    workflow.add_edge("generar_terminos", "buscar")
                    workflow.add_edge("buscar", "enriquecer")
                    workflow.add_edge("enriquecer", "preview")
                    workflow.add_edge("preview", "transcribir")
                    workflow.add_edge("transcribir", "curar")
                    workflow.add_edge("curar", "guardar")
                    workflow.add_conditional_edges(
                        "guardar",  # Nodo de origen
                        trig,       # Función lógica
                        {
                            "reproducir": "reproducir", # Si devuelve "reproducir", va al nodo reproducir
                            "fin": END                  # Si devuelve "fin", va al final
                        }
                    )
                    workflow.add_edge("reproducir", END)
                    
                    app = workflow.compile()
                    
                    # --- Ejecución ---
                    inputs = {"genero": genero, 
                              "vibe": vibe,
                              "terminos_busqueda": [], 
                              "canciones_encontradas": [],
                              "canciones_enriquecidas": [],
                              "canciones_locales": [],
                              "setlist_final": [],
                              "archivo_guardado": "",
                              "vlc": vlc
                    }

                    final_state = await app.ainvoke(inputs)
                    if vlc and final_state.get("archivo_guardado") and final_state["archivo_guardado"] != "Error":
                        _lanzar_vlc(final_state["archivo_guardado"])

                    return final_state

if __name__ == "__main__":
    if len(sys.argv) > 1:
        g = sys.argv[1]
        v = sys.argv[2] if len(sys.argv) > 2 else "Party"
        vlc_flag = sys.argv[3].lower() == "true" if len(sys.argv) > 3 else False
        asyncio.run(run_agent(g, v, vlc_flag))
    else:
        print("Uso: python agent.py <genero> <vibe> [true/false]")

# if __name__ == "__main__":
#     # Prueba rápida CLI
#     if len(sys.argv) > 1:
#         g = sys.argv[1]
#         v = sys.argv[2] if len(sys.argv) > 2 else "Party"
#         asyncio.run(run_agent(g, v))
#     else:
#         print("Uso: python agent.py <genero> <vibe>")
