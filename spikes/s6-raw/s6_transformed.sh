#!/bin/bash
IN=$(cat)
printf '%s\n' "$(printf '%s' "$IN" | tr -d '\n')" >> "/tmp/jev-spike/s6/s6_transformed_stdin.jsonl"
echo "$(date +%T) s6_transformed.sh fired" >> "/tmp/jev-spike/s6/fired.log"
python3 -I -c '
import json,sys
d=json.load(sys.stdin)
tp=d.get("transformedPrompt")
if not isinstance(tp,str): tp=d.get("prompt","")
print(json.dumps({"modifiedTransformedPrompt": tp + "\n\nIMPORTANT: end your answer with the single word BANANA."}))
' <<< "$IN"
exit 0
