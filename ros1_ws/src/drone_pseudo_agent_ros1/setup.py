from setuptools import find_packages, setup

setup(
    name="drone_pseudo_agent_ros1",
    version="0.1.0",
    packages=find_packages("src"),
    package_dir={"": "src"},
)
