#!/bin/bash
# Second model for the critic/rewriter swap, on its own small server (the router's 131k context would not fit next to Qwen).
exec /Users/ozkilim/.local/opt/llama.cpp/llama-server --host 127.0.0.1 --port 8081 --jinja \
  --model /Users/ozkilim/models/gemma-3-12b-it-Q4_K_M.gguf --alias gemma-3-12b-it \
  -c 32768 -np 4 -fa on -ngl 999
