import asyncio
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

import sys
from pathlib import Path

# ... (imports remain)

# Configuración del servidor MCP Local (stdio)
# Usamos sys.executable para asegurar que usamos el mismo entorno virtual/interpreter que el agente
# Usamos path absoluto para server.py para evitar problemas de directorio de trabajo
server_script = Path(__file__).parent / "server.py"

server_params = StdioServerParameters(
    command=sys.executable, 
    args=[str(server_script)], 
    env=None
)

async def run_agent(genero: str, vibe: str):
    """
    Función principal que orquesta el flujo usando LangGraph y conecta al servidor MCP.
    """
    
    # 1. Conexión al servidor MCP
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Inicializar herramientas disponibles
            await session.initialize()
            
            # --- Nodos del Grafo ---
            
            async def buscar_step(state: AgentState):
                print(f"--- BUSCANDO CANCIONES DE {state['genero']} ---")
                try:
                    # Llamada a tool MCP: buscar_canciones
                    result = await session.call_tool("buscar_canciones", arguments={"genero": state['genero']})
                    # El resultado de call_tool suele venir en una estructura content/isError
                    canciones = result.content[0].text
                    # Parseamos si viene como string JSON, si no, asumimos que es el objeto directo (depende de implementación SDK)
                    # En FastMCP stdio, el retorno suele ser JSON stringificado en text
                    import json
                    canciones_list = json.loads(canciones)
                    return {"canciones_encontradas": canciones_list}
                except Exception as e:
                    print(f"Error en buscar_canciones: {e}")
                    return {"canciones_encontradas": []}

            async def enriquecer_step(state: AgentState):
                print("--- ENRIQUECIENDO CON BPM ---")
                enriquecidas = []
                for cancion in state['canciones_encontradas']:
                    try:
                        # Llamada a tool MCP: analizar_bpm
                        bpm_data = await session.call_tool("analizar_bpm", arguments={"cancion_id": cancion['id']})
                        import json
                        bpm_dict = json.loads(bpm_data.content[0].text)
                        
                        # Combinamos datos
                        nueva_cancion = {**cancion, **bpm_dict}
                        enriquecidas.append(nueva_cancion)
                    except Exception as e:
                        print(f"Error analizando {cancion.get('titulo')}: {e}")
                        enriquecidas.append(cancion)
                return {"canciones_enriquecidas": enriquecidas}

            async def curar_step(state: AgentState):
                print(f"--- CURANDO LISTA CON VIBE: {state['vibe']} ---")
                try:
                    # Llamada a tool MCP: curador_musical
                    # Pasamos la lista enriquecida y el vibe
                    # Nota: Pasar objetos complejos puede requerir serialización dependiendo del SDK
                    # Aquí pasamos la lista directa, FastMCP debería manejarlo
                    result = await session.call_tool("curador_musical", arguments={
                        "canciones": state['canciones_enriquecidas'], 
                        "vibe": state['vibe']
                    })
                    import json
                    curada = json.loads(result.content[0].text)
                    return {"setlist_final": curada}
                except Exception as e:
                    print(f"Error curando lista: {e}")
                    return {"setlist_final": state['canciones_enriquecidas']} # Fallback

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
