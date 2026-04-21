from setuptools import setup, find_packages

setup(
    name="sheet_metal_mfg",
    version="1.0.0",
    description="Sheet Metal WIP Management for ERPNext V16",
    author="Your Company",
    author_email="info@yourcompany.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=[],   # ← direct and safe
)
