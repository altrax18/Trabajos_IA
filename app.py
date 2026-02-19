import streamlit as st
import asyncio
import os
from agent import run_agent

# Configuración de la página
st.set_page_config(page_title="Setlist Architect MCP", page_icon="🎵")

st.title("🎵 Setlist Architect MCP")
st.markdown("""
Este asistente utiliza **Agentes de IA** y el protocolo **MCP** para crear la lista de reproducción perfecta.
Conecta con un servidor local de música para buscar, analizar BPM y curar tu setlist.
""")

# Sidebar con información
with st.sidebar:
    st.header("Configuración")
    st.info("Asegúrate de tener `server.py` en el mismo directorio.")
    st.markdown("---")
    st.write("**Tecnologías:**")
    st.write("- LangGraph")
    st.write("- Model Context Protocol (MCP)")
    st.write("- Streamlit")

# Formulario de entrada
col1, col2 = st.columns(2)
with col1:
    genero = st.selectbox("Selecciona un Género", ["Rock", "Pop", "Reggaeton", "Metal", "Soul"])
with col2:
    vibe = st.text_input("Define el Vibe / Objetivo", placeholder="Ej: High Energy Workout, Chill Sunday...")

# Botón de acción
if st.button("🎛️ Generar Setlist", type="primary"):
    if not vibe:
        st.warning("Por favor define un 'vibe' para tu playlist.")
    else:
        status_text = st.empty()
        status_text.write("🚀 Iniciando agente... conectando a servidor MCP...")
        
        try:
            # Ejecutar el agente asíncronamente
            # Streamlit corre en un loop de eventos propio, asyncio.run puede dar conflictos si ya hay loop.
            # Pero normalmente en script top-level de streamlit está bien.
            final_state = asyncio.run(run_agent(genero, vibe))
            
            # Mostrar resultados
            status_text.success("¡Setlist generado con éxito!")
            
            st.subheader("🎼 Tu Setlist Curado")
            
            canciones = final_state.get("setlist_final", [])
            if not canciones:
                st.error("No se encontraron canciones o hubo un error en el proceso.")
            else:
                for i, c in enumerate(canciones, 1):
                    st.markdown(f"**{i}. {c['titulo']}** - {c['artista']}")
                    st.caption(f"BPM: {c.get('bpm', 'N/A')} | Key: {c.get('key', 'N/A')} | Género: {c['genero']}")
                
                st.divider()
                st.success(f"Archivo guardado en: `{final_state.get('archivo_guardado')}`")
                
                # Opción para descargar (leemos el archivo generado)
                archivo_path = final_state.get("archivo_guardado")
                if archivo_path and os.path.exists(archivo_path):
                    with open(archivo_path, "r") as f:
                        file_content = f.read()
                    st.download_button(
                        label="💾 Descargar .m3u",
                        data=file_content,
                        file_name=os.path.basename(archivo_path),
                        mime="audio/x-mpegurl"
                    )

        except Exception as e:
            st.error(f"Ocurrió un error: {e}")
            st.exception(e)

if __name__ == "__main__":
    # Workaround para running loops en Streamlit si fuera necesario, 
    # pero simple asyncio.run suele funcionar en script mode.
    pass
