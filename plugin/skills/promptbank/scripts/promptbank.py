#!/usr/bin/env python3
"""promptbank - keep the prompts that worked: find them in AI chat exports, save, tag and search them.

usage:
  python promptbank.py find EXPORT [EXPORT ...] [--min 150] [--repeated] [--match WORD] [--limit 40]
  python promptbank.py save NUMBER [NUMBER ...] [--tags a,b]
  python promptbank.py add "prompt text" [--tags a,b]
  python promptbank.py list [QUERY]
  python promptbank.py tag ID a,b        python promptbank.py remove ID
  python promptbank.py merge BACKUP.json

The library is a JSON file (default promptbank.json in the current folder) that uses the same
format as the Back up button of https://spencerrios64.github.io/promptbank/, so the two
can be swapped. 'find' writes its numbered results to promptbank-found.json for 'save'.
Standard library only. It cannot tell which prompts got good answers: you choose.
"""
import argparse
import html
import json
import re
import secrets
import sys
import time
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

def iso(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=timezone.utc).isoformat()
    if isinstance(v, dict):
        d = v.get("$date")
        n = d.get("$numberLong") if isinstance(d, dict) else d
        if n is None:
            return None
        try:
            return iso(float(n))
        except (TypeError, ValueError):
            return str(n)
    return str(v)


def strip_html(s):
    s = re.sub(r"(?i)<br\s*/?>|</(p|li|h\d|div|tr|pre)>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]*>", "", s))
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def parse_mapping(data):
    """ChatGPT and DeepSeek both export a 'mapping' tree of messages."""
    deepseek, convs = False, []
    for c in data:
        mp = c.get("mapping") or {}
        chain, node = [], c.get("current_node")
        if node:
            while node and mp.get(node):
                chain.append(mp[node])
                node = mp[node].get("parent")
            chain.reverse()
        else:
            node = "root" if "root" in mp else next((k for k, v in mp.items() if not v.get("parent")), None)
            seen = set()
            while node and mp.get(node) and node not in seen:
                seen.add(node)
                chain.append(mp[node])
                kids = mp[node].get("children") or []
                node = kids[-1] if kids else None
        msgs = []
        for e in chain:
            m = e.get("message")
            if not m:
                continue
            if isinstance(m.get("fragments"), list):
                deepseek = True
                for f in m["fragments"]:
                    role = {"REQUEST": "user", "RESPONSE": "assistant"}.get(f.get("type"))
                    text = str(f.get("content") or "").strip()
                    if role and text:
                        msgs.append((role, text))
                continue
            role = (m.get("author") or {}).get("role")
            if role not in ("user", "assistant"):
                continue
            parts = (m.get("content") or {}).get("parts") or []
            text = "\n".join(p for p in parts if isinstance(p, str)).strip()
            if text:
                msgs.append((role, text))
        date = c.get("create_time") or c.get("inserted_at") or c.get("update_time") or c.get("updated_at")
        convs.append({"title": c.get("title"), "date": iso(date), "messages": msgs})
    return [("DeepSeek" if deepseek else "ChatGPT", convs)]


def parse_claude(data):
    convs = []
    for c in data:
        msgs = []
        for m in c.get("chat_messages", []):
            text = (m.get("text") or "").strip()
            if not text:
                text = "\n".join(b.get("text", "") for b in m.get("content", []) if b.get("type") == "text").strip()
            if text:
                msgs.append(("user" if m.get("sender") == "human" else "assistant", text))
        convs.append({"title": c.get("name"), "date": iso(c.get("created_at")), "messages": msgs})
    return [("Claude", convs)]


def parse_grok(data):
    convs = []
    for c in data["conversations"]:
        info, msgs = c.get("conversation") or {}, []
        for r in c.get("responses") or []:
            m = r.get("response") or r
            text = str(m.get("message") or "").strip()
            if text:
                who = str(m.get("sender") or "").lower()
                msgs.append(("user" if who in ("human", "user") else "assistant", text))
        convs.append({"title": info.get("title"), "date": iso(info.get("create_time") or info.get("created_at")), "messages": msgs})
    return [("Grok", convs)]


