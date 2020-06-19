from setuptools import setup
import pathlib

plugin_dir = pathlib.Path(__file__).parent.absolute()

with open(f"{plugin_dir}/README.md", "r") as fh:
    long_description = fh.read()

setup(
    author="Tenzir",
    author_email="engineering@tenzir.com",
    classifiers=[
        # https://pypi.org/classifiers/
        "Development Status :: 3 - Alpha",
        "Environment :: Plugins",
        "License :: OSI Approved :: BSD License",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Topic :: Security",
        "Topic :: Software Development :: Object Brokering",
    ],
    description="A simplistic in-memory backbone for threatbus.",
    entry_points={"threatbus.backbone": ["inmem = threatbus_inmem.plugin"]},
    install_requires=["threatbus>=2020.04.29",],
    keywords=["threatbus", "plugin"],
    license="BSD 3-clause",
    long_description=long_description,
    long_description_content_type="text/markdown",
    name="threatbus-inmem",
    package_dir={"": "plugins/backbones"},
    packages=["threatbus_inmem"],
    python_requires=">=3.7",
    url="https://github.com/tenzir/threatbus",
    version="2020.06.25",
)
