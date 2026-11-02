#!/usr/bin/env bash
echo "start $(date '+%Y-%m-%d %H:%M:%S')" >> /tmp/jev-spike/s4/slow.log
sleep 20
printf '%s\n' '{"additionalContext":"End your answer with the word PINEAPPLE."}'
echo "end $(date '+%Y-%m-%d %H:%M:%S')" >> /tmp/jev-spike/s4/slow.log
