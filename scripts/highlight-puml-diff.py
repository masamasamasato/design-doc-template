#!/usr/bin/env python3
"""PRで足した・変えた行だけを赤くした .puml を作る。PRコメント用。

使い方:
  scripts/highlight-puml-diff.py --base REV [--summary FILE] [--out-dir DIR] file.puml ...

- REV（比較元のコミット）の .puml と、作業ツリーの .puml を行ごとに比べる。
- 足した・変えた行に PlantUML の色指定を付ける。
  --out-dir が無いときは、作業ツリーのファイルを書き換える（Actions の中だけで使う）。
- 色を付けられない種類の行は、そのまま残す（図を壊さない）。
- 消した行・変える前の行・色を付けられなかった行を、--summary の JSON に書く。
- 比較元に無いファイル（新しい図）は、色を付けない。

リポジトリにコミットする SVG（plantuml-svg.yml）には使わない。
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field

FILL = "#FFD6D6"
STYLE = f"{FILL};line:red;line.bold"  # 枠も赤くできる種類に使う
ARROW = "#red,bold"

# 区切りで終わるアクティビティ。;|<>/]} のどれか
ACTIVITY_END = re.compile(r"[;|<>/\]}]\s*$")
COND = re.compile(r"^(\s*)(?:#[\w]+\s*:\s*)?(if|elseif|while|repeat\s+while|switch)\b\s*\(")
NOTE = re.compile(r"^\s*(?:floating\s+)?(?:r|h)?note\b", re.IGNORECASE)
END_NOTE = re.compile(r"^\s*end\s*(?:r|h)?note\b", re.IGNORECASE)
ACT_ARROW = re.compile(r"^(\s*)(-+)(-?>)(\s*)(.*)$")
LEGACY_COLOR = re.compile(r"^(\s*)#[\w]+\s*:")  # #pink:if ( … の色。: ごと外す
LEGACY_ACT = re.compile(r"^(\s*)#[\w]+\s*(?=:)")  # #pink :処理; の色。: は残す

SEQ_DECL = {
    "participant", "actor", "boundary", "control", "entity", "database",
    "collections", "queue",
}
BOX_DECL = {
    "class", "interface", "abstract", "enum", "annotation", "component",
    "rectangle", "node", "cloud", "folder", "frame", "package", "usecase",
    "state", "object", "artifact", "card", "file", "storage", "agent", "stack",
    "hexagon", "person", "circle", "protocol", "struct", "exception", "map", "json",
}
# 中身の行が変わったら、宣言の行を赤くする（クラスの中身など）
MEMBER_CONTAINERS = {
    "class", "interface", "abstract", "enum", "annotation", "object", "struct",
    "protocol", "exception", "entity", "map", "json",
}
KEYWORDS = SEQ_DECL | BOX_DECL | {
    "if", "else", "elseif", "endif", "while", "endwhile", "repeat", "switch",
    "case", "endswitch", "fork", "end", "start", "stop", "kill", "detach",
    "note", "title", "skinparam", "hide", "show", "left", "top", "alt", "opt",
    "loop", "group", "par", "break", "critical", "ref", "activate",
    "deactivate", "destroy", "return", "autonumber", "partition", "legend",
    "header", "footer", "caption", "newpage", "box", "split", "together",
}
DECL = re.compile(r"^(\s*)(abstract\s+class|[a-z]+)\b(.*?)(\s*\{\s*)?$", re.IGNORECASE)
# 左の名前、矢印、右側。矢印に [ や向き（up など）があるときは触らない。
LINK = re.compile(
    r"^(\s*)"
    r"(\"[^\"]*\"|\[[^\]]*\]|\(\*?\)|[\w\u0080-\uffff.:()*]+?)"
    r"(\s*)"
    r"((?:<<|<\||<|\*|o|x|\\\\|\\|//|/)?)"
    r"(-+|\.+)"
    r"((?:>>|\|>|>|\*|o|x|\\\\|\\|//|/)?)"
    r"(\s*)(.*)$"
)


@dataclass
class Stmt:
    kind: str  # activity / cond / note / act_arrow / link / decl / none
    start: int
    end: int
    container: int | None = None  # 中身の行なら、色を付ける宣言の行


@dataclass
class FileResult:
    path: str
    status: str  # new / changed / same
    colored: list[str] = field(default_factory=list)
    uncolored: list[str] = field(default_factory=list)
    changed: list[list[str]] = field(default_factory=list)  # [前, 後]
    removed: list[str] = field(default_factory=list)


def is_blank_or_comment(line: str) -> bool:
    s = line.strip()
    return not s or s.startswith("'") or s.startswith("/'")


def first_word(line: str) -> str:
    m = re.match(r"\s*([A-Za-z]+)", line)
    return m.group(1).lower() if m else ""


def parse(lines: list[str]) -> list[Stmt]:
    """行ごとに、どの文に属するかを返す。"""
    out: list[Stmt | None] = [None] * len(lines)
    i = 0
    containers: list[int | None] = []  # { } の入れ子。色を付ける宣言の行、または None
    in_block_comment = False
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if in_block_comment:
            out[i] = Stmt("none", i, i)
            if "'/" in s:
                in_block_comment = False
            i += 1
            continue
        if s.startswith("/'"):
            out[i] = Stmt("none", i, i)
            in_block_comment = "'/" not in s[2:]
            i += 1
            continue
        container = next((c for c in reversed(containers) if c is not None), None) if containers else None
        inner = containers and containers[-1] is not None
        if inner:
            # クラスなどの中身。閉じ括弧までは中身として扱う
            if s.startswith("}"):
                containers.pop()
            elif s.endswith("{"):
                containers.append(containers[-1])
            out[i] = Stmt("none", i, i, container)
            i += 1
            continue
        if s.startswith("}"):
            if containers:
                containers.pop()
            out[i] = Stmt("none", i, i)
            i += 1
            continue
        # 複数行のノート
        if NOTE.match(line) and ":" not in line.split("note", 1)[-1] and not re.search(r'"\s*as\s+\w+', line):
            j = i + 1
            while j < len(lines) and not END_NOTE.match(lines[j]):
                j += 1
            if j < len(lines):
                for k in range(i, j + 1):
                    out[k] = Stmt("note", i, i)
                i = j + 1
                continue
        if NOTE.match(line):
            out[i] = Stmt("note", i, i)
            i += 1
            continue
        # アクティビティ（複数行もある）
        body = LEGACY_ACT.sub(r"\1", line)
        if body.lstrip().startswith(":"):
            j = i
            while j < len(lines) and not ACTIVITY_END.search(re.sub(r"\s*<<[^>]*>>\s*$", "", lines[j])):
                j += 1
            if j >= len(lines):
                j = i
            for k in range(i, j + 1):
                out[k] = Stmt("activity", i, j)
            i = j + 1
            continue
        if COND.match(line):
            out[i] = Stmt("cond", i, i)
            i += 1
            continue
        if ACT_ARROW.match(line):
            out[i] = Stmt("act_arrow", i, i)
            i += 1
            continue
        word = first_word(line)
        if word in SEQ_DECL | BOX_DECL or s.lower().startswith("abstract class"):
            out[i] = Stmt("decl", i, i)
            if s.endswith("{"):
                containers.append(i if word in MEMBER_CONTAINERS else None)
            i += 1
            continue
        if s.endswith("{"):
            containers.append(None)
        if word not in KEYWORDS and LINK.match(line) and link_ok(LINK.match(line)):
            out[i] = Stmt("link", i, i)
        else:
            out[i] = Stmt("none", i, i)
        i += 1
    return [o if o is not None else Stmt("none", n, n) for n, o in enumerate(out)]


def link_ok(m: re.Match) -> bool:
    left_head, body, right_head = m.group(4), m.group(5), m.group(6)
    if not m.group(8).strip():
        return False  # 右に相手が無い（... など）
    if left_head or right_head:
        return True
    return len(body) >= 2  # A -- B / A .. B


def color_activity_end(line: str) -> str | None:
    if re.search(r"<<[^>]*>>\s*$", line):
        if re.search(r"<<\s*#[^>]*>>\s*$", line):
            return re.sub(r"<<\s*#[^>]*>>\s*$", f"<<{STYLE}>>", line)
        return None  # <<input>> などの形の指定は触らない
    return line.rstrip() + f" <<{STYLE}>>"


def color_line(stmt: Stmt, lines: list[str], target: int) -> str | None:
    line = lines[target]
    if stmt.kind == "activity":
        return color_activity_end(line)
    if stmt.kind == "cond":
        line = LEGACY_COLOR.sub(r"\1", line)
        return color_activity_end(line)
    if stmt.kind == "note":
        m = re.match(r"^(\s*(?:floating\s+)?\w*note\b)(.*)$", line, re.IGNORECASE)
        if not m:
            return None
        head, rest = m.group(1), m.group(2)
        if ":" in rest:
            pos, text = rest.split(":", 1)
            pos = re.sub(r"\s+#[\w]+\s*$", "", pos)
            return f"{head}{pos.rstrip()} {FILL}:{text}"
        rest = re.sub(r"\s+#[\w]+\s*$", "", rest)
        return f"{head}{rest.rstrip()} {FILL}"
    if stmt.kind == "act_arrow":
        m = ACT_ARROW.match(line)
        assert m
        indent, dashes, tip, sp, label = m.groups()
        label = label.strip()
        if label and label not in {";"} and label.endswith(";"):
            label = f"<color:red>{label}"
        # アクティビティ図の矢印は -[色]-> の形しか通らない
        return f"{indent}-[{ARROW}]->{(' ' + label) if label else ''}"
    if stmt.kind == "link":
        m = LINK.match(line)
        if not m:
            return None
        indent, left, sp1, lh, body, rh, sp2, rest = m.groups()
        # 点線（..>）は bold を付けると実線になるため、dashed を付ける
        style = "#red,dashed" if body.startswith(".") else ARROW
        arrow = f"{lh}{body[0]}[{style}]{body[1:]}{rh}"
        # ラベル（右側の最初の : より後ろ）も赤くする
        if ":" in rest and not rest.lstrip().startswith(":"):
            target_part, label = rest.split(":", 1)
            if label.strip():
                rest = f"{target_part}: <color:red>{label.strip()}"
        return f"{indent}{left}{sp1}{arrow}{sp2 or ' '}{rest}"
    if stmt.kind == "decl":
        m = DECL.match(line)
        if not m:
            return None
        indent, word, rest, brace = m.groups()
        w = word.lower()
        if re.search(r'^[^"]*(?:"[^"]*"[^"]*)*:', rest):
            return None  # state X : 説明 などは触らない
        rest = re.sub(r"\s+#[\w]+(?:;[^\s{]*)?\s*$", "", rest)
        color = FILL if w in SEQ_DECL else STYLE
        return f"{indent}{word}{rest.rstrip()} {color}{(' ' + brace.strip()) if brace else ''}"
    return None


def git_show(rev: str, path: str) -> str | None:
    try:
        return subprocess.run(
            ["git", "show", f"{rev}:{path}"], check=True, capture_output=True
        ).stdout.decode("utf-8")
    except subprocess.CalledProcessError:
        return None


def deleted_files(base: str) -> list[str]:
    # リネーム検出はしない。消した図と新しい図が似ていても、別々に扱う
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "diff", "--no-renames", "--name-only", "--diff-filter=D", base, "--", "*.puml", "*.plantuml"],
        check=True, capture_output=True, text=True,
    ).stdout
    return [p for p in out.splitlines() if p.strip()]


def norm(line: str) -> str:
    """空白をそろえた行。比較と相殺に使う"""
    return " ".join(line.split())


def highlight(base_text: str, head_text: str, res: FileResult) -> str:
    base = base_text.splitlines()
    head = head_text.splitlines()
    base_n = [norm(l) for l in base]
    head_n = [norm(l) for l in head]
    # 同じ文が両方に残る行は、場所が動いただけ。足した・消した・変えたにしない。
    # 文ごとの数の差（多重集合の差）だけを、本当に足した・消した行として扱う。
    base_count = Counter(t for t, l in zip(base_n, base) if not is_blank_or_comment(l))
    head_count = Counter(t for t, l in zip(head_n, head) if not is_blank_or_comment(l))
    add_left = head_count - base_count
    rm_left = base_count - head_count
    sm = difflib.SequenceMatcher(None, base_n, head_n, autojunk=False)
    touched: list[int] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        new_idx: list[int] = []
        for j in range(j1, j2):
            if is_blank_or_comment(head[j]) or add_left[head_n[j]] <= 0:
                continue
            add_left[head_n[j]] -= 1
            new_idx.append(j)
        touched.extend(new_idx)
        used: set[int] = set()
        for i in range(i1, i2):
            old = base[i]
            if is_blank_or_comment(old) or rm_left[base_n[i]] <= 0:
                continue
            rm_left[base_n[i]] -= 1
            best, best_ratio = None, 0.0
            for j in new_idx:
                if j in used:
                    continue
                r = difflib.SequenceMatcher(None, base_n[i], head_n[j]).ratio()
                if r > best_ratio:
                    best, best_ratio = j, r
            if best is not None and best_ratio >= 0.5:
                used.add(best)
                res.changed.append([old.strip(), head[best].strip()])
            else:
                res.removed.append(old.strip())
    if not touched:
        return head_text
    stmts = parse(head)
    out = list(head)
    done: set[int] = set()
    for j in touched:
        if is_blank_or_comment(head[j]):
            continue
        st = stmts[j]
        if st.container is not None:
            target, cst = st.container, stmts[st.container]
        else:
            cst = st
            target = st.end if st.kind == "activity" else st.start
        if cst.kind == "none":
            res.uncolored.append(head[j].strip())
            continue
        if target in done:
            res.colored.append(head[j].strip())
            continue
        new = color_line(cst, head, target)
        if new is None:
            res.uncolored.append(head[j].strip())
            continue
        out[target] = new
        if cst.kind == "activity":
            # 古い書き方の色（#pink :処理;）は外す。残すと後ろの色と二重になり、警告が図に出る
            out[cst.start] = LEGACY_ACT.sub(r"\1", out[cst.start])
        done.add(target)
        res.colored.append(head[j].strip())
    text = "\n".join(out)
    if head_text.endswith("\n"):
        text += "\n"
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True, help="比較元のコミット")
    ap.add_argument("--summary", help="結果の JSON を書く先")
    ap.add_argument("--out-dir", help="ここへ書く。無いときは作業ツリーを書き換える")
    ap.add_argument("files", nargs="*")
    args = ap.parse_args()

    results: dict[str, dict] = {}
    for path in args.files:
        with open(path, encoding="utf-8") as f:
            head_text = f.read()
        base_text = git_show(args.base, path)
        if base_text is None:
            res = FileResult(path, "new")
            text = head_text
        else:
            res = FileResult(path, "changed")
            text = highlight(base_text, head_text, res)
            if not (res.colored or res.uncolored or res.changed or res.removed):
                res.status = "same"
        dest = os.path.join(args.out_dir, path) if args.out_dir else path
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(text)
        results[path] = res.__dict__
        print(f"{path}: {res.status} 赤くした行 {len(res.colored)} / 色なし {len(res.uncolored)} / 消した行 {len(res.removed)}", file=sys.stderr)

    if args.summary:
        with open(args.summary, "w", encoding="utf-8") as f:
            json.dump({"files": results, "deleted_files": deleted_files(args.base)}, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
