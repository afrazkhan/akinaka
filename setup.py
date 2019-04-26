import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="akinaka",
    python_requires='>=3.3.0',
    version="0.2.10",
    author="Afraz",
    author_email="afraz@olindata.com",
    description="OlinData's aws cli Extras",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://gitlab.olindata.com/olindata/akinaka",
    packages=setuptools.find_packages(),
    install_requires=[
        'boto3',
        'datetime',
        'click'
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Operating System :: OS Independent",
    ],
    scripts=['akinaka.py'],
    zip_safe=False
)
