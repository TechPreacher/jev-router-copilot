#!/usr/bin/env bash
# dump stdin, then rewrite the submitted prompt
input=$(cat)
printf '%s\n' "$input" >> "/tmp/jev-spike/s1/s1_submitted_stdin.jsonl"
python3 -I - "$input" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
prompt = d.get("prompt", "")
print(json.dumps({"modifiedPrompt": prompt + "\n\nIMPORTANT: end your answer with the single word MANGO.", "additionalContext": "End your answer with the word MANGO."}))
PY
