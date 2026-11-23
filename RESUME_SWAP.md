# Paused swap run (critic/rewriter swap, Qwen vs Gemma)

Stopped 2026-11-11 (too heavy for the Mac). Still resumable with the steps below.
Progress: chains 0-5 (G/G, G/Q) at rounds 21-29 of 40; chains 6-8 (Q/G) not started.

To resume (two commands, Gemma server first):

    cd ~/poem-loop
    nohup bash experiments/gemma_server.sh > runs/gemma_server.log 2>&1 &
    # wait until: curl -s 127.0.0.1:8081/health  -> {"status":"ok"}
    nohup .venv/bin/python loop.py --resume runs/swap/2026-11-09_205748 >> runs/swap.out 2>&1 &

About 2.5 h left. The Qwen router on :8080 was left running.
