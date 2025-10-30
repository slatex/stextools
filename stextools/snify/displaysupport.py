"""
Various helper functions for displaying snify content.
"""
from stextools.snify.new_snify_state import NewSnifyState
from stextools.stepper.document import Document, WdAnnoHtmlDocument
from stextools.stepper.interface import interface, BrowserInterface


def display_snify_header(state: NewSnifyState):
    # TODO: add:
    #   * current annotation type
    #   * statistics (# annos, remaining/total documents, ...)
    interface.write_header(
        state.get_current_document().identifier
    )

def display_text_selection(doc: Document, selection: tuple[int, int] | None):
    if isinstance(interface.get_object(), BrowserInterface) and isinstance(doc, WdAnnoHtmlDocument):
        # render the HTML, rather than its source
        if isinstance(selection, tuple):
            a, b = selection
            content = (
                    doc.get_content()[doc.get_body_range()[0]:a] +
                    '<span class="highlight" id="snifyhighlight">' +  # TODO: in MathML, this works but is not ideal
                    doc.get_content()[a:b] +
                    '</span>' +
                    doc.get_content()[b:doc.get_body_range()[1]]
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
            limit_range=5,
        )
