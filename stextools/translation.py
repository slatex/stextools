# Naming conventions:
#   - hnode for HTML node, lnode for LaTeX node
#   - transparent: "should be processed recursively", e.g. a macro argument. By default, everything is opaque.
#   - inplace: something be translated where it is, not separately.
# Design decisions:
#   - All relevant should be in the HTML, so that we can recover the translated tex from the translated HTML
#     without resorting to other data structures for storage.
#     The path to the original file is stored in the HTML, so we can always go back to the original document.
#     This might be relevant if we use external services for translation.

import dataclasses
from io import StringIO
from pathlib import Path
from typing import Optional, Iterator

import lxml.etree as etree
from pylatexenc.latexwalker import LatexWalker, LatexNode, LatexCommentNode, LatexSpecialsNode, LatexGroupNode, \
    LatexMathNode, LatexMacroNode, LatexEnvironmentNode, LatexCharsNode

from stextools.macros import STEX_CONTEXT_DB


# We can ignore some macros and environments because they will be "imported" by [sig=en] in the smodule
MACROS_TO_IGNORE: set[str] = {
    r'symdecl', r'notation', r'MSC', r'symdef', r'importmodule'
}

ENVIRONMENTS_TO_IGNORE: set[str] = {
    'mathstructure'
}


class LNodeComponent:
    """ Part of a latex node (e.g. an argument) """


@dataclasses.dataclass
class KeyValParam(LNodeComponent):
    key: str


@dataclasses.dataclass
class Argument(LNodeComponent):
    n: int = 0


@dataclasses.dataclass
class EnvBody(LNodeComponent):
    pass


@dataclasses.dataclass
class TranslationRule:
    # The "main thing" that should be recursed into.
    inplace_transparent: Optional[LNodeComponent] = None
    # Something external that should be translated separately
    external_transparent: Optional[LNodeComponent] = None


# Does not include macros that require custom treatment
MACRO_RULES: dict[str, list[TranslationRule]] = {

}


@dataclasses.dataclass
class EnvTransparencyRule:
    pass


# Does not include environments that require custom treatment
ENVIRONMENT_RULES: dict[str, TranslationRule] = {
    'document': TranslationRule(inplace_transparent=EnvBody()),
    'sdefinition': TranslationRule(inplace_transparent=EnvBody()),
    'smodule': TranslationRule(inplace_transparent=EnvBody(), external_transparent=KeyValParam('title')),
}


def bergamot_html_translate(html: str, repository: str = 'browsermt', model_name: str = 'en-de-base') -> str:
    # import is slow, so we only do it when we actually need it
    from bergamot import REPOSITORY, ResponseOptions, Service, ServiceConfig, VectorString  # type: ignore

    config = ServiceConfig(numWorkers=1)  #, logLevel=args.log_level)
    service = Service(config)       # TODO: Should we use a global service?
    model = service.modelFromConfigPath(REPOSITORY.modelConfigPath(repository, model_name))

    # Configure a few options which require how a Response is constructed
    options = ResponseOptions(
        alignment=False, qualityScores=False, HTML=True
        # HTML=True
    )

    responses = service.translate(model, VectorString([html]), options)
    assert len(responses) == 1
    return responses[0].target.text


class ID_COUNTER:
    _count = 0

    @classmethod
    def __call__(cls):
        cls._count += 1
        return cls._count


