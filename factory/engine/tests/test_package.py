import sys

import factory_engine


def test_package_imports_and_has_version():
    assert factory_engine.__version__ == "0.1.0"


def test_python_floor_is_3_10():
    assert sys.version_info >= (3, 10)
