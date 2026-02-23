import streamlit as st
import subprocess
import sys

st.title("Subprocess Debugger")
st.write(f"Current stderr type: {type(sys.stderr)}")

try:
    st.write("Attempting subprocess.Popen with stderr=sys.stderr...")
    # This mimics what might happen inside mcp.client.stdio_client or anyio
    p = subprocess.Popen(
        [sys.executable, "-c", "print('hello from subprocess', file=sys.stderr)"], 
        stdin=subprocess.PIPE, 
        stdout=subprocess.PIPE, 
        stderr=sys.stderr 
    )
    st.write("Subprocess started successfully!")
    out, err = p.communicate()
    with open("repro_result.txt", "w") as f:
        f.write("Communication successful\n")
    
except Exception as e:
    with open("repro_result.txt", "w") as f:
        f.write(f"Caught exception: {e}\n")
