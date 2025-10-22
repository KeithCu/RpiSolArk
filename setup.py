#!/usr/bin/env python3
"""
Setup script for the GIL-safe pulse counter C extension.
Uses modern setuptools for building C extensions.
"""

from setuptools import setup, Extension
import sys

# Define the C extension
pulse_counter_extension = Extension(
    'pulse_counter',
    sources=['pulse_counter.c'],
    libraries=['gpiod', 'pthread'],
    extra_compile_args=['-fPIC', '-O2'],
)

setup(
    name='pulse_counter',
    version='1.0.0',
    description='GIL-safe pulse counter for GPIO interrupts',
    ext_modules=[pulse_counter_extension],
    python_requires='>=3.11',
    install_requires=[
        'setuptools>=65.0.0',
    ],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: C',
        'Topic :: System :: Hardware',
        'Topic :: System :: Hardware :: Hardware Drivers',
    ],
)
