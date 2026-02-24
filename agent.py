import asyncio
import json
import os
import sys
from pathlib import Path
from typing import TypedDict, List
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Estado del Grafo
class AgentState(TypedDict):
    genero: str
    vibe: str
    canciones_encontradas: List[dict]
    canciones_enriquecidas: List[dict]
    canciones_locales: List[dict]
    setlist_final: List[dict]
    archivo_guardado: str

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
        return open(os.devnull, "w")

async def run_agent(genero: str, vibe: str):
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
                    
                    # --- Nodos del Grafo ---
                    
                    async def buscar_step(state: AgentState):
                        print(f"--- BUSCANDO CANCIONES DE {state['genero']} ---")
                        canciones_list = []
                        
                        # Buscar en iTunes según género + vibe
                        try:
                            search_term = f"{state['genero']} {state['vibe']}"
                            result = await music_session.call_tool("buscar_canciones_api_externa", arguments={"termino": search_term, "limite": 10})
                            itunes_raw = []
                            for item in result.content:
                                parsed = json.loads(item.text)
                                if isinstance(parsed, list):
                                    itunes_raw.extend(parsed)
                                else:
                                    itunes_raw.append(parsed)
                            
                            for idx, it_song in enumerate(itunes_raw):
                                canciones_list.append({
                                    "id": f"itunes_{idx}",
                                    "titulo": it_song.get("titulo", ""),
                                    "artista": it_song.get("artista", ""),
                                    "genero": state['genero'],
                                    "preview_url": it_song.get("preview_url", ""),
                                })
                            print(f"  iTunes: {len(canciones_list)} resultados ('{search_term}')")
                        except Exception as e:
                            print(f"  Error en búsqueda iTunes: {e}")
                        
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
                        
                        # Filtrar outliers de BPM: mantener canciones dentro de ±25 BPM de la mediana
                        con_bpm = [c for c in enriquecidas if c.get('bpm', 0) > 0]
                        sin_bpm = [c for c in enriquecidas if c.get('bpm', 0) == 0]
                        
                        if len(con_bpm) >= 3:
                            bpms = sorted([c['bpm'] for c in con_bpm])
                            mediana = bpms[len(bpms) // 2]
                            filtradas = [c for c in con_bpm if abs(c['bpm'] - mediana) <= 25]
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
                        print("--- GUARDANDO ARCHIVO .M3U (via Filesystem MCP) ---")
                        
                        run_dir_name = f"setlist_{state['genero']}_{state['vibe'].replace(' ', '_')}"
                        run_output_dir = str(Path(output_dir) / run_dir_name)
                        os.makedirs(run_output_dir, exist_ok=True)
                        
                        nombre_archivo = f"{run_dir_name}.m3u"
                        ruta_completa = str(Path(run_output_dir) / nombre_archivo)
                        contenido = "#EXTM3U\n"
                        for c in state['setlist_final']:
                            contenido += f"#EXTINF:-1,{c.get('artista')} - {c.get('titulo')} (BPM: {c.get('bpm', 'N/A')})\n"
                            ruta_local = c.get('ruta_local', '')
                            if ruta_local:
                                # Usar solo el nombre del archivo si esta en el mismo dir
                                nombre_audio = os.path.basename(ruta_local)
                                contenido += f"{nombre_audio}\n"
                            else:
                                contenido += f"# Sin preview disponible: {c.get('titulo')}.mp3\n"
                        
                        try:
                            # Usar el MCP Filesystem de terceros para escribir el archivo
                            await fs_session.call_tool("write_file", arguments={
                                "path": ruta_completa,
                                "content": contenido
                            })
                            print(f"  ✓ Archivo guardado via MCP Filesystem: {ruta_completa}")
                            return {"archivo_guardado": ruta_completa}
                        except Exception as e:
                            print(f"  Error guardando via MCP Filesystem: {e}")
                            # Fallback: escritura directa
                            try:
                                Path(ruta_completa).write_text(contenido, encoding='utf-8')
                                print(f"  ✓ Archivo guardado (fallback local): {ruta_completa}")
                                return {"archivo_guardado": ruta_completa}
                            except Exception as e2:
                                print(f"  Error total guardando: {e2}")
                                return {"archivo_guardado": "Error"}

                    # --- Construcción del Grafo ---
                    workflow = StateGraph(AgentState)
                    
                    workflow.add_node("buscar", buscar_step)
                    workflow.add_node("enriquecer", enriquecer_step)
                    workflow.add_node("preview", preview_step)
                    workflow.add_node("transcribir", transcribir_step)
                    workflow.add_node("curar", curar_step)
                    workflow.add_node("guardar", guardar_step)
                    
                    workflow.add_edge(START, "buscar")
                    workflow.add_edge("buscar", "enriquecer")
                    workflow.add_edge("enriquecer", "preview")
                    workflow.add_edge("preview", "transcribir")
                    workflow.add_edge("transcribir", "curar")
                    workflow.add_edge("curar", "guardar")
                    workflow.add_edge("guardar", END)
                    
                    app = workflow.compile()
                    
                    # --- Ejecución ---
                    inputs = {"genero": genero, "vibe": vibe, "canciones_encontradas": [], "canciones_enriquecidas": [], "canciones_locales": [], "setlist_final": [], "archivo_guardado": ""}
                    final_state = await app.ainvoke(inputs)
                    
                    return final_state

if __name__ == "__main__":
    # Prueba rápida CLI
    if len(sys.argv) > 1:
        g = sys.argv[1]
        v = sys.argv[2] if len(sys.argv) > 2 else "Party"
        asyncio.run(run_agent(g, v))
    else:
        print("Uso: python agent.py <genero> <vibe>")
