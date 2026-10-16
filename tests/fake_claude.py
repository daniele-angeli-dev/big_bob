"""Claude Code finto per i test: parla stream-json come `claude -p --input-format stream-json`."""
import json
import sys

sid = "sess-test"
print(json.dumps({"type": "system", "subtype": "init", "session_id": sid}), flush=True)
for line in sys.stdin:
    msg = json.loads(line)
    content = msg["message"]["content"]
    text = next(b["text"] for b in content if b["type"] == "text")
    has_img = any(b["type"] == "image" for b in content)
    if "[APPRENDIMENTO" in text:
        import time
        time.sleep(0.6)  # l'apprendimento richiede un po' di tempo: la chat deve aspettarlo
        print(json.dumps({"type": "assistant", "session_id": sid, "message": {"content": [
            {"type": "tool_use", "name": "mcp__origins__record_lesson",
             "input": {"lezione": "Dracula tiene Brides per il centro", "tipo": "mossa_avversaria"}}]}}), flush=True)
        print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "imparato",
                          "session_id": sid, "usage": {"output_tokens": 7}}), flush=True)
        continue
    print(json.dumps({"type": "assistant", "session_id": sid, "message": {"content": [
        {"type": "tool_use", "name": "mcp__origins__update_match", "input": {}}]}}), flush=True)
    if "analisi round" in text:
        ans = ("▶ Little John a destra, Marian al centro\nperché: chiudi la destra\n"
               "⚠ Brides of Dracula 41% · centro\n🎴 Marian 12%\nnota libera img=" + str(has_img))
    else:
        ans = "Risposta libera img=" + str(has_img) + (" segnalazioni=si" if "ha segnalato" in text else "")
    print(json.dumps({"type": "assistant", "session_id": sid, "message": {"content": [{"type": "text", "text": ans}]}}), flush=True)
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": ans, "session_id": sid,
                      "usage": {"output_tokens": 42}}), flush=True)
