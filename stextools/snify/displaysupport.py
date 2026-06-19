"""
Various helper functions for displaying snify content.
"""
import re

from stextools.config import get_config
from stextools.snify.snify_state import SnifyState
from stextools.stepper.document import Document, WdAnnoHtmlDocument, LocalFtmlDocument
from stextools.stepper.interface import interface, BrowserInterface
from stextools.stex.local_stex import FlamsUri


def display_snify_header(state: SnifyState):
    # TODO: add:
    #   * current annotation type
    #   * statistics (# annos, remaining/total documents, ...)
    interface.write_header(state.get_current_document().identifier)
    interface.write_statistics(
        f'{str(state.cursor.document_index + 1).rjust(len(str(len(state.documents))))}/{len(state.documents)}   {state.get_current_document().format}:{state.get_current_document().language.upper()}   {state.ongoing_annotype}'
    )

def display_text_selection(doc: Document, selection: tuple[int, int] | None):
    if isinstance(interface.get_object(), BrowserInterface) and (
            isinstance(doc, WdAnnoHtmlDocument)
            or isinstance(doc, LocalFtmlDocument)
    ):
        if get_config().getboolean('stextools.snify', 'strip_html_style_attrs', fallback=False):
            def _remove_style_attrs(html: str) -> str:
                # TODO: cleaner implementation
                return re.sub(r'\sstyle="[^"]*"', '', html)
        else:
            _remove_style_attrs = lambda x: x


        # render the HTML, rather than its source
        if isinstance(selection, tuple):
            a, b = selection
            content = (
                    _remove_style_attrs(doc.get_content()[doc.get_body_range()[0]:a]) +
                    '<span class="highlight" id="snifyhighlight">' +  # TODO: in MathML, this works but is not ideal
                    _remove_style_attrs(doc.get_content()[a:b]) +
                    '</span>' +
                    _remove_style_attrs(doc.get_content()[b:doc.get_body_range()[1]])
            )
        else:
            content = doc.get_body_content()
        interface.write_text(
            '<div style="border: 1px solid black; padding: 5px; margin: 5px; max-height: 40vh; overflow: auto;">' +
            content +
            '</div>' + r'''
            ''',
            prestyled=True,
        )
    else:
        interface.show_code(
            doc.get_content(),
            doc.format,  # type: ignore
            highlight_range=selection if isinstance(selection, tuple) else None,
            limit_range=get_config().getint('stextools.snify', 'display_context_lines', fallback=5)
        )


def stex_symbol_style(uri: FlamsUri) -> str:
    style = interface.apply_style
    return (
        style(uri.archive, 'highlight1') +
        ' ' + uri.path + '?' +
        style(uri.module, 'highlight2') +
        '?' + style(uri.symbol, 'highlight3')
    )
