from setuptools import setup, find_packages

setup(
    name="pokedex-rsa",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "click>=8.0.0",
        "requests>=2.31.0",
    ],
    extras_require={
        "ui": ["flask>=3.0.0"],
    },
    entry_points={
        "console_scripts": [
            "poke-rsa=pokedex_rsa.views.cli:cli",
            "poke-rsa-ui=ui.serve:main",
        ],
    },
    python_requires=">=3.12",
)
