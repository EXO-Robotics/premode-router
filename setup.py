from setuptools import setup
from setuptools.command.build_py import build_py


RESEARCH_MODULES = {
    "premode.lab73ab_sharded",
    "premode.lab73i",
    "premode.lab73l",
    "premode.live_token_harness",
    "premode.sharded_runner",
}


class ProductionBuildPy(build_py):
    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        return [item for item in modules if f"{item[0]}.{item[1]}" not in RESEARCH_MODULES]


setup(cmdclass={"build_py": ProductionBuildPy})
