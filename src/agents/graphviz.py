from pathlib import Path
from typing import List
import json
import networkx as nx
import matplotlib.pyplot as plt


FONT_SIZE = 8


class StateGraphViz:
    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.index = json.loads((self.run_dir / 'index.json').read_text())
        self.nodes = self.index.get('states', [])

    def _edges(self):
        edges = []
        for i in range(1, len(self.nodes)):
            a = self.nodes[i - 1]
            b = self.nodes[i]
            act = b.get('action_leading_here') or ''
            edges.append((a['id'], b['id'], {'label': act}))
        return edges

    def _labels(self):
        return {n['id']: f"{n['id']}\n{n.get('label','')}" for n in self.nodes}

    def render_linear(self, out='state_graph_linear.png'):
        G = nx.DiGraph()
        for n in self.nodes:
            G.add_node(n['id'])
        for u, v, data in self._edges():
            G.add_edge(u, v, **data)
        pos = {n['id']: (i, -i) for i, n in enumerate(self.nodes)}
        labels = self._labels()
        plt.figure(figsize=(8, max(4, len(self.nodes) * 0.6)))
        nx.draw(G, pos, with_labels=False, node_size=1200)
        nx.draw_networkx_labels(G, pos, labels, font_size=FONT_SIZE)
        edge_labels = nx.get_edge_attributes(G, 'label')
        nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=FONT_SIZE)
        plt.axis('off')
        plt.tight_layout()
        plt.savefig(self.run_dir / out, dpi=160)
        plt.close()

    def render_force(self, out='state_graph_force.png'):
        G = nx.DiGraph()
        for n in self.nodes:
            G.add_node(n['id'])
        for u, v, data in self._edges():
            G.add_edge(u, v, **data)
        pos = nx.spring_layout(G, seed=42)
        labels = self._labels()
        plt.figure(figsize=(8, 6))
        nx.draw(G, pos, with_labels=False, node_size=1200)
        nx.draw_networkx_labels(G, pos, labels, font_size=FONT_SIZE)
        edge_labels = nx.get_edge_attributes(G, 'label')
        nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=FONT_SIZE)
        plt.axis('off')
        plt.tight_layout()
        plt.savefig(self.run_dir / out, dpi=160)
        plt.close()

