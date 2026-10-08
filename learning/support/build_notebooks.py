"""从 percent 格式源码生成 learning/*.ipynb。

notebook 的主产物是 ``learning/NN_*.ipynb``,但手工维护 ipynb 的 JSON 很痛苦,
所以源码以 percent 格式放在 ``learning/nb_src/NN_*.py``(纯文本、可 diff),
再用本脚本生成 ipynb:

    uv run python learning/support/build_notebooks.py            # 全部重建
    uv run python learning/support/build_notebooks.py 03 05      # 只重建 03/05

源码格式(每本 notebook 就是一串 cell):

    # %% [markdown]      ← 以下到下一个标记之间是 markdown cell
    # # 标题             ← markdown 内容按 jupytext 惯例逐行以 "# " 注释;
    # 正文...               构建时会剥掉这一个前缀(裸 "#" 表示空行)
    # %%                 ← 以下到下一个标记之间是代码 cell(原样保留)
    print("hello")

这种注释式 markdown 与 VS Code 的 Interactive Window / jupytext 完全兼容,
所以 ``nb_src/*.py`` 也能直接当 notebook 源读。

内核:ipynb 的 kernelspec 指向**具名内核** ``octop-harness``(见 README 的
一次性注册命令)。它指向本仓库 .venv,VS Code 与 jupyter 都能直接选中。
生成后可用 ``jupyter nbconvert --execute`` 验证运行。
"""

from __future__ import annotations

import sys
from pathlib import Path

import nbformat as nbf

LEARNING_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = LEARNING_DIR / "nb_src"

MARKDOWN_MARKER = "# %% [markdown]"
CODE_MARKER = "# %%"

KERNEL_NAME = "octop-harness"
KERNEL_DISPLAY = "octop-harness (.venv)"


def _strip_markdown_prefix(line: str) -> str:
    """剥掉 markdown 行的一个 jupytext 注释前缀:"# xxx" → "xxx","#" → ""。"""
    if line.startswith("# "):
        return line[2:]
    if line == "#":
        return ""
    return line


def parse_percent_source(text: str) -> list[tuple[str, str]]:
    """把 percent 源码解析成 (kind, content) 列表,kind ∈ {"markdown", "code"}。"""
    cells: list[tuple[str, str]] = []
    kind: str | None = None
    lines: list[str] = []

    def flush() -> None:
        if kind is not None:
            while lines and not lines[0].strip():
                lines.pop(0)
            while lines and not lines[-1].strip():
                lines.pop()
            if lines:
                cells.append((kind, "\n".join(lines) + "\n"))

    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped == MARKDOWN_MARKER or stripped == CODE_MARKER:
            flush()
            kind = "markdown" if stripped == MARKDOWN_MARKER else "code"
            lines = []
            continue
        if kind is not None:
            lines.append(_strip_markdown_prefix(raw) if kind == "markdown" else raw)
    flush()
    return cells


def build_one(src_path: Path) -> Path:
    cells_spec = parse_percent_source(src_path.read_text(encoding="utf-8"))
    if not cells_spec:
        raise SystemExit(f"{src_path} 中没有解析到任何 cell")
    notebook = nbf.v4.new_notebook()
    notebook.metadata = {
        "kernelspec": {
            "display_name": KERNEL_DISPLAY,
            "language": "python",
            "name": KERNEL_NAME,
        },
        "language_info": {"name": "python"},
    }
    for kind, content in cells_spec:
        if kind == "markdown":
            notebook.cells.append(nbf.v4.new_markdown_cell(content))
        else:
            notebook.cells.append(nbf.v4.new_code_cell(content))
    out_path = LEARNING_DIR / f"{src_path.stem}.ipynb"
    nbf.write(notebook, out_path)
    return out_path


def main(argv: list[str]) -> None:
    sources = sorted(SRC_DIR.glob("*.py"))
    if not sources:
        raise SystemExit(f"{SRC_DIR} 下没有找到 percent 源文件")
    if argv:
        sources = [
            p
            for p in sources
            if any(p.stem == s or p.stem.startswith(f"{s}_") or p.stem.split("_")[0] == s for s in argv)
        ]
        if not sources:
            raise SystemExit(f"没有匹配的源文件:{argv}")
    for src in sources:
        out = build_one(src)
        print(f"built {out.relative_to(LEARNING_DIR.parent)}")


if __name__ == "__main__":
    main(sys.argv[1:])
