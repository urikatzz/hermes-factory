import unittest

from factory_art.model_checks import check_model

CLASS = {'triangles_max': 100, 'materials_max': 1, 'texture_max_px': 512,
         'height_m': [0.5, 2.0], 'origin': 'bottom_center'}
GOOD = {'triangles': 12, 'materials': 1, 'textures': [{'name': 't', 'width': 512, 'height': 256}],
        'bbox_min': [-0.5, -0.5, 0.0], 'bbox_max': [0.5, 0.5, 1.0]}


def checks(stats, cls=CLASS):
    return [(f['severity'], f['check']) for f in check_model('crate.glb', stats, cls)]


class ModelTests(unittest.TestCase):
    def test_good_model(self):
        self.assertEqual(checks(GOOD), [])

    def test_limits(self):
        stats = dict(GOOD, triangles=101, materials=2, textures=[{'name': 't', 'width': 2048, 'height': 2048}])
        self.assertEqual(checks(stats), [('HIGH', 'triangles'), ('HIGH', 'materials'), ('HIGH', 'texture_size')])

    def test_height_and_origin(self):
        stats = dict(GOOD, bbox_min=[0.5, -0.5, 0.0], bbox_max=[1.5, 0.5, 3.0])
        self.assertEqual(checks(stats), [('MEDIUM', 'height'), ('MEDIUM', 'origin')])

    def test_centre_origin(self):
        self.assertEqual(checks(GOOD, {'origin': 'center'}), [('MEDIUM', 'origin')])
        centred = dict(GOOD, bbox_min=[-0.5, -0.5, -0.5], bbox_max=[0.5, 0.5, 0.5])
        self.assertEqual(checks(centred, {'origin': 'center'}), [])

    def test_import_error_is_a_blocker(self):
        self.assertEqual(checks({'error': 'RuntimeError: bad file'}), [('BLOCKER', 'import')])
