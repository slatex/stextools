import unittest

from stextools.snify.text_anno.catalog import Catalog, catalogs_from_stream, Verbalization


def get_test_catalog() -> Catalog:
    return catalogs_from_stream(
        [
            ('en', '?edge', Verbalization('edge')),
            ('en', '?edgenum', Verbalization('edge number')),
            ('en', '?int', Verbalization('integer')),
        ]
    )['en']


class TestCatalog(unittest.TestCase):
    def test_find_match(self):
        catalog = get_test_catalog()

        for example, expected_string in [
            ('\nintegers  are fun...\n', 'integers'),
            ('\ninteger edge\n', 'integer'),
            ('The edge   number is', 'edge   number'),
            ('The edge   degree is', 'edge'),
        ]:
            with self.subTest(example=example, expected_string=expected_string):
                match = catalog.find_first_match(
                    string=example,
                    stems_to_ignore=set(),
                    words_to_ignore=set(),
                    symbols_to_ignore=set(),
                )
                self.assertIsNotNone(match)
                start, end = match[:2]
                self.assertEqual(example[start:end], expected_string)
