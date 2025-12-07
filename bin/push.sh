#!/bin/bash

target=root@192.168.0.146
rsync -a ./core-* $target:~
