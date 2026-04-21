#!/bin/bash

# waiting for 192.168.0.39
while ! ping -c 1 -W 1 192.168.0.39 >/dev/null 2>&1; do
    echo 'waiting for bpi'
    sleep 1
done

echo 'bpi ok'

# start core-cap & core-gos
# check and kill 
ssh root@192.168.0.39 "pgrep -f '\$HOME/core-cap' | xargs -r kill -9"
ssh root@192.168.0.39 "pgrep -f '\$HOME/core-gos' | xargs -r kill -9"

# strat core-cap
ssh root@192.168.0.39 "nohup ~/core-cap > ~/core-cap.log 2>&1 &"

sleep 1

# start core-gos
ssh root@192.168.0.39 "nohup ~/core-gos > ~/core-gos.log 2>&1 &"

sleep 1

# start navi
uv run main.py
