from pathlib import Path

from lxml import etree
from pylatexenc.latexwalker import LatexWalker

from stextools.macros import STEX_CONTEXT_DB
from stextools.translation import stex_to_html, documents_to_html, html_to_stex, bergamot_html_translate

walker = LatexWalker('\\definiendum[x]{a}{b}', latex_context=STEX_CONTEXT_DB)
print(walker.get_latex_nodes()[0])
walker = LatexWalker('\\definiendum{a}{b}', latex_context=STEX_CONTEXT_DB)
print(walker.get_latex_nodes()[0])


print('------------------')


element = stex_to_html(Path('/home/jfs/git/gl.mathhub.info/smglom/cs/source/mod/cryptology.en.tex'))
print(etree.tostring(element, pretty_print=True).decode())


print('------------------')

html = documents_to_html([Path('/home/jfs/git/gl.mathhub.info/smglom/cs/source/mod/cryptology.en.tex')])
print(html)

print(html_to_stex(html)[0][1])

print('------------------')

html2 = html.replace('\n', '<img data-replace="&#10;"/>')
print(bergamot_html_translate(html2))

print(html_to_stex(bergamot_html_translate(html2))[0][1])
