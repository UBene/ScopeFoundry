from setuptools import setup

setup(
    name = 'ScopeFoundry',
    
    version = "2.0.3",
    
    description = 'a platform for laboratory equipment control and scientific data analysis',
    long_description =open('README.md', 'r').read(),
    long_description_content_type='text/markdown',
    
    # Author details
    author='Edward S. Barnard',
    author_email='esbarnard@lbl.gov',

    # Choose your license
    license='BSD',
    
    url='https://www.scopefoundry.org/',

    package_dir={'ScopeFoundry': '.'},
    
    packages=[
        "ScopeFoundry",
        "ScopeFoundry.base_app",
        "ScopeFoundry.base_app.icons",
        "ScopeFoundry.controlling",
        "ScopeFoundry.data_browser",
        "ScopeFoundry.data_browser.viewers",
        "ScopeFoundry.data_browser.plug_ins",
        "ScopeFoundry.dynamical_widgets",
        "ScopeFoundry.examples",
        "ScopeFoundry.examples.ScopeFoundryHW",
        "ScopeFoundry.examples.ScopeFoundryHW.bsinc_noiser200",
        "ScopeFoundry.examples.ScopeFoundryHW.simulon_xyzstage",
        "ScopeFoundry.graphics",
        "ScopeFoundry.graphics.zoomable_map",
        "ScopeFoundry.logged_quantity",
        "ScopeFoundry.scanning",
        "ScopeFoundry.sequencer",
        "ScopeFoundry.sequencer.item_types",
        "ScopeFoundry.tools",
        "ScopeFoundry.tools.features",
        "ScopeFoundry.tools.templates",
        "ScopeFoundry.tools.pages",
    ],
    package_data={
        "": [
            "*.ui",
            "*.icns",
            "*.png",
            "*.svg",
            "*.qss",
            # for ScopeFoundry tools
            "_LICENSE",
            "*.md",
            "**/default_settings.ini",
            "**/defaults.ini",
            "**/sweep_h_centers.json",
            "**/.gitignore",
        ]
    },
    install_requires=["numpy", "h5py", "uuid7", "qtpy", "pyqtgraph"],
    extras_require={"all": ["PyQt6", "qtconsole", "pyqtdarktheme", "matplotlib"]},
)
