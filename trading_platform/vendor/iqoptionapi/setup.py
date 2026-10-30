from setuptools import setup, find_packages

setup(
    name="iqoptionapi",
    version="0.1.0",
    description="Wrapper Python para IQ Option API",
    author="L0k1",
    author_email="cassioms764@gmail.com",
    url="https://github.com/cassDS/iqoptionapi",
    packages=find_packages(),
    # pylint is a development tool, not a runtime dependency. Keeping it out
    # of install_requires avoids shipping the linter and its dependency tree
    # in the production image.
    install_requires=["requests", "websocket-client==1.8.0"],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License"
    ],
)
