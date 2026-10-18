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
    if "[LETTORE" in text:
        if "[LETTORE · lato di Daniele]" in text:
            out = {"fase": "gioco", "turn": 5, "mana": 6, "my_hand": ["Marian", "Little John"],
                   "mie": {"sinistra": ["Friar Tuck 4/3", None], "centro": [None, None], "destra": [None, None]},
                   "my_barriers": [20, 8, 20], "my_reinforced": [False, False, False], "my_destroyed": 0,
                   "reveals_first": "avversario"}
        else:
            out = {"avv": {"sinistra": ["Bat 2/1", None], "centro": [None, None], "destra": [None, None]},
                   "opp_barriers": [12, 20, 31], "opp_reinforced": [False, False, True], "opp_destroyed": 1,
                   "opp_hand_size": 4, "opp_played_new": ["Bat"], "my_played_new": ["Friar Tuck"]}
        txt = "```json\n" + json.dumps(out) + "\n```"
        print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": txt,
                          "session_id": sid, "usage": {"output_tokens": 30}}), flush=True)
        continue
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
    if "[CRONOLOGIA" in text and "ti insegno" in text.lower():
        print(json.dumps({"type": "assistant", "session_id": sid, "message": {"content": [
            {"type": "tool_use", "name": "mcp__origins__record_lesson",
             "input": {"lezione": "Contro Dracula tieni Garlic per il centro", "tipo": "strategia",
                       "fonte": "Daniele"}}]}}), flush=True)
    if "analisi round" in text:
        ans = ("▶ Little John a destra, Marian al centro\nperché: chiudi la destra\n"
               "⚠ Brides of Dracula 41% · centro\n🎴 Marian 12%\nnota libera img=" + str(has_img)
               + (" letto=si" if "schermata già letta" in text and "RISULTATO DI update_match" in text else "")
               + (" recenti=si" if "Consigli dei round prima" in text else ""))
    else:
        ans = "Risposta libera img=" + str(has_img) + (" segnalazioni=si" if "ha segnalato" in text else "") \
            + (" seguito=si" if "[CRONOLOGIA · seguito]" in text else "") + ("\n❓ Perché?" if "[CRONOLOGIA]" in text else "")
    print(json.dumps({"type": "assistant", "session_id": sid, "message": {"content": [{"type": "text", "text": ans}]}}), flush=True)
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": ans, "session_id": sid,
                      "usage": {"output_tokens": 42}}), flush=True)
