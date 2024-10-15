from __future__ import annotations

import dataclasses
from collections import defaultdict
from pathlib import Path
from typing import Optional

from stextools.cache import Cache
from stextools.mathhub import MathHub, make_filter_fun


@dataclasses.dataclass
class Node:  # an archive
    archive_name: str
    edges: list[Edge] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class Edge:  # a dependency
    from_node: Node
    to_node: Node
    because_of_files: list[Path]

    __hash__ = object.__hash__


@dataclasses.dataclass
class Graph:
    nodes: dict[str, Node] = dataclasses.field(default_factory=dict)


def get_dependency_graph(mh: MathHub) -> Graph:
    if mh.load_all_doc_infos():
        Cache.store_mathhub(mh)

    graph = Graph()
    for archive in mh.iter_stex_archives():
        name = archive.get_archive_name()
        if name not in graph.nodes:
            graph.nodes[name] = Node(name)
        node = graph.nodes[name]

        dep_to_files: dict[str, set[Path]] = defaultdict(set)
        for doc in archive.stex_doc_iter():
            for dep in doc.get_doc_info(mh).flattened_dependencies():
                if dep.archive == name:  # ignore loops
                    continue
                dep_to_files[dep.archive].add(doc.path)
        for dep_name, files in dep_to_files.items():
            if dep_name not in graph.nodes:
                graph.nodes[dep_name] = Node(dep_name)
            dep_node = graph.nodes[dep_name]
            node.edges.append(Edge(node, dep_node, list(files)))

    return graph


def show_graph(filter: Optional[str] = None):
    import networkx as nx
    from matplotlib import pyplot as plt  # slow import => only do it if needed
    filter_fun = make_filter_fun(filter)

    mygraph = get_dependency_graph(Cache.get_mathhub())

    G = nx.DiGraph()
    for node in mygraph.nodes.values():
        if not filter_fun(node.archive_name):
            continue
        G.add_node(node.archive_name)
        for edge in node.edges:
            if not filter_fun(edge.to_node.archive_name):
                continue
            G.add_edge(edge.from_node.archive_name, edge.to_node.archive_name)

    pos = nx.spring_layout(G, k=0.05, iterations=40)
    nx.draw(G, pos, with_labels=True, node_size=100, font_size=5)
    plt.show()


def show_weak_dependencies(filter: Optional[str] = None):
    filter_fun = make_filter_fun(filter)
    mh: MathHub = Cache.get_mathhub()
    graph = get_dependency_graph(mh)
    edges = [edge for node in graph.nodes.values() for edge in node.edges if filter_fun(edge.from_node.archive_name)]
    ratings: dict[Edge, float] = {}
    for edge in edges:
        # Note: this is just a first attempt to rate the relevance of a dependency
        from_archive = mh.get_archive(edge.from_node.archive_name)
        assert from_archive is not None
        ratings[edge] = (len(edge.because_of_files) /
                         from_archive.number_of_documents() ** 0.5)

    edges.sort(key=lambda edge: ratings[edge], reverse=True)

    for edge in edges[-200:]:
        print(f'{edge.from_node.archive_name} -> {edge.to_node.archive_name}: {ratings[edge]}')
        for file in edge.because_of_files:
            print(f'    {file}')
