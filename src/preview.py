"""The picture a link to the dashboard shows when it's shared (site/preview.png, 1200 x 630).

Drawn from the same numbers as the page, so it never disagrees with it. export_site.py
calls write_preview() every time it writes data.json.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PAGE, INK, MUTED, RED, BAR = "#13120f", "#ece6d6", "#857e6e", "#ec5a35", "#ece6d6"
WIDTH, HEIGHT, DPI = 1200, 630, 100


def write_preview(data, path):
    h = data["headline"]
    runs = data["champions"]
    fig = plt.figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=PAGE)
    px = lambda x, y: (x / WIDTH, 1 - y / HEIGHT)  # place things in pixels from the top left

    fig.text(*px(60, 62), "KNOCKOUT LUCK", color=RED, fontsize=15, fontweight="bold", family="monospace", va="center")
    title = dict(color=INK, fontsize=48, fontweight="bold", va="baseline")
    fig.text(*px(56, 160), "How much of a Champions", **title)
    second = fig.text(*px(56, 225), "League knockout is ", **title)
    # Put "luck?" straight after the second line, in red.
    fig.canvas.draw()
    end = second.get_window_extent().x1 / WIDTH
    fig.text(end, 1 - 225 / HEIGHT, "luck?", **{**title, "color": RED})

    stats = [
        (f"{round(h['underdog'] * 100)}%", "average chance the\nunderdog goes through"),
        (f"{round(h['median_champion_run'] * 100)}%", "chance the typical champion\nhad of winning every tie"),
        (f"{h['real_won']} of {h['real_ties']}", f"ties won by Real Madrid,\nwhen the model expected {round(h['real_expected'])}"),
    ]
    for k, (value, label) in enumerate(stats):
        y = 330 + k * 84
        fig.text(*px(60, y), value, color=RED if k == 2 else INK, fontsize=34, fontweight="bold", va="center")
        fig.text(*px(310, y), label, color=MUTED, fontsize=15, va="center", linespacing=1.3)

    # Every champion's chance of its whole run, as in the page's "Even champions mostly got lucky".
    ax = fig.add_axes([680 / WIDTH, 110 / HEIGHT, 460 / WIDTH, 210 / HEIGHT], facecolor=PAGE)  # 310-520px down
    values = [r["probability"] for r in runs]
    least = values.index(min(values))
    ax.bar(range(len(values)), values, width=0.72, color=[RED if i == least else BAR for i in range(len(values))])
    ax.set_ylim(0, max(values) * 1.12)
    ax.set_xlim(-0.6, len(values) - 0.4)
    ax.axis("off")
    ax.set_title("Each champion's chance of its whole run", color=MUTED, fontsize=14, loc="left", pad=12)
    ax.text(least, values[least] + max(values) * 0.03, f"{values[least] * 100:.1f}%", color=RED,
            fontsize=13, fontweight="bold", ha="center")
    first, last = runs[0]["season"], runs[-1]["season"]
    ax.text(0, -max(values) * 0.08, first, color=MUTED, fontsize=12, ha="center", va="top")
    ax.text(len(values) - 1, -max(values) * 0.08, last, color=MUTED, fontsize=12, ha="center", va="top")

    fig.text(*px(60, 590), f"Every knockout tie since {h['first_season']}, tested against the bookmakers",
             color=MUTED, fontsize=14, va="center")
    fig.text(*px(1140, 590), "kgadharsh.github.io/ucl-luck", color=INK, fontsize=14, va="center", ha="right",
             family="monospace")
    fig.savefig(path, dpi=DPI, facecolor=PAGE, metadata={"Software": None})
    plt.close(fig)