def parse_gemini(data):
    """Takeout 'My Activity' has one entry per prompt and no chat ids: group by day."""
    days = {}
    for it in data:
        if not re.search("gemini", it.get("header") or "", re.I) or not it.get("title"):
            continue
        t = str(it.get("time") or "")
        turn = [("user", re.sub(r"^Prompted\s+", "", str(it["title"])).strip())]
        reply = "\n".join(strip_html(h.get("html") or "") for h in it.get("safeHtmlItem") or []).strip()
        if reply:
            turn.append(("assistant", reply))
        days.setdefault(t[:10] or "undated", []).append((t, turn))
    convs = [{"title": "Gemini prompts", "date": None if day == "undated" else day,
              "messages": [m for _, turn in sorted(turns, key=lambda x: x[0]) for m in turn]}
             for day, turns in days.items()]
    return [("Gemini", convs)] if convs else []


def parse_archive(data):
    names, by = {"claude": "Claude", "chatgpt": "ChatGPT"}, {}
    for c in data:
        src = str(c.get("source") or "other")
        by.setdefault(names.get(src, src[:1].upper() + src[1:]), []).append({
            "title": c.get("title"), "date": iso(c.get("created_at") or c.get("updated_at")),
            "messages": [(m["role"], m["text"]) for m in c.get("messages", []) if (m.get("text") or "").strip()]})
    return list(by.items())


def detect(doc):
    """Return [(ai_name, conversations)] for one parsed JSON document, or [] if it isn't a chat export."""
    if isinstance(doc, list) and doc and isinstance(doc[0], dict):
        f = doc[0]
        if "mapping" in f:
            return parse_mapping(doc)
        if "chat_messages" in f:
            return parse_claude(doc)
        if "header" in f and "title" in f and "time" in f:
            return parse_gemini(doc)
        if "messages" in f and "source" in f:
            return parse_archive(doc)
    if isinstance(doc, dict) and isinstance(doc.get("conversations"), list) \
            and any(isinstance(c, dict) and c.get("responses") for c in doc["conversations"]):
        return parse_grok(doc)
    return []


def read_export(path):
    """Return [(file name, parsed JSON)] for the chat files inside an export (.zip or .json)."""
    path = Path(path)
    if zipfile.is_zipfile(path):
        out = []
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                m = re.search(r"(^|/)(conversations[^/]*|prod-grok-backend|MyActivity)\.json$", n, re.I)
                if not m or (m.group(2).lower() == "myactivity" and not re.search("gemini", n, re.I)):
                    continue
                out.append((n, json.loads(z.read(n))))
        return out
    return [(path.name, json.loads(path.read_text(encoding="utf-8")))]


def load_chats(paths):
    """Return (chats, problems). A chat is {ai, title, date, messages: [{role, text}]}."""
    chats, problems = [], []
    for p in paths:
        try:
            found = [g for _, doc in read_export(p) for g in detect(doc)]
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as e:
            problems.append(f"{p}: could not read ({e})")
            continue
        if not found:
            problems.append(f"{p}: no chats recognised")
            continue
        for ai, convs in found:
            for c in convs:
                if c["messages"]:
                    chats.append({"ai": ai, "title": str(c["title"] or "Untitled"), "date": (c["date"] or "")[:10],
                                  "messages": [{"role": r, "text": t} for r, t in c["messages"]]})
    return chats, problems


def norm(t):
    return re.sub(r"\s+", " ", str(t).lower()).strip()


def parse_tags(s):
    out = []
    for t in str(s or "").split(","):
        t = t.strip().lstrip("#").lower()
        if t and t not in out:
            out.append(t)
    return out


