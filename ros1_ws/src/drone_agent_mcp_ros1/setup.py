from setuptools import find_packages, setup

setup(
    name="drone_agent_mcp_ros1",
    version="1.0.0",
    packages=find_packages("src"),
    package_dir={"": "src"},
)
