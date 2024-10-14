import re
from typing import Iterable, Any

# python 3.9 doesn't have TypeAlias yet
# TREE_TYPE: TypeAlias = dict[str, 'TREE_TYPE']
TREE_TYPE = Any


def words_to_tree(words: Iterable[str]) -> TREE_TYPE:
    tree: TREE_TYPE = {}
    for word in words:
        current = tree
        for char in word:
            if char not in current:
                current[char] = {}
            current = current[char]
        current[''] = {}   # leaf
    return tree


def tree_to_regex(trie: TREE_TYPE) -> str:
    parts: list[str] = []

    def _tree_to_regex(tree):
        if len(tree) == 1:
            key, val = list(tree.items())[0]
            if key:
                parts.append(re.escape(key))
                _tree_to_regex(tree[key])
            else:  # leaf
                pass
        else:
            parts.append('(?:')
            for i, char in enumerate(c for c in tree if c != ''):
                if i:
                    parts.append('|')
                if char:
                    parts.append(re.escape(char))
                    _tree_to_regex(tree[char])
            if '' in tree:  # putting leafs last makes it greedy, i.e. we find the longest matching namespace
                parts.append('|')
            parts.append(')')

    _tree_to_regex(trie)

    return ''.join(parts)


def words_to_regex(words: Iterable[str]) -> str:
    return tree_to_regex(words_to_tree(words))
