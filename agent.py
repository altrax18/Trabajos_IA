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
                try:
                    result = await session.call_tool("buscar_canciones", arguments={"genero": state['genero']})
                    # FastMCP serializa List[dict] como múltiples TextContent (uno por dict)
                    canciones_list = []
                    for item in result.content:
                        canciones_list.append(json.loads(item.text))
                    
                    print(f"  Encontradas: {len(canciones_list)} canciones")
                    return {"canciones_encontradas": canciones_list}
                except Exception as e:
                    print(f"Error en buscar_canciones: {e}")
                    return {"canciones_encontradas": []}

            async def enriquecer_step(state: AgentState):
                print("--- ENRIQUECIENDO CON BPM ---")
                enriquecidas = []
                for cancion in state['canciones_encontradas']:
                    # Asegurar que cancion es dict (LangGraph puede serializar a str)
                    if isinstance(cancion, str):
                        cancion = json.loads(cancion)
                    try:
                        bpm_data = await session.call_tool("analizar_bpm", arguments={"cancion_id": cancion['id']})
                        bpm_dict = json.loads(bpm_data.content[0].text)
                        nueva_cancion = {**cancion, **bpm_dict}
                        enriquecidas.append(nueva_cancion)
                    except Exception as e:
                        print(f"Error analizando {cancion.get('titulo', '?')}: {e}")
                        enriquecidas.append(cancion)
                return {"canciones_enriquecidas": enriquecidas}

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
                     # Formato M3U simple: #EXTINF:duracion,Artista - Titulo
                    contenido += f"#EXTINF:-1,{c.get('artista')} - {c.get('titulo')} (BPM: {c.get('bpm', 'N/A')})\n"
                    contenido += f"{c.get('titulo')}.mp3\n" # Simulación ruta archivo
                
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
            workflow.add_node("curar", curar_step)
            workflow.add_node("guardar", guardar_step)
            
            workflow.add_edge(START, "buscar")
            workflow.add_edge("buscar", "enriquecer")
            workflow.add_edge("enriquecer", "curar")
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
