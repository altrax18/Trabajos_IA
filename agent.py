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
    setlist_final: List[dict]
    archivo_guardado: str

# Configuración del servidor MCP Local (stdio)
# Usamos sys.executable para asegurar que usamos el mismo entorno virtual/interpreter que el agente
# Usamos path absoluto para server.py para evitar problemas de directorio de trabajo
server_script = Path(__file__).parent / "server.py"

server_params = StdioServerParameters(
    command=sys.executable, 
    args=[str(server_script)], 
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
    Función principal que orquesta el flujo usando LangGraph y conecta al servidor MCP.
    """
    
    # 1. Conexión al servidor MCP
    # Pasamos un errlog seguro para evitar crash en Streamlit
    errlog = _get_safe_errlog()
    async with stdio_client(server_params, errlog=errlog) as (read, write):
        async with ClientSession(read, write) as session:
            # Inicializar herramientas disponibles
            await session.initialize()
            
            # --- Nodos del Grafo ---
            
            async def buscar_step(state: AgentState):
                print(f"--- BUSCANDO CANCIONES DE {state['genero']} ---")
                canciones_list = []
                
                # Buscar en iTunes según género + vibe
                try:
                    search_term = f"{state['genero']} {state['vibe']}"
                    result = await session.call_tool("buscar_canciones_api_externa", arguments={"termino": search_term, "limite": 10})
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
                    result = await session.call_tool("analizar_bpm_batch", arguments={"canciones": canciones})
                    bpm_list = []
                    for item in result.content:
                        parsed = json.loads(item.text)
                        if isinstance(parsed, list):
                            bpm_list.extend(parsed)
                        else:
                            bpm_list.append(parsed)
                    
                    # Mapear BPMs por título
                    bpm_map = {b.get("titulo", "").lower(): b for b in bpm_list}
                    enriquecidas = []
                    for cancion in canciones:
                        titulo_lower = cancion.get("titulo", "").lower()
                        if titulo_lower in bpm_map:
                            cancion["bpm"] = bpm_map[titulo_lower].get("bpm", 0)
                            cancion["key"] = bpm_map[titulo_lower].get("key", "Unknown")
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
                        result = await session.call_tool("buscar_canciones_api_externa", arguments={"termino": query, "limite": 1})
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

            async def curar_step(state: AgentState):
                print(f"--- CURANDO LISTA CON VIBE: {state['vibe']} ---")
                try:
                    result = await session.call_tool("curador_musical", arguments={
                        "canciones": state['canciones_enriquecidas'], 
                        "vibe": state['vibe']
                    })
                    # Parsear respuesta: puede ser un solo content o múltiples
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
                    return {"setlist_final": state['canciones_enriquecidas']}

            async def guardar_step(state: AgentState):
                print("--- GUARDANDO ARCHIVO .M3U ---")
                # Aquí simulamos la herramienta de filesystem MCP
                # En producción: await session.call_tool("filesystem_write", ...)
                
                nombre_archivo = f"setlist_{state['genero']}_{state['vibe'].replace(' ', '_')}.m3u"
                contenido = "#EXTM3U\n"
                for c in state['setlist_final']:
                     # Formato M3U: #EXTINF:duracion,Artista - Titulo
                    contenido += f"#EXTINF:-1,{c.get('artista')} - {c.get('titulo')} (BPM: {c.get('bpm', 'N/A')})\n"
                    # Usar preview URL real de iTunes si está disponible
                    preview = c.get('preview_url', '')
                    if preview:
                        contenido += f"{preview}\n"
                    else:
                        contenido += f"# Sin preview disponible: {c.get('titulo')}.mp3\n"
                
                try:
                    p = Path(nombre_archivo)
                    p.write_text(contenido, encoding='utf-8')
                    return {"archivo_guardado": str(p.absolute())}
                except Exception as e:
                     print(f"Error guardando archivo: {e}")
                     return {"archivo_guardado": "Error"}

            # --- Construcción del Grafo ---
            workflow = StateGraph(AgentState)
            
            workflow.add_node("buscar", buscar_step)
            workflow.add_node("enriquecer", enriquecer_step)
            workflow.add_node("preview", preview_step)
            workflow.add_node("curar", curar_step)
            workflow.add_node("guardar", guardar_step)
            
            workflow.add_edge(START, "buscar")
            workflow.add_edge("buscar", "enriquecer")
            workflow.add_edge("enriquecer", "preview")
            workflow.add_edge("preview", "curar")
            workflow.add_edge("curar", "guardar")
            workflow.add_edge("guardar", END)
            
            app = workflow.compile()
            
            # --- Ejecución ---
            inputs = {"genero": genero, "vibe": vibe, "canciones_encontradas": [], "canciones_enriquecidas": [], "setlist_final": [], "archivo_guardado": ""}
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
