import json

file_path = 'c:/Users/sabax/OneDrive/Desktop/Trabajo_IA/Trabajos_IA/main copy.ipynb'

with open(file_path, 'r', encoding='utf-8') as f:
    nb = json.load(f)

# New Test Cell Content
new_test_source = [
    "# --- TEST EXTENDIDO: VARIOS ESCENARIOS ---\n",
    "def run_scenarios():\n",
    "    scenarios = [\n",
    "        (\"ESCENARIO 1: Solo Música\", \"Crea una canción de Jazz.\"),\n",
    "        (\"ESCENARIO 2: Solo Investigación\", \"Busca conciertos de Coldplay en 2024.\"),\n",
    "        (\"ESCENARIO 3: Completo (Inv+Mus+Ed)\", \"Busca conciertos de Taylor Swift, crea una canción sobre ella y mándame todo por email a test@test.com\")\n",
    "    ]\n",
    "    \n",
    "    for title, query in scenarios:\n",
    "        print(f\"\\n{'='*60}\\n{title}\\nQuery: '{query}'\\n{'='*60}\")\n",
    "        try:\n",
    "            state = {\"messages\": [HumanMessage(content=query)], \"concerts\": [], \"suno_audio_url\": \"\", \"formato_entrega\": \"local\", \"pdf_path\": \"\", \"user_email\": \"\", \"mp3_path\": \"\"}\n",
    "            \n",
    "            # Ejecutar Grafo\n",
    "            for chunk in app_completa.stream(state, stream_mode=\"updates\"):\n",
    "                for node, values in chunk.items():\n",
    "                    print(f\"   📍 Paso por nodo: {node}\")\n",
    "                    if node == 'router':\n",
    "                        print(f\"      Flags: Research={values.get('needs_research')}, Music={values.get('needs_music')}, Export={values.get('needs_export')}\")\n",
    "        except Exception as e:\n",
    "            print(f\"Error en escenario: {e}\")\n",
    "\n",
    "if __name__ == \"__main__\":\n",
    "    run_scenarios()\n"
]

# Find the old run_test cell and replace it
replaced = False
for cell in nb['cells']:
    if cell['cell_type'] == 'code':
        src = "".join(cell['source'])
        if "def run_test():" in src:
            cell['source'] = new_test_source
            replaced = True
            break

if not replaced:
    # Append if not found
    nb['cells'].append({
        "cell_type": "code",
        "execution_count": None,
        "id": "new_test_cell",
        "metadata": {},
        "outputs": [],
        "source": new_test_source
    })

with open(file_path, 'w', encoding='utf-8') as f:
    json.dump(nb, f, indent=1)
print("Updated run_test with scenarios.")
