#!/usr/bin/env python3
"""Shared publication plotting style for experiment figures."""

from __future__ import annotations

import matplotlib.pyplot as plt


def setup_pub_style() -> None:
    plt.rcParams.clear()
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "DejaVu Serif", "serif"],
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "axes.linewidth": 1.0,
        "grid.alpha": 0.30,
        "grid.linewidth": 0.7,
        "font.size": 10,
        "axes.labelsize": 11.5,
        "axes.titlesize": 11.5,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "lines.linewidth": 1.8,
        "lines.markersize": 5,
        "mathtext.fontset": "stix",
    })
