#!/usr/bin/env bash
# dump stdin, then rewrite the transformed prompt
input=$(cat)
printf '%s\n' "$input" >> "/tmp/jev-spike/s1/s1_stdin.jsonl"
python3 -I - "$input" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
tp = d.get("transformedPrompt") or d.get("transformed_prompt") or d.get("prompt") or ""
if not isinstance(tp, str):
    tp = json.dumps(tp)
print(json.dumps({"modifiedTransformedPrompt": tp + "\n\nIMPORTANT: end your answer with the single word BANANA."}))
PY
