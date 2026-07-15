from stextools.snify.text_anno.local_stex_catalog import local_flams_stex_catalogs

catalogs = local_flams_stex_catalogs()

deutsch = catalogs['de']


for symbol in deutsch.symb_iter():
    print(symbol.uri)
    for verbalization in deutsch.symb_to_verb[symbol]:    
        print('    ', repr(verbalization.verb))

