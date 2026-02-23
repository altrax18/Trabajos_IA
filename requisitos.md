Práctica MCP
🎯 Objetivo general
Que los alumnos diseñen, implementen e integren un ecosistema MCP completo, compuesto por:
Uno o varios servidores MCP propios
Tools basadas en LLMs
Integración con APIs externas
Uso de diferentes transportes MCP
Consumo desde clientes MCP reales
Uso dentro de agentes
Integración con proveedores MCP externos
UI funcional para usuarios finales
Arquitectura mínima requerida
┌────────────┐
│ UI (Web) │ ← Gradio / Streamlit
└─────┬──────┘
│
┌─────▼──────┐
│ MCP Client │ ← Claude Code / Cherry / VS Code└─────┬──────┘
│
┌─────▼──────────────────────────┐
│ MCP Server(s) │
│ - Tools │
│ - Resources │
│ - Prompts │
│ - OAuth2 │
└─────┬──────────┬───────────────┘
│ │
┌─────▼──────┐ ┌─▼──────────────┐
│ APIs ext. │ │ MCP terceros │
│ (Spotify, │ │ (Zapier, Make, │
│ TMDB…) │ │ Cloudflare…) │
└────────────┘ └────────────────┘
✅ Requisitos obligatorios (core)
1️⃣ Servidor MCP propio
Implementado en Python
Al menos 2 tools:
🔧 Tool que consuma una API externa
🧠 Tool que use un LLM
2️⃣ Uso de transportes MCP
stdio (para uso local)
streamablehttp (para despliegue remoto)
3️⃣ Pruebas con clientes MCP
Probar el servidor con:
✅ MCP Inspector
✅ Al menos un cliente MCP real
Claude Code
Cherry Studio
VS Code MCP extension
4️⃣ Integración con agentes
Usar el servidor MCP dentro de:
LangGraph Agent
o
Cualquier otro
📌 El agente debe:
Usar al menos una tool MCP
Resolver una tarea compleja (multi-step)
5️⃣ UI para usuario final
Construida con:
Gradio o Streamlit
🔐 Seguridad y despliegue
6️⃣ Autenticación OAuth2 (opcional)

7️⃣ Integración con FastAPI (opcional)
El MCP Server debe:
Estar integrado en un servidor REST
Compartir autenticación / estado
Exponer endpoints auxiliares
🌐 Ecosistema externo
8️⃣ Uso de MCPs de terceros
Integrar al menos uno:
Make MCP Server
Zapier MCP
Cloudflare MCP
Otro MCP público

Para probar stdio

Arrancas el servidor SIN http:

python server.py

Eso activa:

mcp.run(transport="stdio")

server

Luego lo pruebas con:

MCP Inspector (modo stdio)

O tu agente LangGraph (que ya lo usa)

En tu agent.py usas:

StdioServerParameters(...)

agent

Eso confirma que tu agente usa stdio.

🔹 Para probar streamable-http

Arrancas:

python server.py http

Eso activa:

mcp.run(transport="streamable-http")

server

Luego en Cherry configuras:

Type: Streamable HTTP
URL: http://127.0.0.1:8000/mcp
