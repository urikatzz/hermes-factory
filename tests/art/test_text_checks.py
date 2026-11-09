import json
import unittest

from factory_art.text_checks import check_text, strings

CLASS = {'max_chars': 10, 'forbidden': ['!!']}


def found(document):
    return [(f['severity'], f['check'], f['file']) for f in check_text('ui.json', json.dumps(document).encode(), CLASS)]


class TextTests(unittest.TestCase):
    def test_walks_nested_strings_with_key_paths(self):
        self.assertEqual(list(strings({'a': {'b': 'x'}, 'c': ['y', 3]})), [('a.b', 'x'), ('c[0]', 'y')])

    def test_length_and_forbidden(self):
        self.assertEqual(found({'menu': {'quit': 'Quit the game now', 'go': 'Go!!', 'ok': 'OK'}}),
                         [('HIGH', 'max_chars', 'ui.json#menu.quit'), ('MEDIUM', 'forbidden', 'ui.json#menu.go')])

    def test_unreadable_json_is_a_blocker(self):
        result = check_text('ui.json', b'{', CLASS)
        self.assertEqual([(f['severity'], f['check']) for f in result], [('BLOCKER', 'unreadable')])
