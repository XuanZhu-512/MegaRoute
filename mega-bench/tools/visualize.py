"""Layer views of neutral board/routes; headless PNG/SVG export is supported."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--board', required=True, type=Path)
    p.add_argument('--routes', type=Path)
    p.add_argument('--metrics', type=Path)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    b = json.loads(a.board.read_text(encoding='utf-8'))
    routes = json.loads(a.routes.read_text(encoding='utf-8'))['copper'] if a.routes else []
    metrics = json.loads(a.metrics.read_text(encoding='utf-8')) if a.metrics else {}
    flagged = {v[k] for v in metrics.get('violations', []) for k in ('a', 'b')}
    colors = {n['id']: plt.get_cmap('tab20')(i % 20) for i, n in enumerate(b['nets'])}
    fig, axes = plt.subplots(1, b['layers'], figsize=(6*b['layers'], 6), squeeze=False)
    for z, ax in enumerate(axes[0]):
        ax.add_patch(Polygon(b['outline'], facecolor='#f5f6f7', edgecolor='#333333'))
        for h in b.get('holes', []):
            ax.add_patch(Polygon(h, facecolor='white', edgecolor='black'))
        for k in b.get('keepouts', []):
            if z in k['layers']:
                ax.add_patch(Polygon(k['points'], facecolor='#777777', alpha=.5, hatch='//'))
        for s in b.get('pads', []) + b.get('fixed_copper', []) + routes:
            if z not in s['layers']:
                continue
            color = 'red' if s['id'] in flagged else colors.get(s.get('net'), 'gray')
            if s['kind'] == 'segment':
                x, y = s['a']; u, v = s['b']
                dx, dy = u-x, v-y
                length = (dx*dx+dy*dy)**.5
                if length:
                    nx, ny = -dy/length*s['width']/2, dx/length*s['width']/2
                    ax.add_patch(Polygon([[x+nx,y+ny],[u+nx,v+ny],[u-nx,v-ny],[x-nx,y-ny]], color=color))
                for c in (s['a'], s['b']):
                    ax.add_patch(Circle(c, s['width']/2, color=color))
            elif s['kind'] == 'polygon':
                ax.add_patch(Polygon(s['points'], color=color))
            else:
                ax.add_patch(Circle(s['center'], s['radius'], color=color))
                if s['kind'] == 'via':
                    ax.add_patch(Circle(s['center'], s['drill']/2, color='white'))
        ax.autoscale_view(); ax.set_aspect('equal'); ax.set_title(f'Copper layer {z}')
        ax.set_xlabel('x (mm)'); ax.set_ylabel('y (mm)')
    fig.suptitle(f"PCB bench | {metrics.get('status', 'board preview')} | DRC: {metrics.get('DRC', 'not checked')}")
    fig.tight_layout()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out, dpi=160)
    plt.close(fig)


if __name__ == '__main__':
    main()
