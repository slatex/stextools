"""
quick-and-dirty hack for fuzzy stex symbol search
"""

from stextools.stepper.interface import interface, set_interface
from stextools.snify.text_anno.local_stex_catalog import local_flams_stex_catalogs
from stextools.stex.local_stex import FlamsUri, OpenedStexFLAMSFile
from stextools.snify.displaysupport import stex_symbol_style


set_interface('console-true-dark')

catalog = local_flams_stex_catalogs()['en']

interface.list_search(
    {
        stex_symbol_style(FlamsUri(symbol.uri)) : symbol
        for symbol in catalog.symb_iter()
    }
)
