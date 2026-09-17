"""Bundle the single canonical enrollment core into wheel and source releases."""

from pathlib import Path
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist


ROOT = Path(__file__).resolve().parent
VENDORED = Path("src") / "azurefactory" / "_vendor" / "factory_enrollment.py"


def enrollment_source():
    # A release's bundled input wins over unrelated surrounding source trees.
    for path in (
        ROOT / VENDORED,
        ROOT.parent.parent / "bootstrap" / "lib" / "factory_enrollment.py",
        ROOT.parent.parent / "azure-enterprise-scale-ml" / "bootstrap" / "lib" / "factory_enrollment.py",
        ROOT.parent.parent / "lib" / "factory_enrollment.py",
    ):
        if path.is_file():
            return path
    raise RuntimeError("Canonical factory_enrollment.py is missing from the build inputs.")


class BuildPy(build_py):
    def run(self):
        super().run()
        target = Path(self.build_lib) / "azurefactory" / "_vendor" / "factory_enrollment.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(enrollment_source(), target)


class Sdist(sdist):
    def make_release_tree(self, base_dir, files):
        super().make_release_tree(base_dir, files)
        target = Path(base_dir) / VENDORED
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(enrollment_source(), target)


setup(cmdclass={"build_py": BuildPy, "sdist": Sdist})
