"""Bundle canonical enrollment and repository coordination into CLI releases."""

from pathlib import Path
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist


ROOT = Path(__file__).resolve().parent
VENDORED = Path("src") / "azurefactory" / "_vendor"
HELPERS = ("factory_enrollment.py", "provider_repository_state.py")


def enrollment_source(name):
    # A release's bundled input wins over unrelated surrounding source trees.
    for path in (
        ROOT / VENDORED / name,
        ROOT.parent.parent / "bootstrap" / "lib" / name,
        ROOT.parent.parent / "azure-enterprise-scale-ml" / "bootstrap" / "lib" / name,
        ROOT.parent.parent / "lib" / name,
    ):
        if path.is_file():
            return path
    raise RuntimeError("Canonical " + name + " is missing from the build inputs.")


class BuildPy(build_py):
    def run(self):
        super().run()
        target = Path(self.build_lib) / "azurefactory" / "_vendor"
        target.mkdir(parents=True, exist_ok=True)
        for name in HELPERS:
            shutil.copyfile(enrollment_source(name), target / name)


class Sdist(sdist):
    def make_release_tree(self, base_dir, files):
        super().make_release_tree(base_dir, files)
        target = Path(base_dir) / VENDORED
        target.mkdir(parents=True, exist_ok=True)
        for name in HELPERS:
            shutil.copyfile(enrollment_source(name), target / name)


setup(cmdclass={"build_py": BuildPy, "sdist": Sdist})