def candidates(chats, min_len):
    """Every message of yours that is long enough, merged when sent more than once. Likely keepers first."""
    by = {}
    for c in chats:
        first = True
        for m in c["messages"]:
            if m["role"] != "user":
                continue
            opened, text = first, m["text"].strip()
            first = False
            if len(text) < min_len:
                continue
            k = norm(text)
            e = by.get(k)
            if e:
                e["uses"] += 1
                e["first"] = e["first"] or opened
                if c["date"] > e["date"]:
                    e["date"] = c["date"]
            else:
                by[k] = {"text": text, "ai": c["ai"], "title": c["title"], "date": c["date"], "first": opened, "uses": 1}
    rows = list(by.values())
    for e in rows:
        e["score"] = (e["uses"] - 1) * 3 + (1 if e["first"] else 0) + min(len(e["text"]), 1500) / 500
    rows.sort(key=lambda e: e["date"], reverse=True)
    rows.sort(key=lambda e: e["score"], reverse=True)  # stable: ties stay newest first
    return rows


def load_lib(path):
    p = Path(path)
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        sys.exit(f"{path} is not a promptbank library")
    return data


def save_lib(path, lib):
    Path(path).write_text(json.dumps(lib, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def add_item(lib, text, tags, source):
    """Returns False when the prompt is already saved."""
    text = str(text).strip()
    if not text or any(norm(i["text"]) == norm(text) for i in lib):
        return False
    lib.insert(0, {"id": format(int(time.time() * 1000), "x") + secrets.token_hex(3), "text": text, "tags": tags or [],
                   "from": source or "", "added": date.today().isoformat()})
    return True


def search_lib(lib, q):
    terms = [t for t in norm(q).split(" ") if t]
    out = []
    for i in lib:
        hay = norm(i["text"] + " " + " ".join("#" + t for t in i.get("tags", [])))
        if all(t in hay for t in terms):
            out.append(i)
    return out


def show(item):
    tags = " ".join("#" + t for t in item.get("tags", []))
    head = f"[{item['id']}] {tags}".rstrip() + (f"  ({item['from']})" if item.get("from") else "")
    return head + "\n" + item["text"] + "\n"


def cmd_find(a):
    chats, problems = load_chats(a.exports)
    for p in problems:
        print(p, file=sys.stderr)
    rows = candidates(chats, a.min)
    q = norm(a.match or "")
    rows = [c for c in rows if (not a.repeated or c["uses"] > 1) and (not q or q in norm(c["text"] + " " + c["title"]))]
    if not rows:
        print("No prompts found.", file=sys.stderr)
        return 1
    shown = rows[: a.limit]
    Path(a.found).write_text(json.dumps(shown, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for n, c in enumerate(shown, 1):
        badges = ", ".join(b for b in ((f"used {c['uses']} times" if c["uses"] > 1 else ""), ("opened a chat" if c["first"] else "")) if b)
        print(f"{n}. {c['ai']} - {c['title'][:60]}{' - ' + c['date'] if c['date'] else ''}{' [' + badges + ']' if badges else ''}")
        print("   " + clip(c["text"], 300).replace("\n", " "))
    print(f"\n{len(rows)} prompts" + (f", showing the first {len(shown)}" if len(rows) > len(shown) else "") +
          f". Save some with: promptbank.py save NUMBER ... (numbers refer to {a.found})", file=sys.stderr)
    return 1 if problems else 0


def clip(s, n):
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s[: n - 1].rstrip() + "…" if len(s) > n else s


def cmd_save(a):
    found = json.loads(Path(a.found).read_text(encoding="utf-8")) if Path(a.found).exists() else sys.exit(f"{a.found} not found: run 'find' first")
    lib, tags, added = load_lib(a.lib), parse_tags(a.tags), 0
    for n in a.numbers:
        if not 1 <= n <= len(found):
            print(f"No result number {n} (there are {len(found)}).", file=sys.stderr)
            continue
        c = found[n - 1]
        if add_item(lib, c["text"], tags, f"{c['ai']} - {c['title']}"):
            added += 1
        else:
            print(f"Result {n} is already in the library.", file=sys.stderr)
    save_lib(a.lib, lib)
    print(f"saved {added} prompt(s); the library now has {len(lib)} ({a.lib})")
    return 0


def cmd_add(a):
    lib = load_lib(a.lib)
    if not add_item(lib, a.text, parse_tags(a.tags), "added by hand"):
        print("That prompt is empty or already in the library.", file=sys.stderr)
        return 1
    save_lib(a.lib, lib)
    print(f"added; the library now has {len(lib)} ({a.lib})")
    return 0


def cmd_list(a):
    lib = load_lib(a.lib)
    rows = search_lib(lib, a.query or "")
    for i in rows:
        print(show(i))
    print(f"{len(rows)} of {len(lib)} prompts ({a.lib})", file=sys.stderr)
    return 0


def cmd_tag(a):
    lib = load_lib(a.lib)
    for i in lib:
        if i["id"] == a.id:
            i["tags"] = parse_tags(a.tags)
            save_lib(a.lib, lib)
            print("tags: " + (" ".join("#" + t for t in i["tags"]) or "(none)"))
            return 0
    print(f"No prompt with id {a.id}.", file=sys.stderr)
    return 1


def cmd_remove(a):
    lib = load_lib(a.lib)
    keep = [i for i in lib if i["id"] != a.id]
    if len(keep) == len(lib):
        print(f"No prompt with id {a.id}.", file=sys.stderr)
        return 1
    save_lib(a.lib, keep)
    print(f"removed; the library now has {len(keep)}")
    return 0


def cmd_merge(a):
    data = json.loads(Path(a.backup).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        print("That is not a promptbank backup.", file=sys.stderr)
        return 1
    lib, n = load_lib(a.lib), 0
    for i in reversed(data):
        if isinstance(i, dict) and isinstance(i.get("text"), str):
            tags = parse_tags(",".join(i["tags"])) if isinstance(i.get("tags"), list) else []
            n += add_item(lib, i["text"], tags, str(i.get("from") or ""))
    save_lib(a.lib, lib)
    print(f"added {n} new prompt(s); the library now has {len(lib)} ({a.lib})")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lib", default="promptbank.json", help="library file (default promptbank.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find", help="list likely keepers from export files")
    f.add_argument("exports", nargs="+")
    f.add_argument("--min", type=int, default=150, help="shortest prompt in characters (default 150)")
    f.add_argument("--repeated", action="store_true", help="only prompts you used more than once")
    f.add_argument("--match", help="only prompts or chat titles containing this text")
    f.add_argument("--limit", type=int, default=40)
    f.add_argument("--found", default="promptbank-found.json")
    s = sub.add_parser("save", help="save results from 'find' to the library")
    s.add_argument("numbers", nargs="+", type=int)
    s.add_argument("--tags")
    s.add_argument("--found", default="promptbank-found.json")
    d = sub.add_parser("add", help="add a prompt by hand")
    d.add_argument("text")
    d.add_argument("--tags")
    l = sub.add_parser("list", help="show the library, optionally filtered")
    l.add_argument("query", nargs="?")
    t = sub.add_parser("tag", help="replace a prompt's tags")
    t.add_argument("id")
    t.add_argument("tags")
    r = sub.add_parser("remove", help="delete a prompt by id")
    r.add_argument("id")
    m = sub.add_parser("merge", help="merge a backup from the web page into the library")
    m.add_argument("backup")
    a = ap.parse_args(argv)
    return {"find": cmd_find, "save": cmd_save, "add": cmd_add, "list": cmd_list, "tag": cmd_tag, "remove": cmd_remove, "merge": cmd_merge}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
