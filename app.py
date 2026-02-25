import asyncio, os, time
import streamlit as st
from agent import run_agent


def _run_agent_safely(genero: str, vibe: str, vlc: bool):
    """
    Ejecuta el agente MCP de forma segura dentro de Streamlit.
    Crea un event loop nuevo para evitar conflictos con el loop de Streamlit.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(run_agent(genero, vibe, vlc))
    finally:
        loop.close()

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
col1, col2, col3 = st.columns([2,2,1])
with col1:
    genero = st.text_input("Género musical", placeholder="Ej: Rock, Pop, Jazz, Techno, K-Pop...")
with col2:
    vibe = st.text_input("Define el Vibe / Objetivo", placeholder="Ej: High Energy Workout, Chill Sunday...")
with col3:
    st.write("")
    st.write("")
    vlc = st.toggle("VLC Autoplay", value=True, help="Si está activado," \
    " el grafo se ejecuta en modo reproducción.")

# Botón de acción
if st.button("🎛️ Generar Setlist", type="primary"):
    if not genero or not vibe:
        st.warning("Por favor escribe un género y un vibe para tu playlist.")
    else:
        status_text = st.empty()
        status_text.write("🚀 Iniciando agente... conectando a servidor MCP...")
        
        try:
            # Ejecutar el agente de forma segura (parcheando stderr para MCP stdio)
            final_state = _run_agent_safely(genero, vibe, vlc)
            # Mostrar resultados
            status_text.success("¡Setlist generado con éxito!")
            
            st.subheader("🎼 Tu Setlist Curado")
            
            canciones = final_state.get("setlist_final", [])
            if not canciones:
                st.error("No se encontraron canciones o hubo un error en el proceso.")
            else:
                for i, c in enumerate(canciones, 1):
                    col_info, col_audio = st.columns([3, 2])
                    with col_info:
                        st.markdown(f"**{i}. {c['titulo']}** - {c['artista']}")
                        st.caption(f"BPM: {c.get('bpm', 'N/A')} | Key: {c.get('key', 'N/A')} | Género: {c['genero']}")
                    with col_audio:
                        ruta_local = c.get('ruta_local', '')
                        if ruta_local and os.path.exists(ruta_local):
                            st.audio(ruta_local, format="audio/mp4")
                        else:
                            preview_url = c.get('preview_url', '')
                            if preview_url:
                                st.audio(preview_url, format="audio/mp4")
                            else:
                                st.caption("🔇 Sin preview disponible")
                        
                        letra = c.get('letra', '')
                        if letra:
                            with st.expander("Ver Letra (Generada con Whisper)"):
                                st.text(letra)
                
                st.divider()
                st.success(f"Archivo guardado en: `{final_state.get('archivo_guardado')}`")
                
                import zipfile
                import io

                archivo_path = final_state.get("archivo_guardado")
                if archivo_path and os.path.exists(archivo_path):
                    # Crear archivo ZIP en memoria
                    zip_buffer = io.BytesIO()
                    
                    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                        # 1. Añadir el archivo .m3u
                        zip_file.write(archivo_path, os.path.basename(archivo_path))
                        
                        # 2. Añadir todas las canciones y letras de la lista
                        for c in canciones:
                            ruta_local = c.get('ruta_local', '')
                            if ruta_local and os.path.exists(ruta_local):
                                # Añadir audio
                                zip_file.write(ruta_local, os.path.basename(ruta_local))
                                
                                # Intentar añadir el archivo de subtítulos .srt
                                base_name, _ = os.path.splitext(ruta_local)
                                ruta_srt = base_name + ".srt"
                                if os.path.exists(ruta_srt):
                                    zip_file.write(ruta_srt, os.path.basename(ruta_srt))
                    
                    # Preparar buffer para descarga
                    zip_buffer.seek(0)
                    nombre_zip = os.path.basename(archivo_path).replace('.m3u', '.zip')
                    
                    st.download_button(
                        label=" Descargar Setlist Completo (.ZIP)",
                        data=zip_buffer.getvalue(),
                        file_name=nombre_zip,
                        mime="application/zip",
                        help="Descarga el M3U junto con todos los audios y letras generadas para abrir en VLC."
                    )


        except Exception as e:
            st.error(f"Ocurrió un error: {e}")
            st.exception(e)

if __name__ == "__main__":
    # Workaround para running loops en Streamlit si fuera necesario, 
    # pero simple asyncio.run suele funcionar en script mode.
    pass