def stex_to_html_recurse(lnode: LatexNode, parent_hnode: etree._Element):
    if lnode.nodeType() in {LatexCommentNode, LatexSpecialsNode}:
        return    # TODO: Should we keep comments? How should we treat specials?
    elif isinstance(lnode, LatexGroupNode):
        hnode = etree.SubElement(parent_hnode, 'span', attrib={'data-pre': lnode.delimiters[0],
                                                        'data-post': lnode.delimiters[1]})
        for child in lnode.nodelist:
            stex_to_html_recurse(child, hnode)
    elif isinstance(lnode, LatexMathNode):
        hnode = etree.SubElement(parent_hnode, 'span', attrib={'data-replace': lnode.latex_verbatim()})
        hnode.text = 'X'    # this should be a good placeholder for formulae during translation
    elif isinstance(lnode, LatexMacroNode):
        if lnode.macroname in MACROS_TO_IGNORE:
            return
        # TODO: handle macros that require custom treatment
        if lnode.macroname not in MACRO_RULES:          # opaque macro
            hnode = etree.SubElement(parent_hnode, 'img', attrib={'data-replace': lnode.latex_verbatim()})
            return
    elif isinstance(lnode, LatexEnvironmentNode):
        if lnode.environmentname in ENVIRONMENTS_TO_IGNORE:
            return
        elif lnode.environmentname not in ENVIRONMENT_RULES:   # opaque environment
            hnode = etree.SubElement(parent_hnode, 'img', attrib={'data-replace': lnode.latex_verbatim()})
            return

        rule = ENVIRONMENT_RULES[lnode.environmentname]
        if rule.inplace_transparent is None:
            hnode = etree.SubElement(parent_hnode, 'span', attrib={'data-replace': lnode.latex_verbatim()})
        else:
            assert isinstance(rule.inplace_transparent, EnvBody)
            hnode = etree.SubElement(
                parent_hnode, 'span',
                attrib={'data-pre': lnode.latex_verbatim()[:lnode.nodelist[0].pos-lnode.pos],
                        'data-post': lnode.latex_verbatim()[lnode.nodelist[-1].pos + lnode.nodelist[-1].len -lnode.pos:]}
            )
            for lchild in lnode.nodelist:
                stex_to_html_recurse(lchild, hnode)

    elif isinstance(lnode, LatexCharsNode):
        children = list(parent_hnode)
        if children:
            # if lnode.chars.isspace():
            #     if 'data-post' in children[-1].attrib:
            #         children[-1].attrib['data-post'] += lnode.chars
            #     else:
            #         children[-1].attrib['data-post'] = lnode.chars
            if not children[-1].tail:
                children[-1].tail = lnode.chars
            else:   # possible if we ignored a node
                children[-1].tail = lnode.chars
        else:
            parent_hnode.text = lnode.chars


def stex_to_html(doc_path: Path) -> etree._Element:
    walker = LatexWalker(doc_path.read_text(), latex_context=STEX_CONTEXT_DB)
    hnode = etree.Element('div', attrib={'class': 'document', 'id': f'{doc_path}'})

    for lnode in walker.get_latex_nodes()[0]:
        stex_to_html_recurse(lnode, hnode)

    return hnode


def documents_to_html(doc_paths: list[Path]) -> str:
    return '\n'.join(
            # ['<!DOCTYPE html>'] +    # bergamot does not like this
            ['<html>', '<body>'] +
            [etree.tostring(stex_to_html(doc_path)).decode() for doc_path in doc_paths] +
            ['</body>', '</html>']
    )


def html_to_str_iter(hnode: etree._Element) -> Iterator[str]:
    if hnode.tag == 'span':
        if 'data-pre' in hnode.attrib:
            yield hnode.attrib['data-pre']
            yield hnode.text or ''

        if 'data-replace' in hnode.attrib:
            yield hnode.attrib['data-replace']
        else:
            for child in hnode:
                yield from html_to_str_iter(child)
        if 'data-post' in hnode.attrib:
            yield hnode.attrib['data-post']
        yield hnode.tail or ''
    elif hnode.tag == 'img':
        yield hnode.attrib['data-replace']
        if 'data-post' in hnode.attrib:
            yield hnode.attrib['data-post']
        yield hnode.tail or ''
    elif hnode.tag == 'div':
        for child in hnode:
            yield from html_to_str_iter(child)
    else:
        raise Exception(f'Unexpected tag: {hnode.tag}')


def html_to_stex(html: str) -> list[tuple[Path, str]]:
    """Translate an HTML node back to LaTeX."""
    tree = etree.parse(StringIO(html), etree.HTMLParser())   # type: ignore
    results: list[tuple[Path, str]] = []
    for hnode in tree.xpath('//div[@class="document"]'):
        path = Path(hnode.attrib['id'])
        stex = ''.join(html_to_str_iter(hnode))
        results.append((path, stex))

    return results



