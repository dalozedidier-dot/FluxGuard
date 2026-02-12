from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional


def _try_import_matplotlib():
    try:
        import matplotlib  # type: ignore  # noqa: F401
        import matplotlib.pyplot as plt  # type: ignore

        return plt
    except Exception:
        return None


def save_histogram(values: List[float], outpath: Path, *, title: str, xlabel: str) -> Optional[str]:
    """Génère un histogramme si matplotlib est disponible.

    Retourne le chemin (str) si écrit, sinon None.
    """
    plt = _try_import_matplotlib()
    if plt is None:
        return None

    outpath.parent.mkdir(parents=True, exist_ok=True)
    fig = plt.figure()
    ax = fig.add_subplot(111)
    ax.hist(values, bins=30)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("count")
    fig.tight_layout()
    fig.savefig(outpath)
    plt.close(fig)
    return str(outpath)


def save_heatmap(matrix: List[List[float]], labels: List[str], outpath: Path, *, title: str) -> Optional[str]:
    plt = _try_import_matplotlib()
    if plt is None:
        return None

    outpath.parent.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(8, 7))
    ax = fig.add_subplot(111)
    im = ax.imshow(matrix, aspect="auto")
    ax.set_title(title)
    ax.set_xticks(list(range(len(labels))))
    ax.set_yticks(list(range(len(labels))))
    ax.set_xticklabels(labels, rotation=90, fontsize=7)
    ax.set_yticklabels(labels, fontsize=7)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(outpath)
    plt.close(fig)
    return str(outpath)
