#!/usr/bin/env python
# -*- coding: utf-8 -*-

import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="akinaka",
    version="0.8.5",
    python_requires='>=3.3.0',
    author="Afraz",
    author_email="afrazkhan@gmail.com",
    description="Useful AWS CLI Extras",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/afrazkhan/akinaka",
    keywords=['aws'],
    packages=setuptools.find_packages(),
    include_package_data=True,
    entry_points={"console_scripts": ["akinaka=akinaka.main:main"]},
    install_requires=[
        'boto3',
        'datetime',
        'click',
        'pyyaml',
        'kubernetes'
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Operating System :: OS Independent",
    ],
    zip_safe=False
)
